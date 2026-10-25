"""Bureau reconciliation: one-bureau items are unconfirmed; opted-in lenders price on the reconciled view."""
import os

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)

from agent.scorecard import AS_OF  # noqa: E402
from agent.sources import SampleSource  # noqa: E402
from exchange import reconcile as R  # noqa: E402
from exchange.lenders import BOOKS, POLICIES, view_for  # noqa: E402
from exchange.messages import Mandate, DECLINE, OFFER  # noqa: E402
from exchange.referee import Exchange  # noqa: E402
from exchange.scenarios import build  # noqa: E402
from tests.test_passport import passport  # noqa: E402


def test_one_bureau_collection_is_unconfirmed_and_the_passport_says_why():
    q = passport("P17")
    r = q["reconciled"]
    assert q["collections"] == 1 and r["collections"] == 0             # raw field untouched; reconciled view next to it
    [u] = r["unconfirmed"]
    assert (u["item"], u["reported_by"], u["not_reported_by"]) == ("collection", "Experian", ["TransUnion"])
    assert "only at Experian" in r["note"] and "unconfirmed" in r["note"] and "TransUnion" in r["note"]
    assert r["score_low"] == 760 and q["score_low"] == 700              # the bureau with the extra item scores lower
    assert "RECOVERY" not in str(r)                                     # bureau names only, never the creditor


def test_items_bureaus_agree_on_stay_confirmed():
    r = passport("P05")["reconciled"]                                   # collections and lates at all three bureaus
    assert r["collections"] == 2 and r["late_payments"] == 8 and r["unconfirmed"] == [] and r["note"] is None
    r = passport("P11")["reconciled"]                                   # 2, 2 and 1 lates: two bureaus agree on 2
    assert r["late_payments"] == 2 and r["collections"] == 1 and r["unconfirmed"] == []


def test_counts_stand_when_only_one_bureau_has_a_file():
    r = R.reconcile({"TransUnion": {"collections": 1, "score": 650}})
    assert r["collections"] == 1 and r["unconfirmed"] == [] and r["score_low"] == 650


def test_opted_in_lender_no_longer_knocked_out_by_one_bureau_collection():
    q = passport("P17")
    assert BOOKS["campus_cu"].reconciled and not BOOKS["prime_bank"].reconciled
    assert POLICIES["campus_cu"][1](q).eligible                          # prices on the reconciled view
    p = POLICIES["prime_bank"][1](q)
    assert not p.eligible and p.code == "COLLECTION_ON_FILE"             # opted out: worst-bureau view, as before
    lenders, borrower = build("normal")
    r = Exchange("P17", Mandate(), SampleSource(), lenders, borrower, today=AS_OF).run()
    by = {e["actor"]: e["data"]["type"] for e in r["events"] if e["kind"] == "message" and e["round"] == 0}
    assert by["campus_cu"] == OFFER and by["prime_bank"] == DECLINE and r["deal"]["lender"] == "campus_cu"


def test_view_only_for_lenders_that_opt_in():
    q = passport("P17")
    assert view_for("prime_bank", q) is q
    v = view_for("campus_cu", q)
    assert v["collections"] == 0 and v["view"] == "reconciled" and R.view(v) is v
    assert R.view(passport("P04")) == passport("P04")                     # no file: nothing to reconcile
