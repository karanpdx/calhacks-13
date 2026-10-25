"""Under the hood: the judges' view of a session, in plain words. Deterministic, no AI.

`describe(event, ex)` turns ONE referee log entry into a feed item (used live per streamed event and in batch);
`build(ex)` returns the whole panel after `ex.run()`: feed, exclusion banners, which CRS product drove which decision,
stats and what was simulated. Never shows raw verdict codes, sequence numbers, signatures or passport fields.

Feed item: {"id", "kind", "who", "role", "what", "verdict", "verdict_text", "says", "severity", "simulated", "crs"}
plus, on some kinds, "details" (gate findings / passport summary / disclosure lines), "steps" (settlement),
"about" and "suggestion" (watchdog). `id` is the event's seq, for UI keys only.
"""
import re

from agent import signals as S
from .lenders import POLICIES
from .messages import APR_CAP, INTENT, OFFER, COUNTER, ACCEPT, DECLINE, WITHDRAW

# ---------------------------------------------------------------- referee verdicts in plain words
VERDICT_TEXT = {
    "OK": "Allowed",
    "TERMS_INVALID": "Blocked: the terms were missing or impossible (no amount, no term, or a negative rate or fee).",
    "APR_CAP": f"Blocked: the rate is above the exchange's {APR_CAP:g}% cap.",
    "AMOUNT_ABOVE_ASK": "Blocked: it offered more money than you asked for.",
    "TERMS_WORSENED": "Blocked: it tried to make its offer worse after making it. Offers are binding.",
    "UNKNOWN_OFFER": "Blocked: it pointed to an offer that doesn't exist.",
    "OFFER_NOT_LIVE": "Blocked: that offer is no longer open.",
    "NOT_YOUR_OFFER": "Blocked: a lender can only withdraw its own offers.",
    "TERMS_MISMATCH": "Blocked: the acceptance didn't match the offer exactly.",
    "OUTSIDE_MANDATE": "Blocked: it's outside the limits you set. Your agent can't agree to that, whatever it's told.",
    "BAD_SIGNATURE": "Blocked: forged. It wasn't signed by the agent it claims to come from.",
    "UNREGISTERED": "Blocked: the sender isn't a registered agent on this exchange.",
    "EXCLUDED": "Blocked: this lender was already removed from the session.",
    "WRONG_ROLE": "Blocked: that move isn't allowed for its role (only lenders make offers; only your agent accepts).",
    "SESSION_CLOSED": "Blocked: the session was already over.",
    "UNKNOWN_TYPE": "Blocked: not a recognised kind of message.",
}
ALLOWED_TEXT = {OFFER: f"Allowed: valid terms, under the {APR_CAP:g}% cap",
                ACCEPT: "Allowed: matches the offer exactly and fits your limits"}

# why a lender was excluded (referee.HARD_VIOLATIONS + the rule-based injection detector)
EXCLUSION_TEXT = {
    "TERMS_WORSENED": "tried to change its offer after making it",
    "BAD_SIGNATURE": "sent a message forged in another agent's name",
    "INJECTION": "hid instructions for your agent in its message",
}

