"""Applicant screening agent on the CRS sandbox.

Runs checks in stages and stops early when it should:
  1. Identity  - FraudFinder, reverse lookup, identity verification (no credit file touched)
  2. Credit    - tri-bureau soft pulls (TransUnion, Equifax, Experian)
  3. Records   - evictions, liens/judgments (rental use case only, and only if identity checks out)

Rules make the decision (agent/rules.py). Claude, if ANTHROPIC_API_KEY is set, writes the
explanation for the underwriter and a message for the applicant. It cannot change the decision.

Usage:
  python -m agent.screen P13                 # one persona, from saved samples
  python -m agent.screen --all               # every sample persona
  python -m agent.screen P05 --use-case rental --json   # "full" also runs the criminal search
  python -m agent.scorecard                  # all 20 personas vs CRS expected decisions (offline)
  python -m agent.screen P12 --live          # call the real sandbox (needs CRS creds)
"""
import argparse, json, os, sys

from . import signals as S
from . import rules as R
from .sources import SampleSource, LiveSource

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")


def screen(source, persona, use_case="loan", explain=True, as_of=None):
    trail = []  # human-readable log of what the agent did and why

    # ---- stage 1: identity, before touching anyone's credit file
    ff = S.fraud_finder(source.get(persona, "fraudfinder"), today=as_of)
    idv = S.identity(source.get(persona, "idv"))
    applicant = source.applicant(persona)  # what the applicant told us; compared against lookups
    rev = S.reverse(source.get(persona, "reverse"), applicant)
    findings = R.identity_findings(ff, idv, rev)
    decision, _ = R.decide(findings, identity_only=True)
    trail.append(f"Stage 1 identity: {len(findings)} finding(s).")

    # ---- stage 2: credit. Prequal endpoints are soft pulls, so they don't hurt the person's score.
    # Still run when fraud is suspected: the file is evidence (e.g. a burst of applications),
    # but it is used for the fraud case only, never as a credit decision against the victim.
    bureaus = {"TransUnion": S.credit(source.get(persona, "tu")),
               "Equifax": S.credit(source.get(persona, "efx")),
               "Experian": S.credit(source.get(persona, "exp"))}
    findings += R.credit_findings(bureaus)
    trail.append("Stage 2 credit: tri-bureau soft pull" + (" (fraud evidence only)" if decision else "") + ".")

    # ---- stage 3: public records, only for rentals and only once identity is trusted
    rec = {}
    decision, ident_pts = R.decide(findings)
    if use_case in ("rental", "full") and decision not in ("STOP_FRAUD", "VERIFY"):
        crim = source.get(persona, "criminal") if use_case == "full" else None
        rec = S.records(source.get(persona, "blj"), source.get(persona, "eviction"), crim)
        findings += R.record_findings(rec)
        decision, ident_pts = R.decide(findings)
        trail.append("Stage 3 records: evictions, liens and judgments checked. "
                     + ("Criminal search run (use case 'full')." if use_case == "full" else
                        "Criminal search not run (restricted for housing in many places, incl. California)."))
    elif use_case in ("rental", "full"):
        trail.append("Stage 3 skipped: identity not trusted, so records would describe the victim, not the applicant.")

    name = " ".join(x for x in [applicant.get("firstName"), applicant.get("lastName")] if x).title()
    report = {
        "persona": persona,
        "applicant": name,
        "use_case": use_case,
        "decision": decision,
        "headline": R.DECISIONS[decision],
        "identity_risk_points": ident_pts,
        "scores": {b: c.get("score") for b, c in bureaus.items() if c.get("available")},
        "signals": {"fraud_finder": ff, "id_codes": idv.get("messages", [])},  # raw-ish signals for UIs
        "findings": sorted(findings, key=lambda f: -f["severity"]),
        "next_steps": R.NEXT_STEPS[decision],
        "trail": trail,
        "products_called": [l["product"] for l in source.log],
        "source": source.name,
    }
    if explain:
        report["explanation"] = explain_with_claude(report)
    return report


def explain_with_claude(report):
    """Plain-language write-up. Falls back to a template when there's no API key."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        top = [f["text"] for f in report["findings"] if f["severity"] >= 2][:3] or [f["text"] for f in report["findings"]][:2]
        return {"underwriter": f"{report['headline']}. " + " ".join(top), "applicant": None, "by": "template"}
    import anthropic
    client = anthropic.Anthropic()
    slim = {k: report[k] for k in ("applicant", "use_case", "decision", "headline", "scores", "findings", "next_steps")}
    msg = client.messages.create(
        model=MODEL, max_tokens=700,
        system=("You explain an applicant-screening decision that has ALREADY been made by rules. Never change or "
                "second-guess the decision. Only use facts in the findings, and name the CRS source for each claim. "
                "Return JSON with two keys: 'underwriter' (3-4 plain sentences for the person reviewing the case) and "
                "'applicant' (a short, respectful message to the applicant; never accuse them of fraud, never reveal "
                "fraud signals; for a credit decline, list the main reasons; for fraud holds, say more verification "
                "is needed). No markdown."),
        messages=[{"role": "user", "content": json.dumps(slim)}],
    )
    text = msg.content[0].text.strip()
    try:
        out = json.loads(text[text.find("{"): text.rfind("}") + 1])
    except ValueError:
        out = {"underwriter": text, "applicant": None}
    out["by"] = MODEL
    return out


ICON = {3: "!!", 2: "! ", 1: "· "}


def print_report(r):
    print(f"\n=== {r['persona']} {r['applicant']}  [{r['use_case']}]")
    print(f">>> {r['headline']}   (identity risk points: {r['identity_risk_points']})")
    if r["scores"]:
        print("    scores: " + ", ".join(f"{b} {s if s is not None else 'no file'}" for b, s in r["scores"].items()))
    for f in r["findings"]:
        print(f"  {ICON[f['severity']]} [{f['axis']}] {f['text']}  ({f['source']})")
    print("  next steps:")
    for s in r["next_steps"]:
        print(f"    - {s}")
    for t in r["trail"]:
        print(f"    > {t}")
    e = r.get("explanation")
    if e:
        print(f"  explanation ({e['by']}): {e['underwriter']}")
        if e.get("applicant"):
            print(f"  to applicant: {e['applicant']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("personas", nargs="*")
    ap.add_argument("--all", action="store_true", help="run every persona that has samples")
    ap.add_argument("--use-case", choices=["loan", "rental", "full"], default="loan")
    ap.add_argument("--live", action="store_true", help="call the CRS sandbox instead of reading samples")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-explain", action="store_true")
    a = ap.parse_args(argv)

    src_factory = LiveSource if a.live else SampleSource
    personas = a.personas or (src_factory().personas() if a.all else [])
    if not personas:
        ap.error("give a persona (e.g. P13) or --all")
    out = []
    for p in personas:
        src = src_factory()
        r = screen(src, p, a.use_case, explain=not a.no_explain)
        out.append(r)
        if not a.json:
            print_report(r)
    if a.json:
        json.dump(out if len(out) > 1 else out[0], sys.stdout, indent=2)
        print()


if __name__ == "__main__":
    main()
