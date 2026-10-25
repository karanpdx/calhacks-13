# Agent chat and lender app: architecture and migration plan

Oct 25, 2026. Baseline inspected: 784114e on main. Current direction: `/phone` is the sole borrower experience and `/lender` is the lender workspace. The standalone borrower dashboard and legacy exchange page have been deleted. Shared application state, role authorization and live updates remain to be implemented.

Cleanup verified: 204 offline tests pass, including old-URL redirects and retained chat/lender assets. Saved-response DOM checks cover Spanish chat through the result, narration, language switching, and lender queue/filter/search/exception review. No negotiation, lender policy or passport code changed.

Subsequent integration through `0396ba8`: the chat now requests the team's `approval=1` flow. The agent recommends an exact offer; the person accepts or declines. Approval/decline preserve EN/ES, finished stream callbacks are detached before later decisions, and red-team evidence keeps its original schema. The combined suite has 225 passing offline tests. Pending sessions are still held in memory; durable recovery below remains planned work.

## Confirmed requirements

- Preserve http://192.168.4.136:8000/phone exactly, with its current appearance and every agent-app feature.
- Preserve chat, suggested replies, mandate confirmation/editing, form alternative, shopping, progress, results and persona support.
- Connect the agent chat and lender workspace to the same application data in real time.
- Keep the borrower flow inside the chat, with concise results and details on request. Do not add another borrower dashboard.
- Lender staff monitor their agent and handle exceptions. Manual offer editing and negotiation are outside the first version.
- Pooled borrowing and low-credit product changes remain future brainstorming work.

No network or port changes are proposed. Code can preserve /phone but cannot prevent a router assigning another IP; retaining .136 across future network changes would require a separate router/device configuration decision.

## Recommendation

Keep one FastAPI deployment with two product entry points. Introduce server-owned applications, persistent state, a search execution service and role-specific snapshots/event streams. Preserve the existing Python agents and deterministic referee.

Two entry points do not require separate backend services or a new front-end framework. Share JavaScript/CSS where useful while giving each app its own navigation and permissions.

## Original baseline architecture audit (historical)

| Source | Current behavior | Consequence |
| --- | --- | --- |
| app/main.py page routes | /phone and /demo serve demo.html; /exchange serves exchange.html; / serves the screening page. | Product roles are mostly modes inside one page; no independent lender app exists. |
| demo.html: CHAT, M, D | Conversation, mandate and completed result live in browser variables. | Refreshes and other devices do not share authoritative state. |
| POST /api/chat/mandate; exchange/intake.py | Client sends its whole conversation; server interprets it without saving it. | No persistent thread, application identity or ownership. |
| demo.html: loadPerson(), loadExchange(), showPlan() | Initialization runs an exchange; Start shopping runs another through GET. | Opening a page can execute checks/search before the user starts shopping. |
| demo.html: phoneStory() | Animates events after the completed result returns. | Progress is replayed rather than observed during execution. |
| GET /api/exchange/{persona}/stream | Builds a new Exchange and request-local queue per connection. | Subscribers/reconnects cannot observe the same run. |
| exchange/referee.py: Exchange | Mandate, offers, keys, events and deal are in one Python object. | No durable identity, multi-view subscription or restart recovery. |
| Exchange.submit()/emit() | Listener receives a message before _apply() changes offers/deal; enforcement follows. | A snapshot built inside the callback can lag its event. |
| /api/pair; shareWithLaptop() | Phone uploads a completed result to one global _PAIR; laptop polls every 700 ms. | Borrowers overwrite one another; restart loses state; browser supplies the result. |
| demo.html: lScene1()–lScene4() | Scripted scenes display one lender for a selected persona. | Useful visual reference, but no queue across applications or organization scope. |
| person.build(ex); hood.build(ex) | Build borrower summaries and audit explanations after completion. | Reuse their formatting/calculations; add projections for stored and running state. |
| Exchange.result() / API serialization | Full result/events include lender books after close. | Each role needs an allowlisted response, including nested event data. |
| Engine ACCEPT | An agent can accept within its mandate and trigger simulated settlement. | Human approval is a separate roadmap feature, not an invisible UI migration change. |

Agent signing keys currently identify agents inside one simulation. They do not authenticate borrowers or lender employees.

## Entry points and experiences

| Route | Experience |
| --- | --- |
| /phone at the exact existing URL | Preserve all agent-app features and appearance. Replace data plumbing behind its UI. |
| /borrower, /exchange and their old static HTML URLs | Compatibility redirects to /phone; preserve language and other query parameters. No standalone borrower pages remain. |
| /lender | Organization-specific application queue, case detail, agent activity and exceptions. |
| /demo | Retain the story/demo during migration for rehearsal and baseline comparison. |
| / | Keep the screening demo initially; default landing-page changes are separate. |

Links identify the same application. Switching views must never start a search; authorization is checked independently of the URL.

The chat is the borrower interface for instructions, progress, results, explanations and next actions. Keep dashboards, savings widgets and extra financial overview panels out of this flow.