# ---------------------------------------------------------------- CRS products
PRODUCT = {
    "tu": "TransUnion credit report",
    "efx": "Equifax credit report",
    "exp": "Experian credit report",
    "idv": "TransUnion identity verification",
    "fraudfinder": "AtData Fraud Finder",
    "reverse": "AccurateAppend reverse lookup",
    "blj": "PitchPoint bankruptcies, liens and judgments",
    "criminal": "Criminal records search",
    "eviction": "Eviction records search",
}
BUREAU_CODE = {"TransUnion": "tu", "Equifax": "efx", "Experian": "exp"}
BUREAUS = ("tu", "efx", "exp")
IDENTITY = ("idv", "fraudfinder", "reverse")
USED_FOR = {
    "tu": "score, accounts and payment history in the summary lenders saw",
    "efx": "score, accounts and payment history in the summary lenders saw",
    "exp": "score, accounts and payment history in the summary lenders saw",
    "idv": "checking the SSN, name and date of birth belong together, and spotting fraud alerts",
    "fraudfinder": "fraud risk from the email, phone, IP address and mailing address on the application",
    "reverse": "checking the phone and email on the application belong to the applicant",
    "blj": "bankruptcies, liens and judgments on public record",
    "criminal": "criminal records",
    "eviction": "eviction records",
}
# finding.source (agent/rules.py) -> product codes; generic credit sources mean "the bureau reports"
FINDING_SOURCE = {
    "TransUnion identity verification": ("idv",),
    "AtData FraudFinder": ("fraudfinder",),
    "AccurateAppend reverse lookup": ("reverse",),
    "PitchPoint liens/judgments": ("blj",),
    "Criminal search": ("criminal",),
    "Eviction search": ("eviction",),
}
DECISION_TEXT = {
    "APPROVE": "identity and credit check out, cleared for the market",
    "REVIEW": "cleared for the market, with items worth a human look",
    "VERIFY": "cleared for the market, but identity must be verified before any money moves",
    "DECLINE_CREDIT": "identity checks out; credit is weak, so expect few offers",
    "DECLINE_RECORDS": "identity checks out; a public record will limit offers",
    "NO_FILE": "no credit file at any bureau and no sign of fraud, so only identity-based lenders can bid",
    "STOP_FRAUD": "likely identity fraud, stopped before any lender saw anything",
}
# lender policy reasons (exchange/lenders.py Quote.reason) -> what CRS data they rest on
REASON_SOURCES = [
    (re.compile(r"identity", re.I), "identity"),
    (re.compile(r"score|prime file|rebuilding", re.I), "score"),
    (re.compile(r"late payments|collections|charge-offs|bankruptc", re.I), "derog"),
    (re.compile(r"bureaus disagree", re.I), "all"),
    (re.compile(r"accounts?\b|histor|thin|new to credit|new-to-credit|credit file", re.I), "file"),
]
SIMULATED_ITEMS = {
    "lenders": "Lender agents and their offers",
    "hard_pull": "Hard credit check at acceptance",
    "funding": "Funding",
    "reporting": "Reporting the new loan to the bureaus",
    "step_up": "Step-up identity checks (KBA/OTP)",
}
SAYS_MAX = 140


# ---------------------------------------------------------------- formatting
def money(x):
    x = float(x)
    return f"${x:,.0f}" if x == int(x) else f"${x:,.2f}"


def pct(apr):
    s = f"{float(apr):.2f}"
    return s[:-1] + "%" if s.endswith("0") else s + "%"


def _t(terms):
    """Terms arrive as a dict (Message.to_dict, or a streamed JSON copy) or as a Terms object."""
    if terms is None:
        return None
    return terms if isinstance(terms, dict) else vars(terms)


def terms_text(terms):
    t = _t(terms)
    if not t:
        return ""
    fee = float(t.get("fee") or 0)
    return (f"{money(t['amount'])} at {pct(t['apr'])} for {int(t['term_months'])} months"
            + (" with autopay" if t.get("autopay") else "") + (f", {money(fee)} fee" if fee else ", no fee"))


def _low(s):
    """Lowercase the first letter of an ordinary first word ("The", "A"), not of "SSN" or "FraudFinder"."""
    w = s.split(" ", 1)[0]
    return s[:1].lower() + s[1:] if w[1:].islower() or w == "A" else s


def shorten(text, n=SAYS_MAX):
    text = " ".join((text or "").split())
    if not text:
        return None
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0]
    return cut.rstrip(",;:.") + "..."


def name(agent):
    if agent in POLICIES:
        return POLICIES[agent][0]
    return str(agent).replace("_", " ").title()


def role_of(agent, ex=None):
    if ex is not None and agent in getattr(ex, "roles", {}):
        return ex.roles[agent]
    if agent in POLICIES:
        return "lender"
    return "borrower" if agent == "borrower" else "lender"


def who_of(agent, ex=None):
    return "Your agent" if role_of(agent, ex) == "borrower" else name(agent)


def _uniq(xs):
    return list(dict.fromkeys(x for x in xs if x))


def item(e, who, role, what, verdict=None, verdict_text=None, says=None, severity=None, simulated=False, crs=None,
         **extra):
    d = {"id": e.get("seq"), "kind": e["kind"], "who": who, "role": role, "what": what, "verdict": verdict,
         "verdict_text": verdict_text, "says": says, "severity": severity, "simulated": simulated, "crs": crs or []}
    d.update({k: v for k, v in extra.items() if v is not None})
    return d


# ---------------------------------------------------------------- CRS attribution
def products_used(ex):
    """Product codes actually used in this session, in call order (skips samples that are missing / failed calls)."""
    if ex is None or not getattr(ex, "report", None):
        return []
    bad = set()
    for entry in getattr(getattr(ex, "source", None), "log", None) or []:
        st = entry.get("status")
        if st == "missing" or (isinstance(st, int) and st >= 400):
            bad.add(entry.get("product"))
    return [p for p in _uniq(ex.report.get("products_called", [])) if p not in bad]


