"""The person's screen: what the borrower sees, in plain words. Deterministic code, no AI.

`build(ex)` after `ex.run()` returns one dict: outcome, what they agreed to (`before`), the deal or why there's none,
real threats we stopped (`protection`), and what helped them. Written for people with thin or no credit history:
no codes, no raw passport fields, every number tied to something they can act on. Paths to approval re-run the
lenders' own policies on a modified COPY of the passport; they say "would likely", never promise.
"""
import copy, re
from itertools import combinations

from . import finance
from .lenders import POLICIES
from .messages import Terms
from .watchdog import PERSONAL

SOFT_PULL = "Checking won't affect your credit score."
PRIVACY = "Lenders see a summary, never your name, SSN or address."
SEVERITY = {"high": 0, "medium": 1}   # only these reach the person; low/info and sales pressure never do


# ---------------------------------------------------------------- small helpers
def _c(x):
    return round(float(x), 2)


def _usd(x):
    """Whole dollars when there are no cents: "$5,000"; otherwise "$166.07"."""
    return f"${x:,.0f}" if abs(x - round(x)) < 0.005 else f"${x:,.2f}"


def _name(agent):
    return POLICIES.get(agent, (agent,))[0]


def _s(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def _join(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def _pay(t):
    return finance.monthly_payment(t.amount, t.apr, t.term_months)


def _finding(ex, code):
    return next((f for f in (ex.report or {}).get("findings", []) if f["code"] == code), None)


def _one_bureau(ex):
    """The single-bureau collection, if any: {"bureaus": [...], "others": [...], "creditor", "text", "left"}."""
    f = _finding(ex, "DEROG_ONLY_ONE_BUREAU")
    if not f:
        return None
    counts = f.get("value") if isinstance(f.get("value"), dict) else {}
    only = [b for b, n in counts.items() if n] or [m.group(1) for m in [re.search(r"only at ([^.]+)\.", f["text"])] if m]
    m = re.search(r"\(([^)]+)\)", f["text"])
    return {"bureaus": only, "others": [b for b in counts if b not in only], "creditor": m.group(1) if m else None,
            "text": f["text"], "left": max((n for b, n in counts.items() if b not in only), default=0)}


# ---------------------------------------------------------------- build
def build(ex):
    """Call after ex.run(). Returns the person's view (see module docstring); keys are a contract with the UI."""
    pending = getattr(ex, "awaiting_approval", lambda: False)()
    outcome = ("blocked" if not ex.admitted else "awaiting_approval" if pending else "deal" if ex.deal
               else "no_deal")
    return {
        "outcome": outcome,
        "before": before(ex.mandate),
        "deal": deal(ex) if outcome in ("deal", "awaiting_approval") else None,
        "protection": protection(ex),
        "no_deal": no_deal(ex) if outcome == "no_deal" else None,
        "blocked": blocked(ex) if outcome == "blocked" else None,
        "helped": helped(ex) if outcome != "blocked" else [],
    }


def before(m):
    mp = getattr(m, "max_payment", None)
    return {
        "amount": _c(m.amount), "min_amount": _c(m.min_amount),
        "term": f"{m.min_term} months" if m.min_term == m.max_term else f"{m.min_term} to {m.max_term} months",
        "max_monthly_payment": _c(mp) if mp else None,
        "advanced": {"max_apr": float(m.max_apr), "max_fee": _c(m.max_fee), "autopay_ok": "autopay" in m.allow},
        "soft_pull": SOFT_PULL,
        "privacy": PRIVACY,
    }


# ---------------------------------------------------------------- deal
def _best_first(ex):
    """The best opening offer (inside the limits if any were), ignoring lenders removed for breaking the rules."""
    opening = [o for o in ex.offers.values() if o["round"] == 0 and o["lender"] not in ex.excluded]
    fits = [o for o in opening if ex.mandate.allows(o["terms"])[0]]
    pool = fits or opening
    return min(pool, key=lambda o: finance.cost_per_dollar(o["terms"])) if pool else None


def deal(ex):
    t, name = ex.deal["terms"], _name(ex.deal["lender"])
    pay, base = _pay(t), _best_first(ex)
    saved = None
    if base:
        b = base["terms"]
        amt = finance.total_cost(b) * t.amount / b.amount - finance.total_cost(t)
        if amt >= 1:
            saved = {"amount": _c(amt),
                     "sentence": f"Your agent saved you ${amt:,.0f} compared with the best first offer "
                                 f"({b.apr:g}% from {_name(base['lender'])})."}
    return {
        "lender": name, "monthly_payment": _c(pay), "apr": float(t.apr), "term_months": int(t.term_months),
        "amount": _c(t.amount), "fee": _c(t.fee), "total_paid": _c(finance.total_cost(t)),
        "saved": saved,
        "traded": traded(t, base, ex.deal["lender"], ex.mandate),
        "on_accept": on_accept(ex, name, t),
        "headline": f"{name} lends you {_usd(t.amount)}: {_usd(pay)} a month for {t.term_months} months.",
    }


def traded(t, first, lender, m):
    """What the agent gave up, compared with the best first offer (`first`, an offer dict or None)."""
    out, base = [], first["terms"] if first else None
    same = bool(first) and first["lender"] == lender
    if t.autopay:
        out.append("Agreed to autopay (payments come out automatically each month), which lowered the rate."
                   if same and not base.autopay and t.apr < base.apr else
                   "Agreed to autopay (payments come out automatically each month).")
    if same and t.term_months > base.term_months:
        out.append(f"Took a longer loan ({t.term_months} months instead of {base.term_months}), so you pay for longer.")
    if (first and not same and base.amount < t.amount
            and finance.cost_per_dollar(base) < finance.cost_per_dollar(t)):
        out.append(f"Took the full {_usd(t.amount)} at {t.apr:g}% instead of {_usd(base.amount)} at {base.apr:g}% "
                   f"from {_name(first['lender'])}.")
    if t.amount < m.amount:
        out.append(f"Borrowing {_usd(t.amount)} instead of the {_usd(m.amount)} you asked for.")
    if t.fee:
        out.append(f"Pays a one-time {_usd(t.fee)} fee, which is inside your limit.")
    return out


def on_accept(ex, name, t):
    steps = []
    if (ex.passport or {}).get("verification_required"):
        why = ("because there's a fraud alert on your file" if _finding(ex, "FRAUD_ALERT_ON_FILE")
               else "because some identity details need a second look")
        steps.append(f"First you confirm it's really you, with a few questions or a code, {why}.")
    steps += [f"{name} runs a hard credit check. Your score may dip a few points.",
              f"{name} gets your full credit file.",
              f"{name} sends you {_usd(t.amount)}.",
              "The new loan shows up at all three credit bureaus. Paying on time builds your credit."]
    return [{"text": s, "simulated": True} for s in steps]   # none of this happens in the CRS sandbox


# ---------------------------------------------------------------- protection: real threats only
def _asked(ex, f):
    """What personal data the lender asked for, re-read from the message it flagged."""
    ref = f.get("ref")
    text = ex.events[ref]["data"].get("text") or "" if isinstance(ref, int) and ref < len(ex.events) else ""
    out = []
    for m in PERSONAL.finditer(text):
        w = m.group(0).lower()
        word = "SSN" if ("ssn" in w or "social" in w) else "bank login" if "bank" in w else "date of birth"
        if word not in out:
            out.append(word)
    return out


def protection(ex):
    items, seen = [], set()

    def add(key, severity, sentence, meaning):
        if key not in seen:
            seen.add(key)
            items.append({"sentence": sentence, "meaning": meaning, "severity": severity})

    # 1. lenders the referee removed
    for lid, code in ex.excluded.items():
        n = _name(lid)
        if code == "INJECTION":
            add(("injection", lid), "high", f"{n} tried to trick your agent with hidden instructions. We removed it.",
                "Some lenders' agents hide commands in their messages. Here only the loan's numbers count, so it "
                "couldn't make your agent say yes.")
        elif code == "TERMS_WORSENED":
            add(("worse", lid), "high", f"{n} tried to swap in a worse deal after making an offer. We removed it.",
                "Once a lender makes an offer here, it can't raise the price. It can only offer you something better.")
        elif code == "BAD_SIGNATURE":
            add(("forged", lid), "high", f"{n} sent a message pretending to be someone else. We removed it.",
                "Every message is checked to prove who sent it, so fakes don't count.")
        else:
            add(("excluded", lid), "high", f"{n} broke the exchange's rules. We removed it.",
                "Its offers were taken away and it couldn't send anything else.")

    # 2. moves the referee blocked (these hold even with the watchdog off)
    for e in ex.events:
        if e["kind"] != "message" or e["verdict"]["ok"]:
            continue
        code, actor, d = e["verdict"]["code"], e["actor"], e["data"]
        if code == "BAD_SIGNATURE" and ex.roles.get(actor) == "borrower":
            to = f"{_name(d['to'])}'s offer" if d.get("to") in ex.roles else "an offer"
            add(("forged_accept", d.get("to")), "high",
                f"Someone tried to accept {to} while pretending to be your agent. We blocked it.",
                "Only your agent can say yes for you, and every message is checked to prove who sent it.")
        elif code == "BAD_SIGNATURE":
            add(("forged", actor), "high", f"A fake message claiming to be from {_name(actor)} was blocked.",
                "Every message is checked to prove who sent it, so fakes don't count.")
        elif code == "TERMS_WORSENED":
            add(("worse", actor), "high", f"{_name(actor)} tried to swap in a worse deal after making an offer. "
                                          "We blocked it.",
                "Once a lender makes an offer here, it can't raise the price. It can only offer you something better.")
        elif code == "OUTSIDE_MANDATE":
            add(("outside", actor), "high", "Your agent tried to accept a loan outside your limits. We blocked it.",
                "Your limits are enforced by the exchange, not by the agent. But this agent may not be working for "
                "you, so be careful trusting it.")

    # 3. watchdog flags: rule-based, high or medium, never sales pressure
    for e in ex.events:
        if e["kind"] != "watchdog":
            continue
        f = e["data"]
        if f.get("source") != "rules" or f["severity"] not in SEVERITY or f["detector"] == "pressure":
            continue
        det, a, why = f["detector"], f["agent"], f.get("why") or ""
        n = _name(a)
        if det == "injection" and ex.roles.get(a) == "lender":
            add(("injection", a), "high", f"{n} tried to trick your agent with hidden instructions. We ignored them.",
                "Here only the loan's numbers count, so hidden instructions can't make your agent say yes.")
        elif det == "injection":
            add(("injection", a), "high", "Your agent sent a message with hidden instructions in it.",
                "Only the loan's numbers count here, so the words can't change anything. Keep an eye on this agent.")
        elif det == "personal_data":
            asked = _asked(ex, f)
            add(("personal", a), "high",
                f"{n} asked for your {_join(asked) if asked else 'personal details'}. "
                f"Never share {'it' if len(asked) == 1 else 'them'}.",
                "Lenders here never need these to make an offer. Asking for them is a common scam. If you accept a "
                "deal, the lender gets your file through the exchange, not from you.")
        elif det == "text_vs_terms" and why.startswith("Text says"):
            add(("worse", a), "medium", f"{n} said the deal was the same but quietly raised the price.",
                "Only the numbers in an offer count, not what the message says. Our rules caught the change.")
        elif det == "text_vs_terms" and "fee" in why.lower():
            add(("fee", a), "medium", f"{n} mentioned a fee that isn't in its offer.",
                "Only fees written into the offer count. If anyone adds a fee later, you don't have to agree.")
        elif det == "text_vs_terms":
            add(("rate", a), "medium", f"{n}'s message named a different rate than its real offer.",
                "Trust the numbers in the offer, not the sales message.")
        elif det == "borrower_drift" and "tried to accept" in why:
            add(("outside", a), "high", "Your agent tried to accept a loan outside your limits. We blocked it.",
                "Your limits are enforced by the exchange, not by the agent. But this agent may not be working for "
                "you, so be careful trusting it.")
        elif det == "borrower_drift" and "costlier" in why:
            m = re.search(r"about (\$[\d,]+) more", f.get("note") or "")
            add(("costlier", a), "medium", "Your agent picked a pricier offer when a cheaper one fit your limits.",
                f"That costs you about {m.group(1)} more over the loan." if m else "That costs you more over the loan.")
        elif det == "borrower_drift":
            add(("leak", a), "high", "Your agent told lenders the highest rate you'd accept.",
                "Lenders could use that to charge you more instead of competing for you.")
        elif det == "bureau_disagreement" and ex.deal:   # with no deal, `no_deal.bureau_dispute` covers this
            ob = _one_bureau(ex)
            if ob:
                add(("bureau",), "medium", f"A collection shows up at only one credit bureau ({_join(ob['bureaus'])}).",
                    "If it isn't yours or it's already paid, getting it fixed could get you better rates next time.")
    return sorted(items, key=lambda i: SEVERITY[i["severity"]])


# ---------------------------------------------------------------- no deal
def _live(ex):
    """Each lender's last standing offer at the end (removed lenders don't count)."""
    return {oid: o for oid, o in ex.offers.items() if o["status"] == "live" and o["lender"] not in ex.excluded}


def _breaks(m, t):
    """Every limit an offer breaks, plainest first: list of kinds."""
    out = []
    mp = getattr(m, "max_payment", None)
    if mp is not None and _pay(t) > mp + 0.005:
        out.append("payment")
    if t.apr > m.max_apr:
        out.append("apr")
    if not (m.min_amount <= t.amount <= m.amount):
        out.append("amount")
    if not (m.min_term <= t.term_months <= m.max_term):
        out.append("term")
    if t.fee > m.max_fee:
        out.append("fee")
    if t.autopay and "autopay" not in m.allow:
        out.append("autopay")
    return out


def _offer_reason(lead, t, kind, m):
    mp = getattr(m, "max_payment", None)
    return {
        "payment": f"{lead} was {_usd(_pay(t))} a month, above your {_usd(mp or 0)} limit",
        "apr": f"{lead} was {t.apr:g}% a year, above your {m.max_apr:g}% limit",
        "amount": f"{lead} was for {_usd(t.amount)}, less than the {_usd(m.min_amount)} you need",
        "term": f"{lead} was for {t.term_months} months, outside your {m.min_term} to {m.max_term} months",
        "fee": f"{lead} had a {_usd(t.fee)} fee, above your {_usd(m.max_fee)} limit",
        "autopay": f"{lead} needed autopay, which you didn't allow",
    }[kind]


def reasons(ex, live):
    p, m, out = ex.passport, ex.mandate, []
    if live:
        best = min(live.values(), key=lambda o: finance.cost_per_dollar(o["terms"]))
        kinds = _breaks(m, best["terms"])
        if kinds:
            out.append(_offer_reason("The only offer" if len(live) == 1 else "The best offer", best["terms"], kinds[0], m))
    ob = _one_bureau(ex)
    if p["no_file"]:
        out.append("No credit file at any bureau yet")
    if p["no_score"]:
        out.append("No credit score right now")
    if p["thin_file"]:
        out.append(f"Only {_s(p['accounts'], 'account')} so far")
    if p["collections"]:
        out.append(f"A collection shows at {_join(ob['bureaus'])} only" if ob
                   else f"{_s(p['collections'], 'debt')} in collections")
    if p["chargeoffs"]:
        out.append(f"{_s(p['chargeoffs'], 'past debt')} written off as unpaid")
    if p["bankruptcies"]:
        out.append("A bankruptcy on your file")
    if p["late_payments"]:
        out.append(f"{_s(p['late_payments'], 'late payment')}")
    if p["score_low"] is not None and p["score_low"] < 700:
        out.append(f"Lowest credit score is {p['score_low']}")
    if p["bureau_disagreements"] and not ob:
        out.append("The credit bureaus don't all agree about your file")
    if p["identity"] != "strong":
        out.append("Some identity checks came back unclear")
    return out[:3] or ["No lender offered a loan inside your limits"]


def _fixes(ex):
    """Passport changes a person can work toward, smallest first: [(change text, apply(passport copy))].
    Late payments, write-offs and bankruptcies are left out: they stay on a file for years, so they aren't a path."""
    p, out = ex.passport, []
    ob = _one_bureau(ex)
    if ob:
        what = f"{ob['creditor']} collection" if ob["creditor"] else "collection"

        def fix_bureau(q, ob=ob):
            q["collections"] = min(q["collections"], ob["left"])
            q["bureau_disagreements"] = [d for d in q["bureau_disagreements"] if d != ob["text"]]
        out.append((f"get the {what} at {_join(ob['bureaus'])} fixed, if it's wrong", fix_bureau))
    elif p["collections"]:
        out.append((f"clear the {_s(p['collections'], 'collection')} from your file",
                    lambda q: q.update(collections=0)))
    if p["thin_file"]:
        out.append((f"get to 3 accounts in good standing (you have {p['accounts']} now)",
                    lambda q: q.update(accounts=3, thin_file=False)))
    if p["no_file"]:
        out.append(("open your first credit account, such as a secured card, and pay it on time",
                    lambda q: q.update(no_file=False, bureaus_with_file=1, accounts=1, thin_file=True, no_score=True)))
    return out


def _score_needed(policy, q):
    """Lowest score (above the current one) at which this policy says yes, or None."""
    if q["no_file"]:
        return None
    start = 300 if q["score_low"] is None else q["score_low"] + 1
    for s in range(start, 851):
        if policy({**q, "score_low": s, "no_score": False}).eligible:
            return s
    return None


def _path(ex, policy):
    """Smallest set of changes (at most two, plus a score target) that flips this lender to eligible."""
    p, fixes = ex.passport, _fixes(ex)
    for k in range(0, min(2, len(fixes)) + 1):
        for combo in combinations(fixes, k):
            q = copy.deepcopy(p)
            for _, apply in combo:
                apply(q)
            changes = [text for text, _ in combo]
            if not policy(q).eligible:
                s = _score_needed(policy, q)
                if s is None:
                    continue
                changes.append(f"build a credit score of at least {s}" if p["score_low"] is None
                               else f"raise your lowest credit score to {s} (it's {p['score_low']} now)")
                q = {**q, "score_low": s, "no_score": False}
            if changes:
                return changes, policy(q)
    return None


def _best_terms(quote, m):
    """The best a lender's policy allows inside these limits (what a good negotiation could reach)."""
    auto = "autopay" in m.allow
    return Terms(min(m.amount, quote.max_amount), round(quote.floor_apr - (quote.autopay_discount if auto else 0), 2),
                 max(m.min_term, min(m.max_term, quote.term)), auto, 0.0 if auto else quote.fee)


def _limit_item(o, m):
    t, n, kinds = o["terms"], _name(o["lender"]), _breaks(m, o["terms"])
    pay = _usd(_pay(t))
    change = {"payment": f"Allow payments up to {pay} a month", "apr": f"Allow up to {t.apr:g}% a year",
              "amount": f"Borrow {_usd(t.amount)} instead of at least {_usd(m.min_amount)}",
              "term": f"Allow a {t.term_months}-month loan", "fee": f"Allow a one-time {_usd(t.fee)} fee",
              "autopay": "Allow autopay"}
    sentence = (f"If {_usd(t.amount)} is enough and you could pay {pay} a month for {t.term_months} months, "
                if "amount" in kinds else f"If you could pay {pay} a month for {t.term_months} months, ")
    sentence += f"{n} would likely say yes."
    if "apr" in kinds:
        close = t.apr - m.max_apr <= 1
        sentence += f" That's {t.apr:g}% a year, {'just ' if close else ''}above your {m.max_apr:g}% limit."
    if "fee" in kinds:
        sentence += f" It also has a {_usd(t.fee)} fee."
    return {"change": " and ".join(change[k] for k in kinds), "lender": n, "sentence": sentence}


def what_would_change(ex, live):
    m, items = ex.mandate, []
    for o in live.values():                       # offers that broke the person's limits
        if _breaks(m, o["terms"]):
            items.append((o["terms"].apr, _limit_item(o, m)))
    offered = {o["lender"] for o in live.values()}
    for l in ex.lenders:                          # lenders that said no: what would flip their own rules
        if l.id not in POLICIES or l.id in ex.excluded or l.id in offered:
            continue
        name, policy = POLICIES[l.id]
        if policy(ex.passport).eligible:
            continue
        hit = _path(ex, policy)
        if not hit:
            continue
        changes, quote = hit
        if not m.allows(_best_terms(quote, m))[0]:
            continue                              # even a great negotiation wouldn't fit the limits
        first = Terms(min(m.amount, quote.max_amount), quote.open_apr, max(m.min_term, min(m.max_term, quote.term)))
        change = " and ".join(changes)
        items.append((_best_terms(quote, m).apr, {
            "change": change[0].upper() + change[1:], "lender": name,
            "sentence": f"Then {name}'s rules would allow a loan of {_usd(first.amount)}, likely starting around "
                        f"{_usd(_pay(first))} a month."}))
    items.sort(key=lambda x: x[0])
    return [i for _, i in items[:3]]


def bureau_dispute(ex):
    ob = _one_bureau(ex)
    if not ob:
        return None
    where, others = _join(ob["bureaus"]), ob["others"]
    why = (f"{_join(others)} {'doesn' if len(others) == 1 else 'don'}'t show it, so it may be an error or out of date."
           if others else "Only one bureau reports it, so it may be an error or out of date.")
    return {
        "bureau": where,
        "issue": f"a collection from {ob['creditor']}" if ob["creditor"] else "a collection",
        "why_may_be_wrong": why,
        "how_to_dispute": f"Get your free {where} report at annualcreditreport.com. If the collection isn't yours, "
                          f"or it's already paid, dispute it online with {where}. They must look into it, usually "
                          "within 30 days.",
    }


def no_deal(ex):
    live = _live(ex)
    return {"reasons": reasons(ex, live), "what_would_change": what_would_change(ex, live),
            "bureau_dispute": bureau_dispute(ex)}


# ---------------------------------------------------------------- blocked
def _num(text):
    m = re.search(r"\d+", text)
    return m.group(0) if m else None


BLOCK_REASONS = {
    "SSN_NAME_MISMATCH": lambda t: "The SSN belongs to someone with a different name.",
    "DOB_MISMATCH": lambda t: "The date of birth doesn't match the records for this SSN.",
    "DECEASED": lambda t: "The SSN is listed as belonging to someone who has died.",
    "FRAUD_ALERT_ON_FILE": lambda t: "There's a fraud alert on the credit file.",
    "FROZEN": lambda t: "The credit file is frozen.",
    "FRAUD_SCORE_HIGH": lambda t: f"A fraud check rated this application high risk ({_num(t)} out of 100).",
    "FRAUD_SCORE_MEDIUM": lambda t: f"A fraud check rated this application medium risk ({_num(t)} out of 100).",
    "TUMBLING": lambda t: "The same identity is being used with small changes, a common fraud pattern.",
    "NEW_EMAIL": lambda t: f"The email address is only {_num(t)} days old.",
    "EMAIL_VELOCITY": lambda t: "The email address is being used on many applications right now.",
    "PHONE_NOT_APPLICANTS": lambda t: "The phone number belongs to someone else.",
    "BURNER_PHONE": lambda t: "The phone number is a prepaid or internet line.",
    "IP_FAR": lambda t: "The application came from far away from the address given.",
    "CONTACT_BELONGS_TO_OTHER": lambda t: "The phone or email belongs to another person.",
    "CONTACT_UNKNOWN": lambda t: "The phone and email can't be tied to anyone.",
    "INQUIRY_BURST": lambda t: f"{_num(t)} credit applications in 30 days.",
    "SSN_NOT_ON_FILE": lambda t: "The credit bureaus have no record of this SSN.",
}


def blocked(ex):
    findings = (ex.report or {}).get("findings", [])
    codes = {f["code"] for f in findings}
    if "DECEASED" in codes:
        out = {"headline": "This SSN is listed as belonging to someone who has died.",
               "if_you": "If this is your SSN, the record is a mistake. Contact Social Security to fix it, then verify "
                         "your identity (simulated in this demo).",
               "if_not": "If this isn't you, someone may be using a deceased person's details. No lender saw anything "
                         "and nothing was opened."}
    else:
        out = {"headline": "We couldn't confirm this identity.",
               "if_you": "If this is you, verify your identity (simulated in this demo).",
               "if_not": "If this isn't you, someone may be using your details. Freeze your credit at all three "
                         "bureaus; it's free. No lender saw anything."}
    rs = [BLOCK_REASONS[f["code"]](f["text"]) for f in findings if f["code"] in BLOCK_REASONS]
    out["reasons"] = list(dict.fromkeys(rs))[:5]
    return out


# ---------------------------------------------------------------- what helped
def helped(ex):
    p = ex.passport or {}
    ff = ((ex.report or {}).get("signals") or {}).get("fraud_finder") or {}
    out = []
    if p.get("identity") == "strong":
        out.append("Your identity checks out strongly")
    if not p.get("no_file", True):
        if not p["late_payments"]:
            out.append("No late payments")
        bad = {"collections": "No debts in collections", "chargeoffs": "No debts written off as unpaid",
               "bankruptcies": "No bankruptcies"}
        if not any(p[k] for k in bad):
            out.append("No collections, unpaid write-offs or bankruptcies")
        else:
            out += [text for k, text in bad.items() if not p[k]]
        y = p.get("file_age_years")
        if y:
            months = round(y * 12)
            out.append(f"{int(y)} years of credit history" if y >= 2 else f"{_s(months, 'month')} of credit history")
        if p["score_low"] is not None and p["score_low"] >= 700:
            out.append(f"A good credit score ({p['score_low']})")
        if p["bureaus_with_file"] == 3 and not p["bureau_disagreements"]:
            out.append("All three credit bureaus agree about you")
    if ff.get("available") and ff.get("risk_score") is not None and ff["risk_score"] < 30:
        out.append("Fraud checks found nothing unusual")
    if p.get("no_file") or p.get("thin_file") or p.get("no_score"):   # newcomers: these are what lenders can see
        if ff.get("phone_owner_matches"):
            out.append("Your phone number is in your name")
        days = ff.get("email_age_days") or 0
        if days >= 365:
            out.append(f"You've had your email address for over {_s(days // 365, 'year')}")
    return out
