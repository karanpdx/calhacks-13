"""Negotiation engine: lender economics, sealed market, verified competing quotes. Offline, deterministic."""
import copy
import os

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)

from agent.scorecard import AS_OF  # noqa: E402
from agent.sources import SampleSource  # noqa: E402
from exchange import pricing as P  # noqa: E402
from exchange.lenders import BOOKS, RuleLender, POLICIES  # noqa: E402
from exchange.messages import Mandate, Message, Terms, COUNTER, OFFER  # noqa: E402
from exchange.referee import Exchange  # noqa: E402
from exchange.scenarios import build  # noqa: E402

PERSONAS = [f"P{i:02d}" for i in range(1, 21)]


def run(persona, lenders=None, borrower=None, **m):
    if lenders is None:
        lenders, borrower = build("normal")
    return Exchange(persona, Mandate(**m), SampleSource(), lenders, borrower, today=AS_OF)


class Spy(RuleLender):
    """Records everything a lender is told when answering a counter."""
    seen = []

    def respond_to_counter(self, counter, passport, market):
        Spy.seen.append({"cite": counter.cite, "market": copy.deepcopy(market), "lender": self.id})
        return super().respond_to_counter(counter, passport, market)


def test_scorecard_odds_double_every_50_points_and_thin_files_cost_more():
    base = {"score_low": 700, "no_file": False, "no_score": False, "identity": "strong", "file_age_years": 5}
    pd700, _ = P.pd_annual(base)
    pd750, _ = P.pd_annual({**base, "score_low": 750})
    odds = lambda pd: (1 - pd) / pd
    assert abs(odds(pd750) / odds(pd700) - 2) < 1e-9
    assert P.pd_annual({**base, "thin_file": True})[0] > pd700


def test_floor_is_built_from_the_lenders_own_books_not_a_fixed_gap():
    ex = run("P03")
    assert ex.gate()
    p = ex.passport
    cu, ns = BOOKS["campus_cu"], BOOKS["newstart"]
    parts, _, _ = P.breakdown(cu, p, 5000, 36)
    assert set(parts) == {"cost_of_funds", "expected_loss", "servicing", "origination", "capital"}
    gaps = {k: round(P.opening(b, p, 3000, 24) - P.floor(b, p, 3000, 24), 2) for k, b in (("cu", cu), ("ns", ns))}
    assert gaps["cu"] != gaps["ns"]                       # room to negotiate differs by lender
    assert P.floor(ns, p, 3000, 24) > P.floor(cu, p, 3000, 24)   # expensive funding -> higher floor
    assert P.floor(cu, p, 5000, 36, autopay=True) < P.floor(cu, p, 5000, 36)   # autopay lowers expected loss


def test_no_offer_is_ever_below_the_lenders_floor_for_its_exact_terms():
    for persona in PERSONAS:
        lenders, borrower = build("normal")
        ex = run(persona, lenders, borrower)
        ex.run()
        by_id = {l.id: l for l in lenders}
        for e in ex.events:
            if e["kind"] == "message" and e["data"]["type"] == OFFER and e["verdict"]["ok"]:
                t = Terms(**e["data"]["terms"])
                assert t.apr + 1e-9 >= by_id[e["actor"]].floor_for(t), (persona, e["actor"], t)


def test_lenders_never_learn_who_their_rivals_are():
    Spy.seen = []
    lenders = [Spy(i) for i in POLICIES]
    _, borrower = build("normal")
    ex = run("P01", lenders, borrower)
    ex.run()
    assert Spy.seen
    for s in Spy.seen:
        assert s["cite"] is None                            # the citation is stripped before the lender sees it
        assert set(s["market"]) == {"round", "max_rounds", "verified_quote"}
        vq = s["market"]["verified_quote"]
        assert vq is None or "lender" not in vq and set(vq) == {"apr", "amount", "term_months", "autopay", "fee",
                                                                "monthly_payment"}
    assert any(s["market"]["verified_quote"] for s in Spy.seen)   # competition reaches them, anonymously


def test_a_citation_must_be_another_lenders_real_offer():
    ex = run("P01")
    ex.gate()
    a, b, borrower = ex.lenders[0], ex.lenders[1], ex.borrower
    ex.send(a, Message(OFFER, a.id, terms=Terms(5000, 11, 36)))
    ex.send(b, Message(OFFER, b.id, terms=Terms(5000, 12, 36)))
    oa, ob = list(ex.offers)
    same = Message(COUNTER, borrower.id, to=a.id, offer_id=oa, terms=Terms(5000, 10, 36), cite=oa)
    assert ex.send(borrower, same).code == "BAD_CITE"
    ok = Message(COUNTER, borrower.id, to=b.id, offer_id=ob, terms=Terms(5000, 10.5, 36), cite=oa)
    assert ex.send(borrower, ok).ok
    assert ex.market_view(ok, 0)["verified_quote"]["apr"] == 11


def test_motives_change_how_far_a_lender_moves():
    def deal_apr(volume_booked):
        BOOKS["prime_bank"].booked, saved = volume_booked, BOOKS["prime_bank"].booked
        try:
            r = run("P01").run()
            return r["deal"]["terms"]["apr"], r["lender_books"]["prime_bank"]["concession_style"]
        finally:
            BOOKS["prime_bank"].booked = saved
    on_target, style_a = deal_apr(260)    # ahead of its monthly target
    behind, style_b = deal_apr(60)        # far behind: thinner margins, concedes early
    assert behind < on_target and style_a == "holds firm" and style_b == "concedes early"


def test_a_lender_cannot_restructure_a_loan_the_borrower_didnt_ask_for():
    ex = run("P01")
    ex.gate()
    lender = ex.lenders[0]
    assert ex.send(lender, Message(OFFER, lender.id, terms=Terms(5000, 10, 36))).ok
    # same lender, longer loan at a higher total cost, unasked: still bait-and-switch
    assert ex.send(lender, Message(OFFER, lender.id, terms=Terms(5000, 10.5, 48))).code == "TERMS_WORSENED"


def test_a_lender_declines_when_even_its_floor_is_above_the_rate_cap():
    ex = run("P05")
    ex.gate()
    risky = {**ex.passport, "score_low": 500, "identity": "ok"}
    q = POLICIES["second_chance"][1](risky)
    assert not q.eligible and "rate cap" in q.reason


def test_sessions_are_deterministic():
    a, b = run("P03").run(), run("P03").run()
    strip = lambda r: [(e["kind"], e["actor"], e["data"].get("terms")) for e in r["events"]]
    assert strip(a) == strip(b) and a["deal"] == b["deal"]


def test_lender_books_are_revealed_only_after_the_session():
    ex = run("P03")
    assert ex.result()["lender_books"] == {}
    r = ex.run()
    cu = r["lender_books"]["campus_cu"]
    assert cu["floor_apr"] <= cu["opening_apr"] and cu["break_even_apr"] <= cu["floor_apr"]
    assert cu["motive"] and 0 < cu["probability_of_default"] < 1


def test_revealed_books_match_the_passport_each_lender_priced_on():
    # reconciled lenders (Campus CU, Harbor, Ladder) price on the reconciled view; their revealed floor must too
    for persona in PERSONAS:
        r = run(persona).run()
        offers = {}
        for e in r["events"]:
            if e["kind"] == "message" and e["data"]["type"] == OFFER and e["verdict"]["ok"]:
                offers[e["actor"]] = Terms(**e["data"]["terms"])
        for lid, b in r["lender_books"].items():
            if lid in offers:
                assert b["floor_apr"] <= offers[lid].apr + 1e-9, (persona, lid, b["floor_apr"], offers[lid].apr)