def _called(codes, used):
    """Keep `codes` that were called; with no call record (ex=None) keep them all."""
    return [c for c in codes if not used or c in used]


DEROG_KEYS = {"COLLECTIONS": ("collections",), "CHARGEOFFS": ("chargeoffs",),
              "LATE_PAYMENTS": ("lates_30", "lates_60", "lates_90")}


def finding_products(f, used=(), sig=None):
    """Product codes behind one gate finding. Generic credit sources ("credit report", "tri-bureau") are narrowed to
    the bureaus the finding's text names, or (with `sig`, per-bureau signals) the bureaus that report the item."""
    src = f.get("source") or ""
    if src in FINDING_SOURCE:
        return _called(FINDING_SOURCE[src], used)
    if src in BUREAU_CODE:
        return [BUREAU_CODE[src]]
    named = [BUREAU_CODE[b] for b in BUREAU_CODE if b in src or b in (f.get("text") or "")]
    if named:
        return named
    if sig and f.get("code") in DEROG_KEYS:
        has = [c for c in BUREAUS if any(sig.get(c, {}).get(k) for k in DEROG_KEYS[f["code"]])]
        if has:
            return has
    return _called(BUREAUS, used)


def _bureau_signals(ex):
    """Per-bureau signals from the session's (cached) CRS responses; {} without a session."""
    if ex is None or not getattr(ex, "source", None) or not getattr(ex, "persona", None):
        return {}
    out = {}
    for b, code in BUREAU_CODE.items():
        try:
            out[code] = S.credit(ex.source.get(ex.persona, code))   # cached: no new call
        except Exception:
            out[code] = {"available": False}
    return out


def reason_products(reason, ex, eligible=False):
    """Which CRS products a lender's policy reason rests on (deterministic, from the passport's sources).
    A passing identity ("strong identity") rests on every identity check; a failing one on those that raised findings."""
    used = products_used(ex)
    sig = _bureau_signals(ex)
    with_file = [c for c in BUREAUS if sig.get(c, {}).get("hit")] or _called(BUREAUS, used)
    out = []
    for rx, kind in REASON_SOURCES:
        if not rx.search(reason or ""):
            continue
        if kind == "identity":
            report = getattr(ex, "report", None) or {}
            hit = _uniq(p for f in report.get("findings", []) if f["axis"] == "identity"
                        for p in finding_products(f, used) if p in IDENTITY)
            out += _called(IDENTITY, used) if eligible or not hit else hit
        elif kind == "score":
            scores = {c: sig[c].get("score") for c in with_file if sig.get(c, {}).get("score") is not None}
            low = min(scores.values()) if scores else None
            out += [c for c, s in scores.items() if s == low] or with_file
        elif kind == "derog":
            keys = ("collections", "chargeoffs", "bankruptcies", "lates_30", "lates_60", "lates_90")
            out += [c for c in with_file if any(sig.get(c, {}).get(k) for k in keys)] or with_file
        elif kind == "all":
            out += _called(BUREAUS, used)
        else:
            out += with_file
    return _uniq(out)


def _quote(lender, ex):
    try:
        return POLICIES[lender][1](ex.passport)
    except Exception:
        return None


def _names(codes):
    return [PRODUCT[c] for c in codes if c in PRODUCT]


# ---------------------------------------------------------------- one event -> one feed item
def describe(e, ex=None):
    """Turn one event dict into a feed item, or None for events the panel skips. Works on a JSON copy with ex=None."""
    fn = {"gate": _gate, "blocked": _blocked, "passport": _passport, "message": _message, "watchdog": _watchdog,
          "excluded": _excluded, "settlement": _settlement, "disclosure": _disclosure, "no_deal": _no_deal}.get(e.get("kind"))
    return fn(e, ex) if fn else None


