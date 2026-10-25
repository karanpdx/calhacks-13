# Agent credit exchange

```
python -m exchange.demo P01                        # prime borrower: lenders compete, agent negotiates
python -m exchange.demo P03                        # thin-file student: prime bank passes, credit union wins
python -m exchange.demo P04 --max-apr 20           # no file at all: identity-based lender steps in
python -m exchange.demo P13                        # fraud: blocked before any lender sees anything
python -m exchange.demo P01 --scenario bait_switch # lender worsens terms + forges acceptance: both blocked
python -m exchange.demo P01 --scenario injection   # hidden "ignore your mandate" + compromised agent: blocked
```
API: `GET /api/exchange/{P01..P20}?scenario=normal&amount=5000&min_amount=3000&max_apr=18&autopay=1&max_fee=0`

## Flow
1. **Gate** (`agent.screen`): CRS FraudFinder, TU identity verification, reverse lookup, 3-bureau soft pull.
   `STOP_FRAUD` = nobody in the market sees anything.
2. **Passport**: derived attributes only (score band, accounts, file age, lates, collections, thin/no-score/no-file,
   identity strength, bureau disagreements, verification required). Name, SSN, DOB, contact info and accounts are withheld.
3. **Market**: borrower sends `INTENT` (amount + term range, never the max APR). Lenders `OFFER` or `DECLINE` from
   their policy. Borrower `COUNTER`s, lenders respond, borrower `ACCEPT`s the best offer inside the mandate.
4. **Referee checks every message**: registered + signed sender, role, valid terms, APR cap (36%), no amount above
   the ask, live offers binding (`TERMS_WORSENED`), accepted terms identical to offered (`TERMS_MISMATCH`), inside the
   mandate (`OUTSIDE_MANDATE`).
5. **Settlement** (simulated: hard pull, funding, bureau reporting, step-up verification) and a **disclosure** of
   what the agent traded for the deal.

## Current results on the samples (rule-based agents)
| Persona | Outcome |
|---|---|
| P01 prime | Prime Bank, 8.5% -> 7.0% with autopay |
| P03 thin file | Prime declines; Campus CU, 13.5% -> 12.0% |
| P04 no file | Only NewStart bids (identity-based); fits a 20% mandate |
| P05 subprime | Only Second Chance bids, above the 18% mandate: agent walks away |
| P12 / P13 / P14 | Blocked at the gate |
| P16 fraud alert | Deal, with step-up verification in settlement |
| P17 bureaus disagree | A collection at one bureau knocks out the mainstream lenders (watchdog work: reconcile) |
| P20 no score | Campus CU on file history |
