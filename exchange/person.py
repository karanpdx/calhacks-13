"""The person's screen: what the borrower sees, in plain words. Deterministic code, no AI.

`build(ex)` after `ex.run()` returns one dict: outcome, what they agreed to (`before`), the deal or why there's none,
real threats we stopped (`protection`), and what helped them. Written for people with thin or no credit history:
no codes, no raw passport fields, every number tied to something they can act on. Paths to approval re-run the
lenders' own policies on a modified COPY of the passport; they say "would likely", never promise.
"""
import copy, re
from itertools import combinations

from .i18n import t as tr, language, money, count, fmt as _fmt
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
    return money(x)


def _name(agent):
    return POLICIES.get(agent, (agent,))[0]


def _s(n, word):
    return count(n, word)


def _join(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + tr(" and ") + xs[-1]


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


def build(ex, lang="en"):
    """Localized borrower presentation; calculations and raw records stay unchanged."""
    with language(lang):
        return _build(ex)


# ---------------------------------------------------------------- build
def _build(ex):
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
        "term": tr('{v0} months', v0=_fmt(m.min_term, '')) if m.min_term == m.max_term else tr('{v0} to {v1} months', v0=_fmt(m.min_term, ''), v1=_fmt(m.max_term, '')),
        "max_monthly_payment": _c(mp) if mp else None,
        "advanced": {"max_apr": float(m.max_apr), "max_fee": _c(m.max_fee), "autopay_ok": "autopay" in m.allow},
        "soft_pull": tr(SOFT_PULL),
        "privacy": tr(PRIVACY),
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
    pending = getattr(ex, "awaiting_approval", lambda: False)()
    pay, base = _pay(t), _best_first(ex)
    saved = None
    if base:
        b = base["terms"]
        amt = finance.total_cost(b) * t.amount / b.amount - finance.total_cost(t)
        if amt >= 1:
            saved = {"amount": _c(amt),
                     "sentence": tr('Your agent could save you ${v0} compared with the best first offer ({v1}% from {v2}).' if pending else 'Your agent saved you ${v0} compared with the best first offer ({v1}% from {v2}).', v0=_fmt(amt, ',.0f'), v1=_fmt(b.apr, 'g'), v2=_fmt(_name(base['lender']), ''))}
    return {
        "lender": name, "monthly_payment": _c(pay), "apr": float(t.apr), "term_months": int(t.term_months),
        "amount": _c(t.amount), "fee": _c(t.fee), "total_paid": _c(finance.total_cost(t)),
        "saved": saved,
        "traded": traded(t, base, ex.deal["lender"], ex.mandate),
        "on_accept": on_accept(ex, name, t),
        "headline": tr('{v0} offers you {v1}: {v2} a month for {v3} months. Nothing is signed yet.' if pending else '{v0} lends you {v1}: {v2} a month for {v3} months.', v0=_fmt(name, ''), v1=_fmt(_usd(t.amount), ''), v2=_fmt(_usd(pay), ''), v3=_fmt(t.term_months, '')),
    }


def traded(t, first, lender, m):
    """What the agent gave up, compared with the best first offer (`first`, an offer dict or None)."""
    out, base = [], first["terms"] if first else None
    same = bool(first) and first["lender"] == lender
    if t.autopay:
        out.append(tr('Agreed to autopay (payments come out automatically each month), which lowered the rate.')
                   if same and not base.autopay and t.apr < base.apr else
                   tr('Agreed to autopay (payments come out automatically each month).'))
    if same and t.term_months > base.term_months:
        out.append(tr('Took a longer loan ({v0} months instead of {v1}), so you pay for longer.', v0=_fmt(t.term_months, ''), v1=_fmt(base.term_months, '')))
    if (first and not same and base.amount < t.amount
            and finance.cost_per_dollar(base) < finance.cost_per_dollar(t)):
        out.append(tr('Took the full {v0} at {v1}% instead of {v2} at {v3}% from {v4}.', v0=_fmt(_usd(t.amount), ''), v1=_fmt(t.apr, 'g'), v2=_fmt(_usd(base.amount), ''), v3=_fmt(base.apr, 'g'), v4=_fmt(_name(first['lender']), '')))
    if t.amount < m.amount:
        out.append(tr('Borrowing {v0} instead of the {v1} you asked for.', v0=_fmt(_usd(t.amount), ''), v1=_fmt(_usd(m.amount), '')))
    if t.fee:
        out.append(tr('Pays a one-time {v0} fee, which is inside your limit.', v0=_fmt(_usd(t.fee), '')))
    return out


def on_accept(ex, name, t):
    steps = []
    if (ex.passport or {}).get("verification_required"):
        why = (tr("because there's a fraud alert on your file") if _finding(ex, "FRAUD_ALERT_ON_FILE")
               else tr('because some identity details need a second look'))
        steps.append(tr("First you confirm it's really you, with a few questions or a code, {v0}.", v0=_fmt(why, '')))
    steps += [tr('{v0} runs a hard credit check. Your score may dip a few points.', v0=_fmt(name, '')),
              tr('{v0} gets your full credit file.', v0=_fmt(name, '')),
              tr('{v0} sends you {v1}.', v0=_fmt(name, ''), v1=_fmt(_usd(t.amount), '')),
              tr('The new loan shows up at all three credit bureaus. Paying on time builds your credit.')]
    return [{"text": tr("Simulated") + ": " + s, "simulated": True} for s in steps]


# ---------------------------------------------------------------- protection: real threats only
def _asked(ex, f):
    """What personal data the lender asked for, re-read from the message it flagged."""
    ref = f.get("ref")
    text = ex.events[ref]["data"].get("text") or "" if isinstance(ref, int) and ref < len(ex.events) else ""
    out = []
    for m in PERSONAL.finditer(text):
        w = m.group(0).lower()
        word = tr('SSN') if ("ssn" in w or "social" in w) else tr('bank login') if "bank" in w else tr('date of birth')
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
            add(("injection", lid), "high", tr('{v0} tried to trick your agent with hidden instructions. We removed it.', v0=_fmt(n, '')),
                tr("Some lenders' agents hide commands in their messages. Here only the loan's numbers count, so it couldn't make your agent say yes."))
        elif code == "TERMS_WORSENED":
            add(("worse", lid), "high", tr('{v0} tried to swap in a worse deal after making an offer. We removed it.', v0=_fmt(n, '')),
                tr("Once a lender makes an offer here, it can't raise the price. It can only offer you something better."))
        elif code == "BAD_SIGNATURE":
            add(("forged", lid), "high", tr('{v0} sent a message pretending to be someone else. We removed it.', v0=_fmt(n, '')),
                tr("Every message is checked to prove who sent it, so fakes don't count."))
        else:
            add(("excluded", lid), "high", tr("{v0} broke the exchange's rules. We removed it.", v0=_fmt(n, '')),
                tr("Its offers were taken away and it couldn't send anything else."))

    # 2. moves the referee blocked (these hold even with the watchdog off)
    for e in ex.events:
        if e["kind"] != "message" or e["verdict"]["ok"]:
            continue
        code, actor, d = e["verdict"]["code"], e["actor"], e["data"]
        if code == "BAD_SIGNATURE" and ex.roles.get(actor) == "borrower":
            to = tr("{v0}'s offer", v0=_fmt(_name(d['to']), '')) if d.get("to") in ex.roles else tr('an offer')
            add(("forged_accept", d.get("to")), "high",
                tr('Someone tried to accept {v0} while pretending to be your agent. We blocked it.', v0=_fmt(to, '')),
                tr('Only your agent can say yes for you, and every message is checked to prove who sent it.'))
        elif code == "BAD_SIGNATURE":
            add(("forged", actor), "high", tr('A fake message claiming to be from {v0} was blocked.', v0=_fmt(_name(actor), '')),
                tr("Every message is checked to prove who sent it, so fakes don't count."))
        elif code == "TERMS_WORSENED":
            add(("worse", actor), "high", tr('{v0} tried to swap in a worse deal after making an offer. We blocked it.', v0=_fmt(_name(actor), '')),
                tr("Once a lender makes an offer here, it can't raise the price. It can only offer you something better."))
        elif code == "OUTSIDE_MANDATE":
            add(("outside", actor), "high", tr('Your agent tried to accept a loan outside your limits. We blocked it.'),
                tr('Your limits are enforced by the exchange, not by the agent. But this agent may not be working for you, so be careful trusting it.'))

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
            add(("injection", a), "high", tr('{v0} tried to trick your agent with hidden instructions. We ignored them.', v0=_fmt(n, '')),
                tr("Here only the loan's numbers count, so hidden instructions can't make your agent say yes."))
        elif det == "injection":
            add(("injection", a), "high", tr('Your agent sent a message with hidden instructions in it.'),
                tr("Only the loan's numbers count here, so the words can't change anything. Keep an eye on this agent."))
        elif det == "personal_data":
            asked = _asked(ex, f)
            add(("personal", a), "high",
                tr('{v0} asked for your {v1}. Never share {v2}.', v0=_fmt(n, ''), v1=_fmt(_join(asked) if asked else tr('personal details'), ''), v2=_fmt(tr('it') if len(asked) == 1 else tr('them'), '')),
                tr('Lenders here never need these to make an offer. Asking for them is a common scam. If you accept a deal, the lender gets your file through the exchange, not from you.'))
        elif det == "text_vs_terms" and why.startswith("Text says"):
            add(("worse", a), "medium", tr('{v0} said the deal was the same but quietly raised the price.', v0=_fmt(n, '')),
                tr('Only the numbers in an offer count, not what the message says. Our rules caught the change.'))
        elif det == "text_vs_terms" and "fee" in why.lower():
            add(("fee", a), "medium", tr("{v0} mentioned a fee that isn't in its offer.", v0=_fmt(n, '')),
                tr("Only fees written into the offer count. If anyone adds a fee later, you don't have to agree."))
        elif det == "text_vs_terms":
            add(("rate", a), "medium", tr("{v0}'s message named a different rate than its real offer.", v0=_fmt(n, '')),
                tr('Trust the numbers in the offer, not the sales message.'))
        elif det == "borrower_drift" and "tried to accept" in why:
            add(("outside", a), "high", tr('Your agent tried to accept a loan outside your limits. We blocked it.'),
                tr('Your limits are enforced by the exchange, not by the agent. But this agent may not be working for you, so be careful trusting it.'))
        elif det == "borrower_drift" and "costlier" in why:
            m = re.search(r"about (\$[\d,]+) more", f.get("note") or "")
            add(("costlier", a), "medium", tr('Your agent picked a pricier offer when a cheaper one fit your limits.'),
                tr('That costs you about {v0} more over the loan.', v0=_fmt(m.group(1), '')) if m else tr('That costs you more over the loan.'))
        elif det == "borrower_drift":
            add(("leak", a), "high", tr("Your agent told lenders the highest rate you'd accept."),
                tr('Lenders could use that to charge you more instead of competing for you.'))
        elif det == "bureau_disagreement" and ex.deal:   # with no deal, `no_deal.bureau_dispute` covers this
            ob = _one_bureau(ex)
            if ob:
                add(("bureau",), "medium", tr('A collection shows up at only one credit bureau ({v0}).', v0=_fmt(_join(ob['bureaus']), '')),
                    tr("If it isn't yours or it's already paid, getting it fixed could get you better rates next time."))
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
        "payment": tr('{v0} was {v1} a month, above your {v2} limit', v0=_fmt(lead, ''), v1=_fmt(_usd(_pay(t)), ''), v2=_fmt(_usd(mp or 0), '')),
        "apr": tr('{v0} was {v1}% a year, above your {v2}% limit', v0=_fmt(lead, ''), v1=_fmt(t.apr, 'g'), v2=_fmt(m.max_apr, 'g')),
        "amount": tr('{v0} was for {v1}, less than the {v2} you need', v0=_fmt(lead, ''), v1=_fmt(_usd(t.amount), ''), v2=_fmt(_usd(m.min_amount), '')),
        "term": tr('{v0} was for {v1} months, outside your {v2} to {v3} months', v0=_fmt(lead, ''), v1=_fmt(t.term_months, ''), v2=_fmt(m.min_term, ''), v3=_fmt(m.max_term, '')),
        "fee": tr('{v0} had a {v1} fee, above your {v2} limit', v0=_fmt(lead, ''), v1=_fmt(_usd(t.fee), ''), v2=_fmt(_usd(m.max_fee), '')),
        "autopay": tr("{v0} needed autopay, which you didn't allow", v0=_fmt(lead, '')),
    }[kind]


