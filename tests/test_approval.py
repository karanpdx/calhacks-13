"""The person approves the loan, not their agent. Offline: samples only, rule-based agents, no network."""
import os

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402

from agent.scorecard import AS_OF  # noqa: E402
from agent.sources import SampleSource  # noqa: E402
from app.main import app  # noqa: E402
from exchange import person  # noqa: E402
from exchange.messages import Mandate  # noqa: E402
from exchange.referee import Exchange  # noqa: E402
from exchange.scenarios import build  # noqa: E402

client = TestClient(app)


def session(persona="P01", scenario="normal", **m):
    lenders, borrower = build(scenario)
    ex = Exchange(persona, Mandate(**m), SampleSource(), lenders, borrower, today=AS_OF, require_approval=True)
    return ex, ex.run()


def kinds(ex):
    return [e["kind"] for e in ex.events]


def test_agent_accept_is_only_a_recommendation():
    ex, r = session()
    assert r["deal"] is None and r["awaiting_approval"]["lender"] == "prime_bank"
    assert "settlement" not in kinds(ex) and kinds(ex)[-1] == "awaiting_approval"
    assert person.build(ex)["outcome"] == "awaiting_approval" and person.build(ex)["deal"]["lender"] == "Prime Bank"


def test_person_approves_the_exact_offer_and_it_settles_once():
    ex, r = session()
    oid = r["awaiting_approval"]["offer_id"]
    assert not ex.approve("o999").ok and ex.deal and "settlement" not in kinds(ex)
    assert ex.approve(oid).ok
    assert ex.result()["deal"]["lender"] == "prime_bank" and kinds(ex).count("settlement") == 1
    assert ex.approve(oid).code == "NOTHING_TO_APPROVE" and kinds(ex).count("settlement") == 1


def test_person_declines_and_nothing_is_signed():
    ex, r = session()
    assert ex.decline().ok
    assert ex.result()["deal"] is None and "settlement" not in kinds(ex) and kinds(ex)[-1] == "no_deal"
    assert not ex.approve(r["awaiting_approval"]["offer_id"]).ok


def test_no_deal_and_blocked_sessions_have_nothing_to_approve():
    for persona, m in (("P05", {}), ("P13", {})):
        ex, r = session(persona, **m)
        assert r["awaiting_approval"] is None and not ex.awaiting_approval()


def test_without_approval_the_agent_still_closes_the_deal():
    lenders, borrower = build("normal")
    r = Exchange("P01", Mandate(), SampleSource(), lenders, borrower, today=AS_OF).run()
    assert r["deal"]["lender"] == "prime_bank" and r["awaiting_approval"] is None


def test_api_holds_the_session_until_the_person_approves():
    r = client.get("/api/exchange/P01?approval=1").json()
    sid, oid = r["session_id"], r["awaiting_approval"]["offer_id"]
    assert sid and r["deal"] is None and r["person"]["outcome"] == "awaiting_approval"
    assert client.post(f"/api/session/{sid}/approve", json={"offer_id": "o999"}).status_code == 409
    done = client.post(f"/api/session/{sid}/approve", json={"offer_id": oid})
    assert done.status_code == 200 and done.json()["person"]["outcome"] == "deal"
    assert client.post(f"/api/session/{sid}/approve", json={"offer_id": oid}).status_code == 404


def test_api_decline_ends_with_no_deal():
    sid = client.get("/api/exchange/P01?approval=1").json()["session_id"]
    d = client.post(f"/api/session/{sid}/decline").json()
    assert d["deal"] is None and d["person"]["outcome"] == "no_deal"
    assert client.post(f"/api/session/{sid}/decline").status_code == 404


def test_api_default_is_unchanged():
    r = client.get("/api/exchange/P01").json()
    assert r["deal"] and r["session_id"] is None
