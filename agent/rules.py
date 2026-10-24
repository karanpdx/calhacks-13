"""Deterministic findings + decision. The LLM never makes the decision; it only explains this.

Every finding cites the CRS product and the value it came from, so a judge (or an underwriter)
can check exactly why the agent said what it said.
"""
from datetime import date

# severity: 1 = note, 2 = concern, 3 = blocker
DECISIONS = {
    "STOP_FRAUD": "Hold: likely identity fraud",
    "VERIFY": "Step-up verification required",
    "DECLINE_CREDIT": "Decline: credit risk (identity checks out)",
    "DECLINE_RECORDS": "Decline: disqualifying public record (identity checks out)",
    "NO_FILE": "No file: no credit file at any bureau, and no sign of fraud",
    "REVIEW": "Manual review: the file needs a human look",
    "APPROVE": "Approve",
}


def F(code, axis, sev, text, source, value=None):
    return {"code": code, "axis": axis, "severity": sev, "text": text, "source": source, "value": value}


def identity_findings(ff, idv, rev):
    out = []
    if idv.get("available"):
        if idv["ssn_name_mismatch"]:
            out.append(F("SSN_NAME_MISMATCH", "identity", 3, "The SSN on the application belongs to someone with a different name.",
                         "TransUnion identity verification", "code 2201"))
        if idv["dob_mismatch"]:
            out.append(F("DOB_MISMATCH", "identity", 2, "Date of birth doesn't match the file for this SSN.",
                         "TransUnion identity verification", "code 2202"))
        if idv["deceased"]:
            out.append(F("DECEASED", "identity", 3, "SSN is linked to a deceased person.", "TransUnion identity verification"))
        if idv.get("fraud_alert"):
            out.append(F("FRAUD_ALERT_ON_FILE", "identity", 2, "A fraud alert is on file; the bureau recommends step-up authentication.",
                         "TransUnion identity verification", "code 2401"))
        if idv["frozen"]:
            out.append(F("FROZEN", "identity", 2, "Credit file is frozen; the real owner may not have applied.",
                         "TransUnion identity verification"))
    if ff.get("available"):
        s = ff["risk_score"]
        if s is not None and s >= 75:
            out.append(F("FRAUD_SCORE_HIGH", "identity", 2, f"FraudFinder risk score is {s}/100.", "AtData FraudFinder", s))
        elif s is not None and s >= 40:
            out.append(F("FRAUD_SCORE_MEDIUM", "identity", 1, f"FraudFinder risk score is {s}/100.", "AtData FraudFinder", s))
        if ff["tumbling"]:
            out.append(F("TUMBLING", "identity", 2, "This identity is being reused with small variations (tumbling).",
                         "AtData FraudFinder", True))
        if ff["email_age_days"] is not None and ff["email_age_days"] < 30:
            out.append(F("NEW_EMAIL", "identity", 2, f"Email address was first seen {ff['email_age_days']} days ago.",
                         "AtData FraudFinder", ff["email_first_seen"]))
        if (ff["email_velocity"] or 0) >= 7:
            out.append(F("EMAIL_VELOCITY", "identity", 1, f"Email is being used heavily right now (velocity {ff['email_velocity']}/10).",
                         "AtData FraudFinder", ff["email_velocity"]))
        if not ff["phone_owner_matches"]:
            out.append(F("PHONE_NOT_APPLICANTS", "identity", 2, "The phone number is registered to someone else.",
                         "AtData FraudFinder", "owner no_match"))
        if ff["phone_prepaid"] or ff["phone_type"] == "voip":
            out.append(F("BURNER_PHONE", "identity", 1, f"Phone is {'prepaid ' if ff['phone_prepaid'] else ''}{ff['phone_type']}.",
                         "AtData FraudFinder", ff["phone_type"]))
        if ff["ip_distance"] and ">" in ff["ip_distance"]:
            out.append(F("IP_FAR", "identity", 1, f"Application came from an IP {ff['ip_distance']} from the stated address.",
                         "AtData FraudFinder", ff["ip_distance"]))
    if rev.get("available"):
        if rev["found"] and not rev["matches_applicant"]:
            out.append(F("CONTACT_BELONGS_TO_OTHER", "identity", 2,
                         f"Reverse lookup says these contact details belong to {', '.join(rev['owners'])}.",
                         "AccurateAppend reverse lookup", rev["owners"]))
        elif not rev["found"]:
            out.append(F("CONTACT_UNKNOWN", "identity", 1, "Reverse lookup can't tie the contact details to any person.",
                         "AccurateAppend reverse lookup"))
    return out


