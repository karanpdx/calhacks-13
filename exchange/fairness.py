"""Fairness check: do our lenders decide and price only on credit-relevant passport fields?

Four parts, all offline on the saved CRS samples, using whatever lenders exist in `lenders.POLICIES` at run time:

  matrix()       every persona through every lender's eligibility and pricing (no negotiation): offer or decline,
                 the APR range at the lender's default terms (floor with autopay .. opening), the reason code
  blindness()    change what lenders must never use (name, address, city, state, ZIP, date of birth, phone, email)
                 in the applicant data, consistently across every CRS product, and check every decision and price
                 is identical; plus a scan that the passport has no field that could stand in for one
  consistency()  personas with the same credit-relevant fields get the same decision and price
  disparity()    approval rate and median opening APR per lender, thin-file / no-file group vs everyone else

This is an INTERNAL CHECK, NOT A LEGAL FAIR-LENDING REVIEW. The sandbox has no protected-class data (race, sex,
national origin, ...), so it can't measure disparate impact on protected groups; the disparity report compares a
credit factor (file thickness), where differences are expected and explained by each lender's product.
"""
import copy
import re
import statistics
from functools import lru_cache

from agent.scorecard import AS_OF
from agent.sources import SampleSource

from .lenders import BOOKS, POLICIES
from .referee import Exchange

DISCLAIMER = "Internal check, not a legal fair-lending review."
THIN_GROUP = ("P03", "P04", "P06", "P18", "P20")   # students, newcomers, rebuilding, no score

# What lenders must never use, and the stand-in values the blindness test swaps in (fictional, sandbox-style).
STAND_IN = {"first": "AVERY", "last": "QUINTANA", "line1": "77 TEST HARBOR RD", "street": "TEST HARBOR RD",
            "city": "FRESNO", "state": "NM", "zip": "87501", "dob": "1951-11-02", "phone": "5055550147",
            "email": "avery.quintana@example.net"}
ADDRESS_CODES = {"state", "postalCode", "zipCode", "zip"}

# Passport keys that would carry a protected attribute or a close stand-in for one. A key may mention one of these
# only if its value is a pass/fail check result (True/False/None), e.g. `address_stable`, never the attribute itself.
PROXY_KEY = re.compile(r"name|birth|\bdob\b|zip|postal|address|street|city|state|language|^age$|_age$|email|phone|"
                       r"gender|sex|race|ethnic|national|marital|religion", re.I)
# Credit-relevant, but they rise with age: watch them (a long history is allowed to count; age itself is not).
AGE_CORRELATED = ("file_age_years", "oldest_account_years", "months_on_time")


# ---------------------------------------------------------------- running personas through lenders
def _gate(persona, source):
    ex = Exchange(persona, source=source, today=AS_OF)
    ex.gate()
    return ex


def lender_ids():
    """The market's lenders: every policy priced from its own books, read at run time so new lenders show up.
    Attack-scenario agents (QuickCash Now, registered by scenarios.py) have no books and aren't part of the market."""
    return [lid for lid in POLICIES if lid in BOOKS]


def quote_cell(lender_id, passport):
    """One lender's view of one passport at its default terms: offer + APR range, or decline + reason."""
    q = POLICIES[lender_id][1](passport)
    if not q.eligible:
        return {"offer": False, "code": q.code, "reason": q.reason}
    return {"offer": True, "apr_low": round(q.floor_apr - q.autopay_discount, 2), "apr_high": q.open_apr,
            "floor_apr": q.floor_apr, "autopay_discount": q.autopay_discount, "amount": q.max_amount,
            "term": q.term, "fee": q.fee, "reason": q.reason}


