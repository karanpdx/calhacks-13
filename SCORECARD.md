# Decision-agent scorecard

`python -m agent.scorecard` runs the repo's screening agent (`agent/screen.py` + `agent/rules.py`) offline over the
180 saved sample responses in `crs/samples` (20 personas x 9 products) and compares each decision with what CRS
encodes in the collection folder names. No network calls, no credentials.

How decisions are compared:
- "Hold for fraud" counts as a DECLINE-class outcome, so it matches an expected DECLINE (and nothing else).
- "Step-up verification" is a manual-review path, so it counts as REVIEW.
- The scorecard runs the `full` use case: loan checks plus evictions, liens/judgments and the criminal search
  (CRS's P06-P11 expectations depend on those products).

<!-- TABLE START -->
**Match: 19/20**

| Persona | Expected (CRS) | Agent decision | Match | Reason |
|---|---|---|---|---|
| P01 Margaret Okafor | APPROVE | Approve | yes | No findings: clean identity, clean file. |
| P02 Daniel Whitfield | APPROVE | Approve | yes | No findings: clean identity, clean file. |
| P03 Jasmine Reyes | REVIEW | Approve | **NO** | Thin credit file (fewer than 3 accounts). Common for students and new arrivals. |
| P04 Tomas Lindqvist | NO_FILE | No file | yes | The bureau has no record of this SSN. None of the bureaus has a credit file for this person. |
| P05 Ricky Dalton | DECLINE | Decline (credit) | yes | Lowest score is 540. 8 late payments (2 at 90+ days), most recent 2026-09-19. |
| P06 Angela Morrissey | REVIEW | Review | yes | Lowest score is 580. 4 account(s) charged off. |
| P07 Marcus Bellamy | DECLINE | Decline (credit) | yes | Lowest score is 560. 2 account(s) charged off. |
| P08 Priya Venkatesan | REVIEW | Review | yes | 1 judgment(s), 1 lien(s). |
| P09 Derek Holloway | DECLINE | Decline (public record) | yes | 1 felony conviction(s). |
| P10 Lauren Kowalczyk | APPROVE | Approve | yes | No findings: clean identity, clean file. |
| P11 Brandon Szabo | DECLINE | Decline (credit) | yes | Lowest score is 610. 1 account(s) in collections. |
| P12 Victor Anand | DECLINE | Hold for fraud | yes | The SSN on the application belongs to someone with a different name. The bureau has no record of this SSN. |
| P13 Kayla Brennan | DECLINE | Hold for fraud | yes | The SSN on the application belongs to someone with a different name. Date of birth doesn't match the file for this SSN. |
| P14 Harold Pettigrew | DECLINE | Hold for fraud | yes | SSN is linked to a deceased person. FraudFinder risk score is 80/100. |
| P15 Nicole Farragut | REVIEW | Review | yes | TransUnion has no record of this SSN, but Equifax, Experian do. |
| P16 Samuel Oyelaran | REVIEW | Review (step-up verification) | yes | A fraud alert is on file; the bureau recommends step-up authentication. |
| P17 Elena Castellanos | REVIEW | Review | yes | 1 account(s) in collections. A collection (NATIONAL RECOVERY 1) appears only at Experian. A single-bureau check would have missed it. |
| P18 Terrence Abernathy | REVIEW | Review | yes | 2 account(s) charged off. |
| P19 Grace Nakamura | APPROVE | Approve | yes | No findings: clean identity, clean file. |
| P20 Dolores Whitcomb | REVIEW | Review | yes | There is a file but no bureau could produce a score (unscorable). |
<!-- TABLE END -->

## Result and honesty notes

- **Original agent (commit `ca036e6`, before this change): 11/20 on the `loan` use case, 12/20 on `rental`.**
  It had no no-file outcome, ignored charge-offs and unscorable files, didn't use the criminal record, and treated
  "SSN not on file at one bureau" as fraud.
- **After the rule changes below: 19/20.** The rule changes were made after seeing CRS's expected decisions, so
  19/20 is a fit to these 20 samples, not a held-out test. I fixed only gaps that have a defensible reason on their own.
- **The one miss is P03 (thin file).** CRS says REVIEW. The agent says Approve, which is what `agent/README.md`
  describes: a 660 file with 2 clean accounts is a real person with a short history, and `THIN_FILE` is a severity-1
  note. I left that rule alone and report it as a mismatch. Making thin files REVIEW would flip it to a match, but it
  would send every student and new arrival to manual review.

## Rule changes (each with its reason)

| Change | Why |
|---|---|
| `NO_FILE` outcome: no bureau has a file and the identity evidence isn't bad enough to call fraud (P04) | A person with no credit history isn't a fraudster. `SSN_NOT_ON_FILE` and `NO_CREDIT_FILE` moved to a `file` axis so they no longer count as identity points on their own. P12 still holds for fraud because of the real identity evidence (SSN/name mismatch, 2201/2202, FraudFinder 85). |
| `SSN_NOT_ON_FILE` at one bureau while others have a file becomes a severity-2 consistency finding (P15) | The bureaus disagree, which is a human question. It used to be a severity-3 identity blocker and sent P15 (idv clean, FraudFinder 10, 740 at EFX/EXP) to a fraud hold. |
| Read deceased from code `2301` (P14) | The sandbox leaves the `deceases` list empty and reports it only as message 2301, so the old check never fired. P14 was still held by other signals; now the reason is right. |
| Fraud alert code `2401` is a severity-2 identity finding (P16) | A FACTA fraud alert means the bureau recommends step-up authentication before extending credit. With FraudFinder 50 it lands on "step-up verification". |
| Charge-offs are a severity-2 credit finding (P06, P18) | `chargeoffs` was extracted but never used. |
| A file with no score at any bureau is a severity-2 credit finding (P20) | Unscorable files can't be approved automatically. |
| Any credit finding of severity 2 or more now gives REVIEW instead of falling through to APPROVE | Between "decline" (a severity-3 finding, or 5+ credit points) and "approve" there needs to be a review band. |
| Judgments/liens are severity 2, not 1 (P08) | An unsatisfied judgment plus a lien is a real record. It now triggers review on a rental/full run. |
| Criminal search (`full` use case only): felony conviction is severity 3 and declines (P09). Dismissed cases are ignored (P10). Other convictions are a note | Convictions are the only criminal data that should count. P10's only record is a dismissed misdemeanor. |
| `--as-of` date pinned to 2026-10-24 in the scorecard | The "new email" rule uses today's date, so P13's result would drift as the clock moves. |

## Caveats

- `agent/README.md` turns the criminal search off for housing, including California. The default `loan` and `rental`
  use cases still do that. Only `full` runs it, and the "felony conviction = decline" rule is a demo policy. A real
  deployment needs a fair-chance / individualized-assessment step before any criminal record is used.
- Sandbox personas are built to trigger one rule each, so a high match rate says little about real applicants.
- Other use cases on the same samples: `loan` (no records stage) 17/20, missing P03, P08 and P09; `rental`
  (no criminal search) 18/20, missing P03 and P09.
