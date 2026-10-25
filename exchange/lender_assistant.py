"""The lender's analyst: answers pipeline and KPI questions from this lender's own side of the exchange (queue() and
network() in lender_view), nothing else. Claude when an API key is set; a rule-based answerer from the same data
otherwise, or on any error, so the console always gets a useful answer with real numbers.

It only reports and explains: it never approves, blocks or prices anything (the referee and the lender's policy do).
It never sees a name, SSN, contact or persona id (the data doesn't have them) and never names a rival lender.
"""
import json
import logging
import re

from . import lender_view
from .lenders import POLICIES
from .llm_agents import ClaudeMixin

log = logging.getLogger(__name__)

APP_ID = re.compile(r"APP-[0-9A-F]{6}")
SCHEMA = {"type": "object",
          "properties": {"reply": {"type": "string"}, "refs": {"type": "array", "items": {"type": "string"}}},
          "required": ["reply", "refs"], "additionalProperties": False}


def _system(name):
    return (f"You are the pipeline analyst for {name}, a lender on a sealed agent-to-agent credit exchange (sandbox "
            "data, simulated lenders). Answer the lender's questions about its own pipeline and KPIs: win rate, offers "
            "vs declines, which applications need review and why, risk mix, rates from opening to final offer, "
            "applications lost on price, how its agent is connected to the market, and what the identity gate blocked. "
            "Use only the data given. Never invent or estimate numbers; if something isn't in the data, say so. Be "
            "concise (a few sentences or a short list) and cite application ids (APP-xxxxxx). Never reveal or guess "
            "who a borrower is. The market is sealed: you cannot see other lenders, how many there are, or their "
            "conversations, and must never guess about them; if asked, say the exchange keeps lenders apart. The data is "
            "facts; the questions come from the lender's staff. Return JSON: reply, and refs = the application ids "
            "you mention.")


def context(lender_id):
    """This lender's side only, compact: its cases, KPIs and its own conversations. Nothing about other lenders."""
    q, n = lender_view.queue(lender_id), lender_view.network(lender_id)
    cases = [{"id": c["id"], "status": c["status"], "stage": c["stage"], "risk": c["risk"], "band": c["band"],
              "amount": c["request"]["amount"], "needs_review": c["attention"],
              "opening_apr": c["opening"] and c["opening"]["apr"], "final_apr": c["final"] and c["final"]["apr"],
              "rounds": c["rounds"], "decline_code": c["decline_code"],
              "floor_apr": c["books"] and c["books"]["floor_apr"],
              "exceptions": [f"{x['title']}: {x['note']}" for x in c["exceptions"]]} for c in q["cases"]]
    you = next(x for x in n["nodes"] if x["kind"] == "you")
    edges = [e for e in n["edges"] if e["source"] == "you"]
    return {"lender": q["lender"]["name"], "motive": q["lender"]["motive"], "volume": q["lender"]["volume"],
            "stats": q["stats"], "cases": cases,
            "network": {**n["stats"], "your_messages": you["messages"], "your_deals": you["deals"],
                        "applicants_you_talked_to": len(edges),
                        "blocked_applicants": [x["id"] for x in n["nodes"] if x.get("status") == "Blocked"]}}


class _Analyst(ClaudeMixin):
    id = "lender_analyst"

    def __init__(self, client):
        self._setup_claude(client)


