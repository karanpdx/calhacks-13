"""FastAPI wrapper around the decision agent. Run: uvicorn app.main:app --reload

Data source: saved CRS sandbox samples by default (offline, no credentials). `?live=1` calls the CRS sandbox when
CRS_USER and CRS_PASS are set, and falls back to samples on any error. Credentials are read from the environment
only, and are never logged or returned.
"""
import os
import re
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent import scorecard as SC
from agent.explain import explain
from agent.screen import screen
from agent.sources import LiveSource, SampleSource

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
NOTICE = "Data is from the CRS sandbox: fictional test personas, not real people."

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
from exchange.messages import Mandate  # noqa: E402
from exchange.referee import Exchange  # noqa: E402
from exchange.scenarios import build as build_scenario, SCENARIOS  # noqa: E402


@app.get("/api/exchange/scenarios")
def exchange_scenarios():
    return {"scenarios": SCENARIOS}


@app.get("/api/exchange/{persona}")
def exchange(persona: str, scenario: str = "normal", amount: float = 5000, min_amount: float = 3000,
             max_apr: float = 18.0, min_term: int = 12, max_term: int = 48, autopay: int = 1, max_fee: float = 0,
             live: int = 0):
    """Run one market session. Returns the full event log (gate, passport, every message with the referee's verdict,
    settlement, disclosure). The UI can replay `events` in order to animate the negotiation."""
    _row(persona)
    if scenario not in SCENARIOS:
        raise HTTPException(404, f"unknown scenario {scenario!r}; use one of {sorted(SCENARIOS)}")
    lenders, borrower = build_scenario(scenario)
    mandate = Mandate(amount, min(min_amount, amount), max_apr, min_term, max_term,
                      {"autopay"} if autopay else set(), max_fee)
    note, source = None, SampleSource()
    if live:
        if os.environ.get("CRS_USER") and os.environ.get("CRS_PASS"):
            try:
                source = LiveSource()
            except Exception as e:
                note = f"Live CRS login failed ({type(e).__name__}); showing saved samples instead."
        else:
            note = "Live mode needs CRS_USER and CRS_PASS in the environment; showing saved samples instead."
    r = Exchange(persona, mandate, source, lenders, borrower, today=SC.AS_OF if source.name == "samples" else None).run()
    return {"notice": NOTICE, "scenario": scenario, "live_note": note, **r}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC), name="static")