def persona_row(persona, source=None):
    ex = _gate(persona, source or SampleSource())
    if ex.passport is None:
        return {"persona": persona, "admitted": False, "decision": ex.report["decision"], "cells": {
            lid: {"offer": False, "code": "BLOCKED_AT_GATE", "reason": "identity can't be trusted; no lender sees it"}
            for lid in lender_ids()}}
    return {"persona": persona, "admitted": True, "decision": ex.report["decision"],
            "thin_group": persona in THIN_GROUP, "passport": ex.passport,
            "cells": {lid: quote_cell(lid, ex.passport) for lid in lender_ids()}}


def matrix(source=None):
    source = source or SampleSource()
    return [persona_row(p, source) for p in source.personas()]


# ---------------------------------------------------------------- blindness: swap protected data, nothing changes
class PerturbedSource:
    """The saved samples, with one applicant's own name, address, city, state, ZIP, date of birth and email swapped
    for stand-ins in every CRS product, consistently (so the reverse lookup still ties the contact details to the
    applicant). Other people's names (e.g. who a phone really belongs to) are left alone. The samples carry no phone
    number and most carry no date of birth on the application, so both are added there to show they're ignored too."""
    name = "samples (protected fields changed)"

    def __init__(self, base=None, stand_in=STAND_IN, serve_as=None):
        self.base = base or SampleSource()
        self.stand_in = stand_in
        self.serve_as = serve_as or {}     # twin persona id -> the persona whose files it serves
        self.log = self.base.log

    def _real(self, persona):
        return self.serve_as.get(persona, persona)

    def personas(self):
        return self.base.personas()

    def _swaps(self, persona):
        a = self.base.applicant(self._real(persona)) or {}
        s, out = self.stand_in, {}
        addr = (a.get("addresses") or [{}])[0]
        line1 = addr.get("addressLine1") or ""
        street = re.sub(r"^\d+\s+", "", line1)
        for old, new in ((a.get("firstName"), s["first"]), (a.get("lastName"), s["last"]), (line1, s["line1"]),
                         (street, s["street"]), (addr.get("city"), s["city"])):
            if old and len(old) >= 3:
                out[old.upper()] = new
        if a.get("firstName") and a.get("lastName"):
            out[f"{a['lastName']},{a['firstName']}".upper()] = f"{s['last']},{s['first']}"
        codes = {k: v for k, v in (("state", addr.get("state")), ("zip", addr.get("postalCode"))) if v}
        idv = self.base.get(self._real(persona), "idv") or {}
        dobs = [d.get("value") for d in (idv.get("indicative") or {}).get("dateOfBirths", []) if d.get("value")]
        ff = self.base.get(self._real(persona), "fraudfinder") or {}
        email = (ff.get("email_validation") or {}).get("address")
        if email:
            out[email.upper()] = s["email"]
        return out, codes, dobs

    def _rewrite(self, o, swaps, codes, dobs, key=None):
        if isinstance(o, dict):
            return {k: self._rewrite(v, swaps, codes, dobs, k) for k, v in o.items()}
        if isinstance(o, list):
            return [self._rewrite(v, swaps, codes, dobs, key) for v in o]
        if isinstance(o, str):
            if o.upper() in swaps:
                return swaps[o.upper()]
            if key in ADDRESS_CODES and o in codes.values():
                return self.stand_in["state"] if o == codes.get("state") else self.stand_in["zip"]
            if o in dobs:
                return self.stand_in["dob"] + "T00:00:00.000+00:00"
        return o

    def get(self, persona, product):
        body = self.base.get(self._real(persona), product)
        if body is None:
            return None
        swaps, codes, dobs = self._swaps(persona)
        out = self._rewrite(copy.deepcopy(body), swaps, codes, dobs)
        if isinstance(out.get("requestData"), dict):
            out["requestData"].update(dateOfBirth=self.stand_in["dob"], phone=self.stand_in["phone"])
        return out

    def applicant(self, persona):
        swaps, codes, dobs = self._swaps(persona)
        a = self._rewrite(copy.deepcopy(self.base.applicant(self._real(persona)) or {}), swaps, codes, dobs)
        return {**a, "dateOfBirth": self.stand_in["dob"], "phone": self.stand_in["phone"]}


