"""FastAPI wrapper around the decision agent. Run: uvicorn app.main:app --reload

Data source: saved CRS sandbox samples by default (offline, no credentials). `?live=1` calls the CRS sandbox when
CRS_USER and CRS_PASS are set, and falls back to samples on any error. Credentials are read from the environment
only, and are never logged or returned.
"""
import asyncio
import json
import logging
import os
import re
from functools import lru_cache
from typing import Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agent import scorecard as SC
from agent.explain import explain
from agent.screen import screen
from agent.sources import LiveSource, SampleSource

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
NOTICE = "Data is from the CRS sandbox: fictional test personas, not real people."
log = logging.getLogger(__name__)

app = FastAPI(title="Credit-file trust agent", description=NOTICE)


@lru_cache(maxsize=1)
def _rows():
    """Scorecard rows (samples only, deterministic). Cached: 20 personas run in well under a second."""
    return SC.run("full")


def _row(persona):
    if not re.fullmatch(r"P\d\d", persona) or persona not in SC.EXPECTED:
        raise HTTPException(404, f"unknown persona {persona!r}; use P01-P20")
    return next(r for r in _rows() if r["persona"] == persona)


def score_only_view(scores):
    """What a plain credit-score check would say (lowest bureau score). Illustrative thresholds, not CRS's."""
    got = {b: s for b, s in scores.items() if s}
    if not got:
        return {"verdict": "Can't score", "score": None, "basis": "No bureau produced a score."}
    low = min(got.values())
    verdict = "Approve" if low >= 620 else "Review" if low >= 580 else "Decline"
    return {"verdict": verdict, "score": low, "basis": f"Lowest bureau score {low} (>=620 approve, 580-619 review, <580 decline)."}


def _run_agent(persona, live):
    """Returns (report, source_used, live_note). Live failures fall back to samples; the error text is never returned."""
    note = None
    if live:
        if os.environ.get("CRS_USER") and os.environ.get("CRS_PASS"):
            try:
                return screen(LiveSource(), persona, "full", explain=False), "live", None
            except Exception as e:  # network, auth, missing collection file, unexpected payload
                note = f"Live CRS call failed ({type(e).__name__}); showing saved samples instead."
        else:
            note = "Live mode needs CRS_USER and CRS_PASS in the environment; showing saved samples instead."
    return screen(SampleSource(), persona, "full", explain=False, as_of=SC.AS_OF), "samples", note


@app.get("/api/personas")
def personas():
    return {"notice": NOTICE,
            "personas": [{"id": r["persona"], "name": r["name"], "crs_expected": r["expected"]} for r in _rows()]}


@app.get("/api/decide/{persona}")
def decide(persona: str, live: int = 0):
    row = _row(persona)
    report, source, note = _run_agent(persona, bool(live))
    exp = SC.EXPECTED[persona]
    cls = SC.CLASS[report["decision"]]
    ff = report["signals"]["fraud_finder"]
    return {
        "notice": NOTICE,
        "persona": persona,
        "name": report["applicant"] or row["name"],
        "source": source,
        "live_note": note,
        "decision": report["decision"],
        "headline": report["headline"],
        "decision_class": cls,
        "crs_expected": exp,
        "match": cls == exp,
        "identity_risk_points": report["identity_risk_points"],
        "scores": report["scores"],
        "score_only": score_only_view(report["scores"]),
        "fraud_finder": {k: ff.get(k) for k in ("risk_score", "tumbling", "email_age_days", "email_velocity", "phone_type",
                                                "phone_prepaid", "phone_owner_matches", "ip_distance")} if ff.get("available") else None,
        "id_codes": report["signals"]["id_codes"],
        "findings": report["findings"],
        "next_steps": report["next_steps"],
        "explanation": explain(report),
    }


@app.get("/api/scorecard")
def scorecard():
    rows = _rows()
    n = sum(r["match"] for r in rows)
    return {"notice": NOTICE, "match": n, "total": len(rows),
            "rows": [{k: r[k] for k in ("persona", "name", "expected", "decision", "code", "match", "reason")} for r in rows]}


# ---------------------------------------------------------------- agent credit exchange
from exchange.lenders import POLICIES  # noqa: E402
from exchange.messages import Mandate  # noqa: E402
from exchange.referee import Exchange  # noqa: E402
from exchange.scenarios import build as build_scenario, SCENARIOS  # noqa: E402
from exchange.watchdog import ClaudeReview  # noqa: E402
from exchange import hood, person as person_view  # noqa: E402


