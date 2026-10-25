"""Bureau reconciliation: a reconciled view of the file across TransUnion, Equifax and Experian.

A negative item reported by only one bureau, while another bureau that has a file on the person doesn't report it,
is marked "unconfirmed": it may be an error or out of date (P17's collection shows only at Experian). The reconciled
count for each item is the count at least two bureaus agree on (the second-highest across bureaus with a file), so a
single bureau can't add an item on its own. With a file at one bureau only there is nothing to compare: counts stand.

The reconciled score is the lowest score among bureaus that don't carry an unconfirmed item (the bureau with the
extra item is likely scoring the person down for it); if every bureau carries one, the lowest score stands.

Lenders opt in per Book (`reconciled=True`): their policy and pricing read `view(passport)`. Others keep the raw
worst-bureau view. The raw fields in the passport are never changed; the reconciled block sits next to them.
Derived counts and bureau names only: no creditor names, account numbers or other file detail.
"""

# passport field -> (how to read it from one bureau's parsed report, the item in plain words)
ITEMS = {
    "collections": (lambda c: c.get("collections", 0), "collection"),
    "chargeoffs": (lambda c: c.get("chargeoffs", 0), "charged-off account"),
    "bankruptcies": (lambda c: c.get("bankruptcies", 0), "bankruptcy"),
    "serious_lates_90d": (lambda c: c.get("lates_90", 0), "90-day late payment"),
    "late_payments": (lambda c: c.get("lates_30", 0) + c.get("lates_60", 0) + c.get("lates_90", 0), "late payment"),
}


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def _join(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def reconcile(hits):
    """hits = {bureau: parsed credit report} for bureaus with a file. Returns the passport's `reconciled` block."""
    out, unconfirmed = {}, []
    for field, (read, word) in ITEMS.items():
        counts = {b: read(c) for b, c in hits.items()}
        ranked = sorted(counts.values(), reverse=True)
        out[field] = ranked[1] if len(ranked) >= 2 else (ranked[0] if ranked else 0)
        reporting = [b for b, n in counts.items() if n]
        if len(reporting) == 1 and len(counts) >= 2:
            silent = [b for b in counts if b not in reporting]
            unconfirmed.append({"item": word, "field": field, "count": counts[reporting[0]],
                                "reported_by": reporting[0], "not_reported_by": silent})
    flagged = {u["reported_by"] for u in unconfirmed}
    scores = {b: c["score"] for b, c in hits.items() if c.get("score") is not None}
    clean = [s for b, s in scores.items() if b not in flagged]
    out["score_low"] = min(clean or scores.values()) if scores else None
    out["unconfirmed"] = unconfirmed
    # a one-bureau 90-day late is also counted in late_payments: say it once
    said = [u for u in unconfirmed if not (u["field"] == "late_payments"
                                           and any(x["field"] == "serious_lates_90d" for x in unconfirmed))]
    out["note"] = " ".join(_sentence(u) for u in said) or None
    return out


def _sentence(u):
    silent = u["not_reported_by"]
    return (f"{_plural(u['count'], u['item']).capitalize()} appears only at {u['reported_by']}; {_join(silent)} "
            f"{'has' if len(silent) == 1 else 'have'} a file without it, so lenders that price on the reconciled view "
            "treat it as unconfirmed.")


def view(p):
    """The passport as an opted-in lender sees it: reconciled counts and score in place of the worst-bureau ones."""
    r = p.get("reconciled")
    if not r or p.get("view") == "reconciled":
        return p
    return {**p, **{k: r[k] for k in (*ITEMS, "score_low") if k in r}, "view": "reconciled"}
