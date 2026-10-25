"""Simulated lenders. Each has a FIXED underwriting policy (eligibility + price range) computed from the passport.

Two layers on purpose:
  - policy (here, deterministic): who they lend to and the APR range they're allowed to offer. Explainable pricing.
  - negotiation (the agent): how they move inside that range. RuleLender below is a simple stand-in;
    a Claude-powered lender should subclass it and override `respond_to_counter` only, never `policy`.
"""
from dataclasses import dataclass
from typing import Optional

from . import finance, pricing as P
from .messages import Message, Terms, OFFER, DECLINE, APR_CAP


@dataclass
class Quote:
    """A lender's view of one borrower, computed from its books (exchange/pricing.py) at its default loan terms.
    floor_apr / autopay_discount are for `term` and `max_amount`; other terms are priced with `RuleLender.floor_for`."""
    eligible: bool
    reason: str
    open_apr: float = 0.0
    floor_apr: float = 0.0       # lowest APR it accepts at `term`, without autopay
    autopay_discount: float = 0.0
    max_amount: float = 0.0
    term: int = 36
    fee: float = 0.0
    pd: float = 0.0              # its estimate of the borrower's annual probability of default


# ---------------------------------------------------------------- each lender's private books (illustrative)
BOOKS = {
    "prime_bank": P.Book(cost_of_funds=4.0, servicing=1.0, origination_cost=150, lgd=0.85, capital_ratio=0.10,
                         roe_hurdle=0.12, target_margin=2.5, min_margin=0.75, volume_target=400, booked=260,
                         month_progress=0.6, risk_bucket_fill=0.5, terms=(24, 36, 48, 60), preferred_term=36,
                         max_amount=25000,
                         motive="Ahead of its monthly target with cheap deposit funding, so it protects its margin "
                                "and concedes slowly."),
    "campus_cu": P.Book(cost_of_funds=2.5, servicing=0.8, origination_cost=100, lgd=0.80, capital_ratio=0.07,
                        roe_hurdle=0.08, target_margin=1.5, min_margin=0.25, volume_target=120, booked=40,
                        month_progress=0.6, risk_bucket_fill=0.4, terms=(12, 24, 36, 48), preferred_term=36,
                        max_amount=5000,
                        motive="Member-owned with cheap funding and well behind its loan goal this month, so it "
                               "concedes early."),
    "newstart": P.Book(cost_of_funds=7.0, servicing=1.5, origination_cost=80, lgd=0.85, capital_ratio=0.15,
                       roe_hurdle=0.15, target_margin=3.0, min_margin=1.0, volume_target=2000, booked=1100,
                       month_progress=0.6, risk_bucket_fill=0.6, terms=(12, 24), preferred_term=24, max_amount=3000,
                       motive="Funded by an expensive credit line, so even its best rates sit high; growing in "
                              "new-to-credit customers."),
    "second_chance": P.Book(cost_of_funds=7.5, servicing=2.5, origination_cost=200, lgd=0.65, capital_ratio=0.15,
                            roe_hurdle=0.15, target_margin=4.0, min_margin=2.0, volume_target=300, booked=150,
                            month_progress=0.6, risk_bucket_fill=0.85, terms=(12, 24, 36), preferred_term=36,
                            max_amount=5000, fee=150,
                            motive="Subprime specialist whose high-risk bucket is nearly full, so it prices firmly "
                                   "and gives up its fee before its rate."),
    "harbor": P.Book(cost_of_funds=4.5, servicing=1.2, origination_cost=60, lgd=0.80, capital_ratio=0.10,
                     roe_hurdle=0.10, target_margin=2.0, min_margin=0.5, volume_target=200, booked=80,
                     month_progress=0.6, risk_bucket_fill=0.4, terms=(12, 24), preferred_term=24, max_amount=3000,
                     pd_model="identity",
                     motive="Mission lender with community-development funding, building a book of newcomers. "
                            "With no score to lean on it prices on identity strength and on-time history, and it "
                            "is behind its monthly goal."),
    "ladder": P.Book(cost_of_funds=4.0, servicing=2.0, origination_cost=40, lgd=0.60, capital_ratio=0.12,
                     roe_hurdle=0.10, target_margin=2.5, min_margin=1.0, volume_target=150, booked=70,
                     month_progress=0.6, risk_bucket_fill=0.5, terms=(12, 18, 24), preferred_term=24,
                     max_amount=2000, min_amount=500, autopay_margin_cut=1.0, reports_payments=True,
                     motive="Credit-builder lender: small loans for people rebuilding after charge-offs or a "
                            "bankruptcy. Autopay keeps its borrowers on track, so it cuts its margin for it, and it "
                            "reports on-time payments to the bureaus (simulated)."),
}
REPORTING_NOTE = "On-time payments reported to the bureaus (simulated)."


