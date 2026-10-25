"""The person approves the loan, not their agent. Offline: samples only, rule-based agents, no network."""
import os
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

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


@pytest.mark.parametrize("lang", ["en", "es"])
def test_approval_preserves_language_and_exact_terms(lang):
    r = client.get(f"/api/exchange/P01?approval=1&lang={lang}").json()
    pick, sid = r["awaiting_approval"], r["session_id"]
    assert r["lang"] == lang and r["person"]["outcome"] == "awaiting_approval"
    assert not any(e["kind"] == "settlement" for e in r["events"])
    headline = r["person"]["deal"]["headline"]
    assert ("Todavía no se ha firmado nada" if lang == "es" else "Nothing is signed yet") in headline
    assert client.post(f"/api/session/{sid}/approve", json={"offer_id": "wrong"}).status_code == 409
    approved = client.post(f"/api/session/{sid}/approve", json={"offer_id": pick["offer_id"]}).json()
    assert approved["lang"] == lang and approved["person"]["outcome"] == "deal"
    assert approved["deal"]["terms"] == pick["terms"]
    assert sum(e["kind"] == "settlement" for e in approved["events"]) == 1
    if lang == "es":
        assert "te presta" in approved["person"]["deal"]["headline"]
        assert all("Simulado" in s["text"] for s in approved["person"]["deal"]["on_accept"])


@pytest.mark.parametrize("action", ["approve", "decline"])
def test_spanish_stream_can_wait_then_decide_after_the_stream_closes(action):
    response = client.get("/api/exchange/P01/stream?approval=1&lang=es&pace=0")
    assert response.status_code == 200
    data = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    result = next(p for p in data if "person" in p)
    assert result["session_id"] and result["person"]["outcome"] == "awaiting_approval"
    assert not any(p.get("kind") == "settlement" for p in data)
    pending = next(p for p in data if p.get("kind") == "awaiting_approval")
    assert "permiso" in pending["view"]["what"]
    response = client.post(f"/api/session/{result['session_id']}/{action}", json={"offer_id": result["awaiting_approval"]["offer_id"]})
    assert response.status_code == 200
    finished = response.json()
    assert finished["lang"] == "es"
    if action == "decline":
        assert finished["person"]["outcome"] == "no_deal"
        assert finished["person"]["no_deal"]["reasons"] == ["Rechazaste la oferta que recomendó tu agente. No se firmó nada."]
        assert not any(e["kind"] == "settlement" for e in finished["events"])
    else:
        assert finished["person"]["outcome"] == "deal"
        assert sum(e["kind"] == "settlement" for e in finished["events"]) == 1


def test_language_can_change_at_the_decision_without_restarting_the_market():
    pending = client.get("/api/exchange/P01?approval=1&lang=en").json()
    sid, offer = pending["session_id"], pending["awaiting_approval"]["offer_id"]
    assert client.post(f"/api/session/{sid}/approve?lang=xx", json={"offer_id": offer}).status_code == 422
    approved = client.post(f"/api/session/{sid}/approve?lang=es", json={"offer_id": offer}).json()
    assert approved["lang"] == "es" and "te presta" in approved["person"]["deal"]["headline"]


def test_concurrent_double_approval_settles_once():
    pending = client.get("/api/exchange/P01?approval=1").json()
    sid, oid = pending["session_id"], pending["awaiting_approval"]["offer_id"]
    def decide_once(_):
        with TestClient(app) as parallel:
            return parallel.post(f"/api/session/{sid}/approve", json={"offer_id": oid})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(decide_once, range(2)))
    assert sorted(r.status_code for r in responses) == [200, 404]
    finished = next(r.json() for r in responses if r.status_code == 200)
    assert sum(e["kind"] == "settlement" for e in finished["events"]) == 1