def reasons(ex, live):
    p, m, out = ex.passport, ex.mandate, []
    if live:
        best = min(live.values(), key=lambda o: finance.cost_per_dollar(o["terms"]))
        kinds = _breaks(m, best["terms"])
        if kinds:
            out.append(_offer_reason(tr('The only offer') if len(live) == 1 else tr('The best offer'), best["terms"], kinds[0], m))
    ob = _one_bureau(ex)
    if p["no_file"]:
        out.append(tr('No credit file at any bureau yet'))
    if p["no_score"]:
        out.append(tr('No credit score right now'))
    if p["thin_file"]:
        out.append(tr('Only {v0} so far', v0=_fmt(_s(p['accounts'], 'account'), '')))
    if p["collections"]:
        out.append(tr('A collection shows at {v0} only', v0=_fmt(_join(ob['bureaus']), '')) if ob
                   else tr('{v0} in collections', v0=_fmt(_s(p['collections'], 'debt'), '')))
    if p["chargeoffs"]:
        out.append(tr('{v0} written off as unpaid', v0=_fmt(_s(p['chargeoffs'], 'past debt'), '')))
    if p["bankruptcies"]:
        out.append(tr('A bankruptcy on your file'))
    if p["late_payments"]:
        out.append(tr('{v0}', v0=_fmt(_s(p['late_payments'], 'late payment'), '')))
    if p["score_low"] is not None and p["score_low"] < 700:
        out.append(tr('Lowest credit score is {v0}', v0=_fmt(p['score_low'], '')))
    if p["bureau_disagreements"] and not ob:
        out.append(tr("The credit bureaus don't all agree about your file"))
    if p["identity"] != "strong":
        out.append(tr('Some identity checks came back unclear'))
    return out[:3] or [tr('No lender offered a loan inside your limits')]