def priced(lender_id, p, reason):
    """An eligible Quote, priced from the lender's books at its default terms. If even its floor is above the legal
    rate cap, it can't cover the risk and declines (rate caps make lenders decline, not lend at a loss)."""
    b = BOOKS[lender_id]
    amt, term = b.max_amount, b.preferred_term
    flo = P.floor(b, p, amt, term)
    if flo > APR_CAP:
        return Quote(False, f"at this score the risk can't be priced under the {APR_CAP:g}% rate cap")
    return Quote(True, reason, min(P.opening(b, p, amt, term), APR_CAP), flo,
                 round(flo - P.floor(b, p, amt, term, autopay=True), 2), amt, term, b.fee,
                 round(P.pd_annual(p, b.pd_model)[0], 4))


def prime_bank(p):
    if p["no_file"] or p["no_score"]:
        return Quote(False, "needs a scored credit file")
    if p["score_low"] < 700:
        return Quote(False, f"lowest score {p['score_low']} is below our 700 minimum")
    if p["late_payments"] or p["collections"] or p["chargeoffs"]:
        return Quote(False, "needs a file with no late payments, collections or charge-offs")
    if p["thin_file"]:
        return Quote(False, "needs at least 3 accounts of history")
    if p["bureau_disagreements"]:
        return Quote(False, "the bureaus disagree about this file; we only lend on consistent files")
    return priced("prime_bank", p, "prime file")


def campus_cu(p):
    if p["no_file"]:
        return Quote(False, "needs at least one account on file")
    if p["collections"] or p["chargeoffs"] or p["bankruptcies"]:
        return Quote(False, "no collections, charge-offs or bankruptcies")
    if p["score_low"] is not None and p["score_low"] < 620:
        return Quote(False, f"lowest score {p['score_low']} is below our 620 minimum")
    if not (p["thin_file"] or p["no_score"] or (p["file_age_years"] or 0) <= 12):
        return Quote(False, "membership is for students and people with short credit histories")
    return priced("campus_cu", p, "short histories welcome")


def newstart_fintech(p):
    if p["identity"] != "strong":
        return Quote(False, "we lend on identity strength, and this identity isn't strong enough")
    if p["bankruptcies"]:
        return Quote(False, "no bankruptcies")
    if not (p["no_file"] or p["no_score"] or p["thin_file"] or (p["score_low"] or 0) >= 600):
        return Quote(False, "we focus on new-to-credit and thin files")
    return priced("newstart", p, "new to credit, strong identity")


def second_chance(p):
    if p["identity"] == "weak":
        return Quote(False, "identity checks didn't pass")
    if p["no_file"] or p["score_low"] is None:
        return Quote(False, "needs a scored file")
    if p["score_low"] < 500:
        return Quote(False, f"lowest score {p['score_low']} is below our 500 minimum")
    return priced("second_chance", p, "rebuilding credit")


HARBOR_MIN_IDENTITY = 80
LADDER_MIN_SCORE = 500


def harbor_newcomer(p):
    """Uses: no_file, thin_file, identity_score, collections, chargeoffs, bankruptcies (+ positive evidence in price)."""
    if not (p["no_file"] or p["thin_file"]):
        return Quote(False, "we serve people new to credit: no file, or fewer than 3 accounts")
    if p["identity_score"] < HARBOR_MIN_IDENTITY:
        return Quote(False, f"we lend on identity strength, and an identity score of {p['identity_score']} is below "
                            f"our {HARBOR_MIN_IDENTITY} minimum")
    if p["collections"] or p["chargeoffs"] or p["bankruptcies"] or p["bankruptcy_public_record"]:
        return Quote(False, "no collections, charge-offs or bankruptcies")
    return priced("harbor", p, "new to credit, priced on identity strength")


