"""Passport tests for Phase 2 (thin-file and no-file borrowers). Offline: saved samples only."""
import os

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)

import agent.signals as S  # noqa: E402
from agent.scorecard import AS_OF  # noqa: E402
from agent.screen import screen  # noqa: E402
from agent.sources import SampleSource  # noqa: E402
from exchange import passport as PP  # noqa: E402
from exchange.referee import Exchange  # noqa: E402

SIGNALS = {"ssn_name_match", "phone_owned", "email_owned", "email_age_ok", "address_deliverable", "ip_near"}


def passport(persona):
    """The passport the referee builds at the gate (None if the gate blocks the person)."""
    ex = Exchange(persona, today=AS_OF)
    ex.gate()
    return ex.passport


def raw_passport(persona):
    """Build the passport even for a blocked persona, to check the score on fraud cases."""
    src = SampleSource()
    report = screen(src, persona, "loan", explain=False, as_of=AS_OF)
    bureaus = {b: S.credit(src.get(persona, k)) for b, k in (("TransUnion", "tu"), ("Equifax", "efx"), ("Experian", "exp"))}
    return PP.build(report, bureaus, AS_OF)


def test_identity_score_grades_identity_evidence():
    for p in ("P01", "P03", "P04", "P20"):          # clean identities, including the no-file newcomer
        assert passport(p)["identity_score"] == 100, p
    assert passport("P16")["identity_score"] == 90   # one minor note; her own fraud alert stays neutral
    assert passport("P05")["identity_score"] == 80   # two minor notes
    for p in ("P12", "P13", "P14"):                  # stolen, synthetic and deceased identities
        assert raw_passport(p)["identity_score"] < 50, p


def test_identity_signals_say_which_checks_passed():
    s = passport("P04")["identity_signals"]
    assert set(s) == SIGNALS and all(s.values())
    s = raw_passport("P13")["identity_signals"]
    assert s["ssn_name_match"] is False and s["phone_owned"] is False and s["email_age_ok"] is False
    assert s["ip_near"] is False and s["email_owned"] is False
    assert passport("P11")["identity_signals"]["ip_near"] is False   # 100-500 miles: not near, not a finding either


def test_identity_signals_are_booleans_only():
    for p in ("P01", "P04", "P11"):
        q = passport(p)
        assert all(v in (True, False, None) for v in q["identity_signals"].values())
        assert "@" not in str(q) and "miles" not in str(q)


def test_existing_identity_field_unchanged():
    assert passport("P04")["identity"] == "strong" and passport("P05")["identity"] == "ok"
    assert passport("P16")["identity"] == "ok"