def _outcome(row):
    """What must not change: the gate decision, the whole passport, and every lender's decision and price."""
    return {"decision": row["decision"], "passport": row.get("passport"), "cells": row["cells"]}


def _diff(a, b):
    out = [] if a["decision"] == b["decision"] else ["gate decision"]
    if a["passport"] != b["passport"]:
        out += [f"passport.{k}" for k in sorted(set(a["passport"] or {}) | set(b["passport"] or {}))
                if (a["passport"] or {}).get(k) != (b["passport"] or {}).get(k)]
    out += [f"{lid}" for lid in a["cells"] if a["cells"][lid] != b["cells"].get(lid)]
    return out


def blindness(base=None):
    """For each persona: run it as is and with its protected fields changed; list anything that moved."""
    base = base or SampleSource()
    changed = PerturbedSource(base)
    out = []
    for p in base.personas():
        diffs = _diff(_outcome(persona_row(p, base)), _outcome(persona_row(p, changed)))
        out.append({"persona": p, "identical": not diffs, "differences": diffs})
    return out


def _walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield f"{path}.{k}".lstrip("."), k, v
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _walk(v, f"{path}[{i}]")


def proxy_check(rows=None, source=None):
    """No passport key carries a protected attribute or stand-in (a key that mentions one must be a pass/fail result),
    and no applicant value (name, address, city, ZIP, email, DOB) appears anywhere in a passport."""
    source = source or SampleSource()
    rows = rows if rows is not None else matrix(source)
    problems = []
    for r in rows:
        p = r.get("passport")
        if not p:
            continue
        shown = {k: v for k, v in p.items() if k != "withheld"}   # `withheld` names what was left out, on purpose
        for path, key, value in _walk(shown):
            if PROXY_KEY.search(key) and value not in (True, False, None):
                problems.append({"persona": r["persona"], "field": path, "why": "names a protected attribute"})
        a = source.applicant(r["persona"]) or {}
        addr = (a.get("addresses") or [{}])[0]
        flat = str(shown).upper()
        for label, v in (("name", a.get("lastName")), ("address", addr.get("addressLine1")),
                         ("city", addr.get("city")), ("ZIP", addr.get("postalCode"))):
            if v and len(v) >= 3 and re.search(rf"\b{re.escape(v.upper())}\b", flat):
                problems.append({"persona": r["persona"], "field": label, "why": "applicant value in the passport"})
    return {"ok": not problems, "problems": problems, "age_correlated_fields": list(AGE_CORRELATED),
            "note": "File age and on-time months are credit history and may count; they rise with age, so lenders "
                    "must not use them as a stand-in for age. No passport field is the person's age or birth date."}


# ---------------------------------------------------------------- consistency: same credit fields, same result
def _credit_key(passport):
    """Everything a lender could read from the passport: all of it except the list of withheld fields."""
    return repr(sorted((k, repr(v)) for k, v in passport.items() if k != "withheld"))


def consistency(rows=None, base=None):
    base = base or SampleSource()
    rows = rows if rows is not None else matrix(base)
    admitted = [r for r in rows if r["admitted"]]
    groups = {}
    for r in admitted:
        groups.setdefault(_credit_key(r["passport"]), []).append(r)
    pairs = [[x["persona"] for x in g] for g in groups.values() if len(g) > 1]
    pair_fail = [g for g in groups.values() if len(g) > 1 and any(x["cells"] != g[0]["cells"] for x in g)]
    # Twins: each persona's credit files served again under another persona id, with a different identity.
    twins = PerturbedSource(base, serve_as={f"T{r['persona'][1:]}": r["persona"] for r in admitted})
    twin_fail = []
    for r in admitted:
        t = persona_row(f"T{r['persona'][1:]}", twins)
        if t["cells"] != r["cells"] or t["passport"] != r["passport"]:
            twin_fail.append(r["persona"])
    return {"ok": not pair_fail and not twin_fail,
            "real_pairs": pairs, "real_pairs_failed": [[x["persona"] for x in g] for g in pair_fail],
            "twins_checked": len(admitted), "twins_failed": twin_fail,
            "note": ((f"{len(pairs)} group(s) of sandbox personas share every credit-relevant field" if pairs else
                      "No two sandbox personas share every credit-relevant field, so the real-pair check is empty")
                     + f"; {len(admitted)} twins (same credit files, different identity and persona id) checked.")}