def credit_findings(bureaus):
    out = []
    avail = {b: c for b, c in bureaus.items() if c.get("available")}
    hits = {b: c for b, c in avail.items() if c["hit"]}
    for b, c in avail.items():
        for a in c["alerts"]:
            if "NO SSN ON FILE" in (a or "").upper():
                if hits:   # other bureaus do have a file: the bureaus disagree, which is a human question, not proof of fraud
                    out.append(F("SSN_NOT_ON_FILE", "consistency", 2,
                                 f"{b} has no record of this SSN, but {', '.join(hits)} do.", b, a))
                else:      # a file-level fact; whether it is fraud is decided by the identity checks, not by this alone
                    out.append(F("SSN_NOT_ON_FILE", "file", 3, "The bureau has no record of this SSN.", b, a))
    if avail and not hits:
        out.append(F("NO_CREDIT_FILE", "file", 2, "None of the bureaus has a credit file for this person.",
                     "/".join(avail), "no hit"))
        return out

    scores = {b: c["score"] for b, c in hits.items() if c["score"] is not None}
    if not scores:
        out.append(F("NO_SCORE", "credit", 2, "There is a file but no bureau could produce a score (unscorable).",
                     "/".join(hits), "no score"))
    if scores:
        low_b, low = min(scores.items(), key=lambda kv: kv[1])
        if low < 580:
            out.append(F("SCORE_POOR", "credit", 3, f"Lowest score is {low}.", low_b, low))
        elif low < 620:
            out.append(F("SCORE_FAIR", "credit", 2, f"Lowest score is {low}.", low_b, low))
        elif low < 660:
            out.append(F("SCORE_NEAR_PRIME", "credit", 1, f"Lowest score is {low}.", low_b, low))
    worst = max(hits.values(), key=lambda c: c["lates_90"] * 3 + c["lates_60"] * 2 + c["lates_30"] + c["collections"] * 3)
    lates = worst["lates_30"] + worst["lates_60"] + worst["lates_90"]
    if lates:
        out.append(F("LATE_PAYMENTS", "credit", 2 if worst["lates_90"] else 1,
                     f"{lates} late payments ({worst['lates_90']} at 90+ days), most recent {worst['most_recent_late']}.",
                     "credit report", lates))
    chargeoffs = max(c["chargeoffs"] for c in hits.values())
    if chargeoffs:
        out.append(F("CHARGEOFFS", "credit", 2, f"{chargeoffs} account(s) charged off.", "credit report", chargeoffs))
    if worst["collections"]:
        out.append(F("COLLECTIONS", "credit", 2, f"{worst['collections']} account(s) in collections.", "credit report",
                     worst["collections"]))
    if max(c["tradelines"] for c in hits.values()) < 3:
        out.append(F("THIN_FILE", "credit", 1, "Thin credit file (fewer than 3 accounts). Common for students and new arrivals.",
                     "credit report", max(c["tradelines"] for c in hits.values())))

    # application velocity: many inquiries packed into a short window looks like loan stacking / bust-out
    dates = sorted({d for c in hits.values() for d in c["inquiry_dates"]})
    burst = 0
    for i, d in enumerate(dates):
        start = date.fromisoformat(d)
        burst = max(burst, sum(1 for e in dates[i:] if (date.fromisoformat(e) - start).days <= 30))
    if burst >= 5:
        out.append(F("INQUIRY_BURST", "identity", 2, f"{burst} credit applications within 30 days.", "credit report inquiries", burst))
    elif len(dates) >= 5:
        out.append(F("FREQUENT_INQUIRIES", "credit", 1, f"{len(dates)} credit inquiries in the past year.", "credit report inquiries",
                     len(dates)))

    # do the bureaus tell the same story?
    if len(avail) > 1 and len(hits) < len(avail):
        missing = [b for b in avail if b not in hits]
        out.append(F("PARTIAL_NO_HIT", "consistency", 1, f"No file at {', '.join(missing)} but a file at {', '.join(hits)}.",
                     "tri-bureau", missing))
    if len(scores) > 1 and max(scores.values()) - min(scores.values()) >= 40:
        out.append(F("SCORE_SPREAD", "consistency", 1,
                     "Scores differ by " + str(max(scores.values()) - min(scores.values())) + " points: "
                     + ", ".join(f"{b} {s}" for b, s in scores.items()) + ".", "tri-bureau", scores))
    colls = {b: c["collections"] for b, c in hits.items()}
    if len(set(colls.values())) > 1:
        only = [b for b, n in colls.items() if n]
        names = sorted({n for b in only for n in hits[b]["collection_creditors"] if n})
        out.append(F("DEROG_ONLY_ONE_BUREAU", "consistency", 2,
                     f"A collection{' (' + ', '.join(names) + ')' if names else ''} appears only at {', '.join(only)}. "
                     "A single-bureau check would have missed it.", "tri-bureau", colls))
    return out


