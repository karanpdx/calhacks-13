"""Under-the-hood panel tests. Offline: saved samples, rule-based agents, no network, no paid APIs."""
import inspect
import json
import os
import re

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)

from agent.scorecard import AS_OF  # noqa: E402
from agent.sources import SampleSource  # noqa: E402
from exchange import hood  # noqa: E402
from exchange.messages import Mandate  # noqa: E402
from exchange.referee import Exchange, HARD_VIOLATIONS  # noqa: E402
from exchange.scenarios import build  # noqa: E402

RAW_CODE = re.compile(r"\b[A-Z]{2,}(?:_[A-Z]+)+\b")   # TERMS_WORSENED, BAD_SIGNATURE, ...
SESSIONS = [("P01", "normal"), ("P03", "normal"), ("P05", "normal"), ("P13", "normal"), ("P16", "normal"),
            ("P17", "normal"), ("P01", "bait_switch"), ("P01", "injection"), ("P01", "data_grab"), ("P01", "drift")]


def session(persona, scenario="normal", listener=None):
    lenders, borrower = build(scenario)
    ex = Exchange(persona, Mandate(), SampleSource(), lenders, borrower, today=AS_OF, watchdog=True, listener=listener)
    ex.run()
    return ex


def products(h):
    return {c["product"] for c in h["crs_products"]}


def test_every_referee_verdict_code_has_plain_words():
    codes = set(re.findall(r'V\((?:True|False), "([A-Z_]+)"', inspect.getsource(Exchange._check)))
    assert len(codes) >= 16
    assert codes <= set(hood.VERDICT_TEXT), codes - set(hood.VERDICT_TEXT)
    assert set(HARD_VIOLATIONS) | {"INJECTION"} <= set(hood.EXCLUSION_TEXT)
    for text in list(hood.VERDICT_TEXT.values()) + list(hood.EXCLUSION_TEXT.values()):
        assert not RAW_CODE.search(text)


def test_no_raw_codes_or_internals_in_the_panel():
    for persona, scenario in SESSIONS:
        h = hood.build(session(persona, scenario))
        assert h["feed"], (persona, scenario)
        for it in h["feed"]:
            for field in ("what", "verdict_text"):
                assert not RAW_CODE.search(it[field] or ""), (persona, scenario, it)
            assert it["verdict"] in ("allowed", "blocked", None)
            assert it["role"] in ("lender", "borrower", "referee", "watchdog")
            assert not re.search(r"\bo\d+\b", it["what"])   # no offer ids, sequence numbers or signatures
            assert "sig" not in it and "seq" not in it and "round" not in it
        for x in h["exclusions"]:
            assert not RAW_CODE.search(x["banner"])
        for c in h["crs_products"]:
            assert all(not RAW_CODE.search(d) for d in c["drove"])


def test_bait_switch_is_blocked_and_the_lender_gets_a_banner():
    h = hood.build(session("P01", "bait_switch"))
    blocked = [it for it in h["feed"] if it["verdict"] == "blocked"]
    whats = " ".join(it["what"] for it in blocked)
    assert "Tried to change its offer" in whats and "in your agent's name" in whats
    assert any("binding" in it["verdict_text"] for it in blocked)
    assert any("forged" in it["verdict_text"] for it in blocked)
    assert any(it["kind"] == "excluded" for it in blocked)
    [x] = h["exclusions"]
    assert x["lender"] == "Campus Credit Union"
    assert x["banner"].startswith("Campus Credit Union was removed from this session")
    assert "faked your agent's acceptance" in x["banner"] and "withdrawn" in x["banner"]
    assert h["stats"]["blocked"] == 2 and h["stats"]["excluded"] == 1 and h["stats"]["flags"] >= 1


def test_injection_banner_names_the_injecting_lender():
    h = hood.build(session("P01", "injection"))
    [x] = h["exclusions"]
    assert x["lender"] == "QuickCash Now" and "hid instructions" in x["banner"]
    says = next(it["says"] for it in h["feed"] if it["who"] == "QuickCash Now")
    assert len(says) <= hood.SAYS_MAX + 3   # shortened, shown as the agent's own words


def test_fraud_is_blocked_at_the_gate_by_identity_products():
    h = hood.build(session("P13"))
    assert any(it["verdict"] == "blocked" and it["kind"] == "blocked" for it in h["feed"])
    assert not any(it["kind"] == "message" for it in h["feed"])
    assert {"AtData Fraud Finder", "TransUnion identity verification"} <= products(h)
    ff = next(c for c in h["crs_products"] if c["product"] == "AtData Fraud Finder")
    assert any(d.startswith("Blocked as likely fraud") for d in ff["drove"])
    assert h["simulated"] == []