@app.get("/api/exchange/scenarios")
def exchange_scenarios():
    return {"scenarios": SCENARIOS, "lenders": {i: name for i, (name, _) in POLICIES.items()}}


def _views(ex):
    """The two readable views of a finished session: the person's screen and the judges' "under the hood" panel.
    A bug in either never breaks the session result itself."""
    out = {}
    for key, build in (("person", person_view.build), ("under_the_hood", hood.build)):
        try:
            out[key] = build(ex)
        except Exception:
            log.exception("building %s view failed", key)
            out[key] = None
    return out


def _exchange(persona, scenario, amount, min_amount, max_apr, min_term, max_term, autopay, max_fee, live, watchdog,
              review, max_payment=None):
    """Build one market session from query params. Returns (Exchange, live_note)."""
    _row(persona)
    if scenario not in SCENARIOS:
        raise HTTPException(404, f"unknown scenario {scenario!r}; use one of {sorted(SCENARIOS)}")
    lenders, borrower = build_scenario(scenario)
    mandate = Mandate(amount, min(min_amount, amount), max_apr, min_term, max_term,
                      {"autopay"} if autopay else set(), max_fee)
    mandate.max_payment = max_payment if max_payment and max_payment > 0 else None
    note, source = None, SampleSource()
    if live:
        if os.environ.get("CRS_USER") and os.environ.get("CRS_PASS"):
            try:
                source = LiveSource()
            except Exception as e:
                note = f"Live CRS login failed ({type(e).__name__}); showing saved samples instead."
        else:
            note = "Live mode needs CRS_USER and CRS_PASS in the environment; showing saved samples instead."
    ex = Exchange(persona, mandate, source, lenders, borrower, today=SC.AS_OF if source.name == "samples" else None,
                  watchdog=bool(watchdog), review=ClaudeReview() if review else None)
    return ex, note


@app.get("/api/exchange/{persona}")
def exchange(persona: str, scenario: str = "normal", amount: float = 5000, min_amount: float = 3000,
             max_apr: float = 18.0, min_term: int = 12, max_term: int = 48, autopay: int = 1, max_fee: float = 0,
             live: int = 0, watchdog: int = 1, review: int = 0, max_payment: Optional[float] = None):
    """Run one market session. Returns the full event log (gate, passport, every message with the referee's verdict,
    settlement, disclosure), plus `person` (the borrower's plain-English screen: deal, no deal or blocked) and
    `under_the_hood` (the judges' panel: plain-words feed, exclusions, which CRS product drove each decision).
    `max_payment` caps the monthly payment (the main limit for people who don't know APR; max_apr is advanced).
    `watchdog=1` (default) adds flag-only watchdog events; `review=1` adds an advisory Claude pass if ANTHROPIC_API_KEY
    is set (otherwise the rule-based flags stand)."""
    ex, note = _exchange(persona, scenario, amount, min_amount, max_apr, min_term, max_term, autopay, max_fee, live,
                         watchdog, review, max_payment)
    r = ex.run()
    return {"notice": NOTICE, "scenario": scenario, "live_note": note, **r, **_views(ex)}


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@app.get("/api/exchange/{persona}/stream")
async def exchange_stream(persona: str, scenario: str = "normal", amount: float = 5000, min_amount: float = 3000,
                          max_apr: float = 18.0, min_term: int = 12, max_term: int = 48, autopay: int = 1,
                          max_fee: float = 0, live: int = 0, watchdog: int = 1, review: int = 0, pace: float = 0.6,
                          max_payment: Optional[float] = None):
    """The same session as /api/exchange/{persona}, streamed as server-sent events while it runs.

    Events, in order: `meta` (scenario, notice, live note), then one event per referee log entry named after its
    kind (`gate`, `blocked`, `passport`, `message`, `watchdog`, `excluded`, `settlement`, `disclosure`, `no_deal`),
    each carrying the same JSON as an entry in `events` plus `view` (that entry as a plain-words "under the hood" feed
    item, or null for entries the panel skips), then `result` (the full result minus the event log, with `person` and
    `under_the_hood`) and `done`. On a failure mid-session: `error`, then `done`. `pace` (seconds, 0-3) spaces events
    out so a fast rule-based session can be watched; Claude agents stream as fast as they think."""
    pace = min(max(pace, 0.0), 3.0)
    loop, q = asyncio.get_running_loop(), asyncio.Queue()
    ex, note = _exchange(persona, scenario, amount, min_amount, max_apr, min_term, max_term, autopay, max_fee, live,
                         watchdog, review, max_payment)

    def push(e):
        """Runs in the session's worker thread as each event is logged: copy it (the session keeps going), add its
        plain-words feed item, and hand it to the event loop."""
        copy = json.loads(json.dumps(e, default=str))
        try:
            copy["view"] = hood.describe(copy, ex)
        except Exception:
            log.exception("describing event %s failed", e.get("seq"))
            copy["view"] = None
        loop.call_soon_threadsafe(q.put_nowait, (e["kind"], copy))

    ex.listener = push

    async def run():
        try:
            r = await asyncio.to_thread(ex.run)
            views = await asyncio.to_thread(_views, ex)
            q.put_nowait(("result", {**{k: v for k, v in r.items() if k != "events"}, **views}))
        except Exception as e:  # the type only: never leak credentials or vendor bodies into the stream
            q.put_nowait(("error", {"error": type(e).__name__, "note": "The session stopped; nothing was settled."}))
        q.put_nowait(None)

    async def events():
        task = asyncio.create_task(run())
        try:
            yield _sse("meta", {"notice": NOTICE, "persona": persona, "scenario": scenario, "live_note": note,
                                "mandate": {**vars(ex.mandate), "allow": sorted(ex.mandate.allow)}})
            while (item := await q.get()) is not None:
                yield _sse(*item)
                if pace and item[0] not in ("result", "error"):
                    await asyncio.sleep(pace)
            yield _sse("done", {})
        finally:
            await task

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- chat intake: conversation -> mandate
from pydantic import BaseModel, Field  # noqa: E402
from exchange.intake import MandateChat  # noqa: E402