def record_findings(rec):
    out = []
    if rec.get("evictions"):
        out.append(F("EVICTION", "records", 2, f"{rec['evictions']} eviction record(s).", "Eviction search", rec["evictions"]))
    if rec.get("judgments") or rec.get("liens"):
        out.append(F("JUDGMENTS_LIENS", "records", 2, f"{rec.get('judgments', 0)} judgment(s), {rec.get('liens', 0)} lien(s).",
                     "PitchPoint liens/judgments"))
    if rec.get("bankruptcies"):
        out.append(F("BANKRUPTCY", "records", 2, f"{rec['bankruptcies']} bankruptcy record(s).", "PitchPoint liens/judgments"))
    if rec.get("felony_convictions"):
        out.append(F("FELONY_CONVICTION", "records", 3, f"{rec['felony_convictions']} felony conviction(s).", "Criminal search",
                     rec["felony_convictions"]))
    elif rec.get("other_convictions"):
        out.append(F("CONVICTION", "records", 1, f"{rec['other_convictions']} non-felony conviction(s).", "Criminal search"))
    # dismissed / non-conviction cases are deliberately ignored
    return out


def decide(findings, identity_only=False):
    ident = [f for f in findings if f["axis"] == "identity"]
    ident_pts = sum(f["severity"] for f in ident)
    max_sev = lambda axis: max((f["severity"] for f in findings if f["axis"] == axis), default=0)

    if any(f["severity"] == 3 for f in ident) or ident_pts >= 6:
        d = "STOP_FRAUD"
    elif ident_pts >= 3:
        d = "VERIFY"
    elif identity_only:
        d = None  # identity is fine; caller should continue to credit
    elif any(f["code"] == "NO_CREDIT_FILE" for f in findings):
        d = "NO_FILE"  # nobody to score, and the identity evidence is not bad enough to call it fraud
    elif max_sev("credit") >= 3 or (max_sev("credit") == 2 and sum(f["severity"] for f in findings if f["axis"] == "credit") >= 5):
        d = "DECLINE_CREDIT"
    elif max_sev("records") >= 3:
        d = "DECLINE_RECORDS"
    elif max_sev("credit") >= 2 or max_sev("consistency") >= 2 or max_sev("records") >= 2:
        d = "REVIEW"
    else:
        d = "APPROVE"
    return d, ident_pts


NEXT_STEPS = {
    "STOP_FRAUD": [
        "Do not approve or open anything in this name.",
        "Do not use the phone/email on the application to follow up. If you contact anyone, use the contact info on the "
        "credit file, since the real person may not know their identity is being used.",
        "Route to fraud review. No eviction or criminal searches were run, because those would be about the victim, not the applicant.",
    ],
    "VERIFY": [
        "Ask for a government ID plus a live selfie (liveness check) before going further.",
        "Re-run once the applicant confirms their phone and email.",
    ],
    "DECLINE_CREDIT": [
        "Identity checks passed, so this is a credit decision, not a fraud case.",
        "Send an adverse-action notice listing the key reasons below (the FCRA requires the main factors).",
        "Offer an alternative if your policy allows: co-signer, larger deposit, or a secured product.",
    ],
    "DECLINE_RECORDS": [
        "Identity checks passed, so this is about the applicant's own public record.",
        "Check local fair-chance rules before relying on a criminal record (individualized assessment, adverse-action notice).",
    ],
    "NO_FILE": [
        "Nothing to score: ask for an alternative (ITIN / thin-file / bank-statement underwriting) or a co-signer.",
        "Identity evidence did not point to fraud, so do not treat this as a fraud case.",
    ],
    "REVIEW": [
        "Ask the applicant about the item that appears at only one bureau. It may be a reporting error they can dispute.",
        "Decide after review; don't auto-decline on a single-bureau item.",
    ],
    "APPROVE": [
        "Approve. Keep the report for the audit trail.",
    ],
}
