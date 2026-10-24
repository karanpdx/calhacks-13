# Screening agent

Takes an applicant (a CRS test persona), runs CRS checks in stages, and returns a decision with
every reason tied to the CRS product it came from.

```
pip install requests anthropic
python -m agent.screen --all                    # all 5 sample personas, offline
python -m agent.screen P13                      # one persona
python -m agent.screen P03 --use-case rental    # adds eviction / liens / judgments
python -m agent.screen P17 --json               # machine-readable, for a UI
python -m agent.screen P12 --live               # real sandbox calls (CRS_USER, CRS_PASS, collection file)
```

Set `ANTHROPIC_API_KEY` to have Claude write the explanation (an underwriter summary and a message to the applicant).
Without it you get a template explanation. `CLAUDE_MODEL` overrides the model.

## How it decides

1. **Identity first** (FraudFinder, reverse lookup, TransUnion identity verification). No credit file is touched yet.
2. **Credit** (tri-bureau soft pulls; the `prequal` endpoints don't affect the person's score). If fraud is already
   suspected, the file is used only as fraud evidence, never as a credit decision against the victim.
3. **Records** (rental only): evictions, liens, judgments, and only when identity checks out. Criminal search is off:
   it's restricted for housing decisions in many places, including California.

Rules in `rules.py` make the decision. Claude only explains it and can't change it.
Each finding has a severity (1 note, 2 concern, 3 blocker) and an axis: `identity`, `credit`, `consistency`, `records`.

| Decision | When |
|---|---|
| Hold: likely identity fraud | any identity blocker, or 6+ identity points |
| Step-up verification | 3-5 identity points (ID + live selfie / liveness check goes here) |
| Decline: credit risk | identity is fine, credit is poor (adverse-action reasons listed) |
| Manual review | bureaus disagree, or a serious record on a rental |
| Approve | none of the above |

## What the 5 sample personas show

| Persona | Story | Decision |
|---|---|---|
| P03 Jasmine Reyes (Berkeley) | Real person, thin file (2 accounts, 660) | Approve |
| P05 Ricky Dalton | Real person, bad credit (540, lates, collections) | Decline on credit, *not* fraud |
| P12 Victor Anand | Synthetic identity: SSN belongs to someone else, no file at any bureau, contact info belongs to "Rajesh Menon", IP > 1000 mi away | Hold: fraud |
| P13 Kayla Brennan | Stolen identity: real 640 file, but 9 applications in 24 days, 9-day-old email, prepaid VoIP phone that isn't hers | Hold: fraud |
| P17 Elena Castellanos | Clean at TransUnion (760), but a collection shows up only at Experian and Equifax has no file | Manual review |

Demo point: P05 vs P13. Both look "risky" to a score-only model, but one is a person who needs
an honest credit decision and the other is a victim whose identity is being used.
P17 is the case for pulling all three bureaus.

Sandbox quirk: the identity-verification summary block (`riskIndicator: MEDIUM`, address `NO_MATCH`) is the same
for every persona, so the agent reads the add-on mismatch codes (2201, 2202, 2101) instead.
