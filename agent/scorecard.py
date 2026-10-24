"""Scorecard: run the decision agent offline over every persona in crs/samples and compare it with the
decision CRS encodes in the collection folder names.

  python -m agent.scorecard                 # print the table
  python -m agent.scorecard --write SCORECARD.md   # also refresh the table inside SCORECARD.md
  python -m agent.scorecard --use-case rental      # run with a different use case

Reads saved samples only. No network, no credentials.
"""
import argparse, os, sys
from datetime import date

from .screen import screen
from .sources import SampleSource, ROOT

# What CRS expects (from the collection folder names).
EXPECTED = {
    "P01": "APPROVE", "P02": "APPROVE", "P03": "REVIEW", "P04": "NO_FILE", "P05": "DECLINE",
    "P06": "REVIEW", "P07": "DECLINE", "P08": "REVIEW", "P09": "DECLINE", "P10": "APPROVE",
    "P11": "DECLINE", "P12": "DECLINE", "P13": "DECLINE", "P14": "DECLINE", "P15": "REVIEW",
    "P16": "REVIEW", "P17": "REVIEW", "P18": "REVIEW", "P19": "APPROVE", "P20": "REVIEW",
}

# Agent decision -> CRS class. Hold-for-fraud counts as a decline-class outcome (it only matches an
# expected DECLINE). Step-up verification is a manual-review path, so it counts as REVIEW.
CLASS = {"APPROVE": "APPROVE", "REVIEW": "REVIEW", "VERIFY": "REVIEW", "DECLINE_CREDIT": "DECLINE",
         "DECLINE_RECORDS": "DECLINE", "STOP_FRAUD": "DECLINE", "NO_FILE": "NO_FILE"}

LABEL = {"APPROVE": "Approve", "REVIEW": "Review", "VERIFY": "Review (step-up verification)", "DECLINE_CREDIT": "Decline (credit)",
         "DECLINE_RECORDS": "Decline (public record)", "STOP_FRAUD": "Hold for fraud", "NO_FILE": "No file"}

AS_OF = date(2026, 10, 24)  # the day the samples were pulled; keeps the "new email" rule from drifting with the clock


def reason(r):
    top = [f for f in r["findings"] if f["severity"] >= 2] or r["findings"]  # findings come sorted, worst first
    top = top[:2]
    if not top:
        return "No findings: clean identity, clean file."
    return " ".join(f["text"] for f in top)


def run(use_case="full"):
    rows = []
    for p in sorted(EXPECTED):
        r = screen(SampleSource(), p, use_case, explain=False, as_of=AS_OF)
        cls = CLASS[r["decision"]]
        rows.append({"persona": p, "name": r["applicant"], "expected": EXPECTED[p], "decision": LABEL[r["decision"]],
                     "code": r["decision"], "cls": cls, "match": cls == EXPECTED[p], "reason": reason(r)})
    return rows


def table_md(rows):
    out = ["| Persona | Expected (CRS) | Agent decision | Match | Reason |", "|---|---|---|---|---|"]
    for x in rows:
        out.append(f"| {x['persona']} {x['name']} | {x['expected']} | {x['decision']} | {'yes' if x['match'] else '**NO**'} | {x['reason']} |")
    return "\n".join(out)


def print_table(rows):
    w = max(len(x["decision"]) for x in rows)
    print(f"{'persona':<8}{'expected':<10}{'agent':<{w + 2}}{'match':<7}reason")
    for x in rows:
        print(f"{x['persona']:<8}{x['expected']:<10}{x['decision']:<{w + 2}}{'yes' if x['match'] else 'NO':<7}{x['reason'][:110]}")
    n = sum(x["match"] for x in rows)
    print(f"\nMatch: {n}/{len(rows)}")
    for x in rows:
        if not x["match"]:
            print(f"  miss {x['persona']}: expected {x['expected']}, agent {x['decision']} ({x['code']})")


def write_md(path, rows):
    s = open(path).read()
    a, b = "<!-- TABLE START -->", "<!-- TABLE END -->"
    n = sum(x["match"] for x in rows)
    block = f"{a}\n**Match: {n}/{len(rows)}**\n\n{table_md(rows)}\n{b}"
    i, j = s.index(a), s.index(b) + len(b)
    open(path, "w").write(s[:i] + block + s[j:])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--use-case", choices=["loan", "rental", "full"], default="full")
    ap.add_argument("--write", metavar="SCORECARD.md")
    a = ap.parse_args(argv)
    rows = run(a.use_case)
    print_table(rows)
    if a.write:
        write_md(os.path.join(ROOT, a.write) if not os.path.isabs(a.write) else a.write, rows)
    return 0 if all(x["match"] for x in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
