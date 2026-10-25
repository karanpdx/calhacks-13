"""Plain-language explanation of a decision the rules already made. Deterministic templates by default.

  explain(report) -> {"text": "2-4 sentences", "where_wrong": "...", "by": "template"}

`text` already ends with the "where this could be wrong" sentence; `where_wrong` is the same sentence on its own
so a UI can style it. The explainer never changes the decision.

Optional Claude backend: only when EXPLAIN_BACKEND=claude AND ANTHROPIC_API_KEY are both set (it is a paid API).
Any error falls back to the template. Tests never use it.
"""
import os

# Short, borrower-readable reason per finding code, with the CRS source named. Falls back to the finding's own text.
PLAIN = {
    "SSN_NAME_MISMATCH": "the SSN on the application belongs to a different name (TransUnion identity check)",
    "DOB_MISMATCH": "the date of birth doesn't match the file for that SSN (TransUnion identity check)",
    "DECEASED": "the SSN is linked to a deceased person (TransUnion identity check)",
    "FRAUD_SCORE_HIGH": "the FraudFinder risk score is {v}/100 (AtData)",
    "TUMBLING": "the same identity is being reused with small variations (AtData FraudFinder)",
    "NEW_EMAIL": "the email address is brand new (AtData FraudFinder)",
    "PHONE_NOT_APPLICANTS": "the phone number belongs to someone else (AtData FraudFinder)",
    "INQUIRY_BURST": "there were {v} credit applications within 30 days (credit report)",
    "FRAUD_ALERT_ON_FILE": "a fraud alert is on the credit file (TransUnion)",
    "FROZEN": "the credit file is frozen",
    "CONTACT_BELONGS_TO_OTHER": "the phone/email belongs to a different person (AccurateAppend)",
    "SCORE_POOR": "the lowest credit score is {v}",
    "SCORE_FAIR": "the lowest credit score is {v}",
    "NO_CREDIT_FILE": "none of the three bureaus has a credit file",
    "NO_SCORE": "the file can't be scored",
    "SSN_NOT_ON_FILE": None,
    "CHARGEOFFS": "{v} account(s) were charged off",
    "COLLECTIONS": "{v} account(s) are in collections",
    "LATE_PAYMENTS": "there are {v} late payments on file",
    "DEROG_ONLY_ONE_BUREAU": None,
    "FELONY_CONVICTION": "there is a felony conviction on record (criminal search, demo policy)",
    "JUDGMENTS_LIENS": None,
    "EVICTION": "there is an eviction record",
}

LOWER_FIRST = {"The", "A", "An", "This", "Lowest", "None", "Date", "Email", "Phone", "Credit", "Application", "There"}

LEAD = {
    "STOP_FRAUD": "We're holding this application because the identity looks like it may not belong to the person applying",
    "VERIFY": "We need a stronger identity check (government ID and a live selfie) before going further",
    "DECLINE_CREDIT": "This application is declined on credit risk, and the identity checks out",
    "DECLINE_RECORDS": "This application is declined because of a public record, and the identity checks out",
    "NO_FILE": "There is no credit file to score for this person, and nothing points to fraud",
    "REVIEW": "A person needs to look at this file before it's decided",
    "APPROVE": "This application looks fine to approve",
}


def _reasons(report, n=3):
    """Top findings, worst first, one per distinct code, as short phrases."""
    out, seen = [], set()
    pool = [f for f in report["findings"] if f["severity"] >= 2] or report["findings"]
    for f in pool:
        if f["code"] in seen:
            continue
        seen.add(f["code"])
        tmpl = PLAIN.get(f["code"])
        if tmpl is None:  # no short version: use the finding's own sentence
            tmpl = f["text"].rstrip(".").replace("{", "(").replace("}", ")")
            if tmpl.split()[0] in LOWER_FIRST:
                tmpl = tmpl[0].lower() + tmpl[1:]
        out.append(tmpl.format(v=f.get("value")))
        if len(out) == n:
            break
    return out


def _join(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def where_wrong(report):
    codes = {f["code"] for f in report["findings"]}
    d = report["decision"]
    if d == "STOP_FRAUD":
        return ("This could be wrong if a genuine applicant just changed phone or email"
                + (" or typed small variations of their own details" if "TUMBLING" in codes else "")
                + ", and the person on the file may be an identity-theft victim rather than a fraudster, so confirm using the contact details on the credit file, not the application.")
    if d == "VERIFY":
        return "This could be wrong because the signals are probabilistic; a quick ID and selfie check should settle it."
    if d == "NO_FILE":
        return "This could be wrong to treat as risk: no history is not bad history, so use thin-file or alternative-data underwriting."
    if d == "DECLINE_RECORDS":
        return "This is a demo policy: a real lender must run a fair-chance, individualized review before using a criminal record."
    if d == "DECLINE_CREDIT":
        return "This could be wrong if the report has errors or the late payments are old, so the applicant can dispute items and ask for a co-signer or secured product."
    if "THIN_FILE" in codes:
        return ("This could be wrong because a thin file (fewer than 3 accounts) is common for students and new arrivals, "
                "so a short history isn't proof of risk, and CRS's own expectation may differ from this demo policy.")
    if d == "REVIEW":
        return "This could be wrong because the flagged item may be a reporting error at one bureau, so it needs a human, not an auto-decline."
    return ("This could be wrong because the sandbox personas are fictional and built to trigger specific rules, "
            "so a clean result here is a demo policy outcome, not proof about a real applicant.")


def explain_template(report):
    d = report["decision"]
    reasons = _reasons(report)
    s1 = LEAD[d] + (f": {_join(reasons)}." if reasons and d not in ("APPROVE",) else ".")
    parts = [s1]
    scores = {b: s for b, s in report.get("scores", {}).items() if s}
    if d in ("STOP_FRAUD", "VERIFY") and scores:
        low = min(scores.values())
        parts.append(f"The credit score alone ({low}) would not have caught this, which is why identity is checked first.")
    elif d == "APPROVE":
        thin = any(f["code"] == "THIN_FILE" for f in report["findings"])
        parts.append("Identity, all three credit bureaus and public records show nothing that blocks approval"
                     + (", only a short credit history." if thin else "."))
    steps = report.get("next_steps") or []
    if d == "REVIEW":
        parts.append("Next: a reviewer should confirm the flagged item with the applicant before deciding.")
    elif steps:
        parts.append("Next: " + steps[1 if d in ("DECLINE_CREDIT", "DECLINE_RECORDS") and len(steps) > 1 else 0])
    ww = where_wrong(report)
    parts.append(ww)
    return {"text": " ".join(parts), "where_wrong": ww, "by": "template"}  # at most 4 sentences


def explain_claude(report, ww):
    """Optional, small. Rewrites the same facts in friendlier words. Only reached via explain() with both env vars set."""
    import requests
    slim = {k: report[k] for k in ("decision", "headline", "scores", "findings", "next_steps")}
    r = requests.post(
        "https://api.anthropic.com/v1/messages", timeout=30,
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
        json={"model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5"), "max_tokens": 400,
              "system": "Explain a screening decision that rules already made. Do not change it. Use only the facts given. "
                        "2-4 plain sentences, the last one starting 'This could be wrong'. No markdown.",
              "messages": [{"role": "user", "content": str(slim)}]})
    r.raise_for_status()
    return r.json()["content"][0]["text"].strip()


def explain(report):
    base = explain_template(report)
    if os.environ.get("EXPLAIN_BACKEND") == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return {"text": explain_claude(report, base["where_wrong"]), "where_wrong": base["where_wrong"], "by": "claude"}
        except Exception:
            pass  # fall back to the template
    return base
