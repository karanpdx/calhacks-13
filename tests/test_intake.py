"""Chat intake tests. Offline: Claude is a stub client (see test_llm_agents.StubClient); no network, no API key."""
import os

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_MODEL"):
    os.environ.pop(k, None)

from exchange.intake import MandateChat, clean, parse, to_mandate  # noqa: E402
from exchange.messages import APR_CAP, Terms  # noqa: E402
from test_llm_agents import StubClient  # noqa: E402  (pytest puts tests/ on sys.path)


def user(*texts):
    return [{"role": "user", "content": t} for t in texts]


def fields(**kw):
    base = {"reply": "ok", "amount": None, "min_amount": None, "max_apr": None, "min_term": None, "max_term": None,
            "autopay": None, "max_fee": None, "purpose": None}
    return {**base, **kw}


# ------------------------------------------------------------------ rule-based parser (no API key)

def test_rules_read_a_complete_request():
    f = clean(parse(["I need $4,000 for a car repair, at least $3,000. Max 15% APR, 24 to 36 months, "
                     "autopay is fine, no fees."]))
    assert (f["amount"], f["min_amount"], f["max_apr"], f["min_term"], f["max_term"], f["autopay"], f["max_fee"]) == \
           (4000, 3000, 15, 24, 36, True, 0)


def test_rules_handle_years_k_amounts_and_refusing_autopay():
    f = clean(parse(["about 5k over 3 years", "no more than 12.5%", "I don't want autopay"]))
    assert (f["amount"], f["max_term"], f["max_apr"], f["autopay"]) == (5000, 36, 12.5, False)


def test_chat_asks_for_what_is_missing_without_a_key():
    r = MandateChat(client=False).turn(user("Hi, I want a loan for a laptop"))
    assert r["source"] == "rules" and not r["ready"] and r["mandate"] is None
    assert r["missing"] == ["amount", "max_apr", "term"] and "borrow" in r["reply"]


def test_chat_builds_a_mandate_over_several_turns():
    convo = user("I need $3,000") + [{"role": "agent", "content": "What's the highest APR you'd accept?"}] \
        + user("18%, and 24 months. Autopay ok.")
    r = MandateChat(client=False).turn(convo)
    assert r["ready"] and r["missing"] == []
    m = r["mandate"]
    assert (m["amount"], m["max_apr"], m["min_term"], m["max_term"], m["allow"], m["max_fee"]) == \
           (3000, 18, 12, 24, ["autopay"], 0)


def test_agent_messages_are_not_read_as_the_persons_limits():
    convo = [{"role": "agent", "content": "Most people pick $50,000 at 30% over 84 months."}] + user("hello")
    assert MandateChat(client=False).turn(convo)["missing"] == ["amount", "max_apr", "term"]


# ------------------------------------------------------------------ Claude path

def test_claude_fields_become_a_mandate():
    stub = StubClient(fields(reply="Got it. Shall I shop?", amount=5000, max_apr=14, min_term=12, max_term=36,
                             autopay=True, max_fee=0))
    r = MandateChat(client=stub).turn(user("5k, 14% max, 1-3 years, autopay ok, no fees"))
    assert r["source"] == "claude" and r["ready"] and r["reply"] == "Got it. Shall I shop?"
    assert r["mandate"]["max_apr"] == 14 and r["mandate"]["allow"] == ["autopay"]
    assert "5k, 14% max" in stub.requests[0]["messages"][0]["content"]


def test_claude_numbers_are_clamped_to_exchange_limits():
    stub = StubClient(fields(amount=-5, max_apr=99, max_term=600, min_term=1, max_fee=1e9))
    f = MandateChat(client=stub).turn(user("whatever"))["fields"]
    assert f["amount"] is None and f["max_apr"] == APR_CAP and f["max_term"] == 84 and f["min_term"] == 3
    assert f["max_fee"] == 5000


def test_mandate_never_allows_autopay_or_fees_the_person_did_not_mention():
    m = to_mandate(clean(fields(amount=2000, max_apr=20, max_term=24)))
    assert m.allow == set() and m.max_fee == 0
    assert not m.allows(Terms(2000, 15, 24, autopay=True))[0]


def test_claude_failure_falls_back_to_rules():
    r = MandateChat(client=StubClient(RuntimeError("boom"))).turn(user("$2,500 at 20% max over 24 months"))
    assert r["source"] == "rules" and r["ready"] and r["mandate"]["amount"] == 2500


def test_bad_json_falls_back_to_rules():
    r = MandateChat(client=StubClient("not json")).turn(user("$1,000"))
    assert r["source"] == "rules" and r["fields"]["amount"] == 1000
