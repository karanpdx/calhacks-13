"""Fairness check tests. Offline: saved samples only, no network, no paid APIs."""
import os

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402

from agent.sources import SampleSource  # noqa: E402
from app.main import app, STATIC  # noqa: E402
from exchange import fairness as F  # noqa: E402
from exchange.lenders import BOOKS, POLICIES, Quote  # noqa: E402
from exchange.messages import REASON_CODES  # noqa: E402

PERSONAS = [f"P{i:02d}" for i in range(1, 21)]
BLOCKED = ("P12", "P13", "P14")


# ---------------------------------------------------------------- 1. matrix
def test_matrix_covers_every_persona_and_every_lender():
    rows = F.matrix()
    assert [r["persona"] for r in rows] == PERSONAS
    for r in rows:
        assert set(r["cells"]) == set(BOOKS), r["persona"]          # every market lender, no attack agents
        for c in r["cells"].values():
            if c["offer"]:
                assert c["apr_low"] <= c["apr_high"] <= 36 and c["reason"]
            elif r["admitted"]:
                assert c["code"] in REASON_CODES and c["reason"]
    for r in rows:
        assert r["admitted"] == (r["persona"] not in BLOCKED)
        if not r["admitted"]:
            assert all(c["code"] == "BLOCKED_AT_GATE" for c in r["cells"].values())


def test_matrix_matches_the_lenders_own_quotes():
    row = F.persona_row("P03")
    q = POLICIES["campus_cu"][1](row["passport"])
    c = row["cells"]["campus_cu"]
    assert c["offer"] and c["apr_high"] == q.open_apr and c["apr_low"] == round(q.floor_apr - q.autopay_discount, 2)
    assert row["cells"]["prime_bank"]["code"] == "SCORE_BELOW_MIN"


def test_new_lenders_show_up_automatically(monkeypatch):
    monkeypatch.setitem(POLICIES, "test_lender", ("Test Lender", lambda p: Quote(False, "test only", code="OUTSIDE_PRODUCT")))
    monkeypatch.setitem(BOOKS, "test_lender", BOOKS["prime_bank"])
    row = F.persona_row("P01")
    assert row["cells"]["test_lender"]["code"] == "OUTSIDE_PRODUCT"
    assert any(l["lender"] == "test_lender" for l in F.disparity(F.matrix())["lenders"])


# ---------------------------------------------------------------- 2. blindness + proxy fields
def test_protected_fields_really_change():
    s, base = F.PerturbedSource(), SampleSource()
    a, b = base.applicant("P01"), s.applicant("P01")
    assert a["firstName"] != b["firstName"] and a["addresses"][0]["postalCode"] != b["addresses"][0]["postalCode"]
    assert b["dateOfBirth"] and b["phone"]
    assert s.get("P01", "fraudfinder")["email_validation"]["address"] != base.get("P01", "fraudfinder")["email_validation"]["address"]
    assert s.get("P01", "idv")["indicative"]["dateOfBirths"] != base.get("P01", "idv")["indicative"]["dateOfBirths"]
    rec = s.get("P01", "reverse")["data"]["records"][0]
    assert (rec["firstName"], rec["lastName"]) == (b["firstName"], b["lastName"])    # still the applicant's own details
    owner = s.get("P12", "reverse")["data"]["records"][0]
    assert owner["lastName"] == base.get("P12", "reverse")["data"]["records"][0]["lastName"]  # someone else: untouched


def test_decisions_and_prices_are_blind_to_protected_fields():
    results = F.blindness()
    assert len(results) == 20
    assert all(r["identical"] for r in results), [r for r in results if not r["identical"]]


def test_blindness_check_catches_a_credit_change():
    """Negative control: if a credit field changes, the same comparison must report it."""
    class LowerScore(SampleSource):
        def get(self, persona, product):
            body = super().get(persona, product)
            if body and product in ("tu", "efx", "exp"):
                for s in body.get("scores", []):
                    s["scoreValue"] = str(int(s["scoreValue"]) - 80)
            return body
    a, b = F.persona_row("P01"), F.persona_row("P01", LowerScore())
    diffs = F._diff(F._outcome(a), F._outcome(b))
    assert "passport.score_low" in diffs and "prime_bank" in diffs


def test_passport_has_no_protected_or_stand_in_fields():
    r = F.proxy_check()
    assert r["ok"], r["problems"]
    assert "file_age_years" in r["age_correlated_fields"] and "age" in r["note"]


def test_proxy_check_flags_a_protected_field():
    row = F.persona_row("P01")
    leaky = {**row, "passport": {**row["passport"], "zip_code": "95125", "language": "es"}}
    found = {p["field"] for p in F.proxy_check([leaky])["problems"]}
    assert {"zip_code", "language"} <= found
    named = {**row, "passport": {**row["passport"], "note": "OKAFOR"}}
    assert any(p["field"] == "name" for p in F.proxy_check([named])["problems"])


# ---------------------------------------------------------------- 3. consistency
def test_same_credit_fields_same_decision_and_price():
    c = F.consistency()
    assert c["ok"] and c["twins_checked"] == 17 and not c["twins_failed"]
    assert c["real_pairs_failed"] == []
    assert "No two sandbox personas" in c["note"]   # says the real-pair check is empty instead of a vacuous pass


# ---------------------------------------------------------------- 4. disparity
def test_disparity_report_groups_and_says_it_is_not_legal_review():
    d = F.disparity()
    assert d["groups"]["thin_or_no_file"] == ["P03", "P04", "P06", "P18", "P20"]
    assert set(d["excluded"]) == set(BLOCKED) and len(d["groups"]["everyone_else"]) == 12
    assert d["disclaimer"] == "Internal check, not a legal fair-lending review."
    assert "not a protected class" in d["note"]
    by = {l["lender"]: l for l in d["lenders"]}
    assert set(by) == set(BOOKS) and "quickcash" not in by
    h = by["harbor"]
    assert h["thin_or_no_file"]["approved"] >= 2 and h["everyone_else"]["approved"] == 0
    for l in d["lenders"]:
        assert l["note"].startswith(l["name"]) and "approves" in l["note"]
        assert "complian" not in l["note"].lower()


# ---------------------------------------------------------------- 5. API + page
def test_api_and_page():
    c = TestClient(app)
    d = c.get("/api/fairness").json()
    assert {"disclaimer", "lenders", "matrix", "tests", "disparity", "notice"} <= set(d)
    assert all(d["tests"][k]["ok"] for k in ("blindness", "proxy_fields", "consistency"))
    assert len(d["matrix"]) == 20 and "passport" not in d["matrix"][0]
    page = c.get("/fairness")
    assert page.status_code == 200 and "/api/fairness" in page.text and "not a legal fair-lending review" in page.text
    assert 'href="/fairness"' in open(os.path.join(STATIC, "demo.html")).read()
