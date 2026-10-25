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


def network(lender_id):
    """The whole market as a graph, seen from this lender: its agent, five anonymous rival agents ("Lender A".."E",
    stable order) and the 20 borrower agents (hashed ids). Edges are lender<->borrower conversations; gate-blocked
    applicants are nodes with no edges. Rivals appear as counts only, never by name."""
    q = queue(lender_id)   # raises KeyError for an unknown lender
    rivals = [i for i in MARKET if i != lender_id]
    node_of = {lender_id: "you", **{r: f"rival-{chr(65 + k)}" for k, r in enumerate(rivals)}}
    cases = {c["id"]: c for c in q["cases"]}
    lenders = {i: {"id": node_of[i], "kind": "you" if i == lender_id else "rival",
                   "label": POLICIES[i][0] if i == lender_id else f"Lender {node_of[i][-1]}",
                   "messages": 0, "deals": 0} for i in [lender_id, *rivals]}
    applicants, edges, feed = [], [], []
    stats = {"borrower_agents": len(PERSONAS), "lender_agents": len(MARKET), "admitted": 0, "blocked_at_gate": 0,
             "messages_checked": 0, "messages_blocked": 0, "deals": 0}
    order = 0   # one running order across every session in replay order, for "talked to recently"
    for ex in sessions():
        app = _app_id(ex.persona, lender_id)
        bid = ex.borrower.id
        node = {"id": app, "kind": "applicant", "label": app, "risk": None, "band": None, "status": "Blocked",
                "messages": 0, "deals": int(bool(ex.deal))}
        if ex.admitted:
            c = cases[app]
            node.update(risk=c["risk"], band=c["band"], status=c["status"])
            stats["admitted"] += 1
        else:
            stats["blocked_at_gate"] += 1
        stats["deals"] += bool(ex.deal)
        if ex.deal and ex.deal["lender"] in lenders:
            lenders[ex.deal["lender"]]["deals"] += 1
        per = {}
        for e in ex.events:
            if e["kind"] != "message":
                continue
            order += 1
            d, ok = e["data"], e["verdict"]["ok"]
            stats["messages_checked"] += 1
            stats["messages_blocked"] += not ok
            if e["actor"] == bid:
                node["messages"] += 1
            elif e["actor"] in lenders:
                lenders[e["actor"]]["messages"] += 1
            lid = e["actor"] if e["actor"] in lenders else d.get("to") if e["actor"] == bid else None
            if lid not in lenders:
                continue   # broadcasts (the borrower's intent, a walk-away) aren't a conversation with one lender
            edge = per.setdefault(lid, {"messages": 0, "blocked": 0, "last_seq": 0, "offered": False})
            edge["messages"] += 1
            edge["blocked"] += not ok
            edge["last_seq"] = order
            edge["offered"] |= d["type"] == "OFFER" and ok and e["actor"] == lid
            frm, to = (node_of[lid], app) if e["actor"] == lid else (app, node_of[lid])
            if d["type"] == "ACCEPT" and lid != lender_id:
                continue   # would show which (anonymous) rival closed the deal: lenders never learn who won
            feed.append({"from": frm, "to": to, "what": _what(d), "verdict": "allowed" if ok else "blocked"})
        for lid, edge in per.items():
            # who won is shown on this lender's own edges only; a rival's wins are a count on its node, never which
            # applicant it took (so "you lost APP-x" never points at the rival that won it)
            mine, won = lid == lender_id, bool(ex.deal and ex.deal["lender"] == lid)
            kind = "won" if won and mine else "lost" if mine and edge["offered"] and ex.deal \
                else "offered" if edge["offered"] \
                else "declined"
            edges.append({"source": node_of[lid], "target": app, "messages": edge["messages"], "kind": kind,
                          "last_seq": edge["last_seq"], "blocked": edge["blocked"]})
        applicants.append(node)
    return {"lender": {"id": lender_id, "name": POLICIES[lender_id][0]},
            "nodes": list(lenders.values()) + applicants, "edges": edges, "stats": stats, "recent": feed[-RECENT:]}
