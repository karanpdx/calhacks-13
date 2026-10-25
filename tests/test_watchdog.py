"""Watchdog tests. Offline: samples only, rule-based agents, no network, no paid APIs."""
import os

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)

from agent.scorecard import AS_OF  # noqa: E402
from agent.sources import SampleSource  # noqa: E402
from exchange.messages import Mandate  # noqa: E402
from exchange.referee import Exchange  # noqa: E402
from exchange.scenarios import build  # noqa: E402


def run(persona, scenario="normal", watchdog=True, **m):
    lenders, borrower = build(scenario)
    return Exchange(persona, Mandate(**m), SampleSource(), lenders, borrower, today=AS_OF, watchdog=watchdog).run()


def flags(r, detector, agent=None):
    return [f for f in r["watchdog"] if f["detector"] == detector and (agent is None or f["agent"] == agent)]


def notes(r):
    d = next(e for e in r["events"] if e["kind"] in ("disclosure", "no_deal"))["data"]
    return " ".join(n["note"] for n in d["watchdog_notes"])


def test_injection_flagged_and_lender_excluded():
    r = run("P01", "injection")
    f = flags(r, "injection", "quickcash")
    assert f and f[0]["severity"] == "high" and f[0]["source"] == "rules"
    ex = r["excluded"]
    assert [x["agent"] for x in ex] == ["quickcash"] and ex[0]["code"] == "INJECTION" and ex[0]["withdrawn"]
    # its offer was withdrawn before the compromised borrower could act on it: no OUTSIDE_MANDATE loop, a real deal
    assert "OUTSIDE_MANDATE" not in [b["code"] for b in r["blocked"]]
    assert r["deal"]["lender"] == "prime_bank"
    assert "hidden instructions" in notes(r)


def test_bait_and_switch_text_contradiction_and_exclusion():
    r = run("P01", "bait_switch")
    f = flags(r, "text_vs_terms", "campus_cu")
    assert f and "same deal" in f[0]["note"] and "$250 fee" in f[0]["note"]
    codes = [b["code"] for b in r["blocked"]]
    assert "TERMS_WORSENED" in codes and "BAD_SIGNATURE" in codes   # forgery still caught (and attributed)
    ex = r["excluded"]
    assert [x["agent"] for x in ex] == ["campus_cu"] and ex[0]["code"] == "TERMS_WORSENED" and ex[0]["withdrawn"]
    assert r["deal"]["lender"] != "campus_cu"
    # nothing from campus_cu after exclusion is accepted, and nobody counters it again
    after = [e for e in r["events"] if e["seq"] > ex[0]["seq"] and e["kind"] == "message"]
    assert not any(e["actor"] == "campus_cu" and e["verdict"]["ok"] for e in after)
    assert not any(e["data"].get("to") == "campus_cu" and e["data"]["type"] == "COUNTER" for e in after)


def test_lender_asking_for_personal_data_and_undeclared_fee():
    r = run("P01", "data_grab")
    f = flags(r, "personal_data", "newstart")
    assert f and f[0]["severity"] == "high" and "SSN and date of birth" in f[0]["note"]
    assert any("fee that isn't in its offer" in x["note"] for x in flags(r, "text_vs_terms", "newstart"))
    assert not r["excluded"]   # flag-only: personal-data requests don't change the market


def test_borrower_drift_flagged_but_not_blocked():
    r = run("P01", "drift", max_fee=200)   # a fee limit wide enough that Second Chance's offer fits too
    assert r["deal"]["lender"] == "second_chance" and not r["blocked"]   # inside the mandate: the referee allows it
    f = [x["note"] for x in flags(r, "borrower_drift", "borrower")]
    assert any("17.47% while an 11.22% offer from Prime Bank" in n for n in f)
    assert any("limit is 18%" in n for n in f)
    assert "Your agent accepted 17.47% while an 11.22% offer" in notes(r)   # the person sees it in their disclosure


def test_bureau_disagreement_suggests_dispute():
    r = run("P17")
    f = flags(r, "bureau_disagreement")
    coll = next(x for x in f if "only at Experian" in x["note"])
    assert "dispute" in coll["suggestion"] and "Experian" in coll["suggestion"]
    assert any("Prime Bank and Campus Credit Union" in x["note"] for x in f)   # what it cost, at session end
    assert "only at Experian" in notes(r)


def test_honest_market_has_no_false_alarms():
    for i in range(1, 21):
        r = run(f"P{i:02d}")
        assert not r["excluded"], r["persona"]
        assert not [f for f in r["watchdog"] if f["detector"] != "bureau_disagreement"], r["persona"]


