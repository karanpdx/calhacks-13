# Cal Hacks 13.0 project (Karan + Mohammed + Nick)

Credit-file trust agent built on the CRS Credit API sandbox. Working notes live in `crs/`.

- `agent/` - screening agent: staged CRS checks, rule-based decision, Claude-written explanation. Try `python -m agent.screen --all`.
- `docs/crs-brief.md` - what CRS wants, what they gave us, and directions we could take.
- `crs/` - Python client for the CRS sandbox, OpenAPI spec, and saved sample responses (`crs/samples/`).
- Mock data: the sample responses are fictional test personas (P03, P05, P12, P13, P17) from CRS's sandbox.
- NEVER commit the sandbox username/password or the Postman collection (it has the login embedded). Get your own from the CRS portal.
