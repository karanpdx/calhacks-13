"""The credit passport: what lenders see instead of the credit file.

Derived attributes only. No name, SSN, date of birth, address, phone, email, or account-level detail.
Lenders get the full file only after the borrower accepts (simulated in the sandbox).
"""
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
    pts = sum(f["severity"] for f in report["findings"] if f["axis"] == "identity" and f["code"] not in neutral)

    disagreements = [f["text"] for f in report["findings"] if f["axis"] == "consistency"]
    p = {
        "score_band": _band(min(scores.values())) if scores else None,   # lowest bureau, banded
        "score_low": min(scores.values()) if scores else None,
        "scores_by_bureau": {b: (scores.get(b) if b in hits else "no file") for b in BUREAUS if bureaus.get(b, {}).get("available")},
        "bureaus_with_file": len(hits),
        "file_age_years": _years_since(oldest, today),
        "accounts": max((c.get("tradelines", 0) for c in hits.values()), default=0),
        "late_payments": max((c.get("lates_30", 0) + c.get("lates_60", 0) + c.get("lates_90", 0) for c in hits.values()), default=0),
        "serious_lates_90d": worst("lates_90"),
        "collections": worst("collections"),
        "chargeoffs": worst("chargeoffs"),
        "bankruptcies": worst("bankruptcies"),
        "inquiries_6m": inq_6m,
        "thin_file": bool(hits) and max(c.get("tradelines", 0) for c in hits.values()) < 3,
        "no_score": bool(hits) and not scores,
        "no_file": not hits,
        "identity": "strong" if pts == 0 else "ok" if pts <= 2 else "weak",
        "verification_required": "FRAUD_ALERT_ON_FILE" in codes or report["decision"] == "VERIFY",
        "frozen_somewhere": "FROZEN" in codes or any(
            "FROZEN" in (a or "").upper() or "FREEZE" in (a or "").upper() for c in bureaus.values() for a in c.get("alerts", [])),
        "bureau_disagreements": disagreements,
        "withheld": WITHHELD,
    }
    return p
