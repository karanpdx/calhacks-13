# Decision log

Important decisions, newest first. Format and rules: [PROCESS.md](PROCESS.md).

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