def _gate(e, ex):
    d = e["data"]
    used = _uniq(d.get("crs_products") or []) or products_used(ex)
    findings = d.get("findings") or []
    decision = d.get("decision")
    checks = []
    if any(p in used for p in IDENTITY):
        checks.append("identity")
    n = sum(1 for p in BUREAUS if p in used)
    if n:
        checks.append(f"credit at {'all three bureaus' if n == 3 else f'{n} bureau' + ('s' if n > 1 else '')}")
    if any(p in used for p in ("blj", "criminal", "eviction")):
        checks.append("public records")
    what = "Checked " + " and ".join(checks) + " with CRS" if checks else "Ran the CRS checks"
    scores = (getattr(ex, "report", None) or {}).get("scores") or {}
    scored = [s for s in scores.values() if s is not None]
    if scored and decision != "STOP_FRAUD":
        what += f" (lowest score {min(scored)})"
    what += ": " + DECISION_TEXT.get(decision, (d.get("headline") or "done").lower())
    admitted = d.get("admitted", decision != "STOP_FRAUD")
    sig = _bureau_signals(ex)
    details = [{"text": f["text"], "crs": ", ".join(_names(finding_products(f, used, sig))) or None}
               for f in findings[:6]]
    return item(e, "Referee", "referee", what,
                "allowed" if admitted else "blocked",
                "Cleared: lenders may see a summary" if admitted
                else "Blocked: likely identity fraud. No lender sees this application.",
                crs=_names(used), details=details or None)


def _blocked(e, ex):
    report = getattr(ex, "report", None) or {}
    used = products_used(ex)
    crs = _uniq(p for f in report.get("findings", []) if f["axis"] == "identity" and f["severity"] >= 2
                for p in finding_products(f, used))
    return item(e, "Referee", "referee", "Stopped the session: identity can't be trusted, so no lender sees anything",
                "blocked", "Blocked: likely identity fraud. No offers, and no credit decision against the person "
                           "whose identity this is.", crs=_names(crs))


def _passport(e, ex):
    p = (e.get("data") or {}).get("passport") or {}
    used = products_used(ex) or list(BUREAUS + IDENTITY)
    crs = [c for c in used if c in BUREAUS or c in IDENTITY]
    bits = []
    if p.get("no_file"):
        bits.append("no credit file yet")
    else:
        if p.get("score_band"):
            bits.append(f"score band {p['score_band']}")
        if p.get("accounts") is not None:
            bits.append(f"{p['accounts']} account{'s' if p['accounts'] != 1 else ''}")
        if p.get("file_age_years") is not None:
            bits.append(f"{p['file_age_years']:g} years of history")
        lates = p.get("late_payments") or 0
        bits.append(f"{lates} late payment{'s' if lates != 1 else ''}" if lates else "no late payments")
        if p.get("collections"):
            bits.append(f"{p['collections']} in collections")
    if p.get("identity"):
        bits.append(f"identity {p['identity']}")
    if p.get("bureau_disagreements"):
        bits.append("bureaus disagree")
    details = [{"text": "What lenders saw: " + ", ".join(bits) + ".", "crs": None}] if bits else None
    return item(e, "Referee", "referee", "Lenders received a summary (no name, SSN or address)", crs=_names(crs),
                details=details)


def _message(e, ex):
    d, v = e["data"], e.get("verdict") or {"ok": True, "code": "OK"}
    actor, typ = e.get("actor"), d.get("type")
    role = role_of(actor, ex)
    who = who_of(actor, ex)
    to = d.get("to")
    ok = bool(v.get("ok"))
    code = v.get("code")
    simulated = role == "lender"
    crs = []
    if typ == INTENT:
        ask = d.get("ask") or {}
        lo_hi = ask.get("term_range") or []
        what = f"Asked the market for {money(ask['amount'])}" if ask.get("amount") else "Asked the market for a loan"
        if len(lo_hi) == 2:
            what += f" over {lo_hi[0]}-{lo_hi[1]} months"
    elif typ == OFFER:
        what = "Offered " + terms_text(d.get("terms"))
        if code == "TERMS_WORSENED":
            what = "Tried to change its offer to " + terms_text(d.get("terms"))
    elif typ == COUNTER:
        what = f"Asked {name(to)} for " + terms_text(d.get("terms")) if to else "Countered: " + terms_text(d.get("terms"))
    elif typ == ACCEPT:
        what = (f"Accepted {name(to)}'s offer: " if to else "Accepted: ") + terms_text(d.get("terms"))
    elif typ == DECLINE:
        if role == "borrower":
            what = "Walked away without a deal"
        elif d.get("offer_id"):
            what = "Turned down your agent's counter and kept its offer"
        else:
            what = "Declined to make an offer"
    elif typ == WITHDRAW:
        what = "Withdrew its offer"
    else:
        what = "Sent a message the exchange doesn't recognise"

    if code == "BAD_SIGNATURE":   # forged: the claimed sender didn't sign it
        claimed = who
        who = "Someone posing as your agent" if role == "borrower" else f"Someone posing as {claimed}"
        simulated = True
        if typ == ACCEPT:
            what = (f"Tried to accept {name(to)}'s offer in your agent's name: " if to
                    else "Tried to accept an offer in your agent's name: ") + terms_text(d.get("terms"))

    # lender opening moves rest on CRS data via its policy: show which products and why
    opening = e.get("round") == 0 and (typ == OFFER or (typ == DECLINE and not d.get("offer_id")))
    if opening and ok and role == "lender" and ex is not None and getattr(ex, "passport", None):
        q = _quote(actor, ex)
        if q is not None:
            crs = _names(reason_products(q.reason, ex, q.eligible))
            if typ == DECLINE and not q.eligible:
                what = f"Declined to make an offer: {q.reason}"

    verdict_text = (ALLOWED_TEXT.get(typ, VERDICT_TEXT["OK"]) if ok
                    else VERDICT_TEXT.get(code, "Blocked by the referee."))
    if not ok and code == "OUTSIDE_MANDATE":
        m = re.match(r"Blocked: (.+?)\. The person", v.get("reason") or "")
        if m:
            why = m.group(1).replace("the person's", "your").replace("the person", "you")
            verdict_text = f"Blocked: outside the limits you set ({why}). Your agent can't agree to that, whatever it's told."
    says = d.get("text") or ""
    plain = name(actor)
    if says.startswith(plain + ":"):
        says = says[len(plain) + 1:]
    return item(e, who, role, what, "allowed" if ok else "blocked", verdict_text, shorten(says), simulated=simulated,
                crs=crs)


