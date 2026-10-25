"""The person's view (exchange/person.py). Offline: samples only, rule-based agents, no network, no paid APIs."""
import os
import re

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)

from agent.scorecard import AS_OF  # noqa: E402
from agent.sources import SampleSource  # noqa: E402
from exchange import person  # noqa: E402
from exchange.messages import Mandate  # noqa: E402
from exchange.referee import Exchange  # noqa: E402
from exchange.scenarios import build  # noqa: E402
from exchange.watchdog import flag  # noqa: E402

KEYS = {"outcome", "before", "deal", "protection", "no_deal", "blocked", "helped"}
CODE = re.compile(r"\b[A-Z]+_[A-Z_]+\b")   # e.g. TERMS_WORSENED, DEROG_ONLY_ONE_BUREAU


def session(persona, scenario="normal", mandate=None, watchdog=True):
    lenders, borrower = build(scenario)
    ex = Exchange(persona, mandate or Mandate(), SampleSource(), lenders, borrower, today=AS_OF, watchdog=watchdog)
    ex.run()
    return ex


def view(persona, scenario="normal", **kw):
    return person.build(session(persona, scenario, **kw))


def strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)


def test_prime_deal_shows_total_paid_and_simulated_next_steps():
    v = view("P01")
    assert set(v) == KEYS and v["outcome"] == "deal"
    d = v["deal"]
    assert d["lender"] == "Prime Bank" and d["total_paid"] > d["amount"]
    assert d["monthly_payment"] > 0 and d["headline"]
    assert d["on_accept"] and all(s["simulated"] for s in d["on_accept"])
    assert any("hard credit check" in s["text"] for s in d["on_accept"])
    assert v["no_deal"] is None and v["blocked"] is None and v["helped"]


def test_negotiated_deal_shows_savings_and_what_was_traded():
    d = view("P03")["deal"]
    assert d["lender"] == "Campus Credit Union"
    assert d["saved"] and d["saved"]["amount"] > 0 and "Campus Credit Union" in d["saved"]["sentence"]
    assert any("autopay" in t for t in d["traded"])


def test_fraud_alert_adds_identity_step_on_accept():
    d = view("P16")["deal"]
    assert "confirm it's really you" in d["on_accept"][0]["text"] and d["on_accept"][0]["simulated"]


def test_no_deal_gives_reasons_and_a_path_to_approval():
    v = view("P05")
    assert v["outcome"] == "no_deal" and v["deal"] is None
    nd = v["no_deal"]
    assert 1 <= len(nd["reasons"]) <= 3
    assert 1 <= len(nd["what_would_change"]) <= 3
    for w in nd["what_would_change"]:
        assert set(w) == {"change", "lender", "sentence"} and "likely" in w["sentence"]
    # Second Chance offered above the limit: say what monthly payment would get a yes
    assert any(w["lender"] == "Second Chance Lending" and "a month" in w["sentence"] for w in nd["what_would_change"])


def test_path_to_approval_reruns_lender_rules():
    nd = view("P06")["no_deal"]   # 580 score: NewStart's rules take 600+
    assert any(w["lender"] == "NewStart Fintech" and "600" in w["change"] for w in nd["what_would_change"])


def test_single_bureau_collection_explains_how_to_dispute():
    nd = view("P17")["no_deal"]
    b = nd["bureau_dispute"]
    assert b and b["bureau"] == "Experian" and "NATIONAL RECOVERY 1" in b["issue"]
    assert "annualcreditreport.com" in b["how_to_dispute"]
    assert any("Experian" in w["change"] for w in nd["what_would_change"])


def test_stolen_identity_is_blocked_with_both_paths():
    v = view("P13")
    assert v["outcome"] == "blocked" and v["deal"] is None and v["no_deal"] is None
    b = v["blocked"]
    assert b["headline"] and b["if_you"] and b["if_not"] and b["reasons"]
    assert "simulated" in b["if_you"] and "Freeze" in b["if_not"]
    assert v["helped"] == [] and v["protection"] == []


def test_deceased_ssn_gets_its_own_wording():
    b = view("P14")["blocked"]
    assert "died" in b["headline"] and "deceased" in b["if_not"]


def test_bait_and_switch_is_reported_plainly():
    sentences = [p["sentence"] for p in view("P01", "bait_switch")["protection"]]
    assert any("worse deal" in s and "Campus Credit Union" in s for s in sentences)
    assert any("pretending to be your agent" in s for s in sentences)
    assert len(sentences) == len(set(sentences))


def test_bait_and_switch_reported_even_with_watchdog_off():
    sentences = [p["sentence"] for p in view("P01", "bait_switch", watchdog=False)["protection"]]
    assert any("worse deal" in s for s in sentences) and any("pretending" in s for s in sentences)


def test_data_grab_warns_about_ssn_and_hidden_fee():
    prot = view("P01", "data_grab")["protection"]
    assert any("asked for your SSN" in p["sentence"] and "Never share" in p["sentence"] for p in prot)
    assert any("fee" in p["sentence"] for p in prot)
    assert all(p["severity"] in ("high", "medium") for p in prot)


def test_injection_lender_removal_is_shown():
    prot = view("P01", "injection")["protection"]
    assert any("QuickCash Now" in p["sentence"] and "removed" in p["sentence"] for p in prot)


def test_sales_pressure_and_low_flags_never_reach_the_person():
    ex = session("P01")
    ex.events.append({"seq": len(ex.events), "kind": "watchdog", "actor": "watchdog", "round": 0, "t": 0,
                      "data": flag("pressure", "medium", "campus_cu", "pre-approved", "Pressure language.",
                                   "Campus Credit Union used pressure language.", None)})
    ex.events.append({"seq": len(ex.events), "kind": "watchdog", "actor": "watchdog", "round": 0, "t": 0,
                      "data": flag("bureau_disagreement", "low", "bureaus", "spread", "Scores differ.",
                                   "Your scores differ.", None)})
    assert person.build(ex)["protection"] == []


def test_max_payment_shows_in_before():
    m = Mandate()
    setattr(m, "max_payment", 150.0)
    v = view("P01", mandate=m)
    assert v["before"]["max_monthly_payment"] == 150.0
    assert view("P01")["before"]["max_monthly_payment"] is None
    b = v["before"]
    assert b["term"] == "12 to 48 months" and b["advanced"]["autopay_ok"] is True
    assert b["soft_pull"] and b["privacy"]


def test_thin_file_people_hear_what_helped():
    assert "No late payments" in view("P03")["helped"]
    assert "Your identity checks out strongly" in view("P04", mandate=Mandate(max_apr=20))["helped"]


def test_no_codes_or_raw_fields_in_any_sentence():
    cases = [("P01", "normal"), ("P03", "normal"), ("P04", "normal"), ("P05", "normal"), ("P06", "normal"),
             ("P12", "normal"), ("P13", "normal"), ("P14", "normal"), ("P16", "normal"), ("P17", "normal"),
             ("P18", "normal"), ("P20", "normal"), ("P01", "bait_switch"), ("P01", "injection"),
             ("P01", "data_grab"), ("P01", "drift")]
    for p, sc in cases:
        for s in strings(view(p, sc)):
            assert not CODE.search(s), (p, sc, s)
            assert "score_low" not in s and "thin_file" not in s, (p, sc, s)
