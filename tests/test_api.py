"""API tests. Offline: samples only, no network, no credentials, no paid APIs."""
import os

import pytest
from fastapi.testclient import TestClient

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY", "EXPLAIN_BACKEND"):
    os.environ.pop(k, None)

from app.main import app  # noqa: E402

client = TestClient(app)


def test_personas_lists_all_twenty():
    d = client.get("/api/personas").json()
    assert len(d["personas"]) == 20
    p13 = next(p for p in d["personas"] if p["id"] == "P13")
    assert p13["name"] == "Kayla Brennan" and p13["crs_expected"] == "DECLINE"
    assert "fictional" in d["notice"]


def test_p13_clean_score_but_fraud_caught():
    d = client.get("/api/decide/P13").json()
    assert d["decision"] == "STOP_FRAUD" and d["match"] is True
    assert d["score_only"]["verdict"] == "Approve" and d["score_only"]["score"] == 640
    assert d["fraud_finder"]["risk_score"] == 88
    assert {"2201", "2202"} <= {c["code"] for c in d["id_codes"]}
    assert d["source"] == "samples"
    assert d["explanation"]["by"] == "template" and "could be wrong" in d["explanation"]["text"]


def test_p12_synthetic_identity_held():
    d = client.get("/api/decide/P12").json()
    assert d["decision"] == "STOP_FRAUD" and d["score_only"]["verdict"] == "Can't score"


def test_p14_deceased_ssn_held():
    d = client.get("/api/decide/P14").json()
    assert d["decision"] == "STOP_FRAUD"
    assert "2301" in {c["code"] for c in d["id_codes"]}


def test_p03_thin_file_is_the_known_mismatch():
    d = client.get("/api/decide/P03").json()
    assert d["decision"] == "APPROVE" and d["crs_expected"] == "REVIEW" and d["match"] is False
    assert "thin file" in d["explanation"]["where_wrong"]


@pytest.mark.parametrize("p", ["P00", "P21", "X13", "p13"])
def test_unknown_persona_404(p):
    assert client.get(f"/api/decide/{p}").status_code == 404


def test_scorecard_19_of_20():
    d = client.get("/api/scorecard").json()
    assert (d["match"], d["total"]) == (19, 20)
    assert [r["persona"] for r in d["rows"] if not r["match"]] == ["P03"]


def test_live_without_credentials_falls_back_to_samples():
    d = client.get("/api/decide/P13?live=1").json()
    assert d["source"] == "samples" and "CRS_USER" in d["live_note"]


def test_live_error_falls_back_and_leaks_nothing(monkeypatch):
    monkeypatch.setenv("CRS_USER", "demo-user")
    monkeypatch.setenv("CRS_PASS", "s3cret-pass")

    class Boom:
        def __init__(self):
            raise RuntimeError("login failed for demo-user / s3cret-pass")

    monkeypatch.setattr("app.main.LiveSource", Boom)
    r = client.get("/api/decide/P13?live=1")
    assert r.status_code == 200
    d = r.json()
    assert d["source"] == "samples" and d["decision"] == "STOP_FRAUD"
    assert "s3cret-pass" not in r.text and "demo-user" not in r.text


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200 and "fictional" in r.text.lower()


def test_exchange_page_served():
    r = client.get("/exchange")
    assert r.status_code == 200 and "simulated" in r.text.lower() and "/api/exchange/" in r.text


def test_scenarios_include_lender_names():
    d = client.get("/api/exchange/scenarios").json()
    assert "normal" in d["scenarios"]
    assert d["lenders"]["campus_cu"] == "Campus Credit Union"


def test_demo_page_served_and_its_data_loads():
    r = client.get("/demo")
    assert r.status_code == 200 and "scenario=demo" in r.text
    d = client.get("/api/exchange/P03?scenario=demo").json()
    assert [b["code"] for b in d["blocked"]] == ["OUTSIDE_MANDATE"] and d["deal"]["lender"] == "campus_cu"
