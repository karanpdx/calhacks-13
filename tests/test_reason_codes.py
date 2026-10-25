"""Every lender DECLINE carries a fixed reason code next to its unchanged plain sentence. Offline: samples only."""
import os

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402

from agent.scorecard import AS_OF  # noqa: E402
from agent.sources import SampleSource  # noqa: E402
from app.main import app  # noqa: E402
from exchange.hood import REASON_SOURCES  # noqa: E402
from exchange.lenders import POLICIES  # noqa: E402
from exchange.messages import Mandate, REASON_CODES, DECLINE  # noqa: E402
from exchange.referee import Exchange  # noqa: E402
from exchange.scenarios import build  # noqa: E402

ADMITTED = [f"P{i:02d}" for i in range(1, 21) if i not in (12, 13, 14)]


def declines(persona, **m):
    lenders, borrower = build("normal")
    ex = Exchange(persona, Mandate(**m), SampleSource(), lenders, borrower, today=AS_OF)
    r = ex.run()
    return [e for e in r["events"] if e["kind"] == "message" and e["data"]["type"] == DECLINE
            and ex.roles.get(e["actor"]) == "lender"]


def test_every_eligibility_decline_has_a_fixed_code():
    for p in ADMITTED:
        for e in declines(p):
            d = e["data"]
            if "is our best" in d["text"]:     # counter reply: the offer stays live, nothing was declined
                assert d["reason_code"] is None, (p, d["text"])
            else:
                assert d["reason_code"] in REASON_CODES, (p, e["actor"], d["text"])


def test_codes_name_the_actual_reason():
    want = {
        ("P03", "prime_bank"): "SCORE_BELOW_MIN", ("P04", "prime_bank"): "NO_SCORE",
        ("P04", "campus_cu"): "FEW_ACCOUNTS", ("P05", "newstart"): "IDENTITY_UNCONFIRMED",
        ("P15", "prime_bank"): "BUREAUS_DISAGREE", ("P17", "prime_bank"): "COLLECTION_ON_FILE",
        ("P18", "campus_cu"): "CHARGEOFF_ON_FILE", ("P06", "campus_cu"): "BANKRUPTCY_ON_FILE",
        ("P01", "harbor"): "OUTSIDE_PRODUCT", ("P01", "campus_cu"): "OUTSIDE_PRODUCT",
    }
    got = {(p, e["actor"]): e["data"]["reason_code"] for p in {p for p, _ in want} for e in declines(p)}
    for k, code in want.items():
        assert got[k] == code, (k, got.get(k))


def _passport(p):
    ex = Exchange(p, today=AS_OF)
    ex.gate()
    return ex.passport


def test_reason_sentences_unchanged_and_still_matched_by_hood():
    texts = {e["actor"]: e["data"]["text"] for e in declines("P04")}
    assert texts["prime_bank"] == "Prime Bank: needs a scored credit file."
    assert texts["campus_cu"] == "Campus Credit Union: needs at least one account on file."
    for p in ADMITTED:                 # the original lenders' sentences still map to a CRS product in hood.py
        q = _passport(p)
        for lid in ("prime_bank", "campus_cu", "newstart", "second_chance"):
            quote = POLICIES[lid][1](q)
            if not quote.eligible and quote.code != "OUTSIDE_PRODUCT":
                assert any(rx.search(quote.reason) for rx, _ in REASON_SOURCES), (p, lid, quote.reason)


def test_reason_code_reaches_the_api():
    d = TestClient(app).get("/api/exchange/P04").json()
    codes = {e["actor"]: e["data"].get("reason_code") for e in d["events"]
             if e["kind"] == "message" and e["data"]["type"] == DECLINE}
    assert codes["prime_bank"] == "NO_SCORE"