The lender queue prioritizes exceptions, active negotiations and recent outcomes. Columns: application ID, requested amount, authorized credit/file signals, stage, current offer, last update and next action. Detail shows the authorized passport, that lender's messages, decision reasons and its own pricing context. Applicants blocked before admission do not appear in lender queues.

## Target data flow

~~~mermaid
flowchart TD
    P["Agent app /phone"] --> C["Authorized commands"]
    L["Lender app /lender"] --> C
    C --> S["Application service and durable jobs"]
    S --> E["Existing agents and deterministic referee"]
    E --> D["Persistent state and ordered events"]
    D --> V["Role-specific snapshots and event feeds"]
    V --> P
    V --> B
    V --> L
~~~

An application is the shared business record. Each search attempt has its own run ID. A persona ID identifies synthetic input data, not an application or account.

### Persistent records

Use Python's standard sqlite3 module behind a repository interface for the first single-host version. Configure a local, non-synced database path outside this OneDrive checkout. Do not keep the live database in Git or on a network share.

- Applications: owner, persona reference, lifecycle status, current run, version and timestamps.
- Chat messages: application, author, content and stable client message ID.
- Mandate versions: normalized fields, confirmation and source message references.
- Runs: application, backend/scenario, data provenance, status and start/end/error details.
- Offers: run, lender organization, versioned terms, lifecycle and defined conditions/expiration.
- Participants: which lender organizations may see each admitted application.
- Events: global ID, application sequence, run, type, actor, schema version and server-owned payload.
- Jobs: run, state, lease, attempt and command idempotency key.
- Exceptions: organization, application, reason, owner and resolution.
- Approvals: reserved for the later approval feature; bind exact offer and mandate versions.

Keep raw CRS data and private lender context outside public projections. Seed fictional identities locally. A real identity provider can replace demo identities without changing ownership rules.

Move to PostgreSQL when measured write concurrency or multiple hosts require it. SQLite's guidance describes these deployment trade-offs [3].

### API contracts

| Method and route | Effect |
| --- | --- |
| POST /api/applications | Create an application; retries use an idempotency key. |
| GET /api/applications | List only the caller's applications. |
| GET /api/applications/{id} | Authorized snapshot, version and event cursor. No search execution. |
| POST /api/applications/{id}/messages | Save a new message and derive reply/mandate from server history. |
| POST /api/applications/{id}/mandate/confirm | Confirm a specific mandate version. |
| POST /api/applications/{id}/runs | Persist/enqueue a search; return 202 and its run ID. |
| GET /api/applications/{id}/events | Subscribe to existing work using SSE. |
| GET /api/lender/applications | Paginated/filterable queue for the authenticated organization. |
| GET /api/lender/events | Organization feed covering its applications. |
| POST /api/lender/applications/{id}/exceptions/{exception_id}/resolve | Authorized structured action and audit outcome. |
| POST /api/applications/{id}/cancel | Request cancellation; enforce before the next action/commit. |

Start requires confirmed instructions. Repeated clicks return the same run; conflicting starts fail explicitly. State changes include an expected version to detect concurrent edits.

### Real-time consistency

Use one SSE connection per page and HTTP requests for commands. SSE supports named events, IDs and reconnection [1]. WebSockets are unnecessary for this version.

Persist state and ordered events before notifying subscribers. Read the snapshot and cursor consistently, then subscribe after that cursor. Replay missed committed events after reconnect; clients deduplicate by ID. Use heartbeats and bounded buffers. Slow clients reconnect/replay instead of growing server memory indefinitely.

Filter both snapshots and replay on the server. Hidden events still advance cursors correctly. The lender queue feed uses a global cursor across applications. A role/lender ID in a query string grants no authorization.

Reading, refreshing or reconnecting never starts a run. Closing a page does not cancel the worker.

### Execution and recovery

Run a service-owned worker through the app lifecycle, independently of SSE response generators. Claim persisted jobs with leases; only one worker owns a run. The database is authoritative; an in-memory notification hub only reduces latency.

Do not hold database transactions while waiting for Claude or CRS. Persist work status, perform the call, validate the output and commit the transition. Retries must not duplicate accepted messages or simulated settlement.

First-version restart behavior must be honest: chat, events, completed results and waiting states survive. Arbitrary continuation of an in-flight Exchange.run() is not yet supported. Expired jobs become interrupted; the person explicitly starts a fresh attempt with a new run ID. Never silently replay model/vendor calls.

Full engine checkpoints, pending-action recovery and signing-key references can follow if seamless continuation becomes necessary. FastAPI background tasks alone are not a durable job queue; its documentation distinguishes basic in-process work from worker systems [2].

### Referee and role boundaries

Keep pricing, mandate checks, watchdog rules and validation in the deterministic engine.

Refactor submit()/emit() to buffer a command's events, apply validation/state/enforcement, then persist consistent state plus ordered events before publication. Preserve watchdog references and ordering. Do not generate snapshots from the current pre-application listener.

Borrowers receive their instructions, offers, progress and safeguards. Lenders receive authorized passports and their own exchanges. Anonymous competing quotes appear only where the protocol permits them; private books stay within the lender organization. Full judge audit remains a separate demo/admin projection.

