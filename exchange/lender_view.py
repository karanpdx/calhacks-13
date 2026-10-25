"""The lender's side of the exchange: one lender's queue across every sandbox session, built from what that lender
actually saw and did. Never the applicant's name, SSN, contact details or persona id, and never another lender's
identity: only the passport (as this lender priced it), its own offers, the anonymous quotes the referee passed it,
its own books, and how the session ended for it.

Cases get an application id that's a hash of the session, so the queue can't be joined back to a persona by name.
"""
import hashlib
import threading

from agent.scorecard import AS_OF
from agent.sources import SampleSource
from .lenders import BOOKS, POLICIES, view_for
from .messages import Mandate, OFFER, DECLINE
from .referee import Exchange
from .scenarios import build

PERSONAS = [f"P{i:02d}" for i in range(1, 21)]
MARKET = ["prime_bank", "campus_cu", "newstart", "second_chance", "harbor", "ladder"]
_CACHE = {}
_SESSIONS = []
_LOCK = threading.Lock()


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


def sessions():
    """All 20 sandbox sessions (normal market, rule-based agents, saved samples), run once per process and shared by
    queue() and network(). Includes the ones stopped at the CRS gate (ex.admitted is False)."""
    with _LOCK:
        if not _SESSIONS:
            for persona in PERSONAS:
                lenders, borrower = build("normal")
                ex = Exchange(persona, Mandate(), SampleSource(), lenders, borrower, today=AS_OF, watchdog=True)
                ex.run()
                _SESSIONS.append(ex)
    return _SESSIONS


def queue(lender_id):
    """Every admitted sandbox session from this lender's side (normal market, rule-based agents, saved samples)."""
    if lender_id not in MARKET:
        raise KeyError(lender_id)
    if lender_id in _CACHE:
        return _CACHE[lender_id]
    cases = [_case(ex, lender_id) for ex in sessions() if ex.admitted]   # gate-blocked: no lender ever saw these
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


# ---------------------------------------------------------------- the web of agents, from this lender's side
RECENT = 25


def _what(d):
    """Plain words from the message's structured fields only (never its free text, which can carry a lender's name)."""
    t, terms = d["type"], d.get("terms") or {}
    if t in ("OFFER", "COUNTER", "ACCEPT") and terms:
        rate = f"{terms['apr']:g}%" + (" with autopay" if terms.get("autopay") else "")
        if t == "OFFER":
            return f"Offered {rate} on ${terms['amount']:,.0f} over {terms['term_months']} months" + \
                (f", ${terms['fee']:,.0f} fee" if terms.get("fee") else "")
        if t == "COUNTER":
            return f"Asked for {rate}" + (", no fee" if not terms.get("fee") else "")
        return f"Accepted {rate} on ${terms['amount']:,.0f}"
    if t == "DECLINE":
        code = d.get("reason_code")
        return "Declined" + (f": {code.replace('_', ' ').lower()}" if code else "")
    if t == "WITHDRAW":
        return "Withdrew its offer"
    return t.capitalize()



# CRS products the gate called for each applicant, and whether one of them raised a finding. Lenders only learn that a
# check ran and whether it flagged; never the data behind it.
CHECKS = {"tu": "TransUnion", "efx": "Equifax", "exp": "Experian", "idv": "Identity", "fraudfinder": "Fraud",
          "reverse": "Contact"}


def _checks(ex):
    rep = ex.report or {}
    src = " ".join(str(f.get("source") or "") for f in rep.get("findings", [])).lower()
    src = src.replace("tri-bureau", "transunion equifax experian")
    hit = {"idv": "identity verification" in src, "fraudfinder": "fraudfinder" in src,
           "reverse": "accurateappend" in src or "reverse" in src,
           "tu": "transunion" in src.replace("transunion identity verification", "") or "credit report" in src,
           "efx": "equifax" in src or "credit report" in src, "exp": "experian" in src or "credit report" in src}
    return [{"product": c, "label": CHECKS[c], "flag": bool(hit.get(c))}
            for c in rep.get("products_called", []) if c in CHECKS]


