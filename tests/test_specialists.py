"""Phase 2 specialist lenders: Harbor Newcomer Lending and Ladder Credit Builder. Offline: saved samples only."""
import os

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)

from agent.scorecard import AS_OF  # noqa: E402
from agent.sources import SampleSource  # noqa: E402
from exchange import pricing as P  # noqa: E402
from exchange.lenders import BOOKS, POLICIES, REPORTING_NOTE, RuleLender  # noqa: E402
from exchange.messages import Mandate, DECLINE, OFFER  # noqa: E402
from exchange.referee import Exchange  # noqa: E402
from exchange.scenarios import build  # noqa: E402
from tests.test_passport import passport  # noqa: E402


def run(persona, **m):
    lenders, borrower = build("normal")
    return Exchange(persona, Mandate(**m), SampleSource(), lenders, borrower, today=AS_OF).run()


def first_offers(r):
    return {e["actor"]: e["data"] for e in r["events"]
            if e["kind"] == "message" and e["data"]["type"] == OFFER and e["round"] == 0}


def test_thin_and_no_file_personas_get_competing_offers():
    for p in ("P03", "P04", "P06", "P18", "P20"):
        assert len(first_offers(run(p))) >= 2, p
    assert "harbor" in first_offers(run("P04")) and "ladder" in first_offers(run("P06"))


def test_harbor_serves_newcomers_with_strong_identity_only():
    harbor = POLICIES["harbor"][1]
    assert harbor(passport("P04")).eligible and harbor(passport("P03")).eligible
    assert not harbor(passport("P01")).eligible                        # full file: not its product
    assert not harbor({**passport("P04"), "identity_score": 75}).eligible
    assert not harbor({**passport("P03"), "collections": 1}).eligible
    o = first_offers(run("P04"))["harbor"]["terms"]
    assert o["amount"] <= 3000 and o["term_months"] in (12, 24)


def test_harbor_prices_on_identity_strength_and_positive_evidence():
    b, q = BOOKS["harbor"], passport("P04")
    assert P.floor(b, q, 3000, 24) < P.floor(b, {**q, "identity_score": 80}, 3000, 24)
    assert P.floor(b, q, 3000, 24) < P.floor(b, {**q, "address_stable": False, "phone_stable": False}, 3000, 24)
    clean = passport("P03")
    assert P.floor(b, clean, 3000, 24) < P.floor(b, {**clean, "never_late": False, "late_payments": 2}, 3000, 24)


def test_ladder_serves_people_rebuilding():
    ladder = POLICIES["ladder"][1]
    assert ladder(passport("P06")).eligible and ladder(passport("P18")).eligible   # discharged bankruptcy; charge-offs
    assert not ladder(passport("P01")).eligible and not ladder(passport("P04")).eligible
    q = ladder(passport("P07"))                                         # Chapter 13 filed, not discharged
    assert not q.eligible and "in progress" in q.reason
    assert passport("P06")["bankruptcy_discharged"] and passport("P06")["years_since_bankruptcy"] > 2


def test_ladder_small_loans_cheaper_with_autopay_and_reporting_labelled_simulated():
    o = first_offers(run("P06"))["ladder"]
    assert 500 <= o["terms"]["amount"] <= 2000 and REPORTING_NOTE in o["text"] and "simulated" in REPORTING_NOTE
    b, q = BOOKS["ladder"], passport("P06")
    saving = P.floor(b, q, 2000, 24) - P.floor(b, q, 2000, 24, autopay=True)
    no_cut = P.Book(**{**vars(b), "autopay_margin_cut": 0.0})
    assert saving > P.floor(no_cut, q, 2000, 24) - P.floor(no_cut, q, 2000, 24, autopay=True)
    assert P.private_view(b, q, 2000, 24)["reports_payments"].startswith("simulated")


def test_ladder_declines_loans_below_its_minimum():
    ex = Exchange("P06", Mandate(amount=400, min_amount=300), SampleSource(), today=AS_OF)
    ex.gate()
    lender = RuleLender("ladder")
    m = lender.respond_to_intent(ex.borrower.intent(ex.mandate), ex.passport)
    assert m.type == DECLINE and "$500" in m.text
