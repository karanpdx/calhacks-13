"""Turn raw CRS responses into a small, flat set of signals.

Each extractor takes one product's response body and returns a dict.
Keep this the only place that knows CRS field names.
"""
from datetime import date


def _int(x, default=0):
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def credit(body):
    """TransUnion / Equifax / Experian credit report."""
    if not body:
        return {"available": False}
    scores = [_int(s.get("scoreValue"), None) for s in body.get("scores", [])]
    scores = [s for s in scores if s is not None]
    derog = (body.get("summaries") or {}).get("derogatorySummary") or {}
    trades = body.get("tradelines", [])
    return {
        "available": True,
        "hit": bool(trades or scores),
        "score": scores[0] if scores else None,
        "tradelines": len(trades),
        "oldest_account": min((t.get("accountOpenedDate") for t in trades if t.get("accountOpenedDate")), default=None),
        "inquiry_dates": sorted(i.get("inquiryDate") for i in body.get("inquiries", []) if i.get("inquiryDate")),
        "collections": _int(derog.get("collectionsCount")),
        "chargeoffs": _int(derog.get("chargeOffsCount")),
        "bankruptcies": _int(derog.get("bankruptciesCount")),
        "lates_30": _int(derog.get("_30DayLates")),
        "lates_60": _int(derog.get("_60DayLates")),
        "lates_90": _int(derog.get("_90DayLates")),
        "most_recent_late": derog.get("mostRecentLateDate") or None,
        "collection_creditors": [t.get("creditorName") for t in trades
                                 if "RECOVERY" in (t.get("creditorName") or "").upper()
                                 or t.get("accountType") == "Collection"],
        "alerts": [a.get("responseAlertMessageText") for a in body.get("responseAlertMessages", [])],
        "applicant": body.get("requestData") or {},
    }


def fraud_finder(body, today=None):
    """AtData FraudFinder: email/IP/phone/postal risk."""
    if not body:
        return {"available": False}
    today = today or date.today()
    risk, eam = body.get("risk", {}), body.get("eam", {})
    phone, postal = risk.get("phone", {}), risk.get("postal", {})
    first_seen = eam.get("date_first_seen")
    try:
        email_age_days = (today - date.fromisoformat(first_seen)).days
    except (TypeError, ValueError):
        email_age_days = None
    owner = phone.get("owner", {})
    return {
        "available": True,
        "risk_score": _int(risk.get("score"), None),       # 0-100, higher = riskier
        "tumbling": bool(risk.get("tumbling_risk")),         # same identity cycled with small variations
        "email": (body.get("email_validation") or {}).get("address"),
        "email_first_seen": first_seen,
        "email_age_days": email_age_days,
        "email_velocity": _int(eam.get("velocity"), None),  # 1-10, how often this email is being used lately
        "ip_distance": postal.get("ip_postal_distance"),
        "phone_type": phone.get("line_type"),
        "phone_prepaid": bool(phone.get("prepaid")),
        "phone_owner_matches": owner.get("last_name_match") == "match" and owner.get("first_name_match") == "match",
        "address_deliverable": postal.get("deliverability") == "deliverable",
    }


def identity(body):
    """TransUnion identity verification. The summary block is identical across sandbox personas,
    so the useful signal is in the add-on mismatch messages."""
    if not body:
        return {"available": False}
    msgs = []
    for addon in body.get("addOnProducts", []):
        msgs += (addon.get("idManagerVerification") or {}).get("messages", [])
        msgs += [{"code": "MISMATCH", "text": str(a)} for a in addon.get("idMismatchAlerts", [])]
    status = (body.get("fileSummary") or {}).get("creditDataStatus") or {}
    return {
        "available": True,
        "file_hit": (body.get("fileSummary") or {}).get("fileHitIndicator"),
        "messages": [{"code": m.get("code"), "text": m.get("text")} for m in msgs],
        "ssn_name_mismatch": any(m.get("code") == "2201" for m in msgs),
        "dob_mismatch": any(m.get("code") == "2202" for m in msgs),
        "address_mismatch": any(m.get("code") == "2101" for m in msgs),
        "frozen": bool((status.get("freeze") or {}).get("indicator")),
        "deceased": bool(sum(len((a.get("idManagerVerification") or {}).get("deceases", []))
                             for a in body.get("addOnProducts", []))),
    }


def reverse(body, applicant):
    """AccurateAppend reverse lookup: who does the phone/email/address actually belong to?"""
    if not body:
        return {"available": False}
    recs = (body.get("data") or {}).get("records", [])
    first, last = (applicant.get("firstName") or "").upper(), (applicant.get("lastName") or "").upper()
    owners = [f"{r.get('firstName', '')} {r.get('lastName', '')}".strip() for r in recs]
    return {
        "available": True,
        "found": bool(recs),
        "owners": owners,
        "matches_applicant": any((r.get("lastName") or "").upper() == last and (r.get("firstName") or "").upper() == first
                                 for r in recs),
    }


def records(blj, eviction, criminal):
    out = {}
    if blj:
        r = blj.get("DetailedBLJReport", {})
        out.update(judgments=_int(r.get("JudgmentsFound")), liens=_int(r.get("LiensFound")),
                   bankruptcies=_int(r.get("BankruptciesFound")))
    if eviction:
        out["evictions"] = _int((eviction.get("response") or {}).get("count"))
    if criminal is not None:
        out["criminal_records"] = _int(((criminal.get("cicCriminal") or {}).get("candidates") or {}).get("count"))
    return out
