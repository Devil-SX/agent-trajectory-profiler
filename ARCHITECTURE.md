# BatCave Trajectory architecture

## Product boundaries

Sparkstead is a protocol producer. Its worker reads bounded log slices, extracts source fields and explicit target identifiers, and transactionally saves checkpoints with an outbox. A durable server receipt acknowledges a batch. No analysis dashboard, price calculation or SQL query IPC exists in Sparkstead.

BatCave Trajectory is the analysis authority. `trajectory/product/contracts.py` defines the wire schema. `server.py` contains one operation registry from which authenticated routes and live Help are generated. `domain.py` owns the SQLite database and all writes, idempotent receipts, owner bindings, corrections, prices and analytical semantics. `projects.py` interprets the uploaded identifiers conservatively. The browser renders metrics returned by the domain without computing an independent cost model.

## Authentication and isolation

Native Identity determines whether accounts and service clients remain eligible on each request. Shared `batcave_http` validates the registered API Key and its scope. Uploads require a native machine client. An authenticated operator binds a collector to its owner. Owners read and correct only their own data; platform observers require read-all scope. Browser requests use the authenticated ingress and an origin check for writes.

Each record has a physical source ID and event ID. Mutation IDs deduplicate delivery, while consumption IDs deduplicate replayed consumption. Those identities serve different roles and must never be conflated. Missing counters, timestamps, models and prices remain explicit gaps. Tool duration requires matching start/end evidence; an unfinished tool is a symptom, not proof of a particular failure cause.

## Durability and deployment

The domain commits events, revision progress, audit metadata and receipts atomically with SQLite synchronous FULL. The producer does not advance a checkpoint independently of its outbox. Upload retries preserve the same mutation ID and body. A changed body under that ID is rejected. Online database backup uses the domain's SQLite Backup API.

Release candidates are built and tested on batcave-wsl in isolated databases and ports. Existing production services remain online. Installation and native-account changes use the remote deployment lock and recheck active releases and maintenance barriers. Public routing uses authenticated BatCave ingress; current maintenance instructions are published independently of repository worktrees.

## Legacy retirement

The current wheel includes only the `trajectory` package marker and `trajectory.product`. Legacy local CLI, database query API, frontend and native parser are excluded from installation. The old implementation has been removed from current source; its history remains available in Git. Current tests are `tests/product`, client tests where present and the browser scripts in `tests/browser`. No old namespace is needed to collect production tests. User databases are migrated through SQLite Backup API, never by copying an active DB/WAL pair.


## Unified analysis and presentation

The remote domain remains the authority for operation identity, durable source revisions, real usage and human-origin metrics. Agent-session is consumed through a pinned worker adapter; parser-specific source handling must not leak into the browser. Semantic segmentation produces task membership and hierarchy over canonical operations. AgentPProf aggregates supplied metrics into profile paths; it does not replace missing counters with estimated billable usage.

`dashboard.html` is the only installed web entry. Its authenticated API views share project/date filters. Task trees, operation-order timelines and metric-width flamegraphs are different views of the same analysis. Original operation evidence remains accessible. Mutation IDs and analysis revisions guard task-name, merge and split edits against replay and stale writes. Analysis jobs are asynchronous and display incomplete and failed states explicitly.

Automatic collectors and Agent-invoked synchronization must use one source identity and durable checkpoint/outbox chain. Their transports may differ, but source revision and consumption deduplication remain shared; replacing the parser must not reset delivery state or duplicate existing usage. Old metadata-only input cannot produce semantic task labels without original execution evidence.

## Development validation

Current Python requires 3.12 or newer; the wheel contains only the product packages declared in pyproject.toml. Current browser assertions are executable scripts under `tests/browser`, with dependencies isolated there. CI requires a remote isolated BatCave runner and uses disposable directories under `/home/saveer/BatCave/tests`, with no production database mounted. Missing runtime dependencies or test runners are explicit failures.

The retirement audit in `docs/LEGACY-RETIREMENT-AUDIT.md` records the old dependency closure. It is migration evidence, not a second operations guide. Historical benchmark documents retain their original source/date and do not certify the new pipeline.

The optional GitHub workflow is manual (`workflow_dispatch`) and requires a separately registered self-hosted runner with labels `linux` and `batcave-test`. Set repository variable `BATCAVE_HTTP_TEST_PYZ` to a readable immutable shared HTTP artifact. The workflow reuses this artifact through `PYTHONPATH`, without vendoring its source. Runner registration and a successful CI run are separate from SSH-based remote acceptance; neither is presumed by this source configuration.

## Dependency ownership

Agent-session 0.5.17 is a pinned Rust crate in `native/session-worker`, with its
Cargo.lock tracked. AgentPProf is built from immutable commit
`60cc321ceb4b677fec1a69df6ec055a456b75675` by `scripts/native/build-workers.sh`.
The component manifest pins output hashes; the installer verifies binaries and
licenses before copying them into the release. Neither dependency is a mutable
submodule or a runtime checkout of upstream main. The Python service calls the
worker's versioned JSONL protocol and the profiler CLI, keeping dependency schemas
behind adapters. Upgrades require fixture and real-source acceptance.

`semantic.py` stores source archives, normalized snapshots, job state and task
membership in the same domain SQLite database. It never owns a second measured
ledger. The background runtime uses a cross-process lease and an explicit standby
gate during warm deployment. Model output is cached per source/prompt/model
revision so a profiler failure can be retried without charging the model again.
The current parser rebuilds a changed complete snapshot; it does not claim an
incremental parse algorithm. Large histories therefore require bounded delivery
and measured capacity planning.

The domain memoizes one analytical snapshot by owner, filters and committed
ledger audit revision. Public summaries and semantic attribution share this
calculation; concurrent callers coalesce. Usage, price and project-correction
commits invalidate it, while raw uploads and request traces do not. Authorization
is checked before every request and is never cached here. Source collection
progress is distinct from price coverage and does not prove cross-generation
alignment with separately delivered source bytes.
