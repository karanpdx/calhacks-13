"""The referee: deterministic rules, no AI. It runs the CRS gate, builds the passport, and validates every message.

Agents can say anything in free text. Only messages that pass these checks change the state of the market:
  - identity: the sender is registered and the message is signed with that agent's key
  - role: only lenders OFFER/WITHDRAW, only the borrower INTENT/COUNTER/ACCEPT
  - offers: valid numbers, APR under the cap, fees declared in the terms, amount not above what was asked
  - commitment: a lender's new offer can't be worse for the borrower than its live one (no bait-and-switch)
  - acceptance: the offer exists and is live, the accepted terms are exactly the offered terms, and they fit the mandate
Every message and verdict is appended to the event log (the audit trail the UI shows).

With `watchdog=True`, a flag-only watchdog (exchange/watchdog.py) reviews each event and adds `watchdog` events.
One referee rule uses it: a lender that commits a hard violation (TERMS_WORSENED, BAD_SIGNATURE, or a RULE-BASED
injection flag) is excluded for the rest of the session and its live offers are withdrawn. Claude flags never count.
"""
import os, secrets, time
from datetime import date

from agent import signals as S
from agent.screen import screen
from agent.sources import SampleSource

from . import finance, passport as PP
from .messages import (Message, Mandate, Terms, Verdict, TYPES, APR_CAP,
                       INTENT, OFFER, COUNTER, ACCEPT, DECLINE, WITHDRAW)
from .lenders import RuleLender, POLICIES
from .borrower import RuleBorrower
from .watchdog import Watchdog

BLOCKED_DECISIONS = {"STOP_FRAUD"}  # identity can't be trusted: nobody in the market sees anything
ROLE_TYPES = {"borrower": {INTENT, COUNTER, ACCEPT, DECLINE}, "lender": {OFFER, DECLINE, WITHDRAW}}
SIMULATED = "simulated (not available in the CRS sandbox)"
HARD_VIOLATIONS = {"TERMS_WORSENED", "BAD_SIGNATURE"}
EXCLUDING_DETECTORS = {"injection"}  # rule-based detectors whose flags get a lender excluded


class CachedSource:
    """Wraps a CRS source so each product is fetched once per session (one pull, shared by gate and passport)."""

    def __init__(self, inner):
        self.inner, self.name, self._c = inner, inner.name, {}
        self.log = inner.log

    def get(self, persona, product):
        if (persona, product) not in self._c:
            self._c[(persona, product)] = self.inner.get(persona, product)
        return self._c[(persona, product)]

    def applicant(self, persona):
        return self.inner.applicant(persona)


