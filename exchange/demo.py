"""Run one exchange session in the terminal.

  python -m exchange.demo P01
  python -m exchange.demo P03 --amount 3000 --max-apr 16
  python -m exchange.demo P01 --scenario injection
  python -m exchange.demo P13                     # fraud: blocked at the gate
  python -m exchange.demo P01 --json > out.json   # full event log for the UI
"""
import argparse, json, sys

from agent.sources import SampleSource, LiveSource
from .messages import Mandate
from .referee import Exchange
from .scenarios import build, SCENARIOS


def run(persona, scenario="normal", live=False, **mandate):
    lenders, borrower = build(scenario)
    ex = Exchange(persona, Mandate(**{k: v for k, v in mandate.items() if v is not None}),
                  LiveSource() if live else SampleSource(), lenders, borrower)
    return ex.run()


def show(r):
    G = {True: "✓", False: "✗"}
    for e in r["events"]:
        k, d = e["kind"], e["data"]
        if k == "gate":
            print(f"\n[gate] {d['applicant']}: {d['headline']}  (CRS: {', '.join(d['crs_products'])})")
            for f in d["findings"][:4]:
                print(f"         - {f['text']}")
        elif k == "passport":
            p = d["passport"]
            print(f"[passport] score band {p['score_band']}, {p['accounts']} accounts, file {p['file_age_years']}y, "
                  f"identity {p['identity']}, thin={p['thin_file']}, no_score={p['no_score']}, no_file={p['no_file']}"
                  + (f", disagreements: {len(p['bureau_disagreements'])}" if p["bureau_disagreements"] else ""))
        elif k == "message":
            v = e["verdict"]
            t = d.get("terms")
            terms = f" ${t['amount']:,.0f} @ {t['apr']}% {t['term_months']}mo" + (" autopay" if t["autopay"] else "") \
                + (f" fee ${t['fee']:.0f}" if t["fee"] else "") if t else ""
            print(f"  r{e['round']} {G[v['ok']]} {e['actor']:>13} {d['type']:<8}{terms}  | {d['text'][:90]}")
            if not v["ok"]:
                print(f"      BLOCKED {v['code']}: {v['reason']}")
        elif k in ("blocked", "no_deal"):
            print(f"[{k}] {d['reason']}")
        elif k == "settlement":
            for s in d["steps"]:
                print(f"[settle] {s}")
        elif k == "disclosure":
            for s in d["summary"]:
                print(f"[deal] {s}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("persona")
    ap.add_argument("--scenario", choices=SCENARIOS, default="normal")
    ap.add_argument("--amount", type=float)
    ap.add_argument("--min-amount", type=float)
    ap.add_argument("--max-apr", type=float)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = run(a.persona, a.scenario, a.live, amount=a.amount, min_amount=a.min_amount, max_apr=a.max_apr)
    if a.json:
        json.dump(r, sys.stdout, indent=2, default=str)
        print()
    else:
        show(r)


if __name__ == "__main__":
    main()
