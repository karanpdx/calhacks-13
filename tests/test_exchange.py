"""Exchange tests. Offline: samples only, rule-based agents, no network, no paid APIs."""
import os

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402

from agent.scorecard import AS_OF  # noqa: E402
from agent.sources import SampleSource  # noqa: E402
from app.main import app  # noqa: E402
from exchange.messages import Mandate, Message, Terms, ACCEPT, OFFER  # noqa: E402
from exchange.referee import Exchange  # noqa: E402
from exchange.scenarios import build  # noqa: E402

client = TestClient(app)


def run(persona, scenario="normal", **m):
    lenders, borrower = build(scenario)
    return Exchange(persona, Mandate(**m), SampleSource(), lenders, borrower, today=AS_OF).run()


def codes(r):
    return [b["code"] for b in r["blocked"]]


def test_prime_borrower_gets_prime_bank_below_opening_rate():
    r = run("P01")
    assert r["deal"]["lender"] == "prime_bank"
    opening = next(e for e in r["events"] if e["kind"] == "message" and e["actor"] == "prime_bank")["data"]["terms"]["apr"]
    assert r["deal"]["terms"]["apr"] < opening
    assert not r["blocked"]


def test_thin_file_student_is_served_by_credit_union():
    r = run("P03")
    assert r["passport"]["thin_file"] and r["deal"]["lender"] == "campus_cu"


def test_fraud_blocked_before_any_lender_sees_it():
    for p in ("P12", "P13", "P14"):
        r = run(p)
        assert not r["admitted"] and r["passport"] is None and r["deal"] is None
        assert not any(e["kind"] == "message" for e in r["events"])


def test_passport_never_contains_personal_data():
    r = run("P01")
    shown = {k: v for k, v in r["passport"].items() if k != "withheld"}
    flat = str(shown).upper()
    for s in ("MARGARET", "OKAFOR", "666"):  # name, and the sandbox SSN prefix
        assert s not in flat
    assert "SSN" in r["passport"]["withheld"]


def test_no_file_newcomer_gets_an_identity_based_offer():
    r = run("P04", max_apr=20)
    assert r["passport"]["no_file"] and r["passport"]["identity"] == "strong"
    assert r["deal"]["lender"] == "newstart"


def test_subprime_walks_away_when_nothing_fits_mandate():
    r = run("P05")
    assert r["deal"] is None and any(e["kind"] == "no_deal" for e in r["events"])


def test_bait_and_switch_and_forged_acceptance_blocked():
    r = run("P01", "bait_switch")
    assert "TERMS_WORSENED" in codes(r) and "BAD_SIGNATURE" in codes(r)
    assert r["deal"]["lender"] != "campus_cu" or r["deal"]["terms"]["fee"] == 0


def test_injected_acceptance_blocked_by_mandate():
    r = run("P01", "injection")
    assert "OUTSIDE_MANDATE" in codes(r)
    assert r["deal"] is None or r["deal"]["terms"]["apr"] <= 18


def test_referee_rejects_wrong_role_and_mismatched_terms():
    ex = Exchange("P01", Mandate(), SampleSource(), today=AS_OF)
    ex.gate()
    lender, borrower = ex.lenders[0], ex.borrower
    assert ex.send(lender, Message(OFFER, lender.id, terms=Terms(5000, 9, 36))).ok
    oid = next(iter(ex.offers))
    assert ex.send(lender, Message(ACCEPT, lender.id, offer_id=oid, terms=Terms(5000, 9, 36))).code == "WRONG_ROLE"
    assert ex.send(borrower, Message(ACCEPT, borrower.id, offer_id=oid, terms=Terms(5000, 8, 36))).code == "TERMS_MISMATCH"
    assert ex.send(lender, Message(OFFER, lender.id, terms=Terms(5000, 40, 36))).code == "APR_CAP"


def test_api_exchange_endpoint():
    d = client.get("/api/exchange/P03").json()
    assert d["deal"]["lender"] == "campus_cu" and d["events"][0]["kind"] == "gate"
    assert client.get("/api/exchange/P01?scenario=injection&watchdog=0").json()["blocked"]
    assert client.get("/api/exchange/P01?scenario=nope").status_code == 404


def test_api_exchange_watchdog_on_by_default():
    d = client.get("/api/exchange/P01?scenario=injection").json()
    assert [x["agent"] for x in d["excluded"]] == ["quickcash"] and d["watchdog"]
    assert d["deal"]["lender"] == "prime_bank"
    d = client.get("/api/exchange/P17").json()
    assert any(f["detector"] == "bureau_disagreement" for f in d["watchdog"])
    assert not client.get("/api/exchange/P17?watchdog=0").json()["watchdog"]
    assert "drift" in client.get("/api/exchange/scenarios").json()["scenarios"]