class Exchange:
    def __init__(self, persona, mandate=None, source=None, lenders=None, borrower=None, today=None, watchdog=False,
                 review=None):
        self.persona = persona
        self.mandate = mandate or Mandate()
        self.source = CachedSource(source or SampleSource())
        self.today = today or date.today()
        self.borrower = borrower or RuleBorrower()
        self.lenders = lenders if lenders is not None else [RuleLender(i) for i in POLICIES]
        self.keys = {}       # agent id -> signing key ("Know Your Agent": only registered agents can act)
        self.roles = {}
        for a in [self.borrower, *self.lenders]:
            self.register(a)
        self.events, self.offers, self.deal = [], {}, None
        self.round, self.closed, self.admitted = 0, False, False
        self.report = self.passport = None
        self.watchdog = Watchdog() if watchdog else None
        self.review = review   # optional ClaudeReview: advisory flags after the session closes
        self.excluded = {}     # lender id -> reason

    # ---------------------------------------------------------------- bookkeeping
    def register(self, agent):
        self.keys[agent.id] = secrets.token_bytes(32)
        self.roles[agent.id] = agent.role

    def emit(self, kind, actor, data=None, verdict=None):
        e = {"seq": len(self.events), "t": round(time.time(), 3), "round": self.round, "kind": kind, "actor": actor,
             "data": data or {}}
        if verdict:
            e["verdict"] = {"ok": verdict.ok, "code": verdict.code, "reason": verdict.reason}
        self.events.append(e)
        if self.watchdog and kind != "watchdog":
            self.flag_all(self.watchdog.review(e, self))
        return e

    def flag_all(self, flags):
        for f in flags:
            self.emit("watchdog", "watchdog", f)

    def flags_on(self, e):
        return [x["data"] for x in self.events[e["seq"] + 1:] if x["kind"] == "watchdog" and x["data"]["ref"] == e["seq"]]

    def send(self, agent, msg):
        """How agents talk: the harness signs with the agent's own key, then the referee checks it."""
        msg.round = self.round
        return self.submit(msg.sign(self.keys[agent.id]), by=agent.id)

    # ---------------------------------------------------------------- stage 1: CRS gate + passport
    def gate(self):
        self.report = screen(self.source, self.persona, "loan", explain=False, as_of=self.today)
        bureaus = {"TransUnion": S.credit(self.source.get(self.persona, "tu")),
                   "Equifax": S.credit(self.source.get(self.persona, "efx")),
                   "Experian": S.credit(self.source.get(self.persona, "exp"))}
        r = self.report
        self.admitted = r["decision"] not in BLOCKED_DECISIONS
        self.emit("gate", "referee", {
            "applicant": r["applicant"], "decision": r["decision"], "headline": r["headline"],
            "admitted": self.admitted, "crs_products": r["products_called"], "source": r["source"],
            "findings": [{k: f[k] for k in ("code", "axis", "severity", "text", "source")} for f in r["findings"]],
        })
        if not self.admitted:
            self.emit("blocked", "referee", {"reason": "Identity can't be trusted, so no lender sees this application. "
                                                       "No offers, no credit decision against the person whose identity this is.",
                                             "next_steps": r["next_steps"]})
            return False
        self.passport = PP.build(r, bureaus, self.today)
        self.emit("passport", "referee", {"passport": self.passport,
                                          "note": "Lenders see this summary only. Withheld: " + ", ".join(PP.WITHHELD) + "."})
        return True

    # ---------------------------------------------------------------- validation
    def submit(self, m: Message, by=None) -> Verdict:
        """`by` = the agent whose key signed this (the real sender, even if `m.sender` is forged)."""
        by = by or m.sender
        v = self._check(m, by)
        e = self.emit("message", m.sender, m.to_dict(), v)
        if v.ok:
            self._apply(m, e)
        self._enforce(by, v, e)
        return v

    def _enforce(self, by, v, e):
        """With the watchdog on, hard violations get a lender excluded. Deterministic; only rule-based flags count."""
        if not self.watchdog or self.roles.get(by) != "lender" or by in self.excluded:
            return
        hits = [f for f in self.flags_on(e) if f["source"] == "rules" and f["detector"] in EXCLUDING_DETECTORS
                and f["agent"] == by]
        if v.code in HARD_VIOLATIONS:
            code, why = v.code, v.reason
        elif hits:
            code, why = "INJECTION", f"Rule-based watchdog: {hits[0]['why']} Saw: {hits[0]['saw']!r}"
        else:
            return
        self.excluded[by] = code
        withdrawn = [oid for oid, o in self.offers.items() if o["lender"] == by and o["status"] == "live"]
        for oid in withdrawn:
            self.offers[oid]["status"] = "withdrawn"
        self.emit("excluded", "referee", {"agent": by, "code": code, "reason": why, "withdrawn": withdrawn,
                                          "note": f"{POLICIES.get(by, (by,))[0]} is out of this session; "
                                                  "its offers are withdrawn and further messages are rejected."})

    def _live_offer_of(self, lender):
        return next((oid for oid, o in self.offers.items() if o["lender"] == lender and o["status"] == "live"), None)

    def _check(self, m, by=None):
        V = Verdict
        if self.closed:
            return V(False, "SESSION_CLOSED", "The session is over.")
        if m.type not in TYPES:
            return V(False, "UNKNOWN_TYPE", f"{m.type!r} is not a message type.")
        if m.sender not in self.keys:
            return V(False, "UNREGISTERED", f"{m.sender!r} is not a registered agent.")
        if not m.verify(self.keys[m.sender]):
            return V(False, "BAD_SIGNATURE", f"Signature doesn't match {m.sender!r}'s key: someone else sent this.")
        if (by or m.sender) in self.excluded:
            return V(False, "EXCLUDED", f"{by or m.sender} was excluded from this session "
                                        f"({self.excluded[by or m.sender]}).")
        role = self.roles[m.sender]
        if m.type not in ROLE_TYPES[role]:
            return V(False, "WRONG_ROLE", f"A {role} can't send {m.type}.")

        if m.type == OFFER:
            t = m.terms
            if not t or t.amount <= 0 or t.term_months <= 0 or t.apr < 0 or t.fee < 0:
                return V(False, "TERMS_INVALID", "Offer terms are missing or invalid.")
            if t.apr > APR_CAP:
                return V(False, "APR_CAP", f"{t.apr}% is above the exchange's {APR_CAP}% cap.")
            if t.amount > self.mandate.amount:
                return V(False, "AMOUNT_ABOVE_ASK", "Offers can't exceed the amount the borrower asked for.")
            prev = self._live_offer_of(m.sender)
            if prev:
                old = self.offers[prev]["terms"]
                if finance.cost_per_dollar(t) > finance.cost_per_dollar(old) + 1e-9 or t.amount < old.amount:
                    return V(False, "TERMS_WORSENED", f"New offer is worse than {m.sender}'s live offer "
                             f"({old.apr}%, ${old.fee:.0f} fee). Live offers are binding; no bait-and-switch.")
            return V(True, "OK", "Valid offer.")

        if m.type in (COUNTER, ACCEPT, WITHDRAW):
            o = self.offers.get(m.offer_id)
            if not o:
                return V(False, "UNKNOWN_OFFER", f"No offer {m.offer_id!r}.")
            if o["status"] != "live":
                return V(False, "OFFER_NOT_LIVE", f"Offer {m.offer_id} is {o['status']}.")
            if m.type == WITHDRAW and o["lender"] != m.sender:
                return V(False, "NOT_YOUR_OFFER", "Lenders can only withdraw their own offers.")
            if m.type == COUNTER and not m.terms:
                return V(False, "TERMS_INVALID", "A counter needs terms.")
            if m.type == ACCEPT:
                if m.terms is None or m.terms.key() != o["terms"].key():
                    return V(False, "TERMS_MISMATCH", "Accepted terms must be exactly the offered terms.")
                ok, why = self.mandate.allows(o["terms"])
                if not ok:
                    return V(False, "OUTSIDE_MANDATE", f"Blocked: {why}. The person never authorised this, "
                                                       "whatever the agent was told.")
        return V(True, "OK", "Valid.")

    def _apply(self, m, e):
        if m.type == OFFER:
            prev = self._live_offer_of(m.sender)
            if prev:
                self.offers[prev]["status"] = "superseded"
            m.offer_id = f"o{len(self.offers) + 1}"
            self.offers[m.offer_id] = {"lender": m.sender, "terms": m.terms, "text": m.text, "status": "live",
                                       "round": self.round}
            e["data"]["offer_id"] = m.offer_id
        elif m.type == WITHDRAW:
            self.offers[m.offer_id]["status"] = "withdrawn"
        elif m.type == ACCEPT:
            self.offers[m.offer_id]["status"] = "accepted"
            self.deal = {"offer_id": m.offer_id, **self.offers[m.offer_id]}
            self.closed = True

    # ---------------------------------------------------------------- the market loop
    def run(self):
        if not self.gate():
            return self.result()
        by_id = {l.id: l for l in self.lenders}
        intent = self.borrower.intent(self.mandate)
        self.send(self.borrower, intent)
        for l in self.lenders:
            self.send(l, l.respond_to_intent(intent, self.passport))

        for rnd in range(self.mandate.max_rounds):
            self.round = rnd + 1
            live = {oid: o for oid, o in self.offers.items() if o["status"] == "live"}
            msgs = self.borrower.decide(rnd, live, self.mandate, self.passport)
            ended = False
            for m in msgs:
                v = self.send(self.borrower, m)
                if m.type == DECLINE and v.ok:
                    ended = True
                if m.type == COUNTER and v.ok and m.to in by_id and m.to not in self.excluded:
                    others = [o["terms"].apr for o in self.offers.values()  # current, not the round-start snapshot:
                              if o["status"] == "live" and o["lender"] != m.to]   # exclusion may withdraw offers mid-round
                    reply = by_id[m.to].respond_to_counter(m, self.passport,
                                                           {"best_competing_apr": min(others) if others else None})
                    for r in (reply if isinstance(reply, list) else [reply] if reply else []):
                        self.send(by_id[m.to], r)
            if self.deal or ended:
                break
        self.closed = True
        if self.watchdog:
            self.flag_all(self.watchdog.finish(self))
        if self.review:
            self.flag_all(self.review.run(self))
        if self.deal:
            self.settle()
        else:
            self.emit("no_deal", "referee", {"reason": "No offer within the person's limits.",
                                             "lender_reasons": [e["data"]["text"] for e in self.events
                                                                if e["kind"] == "message" and e["data"]["type"] == DECLINE
                                                                and self.roles.get(e["actor"]) == "lender"],
                                             "watchdog_notes": self.watchdog_notes()})
        return self.result()

    def watchdog_notes(self):
        """Plain-English watchdog flags for the person, most serious first. Flag-only: nothing here changed the deal."""
        order = {"high": 0, "medium": 1, "low": 2}
        seen, out = set(), []
        for f in sorted((e["data"] for e in self.events if e["kind"] == "watchdog"), key=lambda f: order.get(f["severity"], 3)):
            if f["severity"] not in order or f["note"] in seen:
                continue
            seen.add(f["note"])
            out.append({"severity": f["severity"], "note": f["note"], "suggestion": f.get("suggestion"),
                        "source": f["source"]})
        return out

    # ---------------------------------------------------------------- settlement + disclosure
    def settle(self):
        t, lender = self.deal["terms"], self.deal["lender"]
        steps = [f"Hard credit inquiry by {POLICIES.get(lender, (lender,))[0]} at one bureau: {SIMULATED}",
                 f"Funding ${t.amount:,.0f}: {SIMULATED}",
                 f"New account reported to all three bureaus (CRS Data Furnishing): {SIMULATED}",
                 "Lender receives the full credit file now that the borrower has accepted"]
        if self.passport.get("verification_required"):
            steps.insert(0, f"Step-up identity verification (fraud alert on file; KBA/OTP): {SIMULATED}")
        self.emit("settlement", "referee", {"steps": steps})
        self.emit("disclosure", "referee", self.disclosure())

    def disclosure(self):
        t = self.deal["terms"]
        opening = [o for o in self.offers.values() if o["round"] == 0]
        fits = [o for o in opening if self.mandate.allows(o["terms"])[0]]
        base = min(fits or opening, key=lambda o: finance.cost_per_dollar(o["terms"]))["terms"]
        pay, base_pay = finance.monthly_payment(t.amount, t.apr, t.term_months), finance.monthly_payment(
            base.amount, base.apr, base.term_months)
        lines = [f"{POLICIES.get(self.deal['lender'], (self.deal['lender'],))[0]}: ${t.amount:,.0f} at {t.apr}% for "
                 f"{t.term_months} months, ${pay:,.2f}/month, ${finance.interest_cost(t):,.2f} total interest and fees."]
        gave = []
        if t.autopay and not base.autopay:
            gave.append("agreed to autopay")
        if t.term_months > base.term_months:
            gave.append(f"a longer term ({t.term_months} vs {base.term_months} months)")
        if t.amount < self.mandate.amount:
            gave.append(f"borrowing ${t.amount:,.0f} instead of the ${self.mandate.amount:,.0f} asked for")
        if t.apr < base.apr or t.fee < base.fee:
            lines.append(f"Negotiated down from the best opening offer of {base.apr}%"
                         + (f" with a ${base.fee:.0f} fee" if base.fee else "")
                         + f": saves ${finance.total_cost(base) * t.amount / base.amount - finance.total_cost(t):,.2f} "
                           f"over the loan.")
        if gave:
            lines.append("To get this, your agent " + ", ".join(gave) + ".")
        return {"summary": lines, "monthly_payment": round(pay, 2), "baseline_monthly_payment": round(base_pay, 2),
                "total_interest_and_fees": round(finance.interest_cost(t), 2), "watchdog_notes": self.watchdog_notes()}

    def result(self):
        blocked = [e for e in self.events if e.get("verdict") and not e["verdict"]["ok"]]
        return {
            "persona": self.persona,
            "applicant": self.report["applicant"] if self.report else None,
            "admitted": self.admitted,
            "gate": {k: self.report[k] for k in ("decision", "headline")} if self.report else None,
            "passport": self.passport,
            "mandate": {**vars(self.mandate), "allow": sorted(self.mandate.allow)},
            "deal": ({"lender": self.deal["lender"], "lender_name": POLICIES.get(self.deal["lender"], (self.deal["lender"],))[0],
                      "terms": vars(self.deal["terms"])} if self.deal else None),
            "blocked": [{"seq": e["seq"], "actor": e["actor"], **e["verdict"]} for e in blocked],
            "watchdog": [{"seq": e["seq"], **e["data"]} for e in self.events if e["kind"] == "watchdog"],
            "excluded": [{"seq": e["seq"], **e["data"]} for e in self.events if e["kind"] == "excluded"],
            "events": self.events,
        }
