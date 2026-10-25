"""Lender console (/api/lender/{id}): one lender's side of every session, passport only. Offline."""
import json
import os

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402

from agent.sources import SampleSource  # noqa: E402
from app.main import app  # noqa: E402
from exchange import lender_view  # noqa: E402

client = TestClient(app)


def _applicant_strings():
    """Every name, SSN, DOB, phone, email and street the sandbox applicants have."""
    s, out = SampleSource(), set()
    for p in lender_view.PERSONAS:
        a = s.applicant(p) or {}
        for k, v in a.items():
            if isinstance(v, str) and len(v) >= 4 and any(w in k.lower() for w in
                                                         ("name", "ssn", "birth", "dob", "phone", "email", "address", "street")):
                out.add(v.lower())
    return out


def test_the_lender_console_never_receives_personal_data_or_rival_names():
    secrets = _applicant_strings()
    assert secrets
    for lid in lender_view.MARKET:
        q = client.get(f"/api/lender/{lid}").json()
        blob = json.dumps(q["cases"]).lower()
        assert not [s for s in secrets if s in blob], lid
        assert '"p0' not in blob and '"p1' not in blob and '"p2' not in blob          # no persona ids
        for other in lender_view.MARKET:                                            # never who beat them
            if other != lid:
                assert other not in blob


def test_every_lender_sees_only_admitted_sessions_and_its_floor_holds():
    for lid in lender_view.MARKET:
        q = lender_view.queue(lid)
        assert q["stats"]["applications"] + q["stats"]["blocked_at_gate"] == 20
        for c in q["cases"]:
            if c["final"] and c["books"]:
                assert c["books"]["floor_apr"] <= c["final"]["apr"] + 1e-9, (lid, c["id"])
            assert not c["attention"] or c["status"] == "Won"


def test_unknown_lender_and_page():
    assert client.get("/api/lender/quickcash").status_code == 404
    html = client.get("/lender").text
    assert "Northstar" not in html and "TANDEM" not in html and "lenderPick" in html