def _watchdog(e, ex):
    f = e["data"]
    sev = f.get("severity")
    if sev not in ("high", "medium", "low"):
        return None
    agent = f.get("agent")
    crs = []
    if f.get("detector") == "bureau_disagreement":
        saw = f.get("saw") or ""
        named = [BUREAU_CODE[b] for b in BUREAU_CODE if b in saw]
        crs = _names(named or _called(BUREAUS, products_used(ex)))
    about = "Credit bureaus" if agent == "bureaus" else None if agent in (None, "watchdog") else who_of(agent, ex)
    return item(e, "Watchdog", "watchdog", f.get("note") or f.get("why") or "Flagged something worth a look",
                severity=sev, crs=crs, about=about, suggestion=f.get("suggestion"),
                ai_review=True if f.get("source") == "claude" else None)


def _excluded(e, ex):
    d = e["data"]
    who = name(d.get("agent"))
    why = EXCLUSION_TEXT.get(d.get("code"), "broke the exchange's rules")
    what = f"Removed {who} from the session" + (" and withdrew its offers" if d.get("withdrawn") else "")
    return item(e, "Referee", "referee", what, "blocked", f"Blocked: {who} {why}. Its later messages are rejected.",
                lender=who)


SIM_SUFFIX = re.compile(r":\s*simulated.*$", re.I)


def _settlement(e, ex):
    steps = []
    for s in (e.get("data") or {}).get("steps", []):
        s = SIM_SUFFIX.sub("", s).replace("now that the borrower has accepted", "now that you've accepted")
        steps.append({"text": s, "simulated": True})
    return item(e, "Referee", "referee", "Closing steps after acceptance (simulated in the CRS sandbox)",
                simulated=True, steps=steps)


def _disclosure(e, ex):
    lines = (e.get("data") or {}).get("summary") or []
    what = "Deal closed: " + lines[0] if lines else "Deal closed"
    return item(e, "Referee", "referee", what, details=[{"text": x, "crs": None} for x in lines[1:]] or None)


def _no_deal(e, ex):
    return item(e, "Referee", "referee", "No deal: no offer fit your limits, so your agent walked away")


# ---------------------------------------------------------------- whole panel
def _forger(e, ex):
    """Who sent a forged message: the agent it was addressed to (a forged acceptance is sent to the forger itself),
    or the lender whose offer it points at."""
    d = e["data"]
    if d.get("to") and role_of(d["to"], ex) == "lender":
        return d["to"]
    o = (getattr(ex, "offers", None) or {}).get(d.get("offer_id"))
    return o["lender"] if o else None


