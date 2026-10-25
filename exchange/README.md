# Agent credit exchange

```
python -m exchange.demo P01                        # prime borrower: lenders compete, agent negotiates
python -m exchange.demo P03                        # thin-file student: prime bank passes, credit union wins
python -m exchange.demo P04                        # no file at all: Harbor and NewStart compete on identity strength
python -m exchange.demo P06 --amount 2000 --min-amount 1000   # discharged bankruptcy: Ladder builder loan
python -m exchange.demo P13                        # fraud: blocked before any lender sees anything
python -m exchange.demo P01 --scenario bait_switch # lender worsens terms + forges acceptance: both blocked
python -m exchange.demo P01 --scenario injection   # hidden "ignore your mandate" + compromised agent: blocked
python -m exchange.demo P01 --scenario injection --watchdog  # ...and the injecting lender is excluded
python -m exchange.demo P01 --scenario drift --watchdog      # agent takes 12.5% over 8.5%: allowed, flagged
python -m exchange.demo P01 --scenario data_grab --watchdog  # lender asks for SSN/DOB: flagged
python -m exchange.demo P17 --watchdog                       # one-bureau collection: Campus CU reconciles and lends
```
API: `GET /api/exchange/{P01..P20}?scenario=normal&amount=5000&min_amount=3000&max_apr=18&autopay=1&max_fee=0&watchdog=1&review=0`

## Flow
1. **Gate** (`agent.screen`): CRS FraudFinder, TU identity verification, reverse lookup, 3-bureau soft pull.
   `STOP_FRAUD` = nobody in the market sees anything.
2. **Passport**: derived attributes only (score band, accounts, file age, lates, collections, thin/no-score/no-file,
   identity strength and a 0-100 `identity_score` with `identity_signals`, positive evidence, bureau disagreements and
   a `reconciled` view, verification required). Name, SSN, DOB, contact info and accounts are withheld.
3. **Market**: borrower sends `INTENT` (amount + term range, never the max APR). Lenders `OFFER` or `DECLINE` from
   their policy. Borrower `COUNTER`s, lenders respond, borrower `ACCEPT`s the best offer inside the mandate.
4. **Referee checks every message**: registered + signed sender, role, valid terms, APR cap (36%), no amount above
   the ask, live offers binding (`TERMS_WORSENED`), accepted terms identical to offered (`TERMS_MISMATCH`), inside the
   mandate (`OUTSIDE_MANDATE`).
5. **Settlement** (simulated: hard pull, funding, bureau reporting, step-up verification) and a **disclosure** of
   what the agent traded for the deal, plus the watchdog's notes in plain English.

## Watchdog (`watchdog.py`)
Reviews every event and adds `watchdog` events: `{detector, severity, agent, saw, why, note, suggestion?, ref, source}`.
It only flags. Rule-based detectors:
- `injection`: instructions hidden in message text ("ignore your mandate", "system note", "disregard your instructions")
- `pressure`: sales pressure ("pre-approved", "accept now"); flag-only, never grounds to exclude
- `text_vs_terms`: "same deal" while terms got worse; a fee mentioned that the terms don't include; a quoted APR that isn't the offer's
- `personal_data`: a lender asking for SSN, date of birth or bank login
- `borrower_drift`: accepting while a cheaper live offer also fits the mandate; trying to accept outside it; revealing the max APR
- `bureau_disagreement`: a collection or score at only one bureau, with how to reconcile or dispute it, and what it cost

**Referee rule** (code, with `watchdog=True`): a lender with `TERMS_WORSENED`, `BAD_SIGNATURE` (attributed to the key
that signed it) or a rule-based `injection` flag is excluded: live offers withdrawn, later messages rejected (`EXCLUDED`).

