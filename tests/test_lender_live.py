"""Live agent web: the latest borrower session, seen from one lender's side. Offline, saved samples."""
import json, os, re

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from exchange.lenders import POLICIES  # noqa: E402

client = TestClient(app)


def test_live_is_empty_until_a_session_runs_then_lights_its_edges():
    seq = client.get("/api/lender/campus_cu/live").json()["seq"]
    assert "session" not in client.get(f"/api/lender/campus_cu/live?after={seq}").json()
    client.get("/api/exchange/P03")
    r = client.get(f"/api/lender/campus_cu/live?after={seq}").json()
    s = r["session"]
    assert r["seq"] == seq + 1 and s["applicant"].startswith("APP-") and s["admitted"]
    ids = {x for st in s["steps"] for x in (st["from"], st["to"])}
    assert ids == {s["applicant"], "you"}   # sealed: only this lender's own conversation
    assert s["steps"][0]["type"] == "INTENT"


def test_live_never_names_rivals_or_shows_who_won():
    client.get("/api/exchange/P01")
    for lid in ("campus_cu", "prime_bank"):
        s = client.get(f"/api/lender/{lid}/live").json()["session"]
        text = json.dumps(s)
        assert not re.search(r"\bP\d\d\b", text)
        assert not any(POLICIES[o][0] in text for o in POLICIES if o != lid)
        assert all(st["to"] == "you" for st in s["steps"] if st["type"] == "ACCEPT")


def test_blocked_session_has_no_lender_steps():
    client.get("/api/exchange/P13")
    s = client.get("/api/lender/campus_cu/live").json()["session"]
    assert not s["admitted"] and all(st["to"] == "*" for st in s["steps"])


def test_live_unknown_lender():
    assert client.get("/api/lender/nope/live").status_code == 404


def test_live_stream_pushes_the_next_session():
    seq = client.get("/api/lender/campus_cu/live").json()["seq"]
    client.get("/api/exchange/P03")
    got = []
    with client.stream("GET", f"/api/lender/campus_cu/live/stream?after={seq}&once=1") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data: "):
                got.append(json.loads(line[6:]))
    assert got[0] == {"seq": seq} and got[-1]["session"]["applicant"].startswith("APP-")
    assert got[-1]["session"]["checks"]
