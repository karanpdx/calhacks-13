"""SSE stream and chat API tests. Offline: saved samples, rule-based agents, no API key."""
import json
import os

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_MODEL"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def stream(url):
    """Read a whole SSE response into [(event, data), ...]."""
    out, event = [], None
    with client.stream("GET", url) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                out.append((event, json.loads(line[6:])))
    return out


def test_stream_matches_the_batch_endpoint():
    got = stream("/api/exchange/P01/stream?pace=0")
    names = [e for e, _ in got]
    assert names[0] == "meta" and names[-2:] == ["result", "done"]
    events = [d for e, d in got if e not in ("meta", "result", "done")]
    batch = client.get("/api/exchange/P01").json()["events"]
    assert [(e["seq"], e["kind"]) for e in events] == [(e["seq"], e["kind"]) for e in batch]
    assert [d["kind"] for e, d in got if e not in ("meta", "result", "done")] == names[1:-2]
    assert got[-2][1]["deal"] == client.get("/api/exchange/P01").json()["deal"]


def test_streamed_offers_carry_their_offer_id():
    offers = [d["data"] for e, d in stream("/api/exchange/P01/stream?pace=0")
              if e == "message" and d["data"]["type"] == "OFFER" and d["verdict"]["ok"]]
    assert offers and all(o["offer_id"] for o in offers)


def test_fraud_is_blocked_on_the_stream():
    names = [e for e, _ in stream("/api/exchange/P13/stream?pace=0")]
    assert "blocked" in names and "message" not in names and names[-1] == "done"


def test_stream_shows_the_referee_blocking_a_bait_and_switch():
    codes = [d["verdict"]["code"] for e, d in stream("/api/exchange/P01/stream?pace=0&scenario=bait_switch")
             if e == "message" and not d["verdict"]["ok"]]
    assert "TERMS_WORSENED" in codes


def test_stream_uses_the_mandate_from_the_query():
    meta = stream("/api/exchange/P03/stream?pace=0&amount=3000&max_apr=16&max_term=36&autopay=0")[0][1]
    assert meta["mandate"]["max_apr"] == 16 and meta["mandate"]["allow"] == []


def test_stream_rejects_unknown_persona_and_scenario():
    assert client.get("/api/exchange/P99/stream").status_code == 404
    assert client.get("/api/exchange/P01/stream?scenario=nope").status_code == 404


def test_streamed_events_carry_a_plain_words_view():
    got = stream("/api/exchange/P01/stream?pace=0&scenario=bait_switch")
    views = [d["view"] for e, d in got if e not in ("meta", "result", "done")]
    assert all("view" in d for e, d in got if e not in ("meta", "result", "done"))
    assert any(v and v["verdict"] == "blocked" for v in views)


def test_result_carries_the_person_and_judge_views():
    result = dict(stream("/api/exchange/P01/stream?pace=0"))["result"]
    assert result["person"]["outcome"] == "deal" and result["person"]["deal"]["total_paid"] > 0
    assert result["under_the_hood"]["feed"]
    batch = client.get("/api/exchange/P13").json()
    assert batch["person"]["outcome"] == "blocked" and batch["under_the_hood"]["stats"]["blocked"] >= 0


def test_max_payment_reaches_the_mandate():
    meta = stream("/api/exchange/P01/stream?pace=0&max_payment=150")[0][1]
    assert meta["mandate"]["max_payment"] == 150
    person = client.get("/api/exchange/P01?max_payment=150").json()["person"]
    assert person["before"]["max_monthly_payment"] == 150
    deal = person["deal"]
    assert deal is None or deal["monthly_payment"] <= 150


def test_chat_endpoint_round_trip():
    r = client.post("/api/chat/mandate", json={"messages": [
        {"role": "user", "content": "I need $4,000, max 15% APR, 36 months, autopay ok"}]}).json()
    assert r["ready"] and r["source"] == "rules" and r["mandate"]["amount"] == 4000
    first = client.post("/api/chat/mandate", json={"messages": []}).json()
    assert not first["ready"] and first["reply"]


def test_chat_endpoint_validates_input():
    assert client.post("/api/chat/mandate", json={"messages": [{"role": "system", "content": "x"}]}).status_code == 422
    assert client.post("/api/chat/mandate", json={"messages": [{"role": "user", "content": "x" * 2001}]}).status_code == 422
