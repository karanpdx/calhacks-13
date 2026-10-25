"""Red team: SwiftLend Express tries to scam the borrower's agent. Offline: no API key, so it plays its fixed script."""
import os

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402

from agent.scorecard import AS_OF  # noqa: E402
from agent.sources import SampleSource  # noqa: E402
from app.main import app  # noqa: E402
from exchange.adversary import ScammerLender, report  # noqa: E402
from exchange.messages import Mandate  # noqa: E402
from exchange.referee import Exchange  # noqa: E402
from exchange.scenarios import build, SCENARIOS  # noqa: E402
from exchange.watchdog import PRESSURE  # noqa: E402

client = TestClient(app)


def run(persona="P01", watchdog=True):
    lenders, borrower = build("red_team")
    ex = Exchange(persona, Mandate(), SampleSource(), lenders, borrower, today=AS_OF, watchdog=watchdog)
    return ex, ex.run()


def test_scripted_scammer_is_caught_every_time_and_removed():
    ex, r = run()
    rep = report(ex)
    assert rep["tried"] >= 3 and rep["caught"] == rep["tried"]
    assert rep["excluded"] == "TERMS_WORSENED" and not rep["won_deal"]
    assert r["deal"] and r["deal"]["lender"] != "swiftlend"
    detectors = {f["detector"] for a in rep["attempts"] for f in a["watchdog"]}
    assert {"pressure", "personal_data", "text_vs_terms"} <= detectors
    assert all(a["source"] == "script" for a in rep["attempts"])


def test_forged_acceptance_is_a_bad_signature():
    class Forger(ScammerLender):
        def _ask(self, counter, cur):
            return {"tactics": ["forge_acceptance"], "apr": cur.apr, "fee": cur.fee, "text": "SwiftLend Express: ok."}
    lenders, borrower = build("normal")
    ex = Exchange("P01", Mandate(), SampleSource(), lenders + [Forger(client=object())], borrower, today=AS_OF,
                  watchdog=True)
    ex.run()
    rep = report(ex)
    assert any(a["tactics"] == ["forge_acceptance"] and a["referee"]["code"] == "BAD_SIGNATURE" for a in rep["attempts"])
    assert ex.excluded.get("swiftlend") == "BAD_SIGNATURE" and not rep["won_deal"]


def test_report_is_none_without_a_red_team_agent():
    lenders, borrower = build("normal")
    ex = Exchange("P01", Mandate(), SampleSource(), lenders, borrower, today=AS_OF)
    ex.run()
    assert report(ex) is None


def test_urgency_counts_as_pressure_but_ordinary_wording_does_not():
    hits = ["This rate is held for only a few minutes.", "Offer expires in 10 minutes.", "Limited-time rate!",
            "Act now to lock it in."]
    misses = ["Prime Bank: we can do 10.8%, with autopay.", "We reply within hours on weekdays.",
              "Your rate ends up lower with autopay."]
    assert all(any(p.search(t) for p in PRESSURE) for t in hits)
    assert not any(any(p.search(t) for p in PRESSURE) for t in misses)


def test_api_returns_the_red_team_report():
    assert "red_team" in SCENARIOS
    r = client.get("/api/exchange/P01?scenario=red_team").json()
    assert r["red_team"]["lender"] == "SwiftLend Express" and r["red_team"]["caught"] == r["red_team"]["tried"]
    assert client.get("/api/exchange/P01").json()["red_team"] is None