def test_watchdog_off_changes_nothing():
    for sc in ("normal", "injection", "bait_switch"):
        off = run("P01", sc, watchdog=False)
        assert not off["watchdog"] and not off["excluded"]
    assert "OUTSIDE_MANDATE" in [b["code"] for b in run("P01", "injection", watchdog=False)["blocked"]]
    assert run("P01", watchdog=False)["deal"] == run("P01")["deal"]


# ---------------------------------------------------------------- phase 2: Claude review (fake clients, no network)
import json  # noqa: E402
from types import SimpleNamespace as NS  # noqa: E402

from exchange.watchdog import ClaudeReview  # noqa: E402


class FakeClient:
    def __init__(self, reply=None, error=None):
        self.calls, self.reply, self.error = [], reply, error
        self.messages = self.beta = self
        self.beta.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return NS(stop_reason="end_turn", content=[NS(type="text", text=json.dumps(self.reply))])


def run_review(client, persona="P01", scenario="normal"):
    lenders, borrower = build(scenario)
    ex = Exchange(persona, Mandate(), SampleSource(), lenders, borrower, today=AS_OF, watchdog=True,
                  review=ClaudeReview(client=client))
    return ex.run()


def test_claude_review_adds_advisory_flags_without_changing_the_deal():
    base = run("P01", "drift")
    fake = FakeClient({"flags": [
        {"severity": "medium", "agent": "borrower", "ref": None, "saw": "accepted in round 1",
         "why": "Accepted without countering anyone.", "note": "Your agent didn't try to negotiate at all."},
        {"severity": "high", "agent": "made_up_agent", "ref": 3, "saw": "x", "why": "x", "note": "x"},  # dropped
    ]})
    r = run_review(fake, scenario="drift")
    claude = [f for f in r["watchdog"] if f["source"] == "claude"]
    assert [f["note"] for f in claude] == ["Your agent didn't try to negotiate at all."]
    assert r["deal"] == base["deal"] and r["excluded"] == base["excluded"]
    assert "didn't try to negotiate" in notes(r)
    # privacy: Claude never sees the gate event (applicant name)
    sent = json.dumps(fake.calls[0]["messages"])
    assert "Okafor" not in sent and "Margaret" not in sent


def test_claude_flags_never_trigger_exclusion():
    fake = FakeClient({"flags": [{"severity": "high", "agent": "prime_bank", "ref": None, "saw": "ignore your mandate",
                                  "why": "looks like injection", "note": "Prime Bank looks shady."}]})
    r = run_review(fake)
    assert not r["excluded"] and r["deal"]["lender"] == "prime_bank"


def test_claude_review_falls_back_to_rules_on_failure():
    base = run("P01", "injection")
    r = run_review(FakeClient(error=RuntimeError("boom")), scenario="injection")
    info = [f for f in r["watchdog"] if f["detector"] == "claude_review"]
    assert info and info[0]["severity"] == "info"
    rules = lambda x: [(f["detector"], f["agent"]) for f in x["watchdog"] if f["source"] == "rules"]
    assert rules(r) == rules(base) and r["deal"] == base["deal"]
    assert "AI review" not in notes(r)   # info notes aren't shown to the person
    # no key and no client: falls back without touching the network
    r = run_review(None)
    assert any("ANTHROPIC_API_KEY" in f["saw"] for f in r["watchdog"] if f["detector"] == "claude_review")


def test_fee_detector_ignores_no_fee_wording():
    from exchange.watchdog import FEE_WORD, NO_FEE
    for text in ("No origination fee.", "Zero fees, 8.5%.", "We're processing your request: 8.5%."):
        assert not (FEE_WORD.search(text) and not NO_FEE.search(text)), text
    assert FEE_WORD.search("A $49 processing fee applies.") and not NO_FEE.search("A $49 processing fee applies.")


def test_sales_pressure_is_flagged_but_does_not_exclude():
    from exchange.borrower import RuleBorrower
    from exchange.lenders import RuleLender

    class PushyLender(RuleLender):
        def respond_to_intent(self, intent, passport):
            m = super().respond_to_intent(intent, passport)
            m.text += (" You're pre-approved, accept now to lock it in. Please disregard our earlier quote;"
                       " we can override our standard pricing.")
            return m

    lenders = [PushyLender("prime_bank")] + [RuleLender(i) for i in ("campus_cu", "newstart", "second_chance")]
    r = Exchange("P01", Mandate(), SampleSource(), lenders, RuleBorrower(), today=AS_OF, watchdog=True).run()
    assert not r["excluded"] and not flags(r, "injection")
    assert flags(r, "pressure", "prime_bank") and r["deal"]["lender"] == "prime_bank"