For the local prototype, use signed demo identity sessions with server-bound roles and organization IDs. Application IDs are not access tokens. Enforce ownership, organization scope and same-origin mutation protection. Real authentication is required before a real pilot.

## File-level changes

| Area | Adjustment |
| --- | --- |
| app/main.py | Keep initialization/static mounting; split page/API routes into modules. |
| app/routes/pages.py | Preserve /phone and /demo; serve /lender; redirect retired borrower page URLs to the chat. |
| app/routes/applications.py, lenders.py, events.py | Commands, authorized reads and subscriptions. |
| app/services/applications.py, runner.py, events.py | Workflow, job ownership and committed publication. |
| app/storage/ | Schema migrations, repository interfaces and transactional persistence. |
| app/auth.py; app/projections/ | Identity context and allowlisted role-specific data. |
| exchange/referee.py | Consistent post-transition event boundary; preserve rules and legacy run adapter. |
| exchange/intake.py | Retain interpretation; service supplies/saves persisted history. |
| exchange/person.py; hood.py | Reuse formatting/calculations; adapt summaries to stored and live state. |
| app/static/demo.html | Preserve phone markup/styles/behaviors while extracting reusable pieces. Keep the story renderer for /demo. |
| app/static/demo.html, lender.html | Chat for borrowers and a separate lender workspace. |
| app/static/chat-access.js and chat-access.css | Shared language/accessibility controls used by the chat and presentation. |
| app/static/lender.js and lender.css | Lender-only operations code and styles. |
| app/static/js/ and css/ | Shared API/event client, formatting and visual tokens; independent page controllers. |
| _PAIR and /api/pair | Temporary old-demo adapter; replace product pairing with authorized application links. |

**Prototype status:** the lender workspace still uses fictional sample cases and in-page exception actions. It is not yet connected to shared application records, durable jobs, role-scoped APIs or live event feeds. The borrower dashboard, its savings milestone and the legacy exchange HTML have been removed.

Do not carry initial loadPerson()/loadExchange() side effects into the new phone shell. Opening a page must not perform checks or shopping.

Track intake model, negotiation model and CRS source separately. A configured key can power chat while scenario=demo still uses rule-based negotiation. Preserve supported modes and disclose backend/fallback truthfully in optional details.

## Implementation sequence and completion gates

1. **Freeze the phone baseline.** Record screenshots and feature inventory from 784114e. Preserve the exact URL and Safari layout.
2. **Add application state and identity checks.** Store conversations and versioned mandates. Gate: refresh resumes the same thread; two borrowers cannot overwrite/read each other's cases.
3. **Separate execution from observation.** Add POST run commands, job ownership and resumable SSE. Gate: chat and lender views observe one run; reconnect neither starts nor cancels it.
4. **Connect the agent chat.** Keep the complete phone flow and accessibility features. Gate: the lender workspace observes chat activity without copying browser-supplied results or repeating the search.
5. **Add lender queue/detail.** Monitor the same runs and resolve authorized exceptions. Gate: concurrent cases appear in the correct organization with isolated transcripts and accurate next actions.
6. **Replace product pairing.** Use authorized application links. Gate: no product view depends on global _PAIR or browser-supplied market results.
7. **Introduce later features separately.** Exact-offer human approval remains the roadmap recommendation; give it a dedicated contract and confirmation UI instead of changing acceptance silently during migration. Summaries and expandable process views use recorded actions, sources and validation results, not claims to expose raw private model reasoning.

Fix the previously reproduced autopay-removal pricing-floor bug separately before expanding live negotiation. Do not hide it inside front-end extraction.

## Verification planned during implementation

Reuse offline API, stream, intake, referee and pricing tests. Retain legacy endpoint coverage until migration completes.

Add meaningful integration coverage for one run observed by chat and lender clients; role isolation including nested events/private books; duplicate commands; concurrent edits; snapshot/stream races; ordered reconnect replay; interrupted jobs and explicit retry; cancellation before commitment; and concurrent lender cases.

Use fake agents and saved CRS samples so these checks never consume paid APIs.

Manually verify Safari parity: exact URL, chat/chips/form alternative, confirmation/editing, keyboard behavior, shopping/progress/results and refresh/network recovery. Check concise chat results, on-demand explanations and paginated lender queues.

No application tests or live model calls were run for this planning task. Findings come from source inspection and repository history.

## Deferred decisions

Lender interaction is settled: monitor agents and handle exceptions. Remaining choices include real authentication provider, later deployment scale and specific structured exception types. They do not require changing the phone experience.

Pooled borrowing needs a separate group/obligation model and explicit member authority. Do not overload application ownership or shared chat access to simulate pooling. Product design remains deferred as requested.

## Technical references

1. [MDN: Using server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events) — IDs, named events and reconnect behavior.
2. [FastAPI: Background tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/) — in-process work and worker-system trade-offs.
3. [SQLite: Appropriate uses](https://www.sqlite.org/whentouse.html) — single-host use and deployment/concurrency limits.

Architecture, file layout and migration gates are recommendations based on this codebase; references describe the underlying technologies.