# ---------------------------------------------------------------- disparity report
def _median(xs):
    return round(statistics.median(xs), 2) if xs else None


def disparity(rows=None):
    rows = rows if rows is not None else matrix()
    admitted = [r for r in rows if r["admitted"]]
    groups = {"thin_or_no_file": [r for r in admitted if r["thin_group"]],
              "everyone_else": [r for r in admitted if not r["thin_group"]]}
    out = []
    for lid in lender_ids():
        stats = {}
        for g, rs in groups.items():
            cells = [r["cells"][lid] for r in rs]
            offers = [c for c in cells if c["offer"]]
            codes = [c["code"] for c in cells if not c["offer"]]
            stats[g] = {"n": len(rs), "approved": len(offers),
                        "approval_rate": round(len(offers) / len(rs), 2) if rs else None,
                        "median_opening_apr": _median([c["apr_high"] for c in offers]),
                        "top_decline_code": max(set(codes), key=codes.count) if codes else None}
        out.append({"lender": lid, "name": POLICIES[lid][0], **stats, "note": _note(POLICIES[lid][0], stats)})
    return {"groups": {g: [r["persona"] for r in rs] for g, rs in groups.items()},
            "excluded": [r["persona"] for r in rows if not r["admitted"]],
            "lenders": out, "disclaimer": DISCLAIMER,
            "note": "Groups are a credit factor (file thickness), not a protected class; the sandbox has no "
                    "protected-class data. Blocked identities are excluded: no lender sees them."}


def _note(name, s):
    t, e = s["thin_or_no_file"], s["everyone_else"]
    line = (f"{name} approves {t['approved']} of {t['n']} thin- or no-file applicants "
            f"({t['approval_rate']:.0%}) and {e['approved']} of {e['n']} others ({e['approval_rate']:.0%})")
    if t["median_opening_apr"] is not None and e["median_opening_apr"] is not None:
        gap = round(t["median_opening_apr"] - e["median_opening_apr"], 2)
        line += (f"; the group's median opening rate is {abs(gap):g} points {'higher' if gap > 0 else 'lower'}"
                 if gap else "; same median opening rate")
    if t["approval_rate"] != e["approval_rate"]:
        lower, who = (t, "thin- or no-file") if t["approval_rate"] < e["approval_rate"] else (e, "other")
        if lower["top_decline_code"]:
            line += f". Most common decline for {who} applicants: {lower['top_decline_code']}"
    return line + "."


# ---------------------------------------------------------------- everything, for the API and the page
@lru_cache(maxsize=1)
def report():
    base = SampleSource()
    rows = matrix(base)
    blind = blindness(base)
    proxy, cons = proxy_check(rows, base), consistency(rows, base)
    return {
        "disclaimer": DISCLAIMER,
        "lenders": [{"id": lid, "name": POLICIES[lid][0]} for lid in lender_ids()],
        "matrix": [{k: v for k, v in r.items() if k != "passport"} for r in rows],
        "tests": {
            "blindness": {"ok": all(b["identical"] for b in blind), "personas": blind,
                          "changed": ["name", "address", "city", "state", "ZIP", "date of birth", "phone", "email"]},
            "proxy_fields": proxy,
            "consistency": cons,
        },
        "disparity": disparity(rows),
    }
