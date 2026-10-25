# Cal Hacks 13.0: agent-to-agent credit exchange on the CRS sandbox

Team: Karan, Mohammed, Nick. Track: CRS Financial Intelligence Challenge. Deadline: Devpost by **Sunday 9:00 AM**.

## What we're building
A working agent-to-agent credit marketplace on the CRS Credit API sandbox, inspired by the "CRS Exchange" CRS
announced on Oct 19 (a waitlist page, not built). Our own product and name; never use CRS branding as ours.

- A **borrower** (one of CRS's 20 sandbox personas) gives their AI agent a **mandate**: amount, max APR, term range,
  allowed concessions (autopay), max fee.
- The **referee** (`exchange/referee.py`, deterministic code, NO AI) runs the CRS gate (fraud, identity, 3 bureaus),
  builds a **passport** (derived attributes only; no name/SSN/DOB/contact), and validates every message.
- Simulated **lender agents** with different policies bid; the **borrower agent** negotiates; the best deal inside the
  mandate wins. The person gets a plain-English **disclosure** of what was traded off.
- A **watchdog** (`exchange/watchdog.py`) reviews every event and adds flags (severity, agent, what it saw, why it
  matters). It can only flag; flags reach the person in their disclosure. Optional Claude review pass on top.
- Next: agent credit files, privacy bargaining.

## Hard rules (don't break these)
1. **The referee is never an LLM.** AI agents propose; the referee's code decides what's valid. An LLM must never be
   the thing that blocks or approves a message, an offer, or a deal.
2. **Free text is untrusted.** `Message.text` is shown and logged but the referee never acts on it. Only structured
   fields (`type`, `terms`, `offer_id`, `ask`) change state. One exception: only the rule-based injection detector
   (`exchange/watchdog.py`, deterministic regex) may trigger exclusion; Claude flags never change state.
3. **Lender pricing comes from `exchange/lenders.py` policies (computed from CRS data).** A Claude-powered lender may
   negotiate only inside its policy's range: override `respond_to_counter`, never `policy`.
4. **Lenders see the passport, never the raw CRS file.** Don't add personal fields to `exchange/passport.py`.
5. **Sandbox test identities only.** Never put real names/SSNs anywhere. Never commit `CRS_USER`/`CRS_PASS`, `.env`,
   or the Postman collection (`calhacks13-*.json`, it has the login).
6. **Label anything simulated** (lenders, hard pull at acceptance, funding, bureau reporting, KBA/OTP) in the UI.
7. Keep `pytest` green and offline (samples only; no network, no paid APIs in tests).

## Layout
- `crs/`: CRS sandbox client (`crs_client.py`), OpenAPI spec, `samples/` = saved responses for P01-P20 (all 9 products)
- `agent/`: screening gate: `screen()` -> findings + decision; `signals.py` (CRS field parsing), `rules.py`,
  `scorecard.py` (19/20 vs CRS expected decisions; `AS_OF` pins the sample date)
- `exchange/`: the marketplace
  - `messages.py`: protocol: `Terms`, `Mandate`, `Message` (INTENT/OFFER/COUNTER/ACCEPT/DECLINE/WITHDRAW), signing
  - `passport.py`: what lenders see
  - `referee.py`: `Exchange`: gate -> passport -> market loop -> settlement -> disclosure; `events` = audit log.
    `watchdog=True`: flags + exclusion rule (lender out after TERMS_WORSENED, BAD_SIGNATURE or a rule-based injection flag)
  - `watchdog.py`: rule-based detectors (injection, text vs terms, personal data, borrower drift, bureau disagreement)
    + `ClaudeReview` (advisory, runs after close, falls back to rule results on any error)
  - `lenders.py`: 4 policies (Prime Bank, Campus CU, NewStart Fintech, Second Chance) + `RuleLender` stand-in agent
  - `borrower.py`: `RuleBorrower` stand-in agent (+ `GullibleBorrower` for the injection scenario)
  - `scenarios.py`: `normal`, `bait_switch` (worse terms + forged acceptance), `injection` (hidden instructions),
    `data_grab` (lender asks for SSN/DOB, undeclared fee), `drift` (borrower takes a costlier offer, leaks max APR)
  - `finance.py`: payment / total cost math
- `app/main.py`: FastAPI: `/api/personas`, `/api/decide/{P}`, `/api/scorecard`,
  `/api/exchange/{P}?scenario=...&watchdog=1&review=0` (watchdog on by default; `review=1` = Claude pass)
- `app/static/index.html`: current UI (screening view)
- `docs/crs-brief.md`: what CRS wants / what the sandbox has

## Commands
```
pip install -r requirements.txt
pytest                                        # 36 offline tests
python -m exchange.demo P01                   # one market session in the terminal
python -m exchange.demo P01 --scenario injection
python -m exchange.demo P03 --max-apr 16 --json
python -m exchange.demo P17 --watchdog             # bureau disagreement flags + what to do
python -m exchange.demo P01 --scenario drift --watchdog --review   # + Claude review (needs ANTHROPIC_API_KEY)
uvicorn app.main:app --reload                 # http://127.0.0.1:8000
```

## Agent interfaces (how to plug in Claude-powered agents)
- Borrower: subclass `RuleBorrower`; implement `decide(rnd, offers, mandate, passport) -> list[Message]`.
  `offers` = `{offer_id: {"lender", "terms", "text", ...}}` (live only). Never reveal `mandate.max_apr` in messages.
- Lender: subclass `RuleLender`; override `respond_to_counter(counter, passport, market) -> Message | list | None`.
  `self.quote` holds the policy range (`floor_apr`, `autopay_discount`, ...). Stay at or above the floor.
- Build agents with the Anthropic SDK (`ANTHROPIC_API_KEY`; model via `CLAUDE_MODEL`, default `claude-sonnet-5-5`).
  Ask the model for structured JSON, parse it into `Message`/`Terms`, and fall back to the rule-based parent on any
  error so the demo never breaks.
- Register new scenarios in `exchange/scenarios.py` (`build()` + `SCENARIOS`) so the API and UI pick them up.

## Conventions
- Python 3, small modules, plain functions; no new heavy dependencies without asking the team.
- Work on branch `decision-agent` (or a feature branch off it) and open PRs to `main`. Pull before you push.
- When you change behaviour, add or update a test in `tests/`.