class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|agent)$")
    content: str = Field(max_length=2000)


class ChatRequest(BaseModel):
    messages: list[ChatTurn] = Field(default_factory=list, max_length=40)


@app.post("/api/chat/mandate")
def chat_mandate(req: ChatRequest):
    """One turn of the person's chat with their agent. Send the whole conversation (oldest first); get back the
    agent's reply, the limits understood so far, what's still missing, and a `mandate` once it's `ready`. Pass the
    mandate's fields to /api/exchange/{persona}/stream to send the agent to the market. Uses Claude when
    ANTHROPIC_API_KEY is set, otherwise a rule-based parser (`source` says which)."""
    return {"notice": NOTICE, **MandateChat().turn([m.model_dump() for m in req.messages])}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/exchange")
def exchange_page():
    return FileResponse(os.path.join(STATIC, "exchange.html"))


@app.get("/demo")
def demo_page():
    return FileResponse(os.path.join(STATIC, "demo.html"))


@app.get("/phone")
def phone_page():
    """The borrower app alone, full screen, for a real phone on the same network (same file as /demo)."""
    return FileResponse(os.path.join(STATIC, "demo.html"))


# ---------------------------------------------------------------- phone pairing (demo only)
# The phone posts the session it just ran; a laptop on /demo?follow=1 polls and replays the same session, so both
# screens show the same numbers. In memory, last session only, no auth: a demo convenience on a trusted network.
_PAIR = {"seq": 0}


@app.post("/api/pair")
def pair_push(body: dict = Body(...)):
    seq = _PAIR.get("seq", 0) + 1
    _PAIR.clear()
    _PAIR.update(body, seq=seq)
    return {"seq": seq}


@app.get("/api/pair")
def pair_latest(after: int = 0):
    return _PAIR if _PAIR.get("seq", 0) > after else {"seq": _PAIR.get("seq", 0)}


@app.get("/api/pair/info")
def pair_info():
    """This machine's address on the local network, so the laptop can tell people which URL to open on the phone."""
    import socket
    ip = "127.0.0.1"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; this just picks the outbound interface
            ip = s.getsockname()[0]
    except OSError:
        pass
    return {"ip": ip}


app.mount("/static", StaticFiles(directory=STATIC), name="static")