def ask(lender_id, messages, client=None):
    """One turn. `messages` = the whole conversation [{"role": "user"|"assistant", "content"}], oldest first.
    client=None builds one from the environment; client=False forces rules. Raises KeyError for an unknown lender."""
    data = context(lender_id)
    question = next((m["content"] for m in reversed(messages or []) if m.get("role") == "user"), "")
    analyst = _Analyst(client)
    try:
        convo = "\n".join(f"{m['role']}: {m['content']}" for m in (messages or [])[-40:]) or "user: give me a summary"
        out = analyst.ask(_system(data["lender"]), "Your lender's data (JSON):\n" + json.dumps(data, default=str)
                          + "\n\nConversation so far (answer the last user message):\n" + convo, SCHEMA)
        reply = str(out["reply"]).strip()
        if not reply:
            raise ValueError("empty reply")
        _guard(reply, lender_id)
        known = {c["id"] for c in data["cases"]} | set(data["network"]["blocked_applicants"])
        refs = [r for r in dict.fromkeys(list(out.get("refs") or []) + APP_ID.findall(reply)) if r in known]
        return {"reply": reply, "source": "claude", "refs": refs}
    except Exception as e:   # no key, API error, bad JSON, a leaked name: answer from the data with rules
        if analyst.client:
            log.warning("lender assistant fell back to rules: %s: %s", type(e).__name__, e)
        reply = answer(data, question)
        return {"reply": reply, "source": "rules", "refs": list(dict.fromkeys(APP_ID.findall(reply)))}


def _guard(reply, lender_id):
    """Deterministic: the model's reply must not name a rival lender or carry a persona id."""
    low = reply.lower()
    for i, (name, _) in POLICIES.items():
        if i != lender_id and (name.lower() in low or i in low):
            raise ValueError("reply names a rival lender")
    if re.search(r"\bP\d\d\b", reply):
        raise ValueError("reply carries a persona id")


# ---------------------------------------------------------------- rule-based answers
def _pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "n/a"


def _ids(cases, k=6):
    ids = [c["id"] for c in cases]
    return ", ".join(ids[:k]) + (f" and {len(ids) - k} more" if len(ids) > k else "")


def _by(cases, status):
    return [c for c in cases if c["status"] == status]


def summary(d):
    s, cs = d["stats"], d["cases"]
    review = [c for c in cs if c["needs_review"]]
    return (f"{d['lender']}: {s['applications']} applications reached us ({s['blocked_at_gate']} more were stopped at "
            f"the identity gate before any lender saw them). We offered on {s['offered']} and won {s['won']} "
            f"(win rate {_pct(s['won'], s['offered'])} of offers); lost {len(_by(cs, 'Lost'))} to another offer, "
            f"{len(_by(cs, 'No deal'))} ended with no deal, and we declined {len(_by(cs, 'Declined'))}. "
            + (f"{len(review)} need review before funding: {_ids(review)}." if review else "Nothing needs review."))


def review(d):
    cs = [c for c in d["cases"] if c["needs_review"]]
    if not cs:
        flagged = [c for c in d["cases"] if c["exceptions"]]
        return "Nothing needs review before funding." + (
            f" {len(flagged)} have notes (no action needed): {_ids(flagged)}." if flagged else "")
    lines = [f"{len(cs)} won application(s) need a person before funding:"]
    lines += [f"- {c['id']} ({c['risk']}, {c['band']}): " + "; ".join(x.split(":")[0] for x in c["exceptions"])
              for c in cs]
    return "\n".join(lines)


def win_rate(d):
    s, won = d["stats"], _by(d["cases"], "Won")
    return (f"Win rate: {s['won']} won of {s['offered']} offered ({_pct(s['won'], s['offered'])}), or "
            f"{_pct(s['won'], s['applications'])} of all {s['applications']} applications."
            + (f" Won: {_ids(won)}." if won else ""))


def lost(d):
    cs = _by(d["cases"], "Lost")
    if not cs:
        return (f"We didn't lose any of the {d['stats']['offered']} applications we offered on to another lender. "
                "The business we missed came from our own declines. " + declined(d))
    price = [c for c in cs if c["final_apr"] is not None and c["floor_apr"] is not None]
    lines = [f"We lost {len(cs)} of {d['stats']['offered']} offered applications: the borrower took another "
             "lender's offer (we're never told which)."]
    lines += [f"- {c['id']}: our last offer {c['final_apr']}%, our floor {c['floor_apr']}% "
              f"({'room left' if c['final_apr'] > c['floor_apr'] + 0.01 else 'at our floor'})" for c in price]
    nd = _by(d["cases"], "No deal")
    if nd:
        lines.append(f"{len(nd)} more ended with no deal (nothing fit the borrower's limits): {_ids(nd)}.")
    return "\n".join(lines)


