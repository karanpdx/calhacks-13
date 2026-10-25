"""Lender analyst (/api/lender/{id}/ask): rule-based answers from the lender's own data, Claude via a stub. Offline."""
import json
import os
import re

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from exchange import lender_assistant, lender_view  # noqa: E402
from exchange.lenders import POLICIES  # noqa: E402
from tests.test_llm_agents import StubClient  # noqa: E402

client = TestClient(app)


def ask(lid, q, **kw):
    return lender_assistant.ask(lid, [{"role": "user", "content": q}], **kw)


def test_fallback_answers_the_common_questions_with_real_numbers():
    q = lender_view.queue("prime_bank")
    s, n = q["stats"], lender_view.network("prime_bank")["stats"]
    summary = ask("prime_bank", "give me a summary")
    assert summary["source"] == "rules"
    assert f"{s['applications']} applications" in summary["reply"] and f"won {s['won']}" in summary["reply"]
    review = ask("prime_bank", "what needs my review?")
    flagged = [c["id"] for c in q["cases"] if c["attention"]]
    assert flagged and set(flagged) <= set(review["refs"])
    win = ask("prime_bank", "what's my win rate?")["reply"]
    assert f"{s['won']} won of {s['offered']} offered" in win
    lost = ask("prime_bank", "why did we lose?")
    lost_ids = [c["id"] for c in q["cases"] if c["status"] == "Lost"]
    assert lost_ids and f"lost {len(lost_ids)}" in lost["reply"] and set(lost_ids) <= set(lost["refs"])
    agents = ask("prime_bank", "how many agents are we connected to?")["reply"]
    assert f"{n['borrower_agents']} borrower agents" in agents and "sealed" in agents and "Lender A" not in agents


def test_fallback_never_names_rivals_or_personas():
    for q in ("give me a summary", "why did we lose?", "how many agents are we connected to?", "what did the gate block?",
              "risk mix", "average rate", "why did we decline?", "offers"):
        reply = ask("campus_cu", q)["reply"]
        assert not re.search(r"\bP\d\d\b", reply)
        assert not [name for i, (name, _) in POLICIES.items() if i != "campus_cu" and name in reply], q


def test_context_is_this_lenders_side_only():
    blob = json.dumps(lender_assistant.context("harbor"))
    assert not re.search(r"P\d\d", blob)
    assert not [name for i, (name, _) in POLICIES.items() if i != "harbor" and name in blob]


def test_claude_path_with_stub_client():
    stub = StubClient({"reply": "APP-ZZZZZZ is invented; one won case needs review.", "refs": ["APP-ZZZZZZ"]})
    r = ask("campus_cu", "what needs my review?", client=stub)
    assert r["source"] == "claude" and r["reply"].startswith("APP-ZZZZZZ") and r["refs"] == []   # unknown ids dropped
    assert "Campus Credit Union" in stub.requests[0]["system"]
    real = lender_view.queue("campus_cu")["cases"][0]["id"]
    r = ask("campus_cu", "summary", client=StubClient({"reply": f"Look at {real}.", "refs": [real]}))
    assert r == {"reply": f"Look at {real}.", "source": "claude", "refs": [real]}


def test_claude_errors_and_leaks_fall_back_to_rules():
    assert ask("campus_cu", "win rate", client=StubClient(RuntimeError("down")))["source"] == "rules"
    assert ask("campus_cu", "win rate", client=StubClient("not json"))["source"] == "rules"
    leak = StubClient({"reply": "You lost to Prime Bank.", "refs": []})
    assert ask("campus_cu", "why did we lose?", client=leak)["source"] == "rules"


def test_endpoint_and_validation():
    r = client.post("/api/lender/campus_cu/ask", json={"messages": [{"role": "user", "content": "give me a summary"}]})
    assert r.status_code == 200 and r.json()["source"] == "rules" and r.json()["reply"]
    assert client.post("/api/lender/nope/ask", json={"messages": []}).status_code == 404
    assert client.post("/api/lender/campus_cu/ask",
                       json={"messages": [{"role": "system", "content": "x"}]}).status_code == 422
    assert client.post("/api/lender/campus_cu/ask",
                       json={"messages": [{"role": "user", "content": "x" * 2001}]}).status_code == 422
    assert client.post("/api/lender/campus_cu/ask",
                       json={"messages": [{"role": "user", "content": "x"}] * 41}).status_code == 422