def _fixes(ex):
    """Passport changes a person can work toward, smallest first: [(change text, apply(passport copy))].
    Late payments, write-offs and bankruptcies are left out: they stay on a file for years, so they aren't a path."""
    p, out = ex.passport, []
    ob = _one_bureau(ex)
    if ob:
        what = tr('{v0} collection', v0=_fmt(ob['creditor'], '')) if ob["creditor"] else tr('collection')

        def fix_bureau(q, ob=ob):
            q["collections"] = min(q["collections"], ob["left"])
            q["bureau_disagreements"] = [d for d in q["bureau_disagreements"] if d != ob["text"]]
        out.append((tr("get the {v0} at {v1} fixed, if it's wrong", v0=_fmt(what, ''), v1=_fmt(_join(ob['bureaus']), '')), fix_bureau))
    elif p["collections"]:
        out.append((tr('clear the {v0} from your file', v0=_fmt(_s(p['collections'], 'collection'), '')),
                    lambda q: q.update(collections=0)))
    if p["thin_file"]:
        out.append((tr('get to 3 accounts in good standing (you have {v0} now)', v0=_fmt(p['accounts'], '')),
                    lambda q: q.update(accounts=3, thin_file=False)))
    if p["no_file"]:
        out.append((tr('open your first credit account, such as a secured card, and pay it on time'),
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
                changes.append(tr('build a credit score of at least {v0}', v0=_fmt(s, '')) if p["score_low"] is None
                               else tr("raise your lowest credit score to {v0} (it's {v1} now)", v0=_fmt(s, ''), v1=_fmt(p['score_low'], '')))
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
    change = {"payment": tr('Allow payments up to {v0} a month', v0=_fmt(pay, '')), "apr": tr('Allow up to {v0}% a year', v0=_fmt(t.apr, 'g')),
              "amount": tr('Borrow {v0} instead of at least {v1}', v0=_fmt(_usd(t.amount), ''), v1=_fmt(_usd(m.min_amount), '')),
              "term": tr('Allow a {v0}-month loan', v0=_fmt(t.term_months, '')), "fee": tr('Allow a one-time {v0} fee', v0=_fmt(_usd(t.fee), '')),
              "autopay": tr('Allow autopay')}
    sentence = (tr('If {v0} is enough and you could pay {v1} a month for {v2} months, ', v0=_fmt(_usd(t.amount), ''), v1=_fmt(pay, ''), v2=_fmt(t.term_months, ''))
                if "amount" in kinds else tr('If you could pay {v0} a month for {v1} months, ', v0=_fmt(pay, ''), v1=_fmt(t.term_months, '')))
    sentence += tr('{v0} would likely say yes.', v0=_fmt(n, ''))
    if "apr" in kinds:
        close = t.apr - m.max_apr <= 1
        sentence += tr(" That's {v0}% a year, {v1}above your {v2}% limit.", v0=_fmt(t.apr, 'g'), v1=_fmt(tr('just ') if close else '', ''), v2=_fmt(m.max_apr, 'g'))
    if "fee" in kinds:
        sentence += tr(' It also has a {v0} fee.', v0=_fmt(_usd(t.fee), ''))
    return {"change": tr(' and ').join(change[k] for k in kinds), "lender": n, "sentence": sentence}


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
        change = tr(' and ').join(changes)
        items.append((_best_terms(quote, m).apr, {
            "change": change[0].upper() + change[1:], "lender": name,
            "sentence": tr("Then {v0}'s rules would allow a loan of {v1}, likely starting around {v2} a month.", v0=_fmt(name, ''), v1=_fmt(_usd(first.amount), ''), v2=_fmt(_usd(_pay(first)), ''))}))
    items.sort(key=lambda x: x[0])
    return [i for _, i in items[:3]]


def bureau_dispute(ex):
    ob = _one_bureau(ex)
    if not ob:
        return None
    where, others = _join(ob["bureaus"]), ob["others"]
    why = ((tr("{v0} doesn't show it, so it may be an error or out of date.", v0=_fmt(_join(others), '')) if len(others) == 1 else tr("{v0} don't show it, so it may be an error or out of date.", v0=_fmt(_join(others), '')))
           if others else tr('Only one bureau reports it, so it may be an error or out of date.'))
    return {
        "bureau": where,
        "issue": tr('a collection from {v0}', v0=_fmt(ob['creditor'], '')) if ob["creditor"] else tr('a collection'),
        "why_may_be_wrong": why,
        "how_to_dispute": tr("Get your free {v0} report at annualcreditreport.com. If the collection isn't yours, or it's already paid, dispute it online with {v1}. They must look into it, usually within 30 days.", v0=_fmt(where, ''), v1=_fmt(where, '')),
    }


def no_deal(ex):
    if getattr(ex, "approval", None) is False:
        return {"reasons": [tr("You turned down your agent's recommendation. Nothing was signed.")],
                "what_would_change": [], "bureau_dispute": None}
    live = _live(ex)
    return {"reasons": reasons(ex, live), "what_would_change": what_would_change(ex, live),
            "bureau_dispute": bureau_dispute(ex)}


# ---------------------------------------------------------------- blocked
def _num(text):
    m = re.search(r"\d+", text)
    return m.group(0) if m else None


BLOCK_REASONS = {
    "SSN_NAME_MISMATCH": lambda t: tr('The SSN belongs to someone with a different name.'),
    "DOB_MISMATCH": lambda t: tr("The date of birth doesn't match the records for this SSN."),
    "DECEASED": lambda t: tr('The SSN is listed as belonging to someone who has died.'),
    "FRAUD_ALERT_ON_FILE": lambda t: tr("There's a fraud alert on the credit file."),
    "FROZEN": lambda t: tr('The credit file is frozen.'),
    "FRAUD_SCORE_HIGH": lambda t: tr('A fraud check rated this application high risk ({v0} out of 100).', v0=_fmt(_num(t), '')),
    "FRAUD_SCORE_MEDIUM": lambda t: tr('A fraud check rated this application medium risk ({v0} out of 100).', v0=_fmt(_num(t), '')),
    "TUMBLING": lambda t: tr('The same identity is being used with small changes, a common fraud pattern.'),
    "NEW_EMAIL": lambda t: tr('The email address is only {v0} days old.', v0=_fmt(_num(t), '')),
    "EMAIL_VELOCITY": lambda t: tr('The email address is being used on many applications right now.'),
    "PHONE_NOT_APPLICANTS": lambda t: tr('The phone number belongs to someone else.'),
    "BURNER_PHONE": lambda t: tr('The phone number is a prepaid or internet line.'),
    "IP_FAR": lambda t: tr('The application came from far away from the address given.'),
    "CONTACT_BELONGS_TO_OTHER": lambda t: tr('The phone or email belongs to another person.'),
    "CONTACT_UNKNOWN": lambda t: tr("The phone and email can't be tied to anyone."),
    "INQUIRY_BURST": lambda t: tr('{v0} credit applications in 30 days.', v0=_fmt(_num(t), '')),
    "SSN_NOT_ON_FILE": lambda t: tr('The credit bureaus have no record of this SSN.'),
}


def blocked(ex):
    findings = (ex.report or {}).get("findings", [])
    codes = {f["code"] for f in findings}
    if "DECEASED" in codes:
        out = {"headline": tr('This SSN is listed as belonging to someone who has died.'),
               "if_you": tr('If this is your SSN, the record is a mistake. Contact Social Security to fix it, then verify your identity (simulated in this demo).'),
               "if_not": tr("If this isn't you, someone may be using a deceased person's details. No lender saw anything and nothing was opened.")}
    else:
        out = {"headline": tr("We couldn't confirm this identity."),
               "if_you": tr('If this is you, verify your identity (simulated in this demo).'),
               "if_not": tr("If this isn't you, someone may be using your details. Freeze your credit at all three bureaus; it's free. No lender saw anything.")}
    rs = [BLOCK_REASONS[f["code"]](f["text"]) for f in findings if f["code"] in BLOCK_REASONS]
    out["reasons"] = list(dict.fromkeys(rs))[:5]
    return out


# ---------------------------------------------------------------- what helped
def helped(ex):
    p = ex.passport or {}
    ff = ((ex.report or {}).get("signals") or {}).get("fraud_finder") or {}
    out = []
    if p.get("identity") == "strong":
        out.append(tr('Your identity checks out strongly'))
    if not p.get("no_file", True):
        if not p["late_payments"]:
            out.append(tr('No late payments'))
        bad = {"collections": tr('No debts in collections'), "chargeoffs": tr('No debts written off as unpaid'),
               "bankruptcies": tr('No bankruptcies')}
        if not any(p[k] for k in bad):
            out.append(tr('No collections, unpaid write-offs or bankruptcies'))
        else:
            out += [text for k, text in bad.items() if not p[k]]
        y = p.get("file_age_years")
        if y:
            months = round(y * 12)
            out.append(tr('{v0} years of credit history', v0=_fmt(int(y), '')) if y >= 2 else tr('{v0} of credit history', v0=_fmt(_s(months, 'month'), '')))
        if p["score_low"] is not None and p["score_low"] >= 700:
            out.append(tr('A good credit score ({v0})', v0=_fmt(p['score_low'], '')))
        if p["bureaus_with_file"] == 3 and not p["bureau_disagreements"]:
            out.append(tr('All three credit bureaus agree about you'))
    if ff.get("available") and ff.get("risk_score") is not None and ff["risk_score"] < 30:
        out.append(tr('Fraud checks found nothing unusual'))
    if p.get("no_file") or p.get("thin_file") or p.get("no_score"):   # newcomers: these are what lenders can see
        if ff.get("phone_owner_matches"):
            out.append(tr('Your phone number is in your name'))
        days = ff.get("email_age_days") or 0
        if days >= 365:
            out.append(tr("You've had your email address for over {v0}", v0=_fmt(_s(days // 365, 'year'), '')))
    return out