def exclusions(ex):
    out = []
    for x in (e for e in ex.events if e["kind"] == "excluded"):
        lender = x["data"]["agent"]
        did, found = [], set()   # everything the lender was caught doing, in order
        for e in ex.events:
            if e["kind"] != "message" or (e.get("verdict") or {}).get("ok", True):
                continue
            code = e["verdict"]["code"]
            if code == "TERMS_WORSENED" and e["actor"] == lender:
                did.append(EXCLUSION_TEXT["TERMS_WORSENED"])
                found.add(code)
            elif code == "BAD_SIGNATURE" and _forger(e, ex) == lender:
                did.append("faked your agent's acceptance" if e["data"].get("type") == ACCEPT
                           else EXCLUSION_TEXT["BAD_SIGNATURE"])
                found.add(code)
        if any(e["kind"] == "watchdog" and e["data"].get("detector") == "injection" and e["data"].get("agent") == lender
               and e["data"].get("source") == "rules" for e in ex.events):
            did.append(EXCLUSION_TEXT["INJECTION"])
            found.add("INJECTION")
        if x["data"]["code"] not in found:
            did.insert(0, EXCLUSION_TEXT.get(x["data"]["code"], "broke the exchange's rules"))
        did = _uniq(did)
        reasons = did[0] if len(did) == 1 else ", ".join(did[:-1]) + " and " + did[-1]
        tail = " Its offers were withdrawn." if x["data"].get("withdrawn") else " It had no open offers."
        out.append({"lender": name(lender),
                    "banner": f"{name(lender)} was removed from this session: it {reasons}.{tail}"})
    return out


def crs_products(ex):
    used = products_used(ex)
    report = ex.report or {}
    decision = report.get("decision")
    drove = {p: [] for p in used}
    sig = _bureau_signals(ex)

    for f in report.get("findings", []):
        if decision == "STOP_FRAUD" and f["axis"] == "identity":
            pre = "Blocked as likely fraud"
        elif decision == "VERIFY" and f["axis"] == "identity" and f["severity"] >= 2:
            pre = "Identity step-up required"
        elif f["axis"] == "consistency":
            pre = "Bureaus disagree"
        elif decision == "STOP_FRAUD":
            pre = "Fraud evidence"
        else:
            pre = "Noted at the gate"
        for p in finding_products(f, used, sig):
            if p in drove:
                drove[p].append(f"{pre}: {_low(f['text'].rstrip('.'))}")

    if ex.passport:
        first = {}
        for e in ex.events:
            if e["kind"] == "message" and role_of(e["actor"], ex) == "lender" and e["actor"] not in first:
                first[e["actor"]] = e
        for lender, e in first.items():
            q = _quote(lender, ex)
            if q is None:
                continue
            line = (f"{name(lender)} made an offer: {q.reason}" if q.eligible else f"{name(lender)} declined: {q.reason}")
            for p in reason_products(q.reason, ex, q.eligible):
                if p in drove:
                    drove[p].append(line)

    out = []
    for p in used:
        used_for = USED_FOR.get(p, "")
        if decision == "STOP_FRAUD" and p in BUREAUS:
            used_for = "credit history checked as fraud evidence only; no lender saw it"
        out.append({"product": PRODUCT.get(p, p), "used_for": used_for, "drove": _uniq(drove[p])})
    return out


def stats(ex):
    msgs = [e for e in ex.events if e["kind"] == "message"]
    return {"messages_checked": len(msgs),
            "blocked": sum(1 for e in msgs if not e["verdict"]["ok"]) + sum(1 for e in ex.events if e["kind"] == "blocked"),
            "flags": sum(1 for e in ex.events if e["kind"] == "watchdog" and e["data"].get("severity") in ("high", "medium", "low")),
            "excluded": sum(1 for e in ex.events if e["kind"] == "excluded")}


def simulated(ex):
    out = []
    if any(e["kind"] == "message" and role_of(e["actor"], ex) == "lender" for e in ex.events):
        out.append(SIMULATED_ITEMS["lenders"])
    settle = next((e for e in ex.events if e["kind"] == "settlement"), None)
    if settle:
        steps = " ".join(settle["data"].get("steps", [])).lower()
        out += [SIMULATED_ITEMS["hard_pull"], SIMULATED_ITEMS["funding"], SIMULATED_ITEMS["reporting"]]
        if "kba" in steps or "step-up" in steps:
            out.append(SIMULATED_ITEMS["step_up"])
    return out


def build(ex):
    """The judges' panel for a finished session (call after ex.run())."""
    return {"feed": [x for x in (describe(e, ex) for e in ex.events) if x],
            "exclusions": exclusions(ex),
            "crs_products": crs_products(ex),
            "stats": stats(ex),
            "simulated": simulated(ex)}