def ladder_builder(p):
    """Uses: identity, no_file, chargeoffs, bankruptcy_public_record/discharged, collections, late_payments, score_low."""
    if p["identity"] == "weak":
        return Quote(False, "identity checks didn't pass")
    if p["no_file"]:
        return Quote(False, "our builder loans are for people rebuilding a file they already have")
    rebuilding = p["chargeoffs"] or p["bankruptcy_discharged"]
    if not rebuilding:
        return Quote(False, "we serve people rebuilding after charge-offs or a discharged bankruptcy")
    if p["bankruptcy_public_record"] and not p["bankruptcy_discharged"]:
        return Quote(False, "a bankruptcy still in progress; we can help once it's discharged")
    if p["collections"]:
        return Quote(False, "no open collections")
    if p["late_payments"]:
        return Quote(False, "needs no late payments since the past problems")
    if p["score_low"] is not None and p["score_low"] < LADDER_MIN_SCORE:
        return Quote(False, f"lowest score {p['score_low']} is below our {LADDER_MIN_SCORE} minimum")
    return priced("ladder", p, "rebuilding credit with a small builder loan")


POLICIES = {
    "prime_bank": ("Prime Bank", prime_bank),
    "campus_cu": ("Campus Credit Union", campus_cu),
    "newstart": ("NewStart Fintech", newstart_fintech),
    "second_chance": ("Second Chance Lending", second_chance),
    "harbor": ("Harbor Newcomer Lending", harbor_newcomer),
    "ladder": ("Ladder Credit Builder", ladder_builder),
}


