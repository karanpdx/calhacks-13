# Cal Hacks 13.0 project (Karan + Mohammed + Nick)

Credit-file trust agent built on the CRS Credit API sandbox. Working notes live in `crs/`.

- `app/` - FastAPI demo + one static page (`app/static/index.html`). See "Run the demo" below.
- `agent/` - screening agent: staged CRS checks, rule-based decision, Claude-written explanation. Try `python -m agent.screen --all`.
- `docs/crs-brief.md` - what CRS wants, what they gave us, and directions we could take.
- `crs/` - Python client for the CRS sandbox, OpenAPI spec, and saved sample responses (`crs/samples/`).
- Mock data: the sample responses are fictional test personas (P03, P05, P12, P13, P17) from CRS's sandbox.
- NEVER commit the sandbox username/password or the Postman collection (it has the login embedded). Get your own from the CRS portal.

## Run the demo

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload          # open http://127.0.0.1:8000
pytest                                  # offline API + explainer tests (samples only)
```

- Default source is the saved samples in `crs/samples` (works offline). Live CRS sandbox: set `CRS_USER` and `CRS_PASS`
  (and keep the Postman collection next to `crs/crs_client.py`), then tick "Live CRS sandbox" in the page or call
  `/api/decide/P13?live=1`. Any live error falls back to samples and the response says so (`live_note`). Credentials are
  read from the environment only; they are never logged or returned.
- Endpoints: `GET /api/personas`, `GET /api/decide/{P01..P20}[?live=1]`, `GET /api/scorecard`.
- Explanations come from templates (`agent/explain.py`). Optional Claude wording only if you set both
  `EXPLAIN_BACKEND=claude` and `ANTHROPIC_API_KEY` (paid API; off by default, never used in tests).
- Click "Side by side" in the page: P13 has a clean 640 score but FraudFinder 88 and ID codes 2201/2202, so a score-only
  check approves it and the agent holds it. All personas are CRS sandbox test data (fictional).