def test_prime_session_uses_all_three_bureau_reports():
    h = hood.build(session("P01"))
    assert {"TransUnion credit report", "Equifax credit report", "Experian credit report"} <= products(h)
    gate = h["feed"][0]
    assert gate["kind"] == "gate" and gate["verdict"] == "allowed" and len(gate["crs"]) == 6
    passport = next(it for it in h["feed"] if it["kind"] == "passport")
    assert passport["what"] == "Lenders received a summary (no name, SSN or address)"
    assert "Margaret" not in json.dumps(h)


def test_lender_declines_name_the_bureau_behind_them():
    h = hood.build(session("P17"))   # collection reported only by Experian
    prime = next(it for it in h["feed"] if it["who"] == "Prime Bank" and it["kind"] == "message")
    assert prime["what"].startswith("Declined to make an offer") and prime["crs"] == ["Experian credit report"]
    exp = next(c for c in h["crs_products"] if c["product"] == "Experian credit report")
    assert any(d.startswith("Prime Bank declined") for d in exp["drove"])
    efx = next(c for c in h["crs_products"] if c["product"] == "Equifax credit report")
    assert not any("declined" in d for d in efx["drove"])


def test_describe_works_on_a_streamed_json_copy_without_the_exchange():
    ex = session("P01", "bait_switch")
    batch = hood.build(ex)["feed"]
    streamed = [hood.describe(json.loads(json.dumps(e, default=str)), None) for e in ex.events]
    streamed = [x for x in streamed if x]
    assert [(x["id"], x["kind"], x["verdict"], x["simulated"]) for x in streamed] == \
           [(x["id"], x["kind"], x["verdict"], x["simulated"]) for x in batch]
    offer = next(x for x in streamed if x["who"] == "Campus Credit Union")
    assert offer["what"] == "Offered $5,000 at 12.5% for 36 months, no fee" and offer["verdict_text"].startswith("Allowed")


def test_describe_live_while_the_session_runs():
    """The SSE stream calls describe() on a JSON copy of each event as it is logged, with the session mid-run."""
    lenders, borrower = build("bait_switch")
    ex = Exchange("P01", Mandate(), SampleSource(), lenders, borrower, today=AS_OF, watchdog=True)
    live = []
    ex.listener = lambda e: live.append(hood.describe(json.loads(json.dumps(e, default=str)), ex))
    ex.run()
    live = [x for x in live if x]
    assert [(x["id"], x["verdict"]) for x in live] == [(x["id"], x["verdict"]) for x in hood.build(ex)["feed"]]
    assert any(x["kind"] == "excluded" for x in live)


def test_settlement_and_lender_messages_are_labelled_simulated():
    h = hood.build(session("P16"))   # fraud alert on file: step-up identity check at settlement
    settle = next(it for it in h["feed"] if it["kind"] == "settlement")
    assert settle["simulated"] and settle["steps"] and all(s["simulated"] for s in settle["steps"])
    assert not any("simulated (not" in s["text"] for s in settle["steps"])
    for it in h["feed"]:
        if it["kind"] == "message":
            assert it["simulated"] == (it["role"] == "lender")
    assert "Step-up identity checks (KBA/OTP)" in h["simulated"] and "Funding" in h["simulated"]
    assert "Funding" not in hood.build(session("P05"))["simulated"]   # no deal, nothing funded


def test_watchdog_items_keep_severity_and_skip_info():
    h = hood.build(session("P17"))
    sev = [it["severity"] for it in h["feed"] if it["kind"] == "watchdog"]
    assert "medium" in sev and "low" in sev
    info = {"seq": 9, "kind": "watchdog", "actor": "watchdog", "round": 0,
            "data": {"detector": "claude_review", "severity": "info", "agent": "watchdog", "note": "n/a"}}
    assert hood.describe(info, None) is None


def test_formatting():
    assert hood.money(5000) == "$5,000" and hood.money(49.5) == "$49.50"
    assert hood.pct(12.5) == "12.5%" and hood.pct(8) == "8.0%" and hood.pct(10.75) == "10.75%"
    assert hood.terms_text({"amount": 5000, "apr": 8.0, "term_months": 36, "autopay": True, "fee": 250}) == \
        "$5,000 at 8.0% for 36 months with autopay, $250 fee"
