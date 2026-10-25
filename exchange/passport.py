"""The credit passport: what lenders see instead of the credit file.

Derived attributes only. No name, SSN, date of birth, address, phone, email, or account-level detail.
Lenders get the full file only after the borrower accepts (simulated in the sandbox).
"""
import re
from datetime import date

BUREAUS = ("TransUnion", "Equifax", "Experian")
WITHHELD = ["name", "SSN", "date of birth", "address", "phone", "email", "employers", "account-level details"]


def _band(score):
    if score is None:
        return None
    lo = (score // 50) * 50
    return f"{lo}-{lo + 49}"


def _years_since(d, today):
    try:
        return round((today - date.fromisoformat(d)).days / 365.25, 1)
    except (TypeError, ValueError):
        return None


# Points off a 100 identity score per identity finding, by the finding's severity (3 = blocker, 2 = concern, 1 = note).
# One note -> 90, two notes -> 80, one concern -> 75: newcomer lenders that need >= 80 accept at most two minor notes.
IDENTITY_PENALTY = {3: 60, 2: 25, 1: 10}


def _near(distance):
    """FraudFinder's IP-to-address distance ("5 miles", "5-100 miles", "> 1000 miles") is within 100 miles."""
    nums = [int(n) for n in re.findall(r"\d+", distance or "")]
    return bool(nums) and ">" not in distance and max(nums) <= 100


def identity_signals(report):
    """Which identity checks passed, as booleans (None = that check didn't run). Derived only: never the SSN,
    phone number, email address or the distance itself."""
    codes = {f["code"] for f in report["findings"]}
    ran = set(report.get("products_called", []))
    ff = (report.get("signals") or {}).get("fraud_finder") or {}
    has_ff = bool(ff.get("available"))
    return {
        "ssn_name_match": ("SSN_NAME_MISMATCH" not in codes) if "idv" in ran else None,
        "phone_owned": (ff.get("phone_owner_matches") is True and not codes & {"PHONE_NOT_APPLICANTS"}) if has_ff else None,
        # FraudFinder has no email owner field: "owned" = not being cycled (tumbling) and not tied to someone else
        "email_owned": not codes & {"TUMBLING", "CONTACT_BELONGS_TO_OTHER"} if has_ff else None,
        "email_age_ok": (ff.get("email_age_days") is not None and ff["email_age_days"] >= 30) if has_ff else None,
        "address_deliverable": ff.get("address_deliverable") is True if has_ff else None,
        "ip_near": _near(ff.get("ip_distance")) if has_ff else None,
    }


def build(report, bureaus, today=None):
    """report = agent.screen() output; bureaus = {name: agent.signals.credit(...)}."""
    today = today or date.today()
    hits = {b: c for b, c in bureaus.items() if c.get("available") and c.get("hit")}
    scores = {b: c["score"] for b, c in hits.items() if c.get("score") is not None}
    worst = lambda k: max((c.get(k, 0) for c in hits.values()), default=0)
    oldest = min((c["oldest_account"] for c in hits.values() if c.get("oldest_account")), default=None)
    inquiries = sorted({d for c in hits.values() for d in c.get("inquiry_dates", [])})
    inq_6m = sum(1 for d in inquiries if (today - date.fromisoformat(d)).days <= 183)
    codes = {f["code"] for f in report["findings"]}
    # Identity strength for lenders. Two findings are left out on purpose:
    #  - CONTACT_UNKNOWN when there's no file: someone new to the country has no contact history yet (P04).
    #    Fake identities don't get through anyway: the gate blocks SSN/name mismatches first.
    #  - FRAUD_ALERT_ON_FILE: a protection the person placed themselves (P16). It still forces verification below.
    neutral = {"FRAUD_ALERT_ON_FILE"} | ({"CONTACT_UNKNOWN"} if not hits else set())
    counted = [f for f in report["findings"] if f["axis"] == "identity" and f["code"] not in neutral]
    pts = sum(f["severity"] for f in counted)
    identity_score = max(0, 100 - sum(IDENTITY_PENALTY.get(f["severity"], 0) for f in counted))

    disagreements = [f["text"] for f in report["findings"] if f["axis"] == "consistency"]
    ff = (report.get("signals") or {}).get("fraud_finder") or {}
    bk = [r for c in hits.values() for r in c.get("bankruptcy_records", [])]
    bk_dates = [d for r in bk for d in [r.get("resolved") or r.get("filed")] if d]
    lates = max((c.get("lates_30", 0) + c.get("lates_60", 0) + c.get("lates_90", 0) for c in hits.values()), default=0)
    p = {
        "score_band": _band(min(scores.values())) if scores else None,   # lowest bureau, banded
        "score_low": min(scores.values()) if scores else None,
        "scores_by_bureau": {b: (scores.get(b) if b in hits else "no file") for b in BUREAUS if bureaus.get(b, {}).get("available")},
        "bureaus_with_file": len(hits),
        "file_age_years": _years_since(oldest, today),
        "accounts": max((c.get("tradelines", 0) for c in hits.values()), default=0),
        "late_payments": lates,
        "serious_lates_90d": worst("lates_90"),
        "collections": worst("collections"),
        "chargeoffs": worst("chargeoffs"),
        "bankruptcies": worst("bankruptcies"),
        # Bankruptcies reported as public records (the summary's `bankruptcies` count can miss them, as for P06).
        "bankruptcy_public_record": bool(bk),
        "bankruptcy_discharged": bool(bk) and all((r.get("disposition") or "").lower() == "discharged" for r in bk),
        "years_since_bankruptcy": min((y for y in (_years_since(d, today) for d in bk_dates) if y is not None),
                                      default=None),
        "inquiries_6m": inq_6m,
        "thin_file": bool(hits) and max(c.get("tradelines", 0) for c in hits.values()) < 3,
        "no_score": bool(hits) and not scores,
        "no_file": not hits,
        "identity": "strong" if pts == 0 else "ok" if pts <= 2 else "weak",
        "identity_score": identity_score,                 # 0-100 from the same findings, for lenders that price on it
        "identity_signals": identity_signals(report),
        "verification_required": "FRAUD_ALERT_ON_FILE" in codes or report["decision"] == "VERIFY",
        "frozen_somewhere": "FROZEN" in codes or any(
            "FROZEN" in (a or "").upper() or "FREEZE" in (a or "").upper() for c in bureaus.values() for a in c.get("alerts", [])),
        "bureau_disagreements": disagreements,
        # Positive evidence: what a thin file has going for it, not just the absence of negatives.
        "months_on_time": max((c.get("on_time_months", 0) for c in hits.values()), default=0),
        "oldest_account_years": _years_since(oldest, today),
        "never_late": (lates == 0 and worst("chargeoffs") == 0 and worst("late_months") == 0) if hits else None,
        # The sandbox has no address or phone history, so "stable" is approximated from FraudFinder: the name is tied
        # to this street and it's deliverable; the phone is the applicant's own, postpaid and not VoIP.
        "address_stable": (ff.get("address_name_matches") is True and ff.get("address_deliverable") is True)
                          if ff.get("available") else None,
        "phone_stable": (ff.get("phone_owner_matches") is True and not ff.get("phone_prepaid")
                         and ff.get("phone_type") not in (None, "voip")) if ff.get("available") else None,
        "withheld": WITHHELD,
    }
    return p