class RuleLender:
    """A lender's negotiating agent. Its limits come from its own books (`pricing.py`); this class decides how it
    moves inside them:
      - concedes from its opening rate toward its floor over the rounds, faster when it's behind its volume target
      - prices whatever loan length the borrower asks for, if it offers that length (a restructure)
      - knows nothing about rival lenders except a verified, anonymous competing offer the borrower chose to show
    A Claude-powered lender overrides `respond_to_counter`; `floor_for` stays the hard limit."""
    role = "lender"

    def __init__(self, agent_id):
        self.id = agent_id
        self.name, self.policy = POLICIES[agent_id]
        self.book = BOOKS.get(agent_id)
        self.quote: Optional[Quote] = None
        self.current: Optional[Terms] = None
        self.passport, self.intent_ask = None, {}

    # ---------------------------------------------------------------- economics for any terms
    def floor_for(self, t):
        """The lowest APR it accepts for these exact terms (amount, length, autopay, fee)."""
        if not self.book:
            return self.quote.floor_apr - (self.quote.autopay_discount if t.autopay else 0)
        return P.floor(self.book, self.passport, t.amount, t.term_months, t.autopay, t.fee)

    def opening_for(self, t):
        """Its opening rate for these terms: the floor plus the room it starts with."""
        if not self.book:
            return self.quote.open_apr
        return round(self.floor_for(t) + max(0.0, self.book.target_margin - self.book.effective_min_margin), 2)

    def within_books(self, apr, term, autopay, fee):
        """Final (apr, fee) for a reply: never below the floor for those exact terms, and on the same loan length
        never worse for the borrower than the live offer (offers are binding). Waiving a fee costs the lender, so it
        raises the rate to cover it; if that would leave the borrower worse off overall, it keeps the fee instead."""
        cur = self.current
        apr = max(apr, self.floor_for(Terms(cur.amount, 0.0, term, autopay, fee)))
        if term != cur.term_months:
            return round(apr, 2), fee        # a restructure the borrower asked for: priced fresh
        cand = Terms(cur.amount, round(apr, 2), term, autopay, fee)
        if fee != cur.fee and finance.cost_per_dollar(cand) > finance.cost_per_dollar(cur) + 1e-9:
            fee = cur.fee                    # the waiver isn't worth it for the borrower: keep the fee
        if fee == cur.fee:
            apr = min(max(apr, self.floor_for(Terms(cur.amount, 0.0, term, autopay, fee))), cur.apr)
        return round(apr, 2), fee

    def _term(self, ask):
        lo, hi = ask.get("term_range", [12, 48])
        if not self.book:
            return max(lo, min(hi, self.quote.term))
        ok = [n for n in self.book.terms if lo <= n <= hi]
        if not ok:
            return None
        return min(ok, key=lambda n: (abs(n - self.book.preferred_term), -n))

    # ---------------------------------------------------------------- messages
    def respond_to_intent(self, intent: Message, passport) -> Message:
        self.passport, self.intent_ask = passport, intent.ask or {}
        self.quote = q = self.policy(passport)
        if not q.eligible:
            return Message(DECLINE, self.id, to=intent.sender, text=f"{self.name}: {q.reason}.")
        term = self._term(self.intent_ask)
        if term is None:
            return Message(DECLINE, self.id, to=intent.sender,
                           text=f"{self.name}: we only lend for {', '.join(map(str, self.book.terms))} months.")
        amt = min(self.intent_ask.get("amount", q.max_amount), q.max_amount)
        if self.book and amt < self.book.min_amount:
            return Message(DECLINE, self.id, to=intent.sender,
                           text=f"{self.name}: our loans start at ${self.book.min_amount:,.0f}.")
        base = Terms(amt, 0.0, term, False, q.fee)
        apr = min(self.opening_for(base), APR_CAP)
        if self.floor_for(base) > APR_CAP:
            return Message(DECLINE, self.id, to=intent.sender,
                           text=f"{self.name}: at this score the risk can't be priced under the {APR_CAP:g}% rate cap.")
        self.current = Terms(amt, apr, term, False, q.fee)
        return Message(OFFER, self.id, to=intent.sender, terms=self.current,
                       text=f"{self.name}: {q.reason}. ${amt:,.0f} at {apr}% for {term} months"
                            + (f", ${q.fee:.0f} origination fee." if q.fee else ".")
                            + (f" {REPORTING_NOTE}" if self.book and self.book.reports_payments else ""))

    def respond_to_counter(self, counter: Message, passport, market) -> Optional[Message]:
        """market = {"round", "max_rounds", "verified_quote"}: verified_quote is an anonymous competing offer the
        borrower cited and the referee checked ({apr, term_months, amount, ...}), or None. Never a rival's name."""
        cur, want = self.current, counter.terms
        rnd, rounds, vq = market.get("round", 1), market.get("max_rounds", 4), market.get("verified_quote")
        term = want.term_months if (self.book and want.term_months in self.book.terms) else cur.term_months
        autopay = want.autopay
        fee = cur.fee
        if want.fee < fee and autopay:      # it trades its fee for autopay, and prices the lost fee in
            fee = 0.0
        shape = Terms(cur.amount, 0.0, term, autopay, fee)
        flo = self.floor_for(shape)
        target = P.concession_target(self.book, self.opening_for(shape), flo, rnd, rounds) if self.book else flo
        why = ""
        if vq and vq.get("apr") is not None:
            beat = round(vq["apr"] - 0.1, 2)
            if beat >= flo and beat < target:
                target, why = beat, f" to beat the verified {vq['apr']}% offer"
            elif beat < flo:
                why = f"; we can't profitably match {vq['apr']}%"
        apr, fee = self.within_books(round(max(want.apr, target, flo), 2), term, autopay, fee)
        if apr > APR_CAP:
            return Message(DECLINE, self.id, to=counter.sender, offer_id=counter.offer_id,
                           text=f"{self.name}: at {term} months we can't price it under the {APR_CAP:g}% cap.")
        new = Terms(cur.amount, apr, term, autopay, fee)
        if new.key() == cur.key():
            return Message(DECLINE, self.id, to=counter.sender, offer_id=counter.offer_id,
                           text=f"{self.name}: {cur.apr}% is our best{why}.")
        self.current = new
        parts = [f"we can do {apr}%"]
        if term != cur.term_months:
            parts.append(f"over {term} months")
        if autopay:
            parts.append("with autopay")
        if cur.fee and not fee:
            parts.append("fee waived")
        return Message(OFFER, self.id, to=counter.sender, terms=new,
                       text=f"{self.name}: " + ", ".join(parts) + f"{why}.")