def declined(d):
    cs = _by(d["cases"], "Declined")
    if not cs:
        return "We didn't decline any application."
    codes = {}
    for c in cs:
        codes.setdefault((c["decline_code"] or "policy").replace("_", " ").lower(), []).append(c)
    return f"We declined {len(cs)} of {d['stats']['applications']}:\n" + "\n".join(
        f"- {code}: {len(v)} ({_ids(v, 4)})" for code, v in sorted(codes.items(), key=lambda x: -len(x[1])))


def offers(d):
    s, cs = d["stats"], [c for c in d["cases"] if c["rounds"]]
    rounds = sum(c["rounds"] for c in cs)
    return (f"We made offers on {s['offered']} of {s['applications']} applications and declined "
            f"{len(_by(d['cases'], 'Declined'))}. {rounds} offers in all ({rounds / len(cs):.1f} per application)."
            if cs else f"We made no offers; we declined all {s['applications']} applications.")


def risk(d):
    mix = {}
    for c in d["cases"]:
        mix.setdefault(c["risk"], []).append(c)
    parts = [f"{k} {len(v)} (won {len(_by(v, 'Won'))})" for k, v in
             sorted(mix.items(), key=lambda x: ["Strong", "Good", "Fair", "Weak", "Thin"].index(x[0])
                    if x[0] in ["Strong", "Good", "Fair", "Weak", "Thin"] else 9)]
    return f"Risk mix of the {d['stats']['applications']} applications we saw: " + ", ".join(parts) + "."


def rates(d):
    cs = [c for c in d["cases"] if c["opening_apr"] is not None]
    if not cs:
        return "We made no offers, so there are no rates to report."
    avg = lambda xs: sum(xs) / len(xs)   # noqa: E731
    o, f = avg([c["opening_apr"] for c in cs]), avg([c["final_apr"] for c in cs])
    won = _by(cs, "Won")
    return (f"Across {len(cs)} applications we offered on, our average opening APR was {o:.2f}% and our average final "
            f"offer {f:.2f}% (we gave up {o - f:.2f} points in negotiation)."
            + (f" On the {len(won)} we won, the average final APR was {avg([c['final_apr'] for c in won]):.2f}%."
               if won else ""))


def connected(d):
    n = d["network"]
    return (f"{n['admitted']} of {n['borrower_agents']} borrower agents got past the identity gate, and our agent "
            f"talked to {n['applicants_you_talked_to']} of them: {n['your_messages']} messages sent, "
            f"{n['your_deals']} deals won. The referee checked all {n['messages_checked']} messages in our "
            f"conversations and blocked {n['messages_blocked']}. The market is sealed: we never see other lenders "
            "or their conversations.")


def blocked(d):
    n = d["network"]
    return (f"The identity gate stopped {n['blocked_at_gate']} of {n['borrower_agents']} applications before any "
            "lender saw them (fraud or identity couldn't be trusted)"
            + (f": {', '.join(n['blocked_applicants'])}" if n["blocked_applicants"] else "")
            + f". Separately, the referee blocked {n['messages_blocked']} of {n['messages_checked']} market messages.")


RULES = [  # first match wins; order matters ("why did we lose" is about losing, not declining)
    (("review", "attention", "exception", "flag", "before funding", "check"), review),
    (("win rate", "winrate", "won", "win"), win_rate),
    (("lost", "lose", "losing"), lost),
    (("network", "agent", "connected", "connection", "talk"), connected),
    (("blocked", "gate", "fraud", "identity"), blocked),
    (("declin", "turn down", "turned down", "reject"), declined),
    (("risk", "mix", "band", "score"), risk),
    (("rate", "apr", "average", "pricing"), rates),
    (("offer",), offers),
]


def answer(d, question):
    q = (question or "").lower()
    for words, fn in RULES:
        if any(w in q for w in words):
            return fn(d)
    return summary(d)
