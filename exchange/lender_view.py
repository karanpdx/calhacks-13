"""The lender's side of the exchange: one lender's queue across every sandbox session, built from what that lender
actually saw and did. Never the applicant's name, SSN, contact details or persona id, and never another lender's
identity: only the passport (as this lender priced it), its own offers, the anonymous quotes the referee passed it,
its own books, and how the session ended for it.

Cases get an application id that's a hash of the session, so the queue can't be joined back to a persona by name.
"""
import hashlib

from agent.scorecard import AS_OF
from agent.sources import SampleSource
from .lenders import BOOKS, POLICIES, view_for
from .messages import Mandate, OFFER, DECLINE
from .referee import Exchange
from .scenarios import build

PERSONAS = [f"P{i:02d}" for i in range(1, 21)]
MARKET = ["prime_bank", "campus_cu", "newstart", "second_chance", "harbor", "ladder"]
_CACHE = {}


def _app_id(persona, lender_id):
    return "APP-" + hashlib.sha256(f"{persona}:{lender_id}:sandbox".encode()).hexdigest()[:6].upper()


def _band(p):
    if p.get("no_file"):
        return "No file"
    if p.get("no_score"):
        return "No score"
    return p.get("score_band") or "Unknown"


def _risk(p):
    s = p.get("score_low")
    if p.get("no_file") or p.get("no_score") or s is None:
        return "Thin"
    return "Strong" if s >= 720 else "Good" if s >= 660 else "Fair" if s >= 600 else "Weak"


def _signals(p):
    out = []
    if p.get("thin_file"):
        out.append("Thin file")
    if p.get("no_file"):
        out.append("No credit file")
    if p.get("no_score"):
        out.append("No score")
    if p.get("identity_score") is not None:
        out.append(f"Identity {p['identity_score']}/100")
    if p.get("never_late"):
        out.append("Never late")
    if p.get("months_on_time"):
        out.append(f"{p['months_on_time']} months on time")
    if p.get("file_age_years") is not None and not p.get("no_file"):
        out.append(f"{p['file_age_years']:.0f}-year file")
    return out


def _case(ex, lender_id):
    p = ex.passport
    seen = view_for(lender_id, p)
    lender = next(l for l in ex.lenders if l.id == lender_id)
    mine = [e for e in ex.events if e["kind"] == "message" and e["actor"] == lender_id]
    offers = [e for e in mine if e["data"]["type"] == OFFER and e["verdict"]["ok"]]
    decline = next((e for e in mine if e["data"]["type"] == DECLINE), None)
    counters = [e for e in ex.events if e["kind"] == "message" and e["data"]["type"] == "COUNTER"
                and e["data"].get("to") == lender_id]
    quotes = sum(1 for e in counters if e["data"].get("cite"))   # the referee verified and passed these on, unnamed
    won = bool(ex.deal and ex.deal["lender"] == lender_id)
    books = ex.lender_books().get(lender_id) if offers else None
    first, last = (offers[0]["data"]["terms"], offers[-1]["data"]["terms"]) if offers else (None, None)

    exceptions = []
    if seen.get("verification_required"):
        exceptions.append(("Step-up identity check", "A fraud alert is on file. Verify identity before funding "
                                                     "(simulated KBA / one-time code).", True))
    unconf = (seen.get("reconciled") or {}).get("unconfirmed") or []
    if unconf and BOOKS.get(lender_id) and BOOKS[lender_id].reconciled:
        exceptions.append(("Unconfirmed bureau item", f"{len(unconf)} item(s) reported by only one bureau. You priced "
                                                      "on the reconciled view; confirm before funding.", True))
    if offers and not won and ex.deal and books:
        exceptions.append(("Lost on price", f"Our last offer was {last['apr']}%; our floor for these terms is "
                                            f"{books['floor_apr']}%. The borrower took another lender's offer "
                                            "(you're never told which).", False))

    if won:
        stage, status = "Accepted", "Won"
    elif offers and ex.deal:
        stage, status = "Borrower chose another offer", "Lost"
    elif offers:
        stage, status = "No deal: nothing fit the borrower's limits", "No deal"
    elif decline:
        stage, status = f"Declined: {decline['data'].get('reason_code') or 'policy'}", "Declined"
    else:
        stage, status = "Not offered", "Declined"
    attention = status == "Won" and any(action for _, _, action in exceptions)   # a human acts before funding
    return {
        "id": _app_id(ex.persona, lender_id),
        "request": {"amount": ex.mandate.amount, "terms": f"{ex.mandate.min_term}-{ex.mandate.max_term} months"},
        "band": _band(seen), "risk": _risk(seen), "signals": _signals(seen),
        "status": status, "stage": stage, "attention": attention,
        "decline_reason": decline["data"].get("text") if decline else None,
        "decline_code": decline["data"].get("reason_code") if decline else None,
        "opening": first, "final": last, "rounds": len(offers), "counters": len(counters),
        "verified_quotes": quotes,
        "books": ({k: books[k] for k in ("break_even_apr", "floor_apr", "opening_apr", "probability_of_default",
                                         "concession_style", "motive")} if books else None),
        "exceptions": [{"title": t, "note": n, "action": a} for t, n, a in exceptions],
    }


def queue(lender_id):
    """Every admitted sandbox session from this lender's side (normal market, rule-based agents, saved samples)."""
    if lender_id not in MARKET:
        raise KeyError(lender_id)
    if lender_id in _CACHE:
        return _CACHE[lender_id]
    cases = []
    for persona in PERSONAS:
        lenders, borrower = build("normal")
        ex = Exchange(persona, Mandate(), SampleSource(), lenders, borrower, today=AS_OF, watchdog=True)
        ex.run()
        if not ex.admitted:
            continue   # stopped at the CRS gate: no lender ever saw these
        cases.append(_case(ex, lender_id))
    order = {"Won": 0, "Lost": 1, "No deal": 2, "Declined": 3}
    cases.sort(key=lambda c: (not c["attention"], order[c["status"]], c["id"]))
    book = BOOKS[lender_id]
    out = {
        "lender": {"id": lender_id, "name": POLICIES[lender_id][0], "motive": book.motive,
                   "volume": {"target": book.volume_target, "booked": book.booked},
                   "reconciled": bool(book.reconciled)},
        "lenders": [{"id": i, "name": POLICIES[i][0]} for i in MARKET],
        "cases": cases,
        "stats": {"applications": len(cases), "offered": sum(c["rounds"] > 0 for c in cases),
                  "won": sum(c["status"] == "Won" for c in cases), "attention": sum(c["attention"] for c in cases),
                  "blocked_at_gate": len(PERSONAS) - len(cases)},
        "privacy": "Lenders see the passport only: no name, SSN, date of birth, address, phone, email or persona id, "
                   "and never which lender they lost to.",
    }
    _CACHE[lender_id] = out
    return out
