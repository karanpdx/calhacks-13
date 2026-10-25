"""Web of agents (/api/lender/{id}/network): one lender's view of the whole market, rivals anonymous. Offline."""
import json
import os
import re

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from exchange import lender_view  # noqa: E402
from exchange.lenders import POLICIES  # noqa: E402

client = TestClient(app)


def test_network_shape_and_counts():
    n = lender_view.network("campus_cu")
    assert set(n) == {"lender", "nodes", "edges", "stats", "recent"}
    kinds = [x["kind"] for x in n["nodes"]]
    assert kinds.count("applicant") == 20 and kinds.count("you") == 1 and kinds.count("rival") == 5
    assert [x["label"] for x in n["nodes"] if x["kind"] == "rival"] == [f"Lender {c}" for c in "ABCDE"]
    you = next(x for x in n["nodes"] if x["kind"] == "you")
    assert you["id"] == "you" and you["label"] == "Campus Credit Union"
    s = n["stats"]
    assert s["borrower_agents"] == 20 and s["lender_agents"] == 6
    assert s["admitted"] + s["blocked_at_gate"] == 20
    q = lender_view.queue("campus_cu")
    assert s["blocked_at_gate"] == q["stats"]["blocked_at_gate"] and you["deals"] == q["stats"]["won"]
    assert sum(x["deals"] for x in n["nodes"] if x["kind"] != "applicant") == s["deals"]
    assert 0 < len(n["recent"]) <= 25
    assert all(r["verdict"] in ("allowed", "blocked") and r["what"] for r in n["recent"])


def test_edges_link_lenders_to_applicants_and_blocked_have_none():
    n = lender_view.network("prime_bank")
    lenders = {x["id"] for x in n["nodes"] if x["kind"] in ("you", "rival")}
    apps = {x["id"]: x for x in n["nodes"] if x["kind"] == "applicant"}
    for e in n["edges"]:
        assert e["source"] in lenders and e["target"] in apps
        assert e["kind"] in ("won", "offered", "declined", "lost") and e["messages"] >= 1
        if e["source"] != "you":
            assert e["kind"] in ("offered", "declined")    # a rival's wins are counts on its node only
    blocked = {i for i, x in apps.items() if x["status"] == "Blocked"}
    assert blocked and not [e for e in n["edges"] if e["target"] in blocked]
    queued = {c["id"]: c["status"] for c in lender_view.queue("prime_bank")["cases"]}
    assert {i: x["status"] for i, x in apps.items() if i not in blocked} == queued   # same ids and statuses as queue
    won = [e for e in n["edges"] if e["source"] == "you" and e["kind"] == "won"]
    assert len(won) == lender_view.queue("prime_bank")["stats"]["won"]


def test_rivals_stay_anonymous_and_no_persona_ids():
    for lid in lender_view.MARKET:
        blob = json.dumps(lender_view.network(lid))
        assert not re.search(r"P\d\d", blob), lid
        for other, (name, _) in POLICIES.items():
            if other != lid:
                assert name not in blob and f'"{other}"' not in blob, (lid, other)


def test_endpoint_and_unknown_lender():
    r = client.get("/api/lender/harbor/network")
    assert r.status_code == 200 and r.json()["lender"]["id"] == "harbor"
    assert client.get("/api/lender/quickcash/network").status_code == 404
