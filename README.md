# Agent Credit Exchange

**Cal Hacks 13.0 · CRS Financial Intelligence Challenge · Karan, Mohammed, Nick**

Credit is about to be negotiated by AI agents. The people with the most to lose are the ones the system already
overlooks: students, newcomers, people rebuilding. We built the version that's safe enough to trust them with.

A person tells their AI agent what they need. The agent shops a market of lender agents and negotiates. A referee made
of plain code (never an LLM) checks every message, and nothing is signed until the person approves the exact offer.
It runs on the CRS Credit API sandbox: CRS fraud, identity and all three credit bureaus decide who enters the market
and what lenders get to see. CRS announced an "Exchange" like this on Oct 19 as a waitlist page; this is a working one.

## Try it

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload            # then open the pages below
pytest                                   # 236 offline tests (saved sandbox data, no paid APIs)
```

| Page | What it shows |
|---|---|
| `/phone` | The borrower: chat with your loan agent (English or Spanish, plain language, read aloud), set limits, watch it shop, approve or decline. |
| `/demo` | The story for a room: a real file next to a stolen one, seven lenders, the attack, the deal. Pairs with a phone. |
| `/safety` | The safety case: 11 attacks run against the referee on page load, the 10 layers that stop them, replayable transcripts, a red-team scoreboard. |
| `/fairness` | Every persona through every lender, plus blindness, proxy-field and consistency tests. |
| `/lender` | A lender's console built from real sessions: the passport only, its own offers and books, never a name or which rival won. |

**Live CRS sandbox:** `export CRS_USER=... CRS_PASS=...`, put the Postman collection in `crs/`, and the pages call the
sandbox (`?live=0` for saved data). A failed call falls back to that product's saved response and the page says so.
**Claude agents:** set `ANTHROPIC_API_KEY`; without it every agent runs on its rule-based version.

## How it works

1. **Mandate.** The person's limits (amount, monthly payment, rate, term, fees, autopay) become a permission boundary
   enforced in code.
2. **CRS gate.** AtData FraudFinder, TransUnion identity verification, reverse phone/email lookup, and TransUnion,
   Equifax and Experian reports. Stolen or synthetic identities stop here; no lender sees anything.
3. **Passport.** Lenders get derived fields only: score band, file age, on-time months, a 0-100 identity score, and a
   reconciled view where an item only one bureau reports is marked unconfirmed. Never a name, SSN or address.
4. **Sealed market.** Six lenders, including two built for thin files (Harbor Newcomer Lending, Ladder Credit Builder),
   price from their own books: cost of funds + expected loss from a credit scorecard + servicing + capital. Private
   motives (volume targets, risk appetite) set how far each one moves. Lenders never see each other; the borrower's
   agent can cite a rival offer, which the referee verifies and passes on anonymously.
5. **Referee.** Every message is signed and checked: valid terms, 36% cap, offers binding, acceptance identical to the
   offer and inside the mandate. Free text is shown but never acted on.
6. **Watchdog.** Flags hidden instructions, pressure, personal-data requests, text that contradicts the terms, and an
   agent drifting from the person's interest. Injection removes a lender.
7. **Approval and disclosure.** The agent recommends; the person approves that exact offer. They see the monthly
   payment, total cost, what was traded, what helped, and, if declined, what would change the answer.

## What it shows (saved sandbox data, default limits $5,000 / 18%)

| Person | Outcome |
|---|---|
| P01, prime | Prime Bank opens at 11.22%, negotiated to 10.17% |
| P03, student, thin file | Campus Credit Union, 9.83% → 8.0% |
| P04, recent immigrant, no credit file | Harbor Newcomer Lending, $3,000 at 13.15% (no deal before the specialist lenders) |
| P17, collection at one bureau only | Reconciled: Campus Credit Union at 6.04% (was $3,000 at 16.49%) |
| P20, retiree, no score | Campus Credit Union, 7.95% |
| P13, stolen identity (clean 640 score) | Blocked at the CRS gate; no lender sees anything |

Safety (`/safety`, `tests/test_safety.py`): 11 of 11 attacks stopped, including hidden instructions with the watchdog
switched off (the referee still blocks every attempt), a forged acceptance, a fake rival quote and a model outage.
Red team: 51 scripted scam moves over 17 sessions, all caught, none won a loan.

## What's simulated

The people are CRS sandbox test personas (fictional). Lenders, their agents and books, the hard pull at acceptance,
funding, bureau reporting and step-up identity checks are simulated and labeled in the UI. Pricing parameters are
illustrative, not calibrated. The fairness and safety pages are internal checks, not legal or security audits.

## Repo

- `exchange/`: the marketplace (`referee.py`, `passport.py`, `pricing.py`, `lenders.py`, `watchdog.py`, `safety.py`,
  `fairness.py`, `adversary.py`, `i18n.py`, ...). Start with `CLAUDE.md`.
- `agent/`: the CRS screening gate (19/20 match with CRS's expected decisions).
- `crs/`: sandbox client, OpenAPI spec, saved responses for P01-P20.
- `app/`: FastAPI server and pages.
- `docs/`: roadmap, CRS brief, decision log (`docs/decisions/LOG.md`).

Never commit the sandbox login or the Postman collection (it embeds the login).