**Claude review** (`ClaudeReview`, `--review` / `review=1`): after the session closes, Claude reads the transcript
(messages, verdicts, rule flags, mandate, passport; never the applicant's name) and flags subtler goal drift. Advisory
only: `source: "claude"` flags never change state. With no key, an API error or bad output, the rule results stand.

## How negotiation works (`pricing.py`, `lenders.py`, `borrower.py`)
Every number a lender quotes comes from its own private **books**, not a fixed rule. All values are illustrative.
- **Probability of default** from a log-odds scorecard (50:1 odds at 700, doubling every 50 points), nudged only
  for what a score misses: thin file, no score/no file, bureaus disagreeing, weak identity, a seasoned file.
- **Break-even APR** = cost of funds + PD x LGD + servicing + origination cost spread over the loan - fee + capital
  x ROE hurdle. Autopay lowers PD and servicing, so its discount is computed. **Floor** = break-even + the least
  margin the lender accepts; **opening** = break-even + its target margin.
- **Private motives** move the floor and the speed: behind its monthly volume target -> thinner margin and early
  concessions (Faratin time-dependent curve); a full risk bucket -> a higher floor. Each lender has a one-line motive.
- **Sealed market**: lenders never see each other. The borrower may `cite` a rival offer; the referee checks it is
  real (`BAD_CITE` otherwise) and passes the lender only the anonymous terms as `verified_quote`. The lender beats it
  if it still clears its floor, otherwise says it can't profitably match. No names, so no collusion.
- **Binding offers**: a worse offer on the same term is `TERMS_WORSENED`. A longer loan is allowed only when the
  borrower asked for it (e.g. to fit a monthly-payment limit). A fee waiver is priced into the rate.
- **36% cap**: a lender whose floor is above it declines instead of bidding.
- The borrower ranks offers by cost per dollar, cites the best rival, asks for autopay if allowed, asks for a longer
  term if only the payment doesn't fit, and walks away when nothing fits. `lender_books` (break-even build-up, floor,
  opening, motive) are shown to judges only after the session closes.

## Thin-file and no-file borrowers (Phase 2)
- **Identity score** (`passport.py`): 100 minus points per identity finding (note 10, concern 25, blocker 60), same
  neutral cases as `identity`. `identity_signals`: SSN-name match, phone owned, email owned, email age >= 30 days,
  address deliverable, IP within 100 miles, as booleans only.
- **Positive evidence**: `months_on_time` (longest current on-time run, capped at months reviewed),
  `oldest_account_years`, `never_late`, `address_stable`, `phone_stable`. The sandbox has no address or phone
  history, so the last two are approximations from FraudFinder (name tied to the street; own postpaid, non-VoIP phone).
  `pricing.positive_evidence` turns them into small odds multipliers (never late x1.15, 12+ months on time x1.10,
  each stable x1.05), only for thin, no-score and no-file passports: a full scored file already reflects them.
- **Specialist lenders**: Harbor Newcomer Lending (no-file or thin file, `identity_score` >= 80, up to $3,000 over
  12-24 months, `pd_model="identity"`) and Ladder Credit Builder (charge-offs or a discharged bankruptcy, $500-$2,000,
  a margin cut for autopay, on-time reporting labelled simulated).
- **Reason codes**: every lender `DECLINE` carries `reason_code` from `messages.REASON_CODES` (NO_SCORE, FEW_ACCOUNTS,
  FILE_TOO_NEW, SCORE_BELOW_MIN, RECENT_LATES, COLLECTION_ON_FILE, CHARGEOFF_ON_FILE, BANKRUPTCY_ON_FILE,
  BUREAUS_DISAGREE, IDENTITY_UNCONFIRMED, OVER_RATE_CAP, OUTSIDE_PRODUCT) next to its unchanged sentence. "X% is our
  best" counter replies carry none: the offer stays live.
- **Reconciliation** (`reconcile.py`): an item one bureau reports while another bureau with a file doesn't is
  "unconfirmed"; reconciled counts are what two bureaus agree on. Books with `reconciled=True` (Campus CU, Harbor,
  Ladder) price on that view; Prime Bank, NewStart and Second Chance keep the worst-bureau view.

## Current results on the samples (rule-based agents, default mandate: $5,000, 18% max, autopay ok)
| Persona | Outcome |
|---|---|
| P01 prime | Prime Bank opens 11.22%, cited rival + autopay -> 10.17% |
| P03 thin file | 4 offers; Campus CU 9.83% -> 8.0% (Harbor bids 14.5% on $3,000) |
| P04 no file | Harbor 15.05% -> 13.15% on $3,000 / 24 months; NewStart also bids (20.98%) |
| P05 subprime | Only Second Chance, above the mandate: agent walks away |
| P06 discharged bankruptcy | Second Chance and Ladder bid; Ladder's $2,000 is below the $3,000 minimum, so no deal. With a $2,000 mandate: Ladder 14.62% with autopay |
| P10 | Campus CU 8.07% -> 6.5% |
| P12 / P13 / P14 | Blocked at the gate |
| P16 fraud alert | Prime Bank 11.93% -> 10.77%, step-up verification in settlement |
| P17 bureaus disagree | Experian-only collection is unconfirmed: Campus CU 7.53% -> 6.04% on $5,000 (Prime still declines) |
| P18 old charge-offs | NewStart $3,000 at 17.33%; Ladder bids 13.6% on $2,000 (with a $2,000 mandate: Ladder 11.7%) |
| P20 no score | Campus CU 9.78% -> 7.95% on file history |
| P03 with a $150/month limit | Campus CU restructures to 48 months when the borrower asks (7.93%) |
