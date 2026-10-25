# Phase 2: language and accessibility

Plan before implementation, 2026-10-25.

**Product update:** the standalone borrower dashboard and old exchange HTML were subsequently removed. Language, accessibility, Spanish intake and narration remain in the agent chat at `/phone` and the `/demo` presentation. Old borrower page URLs redirect to `/phone`. Historical checks below describe the Phase 2 implementation before that cleanup.

1. Centralize borrower copy and EN/ES formatting in `exchange/i18n.py`. Localize `person.build(ex, lang)` without changing its numeric contract or eligibility calculations. Keep proper lender/bureau names and protocol identifiers unchanged.
2. Add validated language selection to the exchange response, stream and chat intake. Extend the offline parser for common Spanish amount, payment, term, fee and autopay phrases; preserve existing English behavior.
3. Localize both existing borrower pages, including chat, preferences, progress, result and errors. Keep `/phone`, `/demo` and `/static/exchange.html`. Use the same catalog in the browser via a small catalog endpoint. Changing language must not start another market run.
4. Default to plain terms, offer accessible term explanations, announce concise progress/result updates, support keyboard interaction and focus, 200% text, reduced motion and browser speech synthesis. Include machine-assisted translation and simulated-action labels in both languages.
5. Run offline tests for catalog parity, English regression, Spanish personas P01/P04/P05/P13/P17, intake, API/stream and page availability. Record one decision in `docs/decisions/LOG.md` after checks pass.

Raw signed agent messages remain source records. Borrower presentation uses localized summaries rather than rewriting those records. Negotiation, lender policies and passport logic are outside this change.

## Implementation and checks

- Implemented the shared catalog, request-local server formatting, `lang` on batch/stream/chat, Spanish fallback intake, borrower controls, glossary, browser narration and accessibility styles. Original agent messages are available in labeled, collapsed source disclosures.
- Full offline Python suite: **201 passed** with `py -m pytest -q`. A local test package marker and pytest paths prevent an unrelated installed `tests` package from shadowing the repo's tests. No test used live CRS or a paid model.
- Saved-response DOM checks passed for the exchange result, EN/ES switching without another request, term expansion, phone chat with Enter → focused confirmation → result, Spanish narration and stop, reduced motion, and `/demo` startup. FastAPI route checks returned 200 for `/demo`, `/phone`, `/exchange` and `/static/exchange.html`.
- Reviewed core light/dark text pairs against the [W3C contrast guidance](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum): measured ratios range from **5.41:1 to 14.30:1**. Font sizes use rem units, rows wrap, and the phone's header/composer reserve layout space for larger text. This is not a complete WCAG conformance audit.
- Real VoiceOver/NVDA behavior, Safari at 200% text, viewport/keyboard interactions, and installed speech voices still require a device check. Offline DOM checks do not measure layout or assistive technology. The [W3C resize requirement](https://www.w3.org/WAI/WCAG21/Understanding/resize-text) is no loss of content or function at 200%.

One decision-log entry was added. Sources: current changes and session, recent local Git history; the decision inbox contained only its README and no relevant teammate excerpts.