def network(lender_id):
    """This lender's agent and the borrower agents it talked to, nothing else. The market is sealed: a lender never
    sees other lenders (not even anonymously), how many there are, or their messages; it sees only its own
    conversations. Gate-blocked applicants are nodes with no edges (they never reached any lender)."""
    q = queue(lender_id)   # raises KeyError for an unknown lender
    cases = {c["id"]: c for c in q["cases"]}
    you = {"id": "you", "kind": "you", "label": POLICIES[lender_id][0], "messages": 0, "deals": 0}
    applicants, edges, feed = [], [], []
    stats = {"borrower_agents": len(PERSONAS), "admitted": 0, "blocked_at_gate": 0,
             "messages_checked": 0, "messages_blocked": 0, "deals": 0}
    order = 0   # one running order across every session in replay order, for "talked to recently"
    for ex in sessions():
        app = _app_id(ex.persona, lender_id)
        bid = ex.borrower.id
        won = bool(ex.deal and ex.deal["lender"] == lender_id)
        node = {"id": app, "kind": "applicant", "label": app, "risk": None, "band": None, "status": "Blocked",
                "messages": 0, "deals": int(won), "checks": _checks(ex)}
        if ex.admitted:
            c = cases[app]
            node.update(risk=c["risk"], band=c["band"], status=c["status"])
            stats["admitted"] += 1
        else:
            stats["blocked_at_gate"] += 1
        stats["deals"] += won
        you["deals"] += won
        edge = {"messages": 0, "blocked": 0, "last_seq": 0, "offered": False}
        for e in ex.events:
            if e["kind"] != "message":
                continue
            order += 1
            d, ok = e["data"], e["verdict"]["ok"]
            if not (e["actor"] == lender_id or (e["actor"] == bid and d.get("to") == lender_id)):
                continue   # sealed market: other lenders' conversations are invisible here
            stats["messages_checked"] += 1
            stats["messages_blocked"] += not ok
            (you if e["actor"] == lender_id else node)["messages"] += 1
            edge["messages"] += 1
            edge["blocked"] += not ok
            edge["last_seq"] = order
            edge["offered"] |= d["type"] == "OFFER" and ok and e["actor"] == lender_id
            frm, to = ("you", app) if e["actor"] == lender_id else (app, "you")
            feed.append({"from": frm, "to": to, "what": _what(d), "verdict": "allowed" if ok else "blocked"})
        if edge["messages"]:
            kind = "won" if won else "lost" if edge["offered"] and ex.deal else "offered" if edge["offered"]                 else "declined"
            edges.append({"source": "you", "target": app, "messages": edge["messages"], "kind": kind,
                          "last_seq": edge["last_seq"], "blocked": edge["blocked"]})
        applicants.append(node)
    return {"lender": {"id": lender_id, "name": POLICIES[lender_id][0]}, "sealed": True,
            "sources": [{"product": k, "label": v} for k, v in CHECKS.items()],
            "nodes": [you] + applicants, "edges": edges, "stats": stats, "recent": feed[-RECENT:]}


# ---------------------------------------------------------------- live: the one session running right now
def snapshot(ex):
    """What the live feed keeps of a finished (or awaiting-approval) session: the persona, whether it got past the
    gate, the winning lender, and its messages in order. Kept server-side; `live()` maps it per lender."""
    msgs = [{"actor": e["actor"], "to": e["data"].get("to"), "type": e["data"]["type"], "ok": e["verdict"]["ok"],
             "data": {k: e["data"].get(k) for k in ("type", "terms", "reason_code")}}
            for e in ex.events if e["kind"] == "message"]
    return {"persona": ex.persona, "admitted": ex.admitted, "borrower": ex.borrower.id, "checks": _checks(ex),
            "deal_lender": ex.deal["lender"] if ex.deal else None, "messages": msgs}


def live(lender_id, snap):
    """One live session from this lender's side, as a timeline of edges to light up in order: only messages between
    this lender's agent and the borrower's agent. Other lenders are invisible (sealed market); the borrower's opening
    ask is shown as reaching this lender."""
    if lender_id not in MARKET:
        raise KeyError(lender_id)
    app = _app_id(snap["persona"], lender_id)
    steps = []
    for m in snap["messages"]:
        mine = m["actor"] == lender_id or (m["actor"] == snap["borrower"] and m["to"] == lender_id)
        if m["actor"] == snap["borrower"] and m["type"] == "INTENT":
            steps.append({"from": app, "to": "you", "type": "INTENT", "verdict": "allowed",
                          "what": "Asked for a loan"})
        elif mine:
            frm, to = ("you", app) if m["actor"] == lender_id else (app, "you")
            steps.append({"from": frm, "to": to, "type": m["type"], "verdict": "allowed" if m["ok"] else "blocked",
                          "what": _what(m["data"])})
    won = snap["deal_lender"] == lender_id
    return {"applicant": app, "admitted": snap["admitted"], "checks": snap.get("checks", []), "steps": steps,
            "outcome": "won" if won else ("closed" if snap["deal_lender"] else "open")}
