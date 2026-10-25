# Decision log

Important decisions, newest first. Format and rules: [PROCESS.md](PROCESS.md).

## 2026-10-25: Red team: a Claude scammer lender (`red_team` scenario)
SwiftLend Express is played by Claude, told to scam the borrower's agent and choose its own tactics each move; it goes through the unchanged referee and watchdog, and `report(ex)` pairs each attempt with what caught it. Its first live runs found a gap ("held for only a few minutes" wasn't flagged), so the pressure detector gained urgency patterns.
Why: an unscripted attacker is a stronger proof than scripted ones. Gave up: it's the one lender allowed to ignore its books (attacking is its job), and without a key it plays a fixed script.

## 2026-10-25: The person approves the loan, not their agent
With `approval=1` (used by the /demo chat) the agent's ACCEPT is only a recommendation; the referee settles only when the person approves that exact offer (`POST /api/session/{id}/approve`, once, inside the mandate) or ends with no deal on decline.
Why: an agent should never sign a loan for someone, and the roadmap listed the missing approval as the first gap. Gave up: held sessions live in server memory (a restart drops them), and the form path and exchange.html still auto-accept.

## 2026-10-25: Fairness check proves blindness by swapping protected data in the raw CRS responses
We swap each applicant's name, address, ZIP, DOB, phone and email consistently across every CRS product and require identical decisions and prices, plus twins and a passport proxy scan; disparity compares thin/no-file vs others, labelled "internal check, not a legal fair-lending review".
Why: it tests the whole pipeline, not just the lender functions. Gave up: no protected-class data in the sandbox, so no disparate-impact measure; file age is credit-relevant but age-correlated (flagged, kept); attack-scenario agents without books are left out of the matrix.

## 2026-10-25: Thin-file lending: identity score, positive evidence, specialist lenders, reason codes, reconciliation
Newcomers are priced on a 0-100 identity score plus positive evidence (thin/no-file only, so full files aren't rewarded twice); Harbor and Ladder serve no-file and rebuilding borrowers; declines carry 12 fixed codes (3 added to the brief's 9 so charge-off, bankruptcy and bureau declines aren't mislabelled); one-bureau items are "unconfirmed" and lenders opt in per Book to price on that view.
Why: thin and no-file people get competing offers and exact reasons. Gave up: address/phone "stable" is approximated (no history in the sandbox), Prime Bank keeps the worst-bureau view, and small add-only edits landed outside the owned files (signals.py, messages.py, scenarios.py, llm_agents.py), agreed in session.

## 2026-10-24: Live CRS mode with per-product fallback
`?live=1` calls the CRS sandbox and, if one product call fails, uses that product's saved sample and says so on screen. Why: the live demo is CRS's one hard rule, and a flaky call at the table must not break it. Gave up: a run can be partly live; the label says which.

## 2026-10-24: Negotiation engine: lender books and a sealed market
Lenders price from their own books (risk-based break-even, floor, private volume/risk motives) and never see rivals; the referee passes only a verified anonymous quote the borrower cites. Why: real negotiation with no fixed "2 points off" rule and no room to collude. Gave up: parameters are illustrative, not calibrated.

## 2026-10-24: Decision logging process
Every finished feature gets a 2-line entry, written from git, PRs, the `inbox/` drop and the session, so decisions from all teammates are captured. Why: the reasoning behind choices gets lost, and judges and teammates need to see it. Gave up: some extra writing per feature.

## 2026-10-24: Backfilled: watchdog flags never change state except injection exclusion
Watchdog only flags; the only thing that can exclude a lender is the deterministic injection regex. Why: keeps the referee's decisions in code and auditable, and stops a Claude opinion from silently removing a lender. Source: CLAUDE.md hard rule 2.

## 2026-10-24: Backfilled: the referee is never an LLM
AI agents propose messages and the referee's code decides what is valid. Why: approvals and blocks must be deterministic and reproducible, and an LLM can be talked into a wrong decision. Gave up: some agent flexibility. Source: CLAUDE.md hard rule 1.

## 2026-10-24: Backfilled: lenders see a passport, never the raw CRS file
Lenders get derived attributes only (no name, SSN, DOB or contact). Why: data minimization, and it is the product's privacy story. Source: CLAUDE.md hard rule 4.

## 2026-10-24: Backfilled: Claude-powered lenders may only negotiate inside their policy range
Claude overrides `respond_to_counter` and never the policy. Why: pricing must come from the CRS-derived policy, so an LLM cannot offer terms outside it. Source: CLAUDE.md hard rule 3.
