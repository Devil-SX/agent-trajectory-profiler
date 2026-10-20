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

## Derived read performance

`read_cache.py` owns bounded, per-revision singleflight caching for derived source
contributions and completed session details. It stores serialized values and
returns independent objects; it is never a canonical store. Keys include owner,
source and authoritative ledger/analysis/source heads. Active or failed jobs
bypass detail caching. Source calculations use a separate two-slot scan bound,
not the overview lock. Cross-source consumption winners are selected globally
before unrelated bodies are discarded; source filtering must never resurrect a
losing duplicate. Task membership, source lines and call IDs use indexes, with
memoized descendant membership and operation-order segments.

The authenticated analysis read returns operation metadata and `body_available`,
without execution text. `operation_read` returns one complete operation pinned to
the displayed `source_revision`; the browser requests it only on expansion. Raw
byte evidence remains a separate bounded operation. Internal analysis workers
continue to consume the complete canonical detail through the same store.

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
and measured capacity planning. A saved analysis stays on screen while a newer
revision is parsed or analyzed: the displayed snapshot is the analysis revision,
not the newest job revision. Its task tree and cost remain readable, and only
ledger records at or below that snapshot's own source-line watermark are
attributed. Records beyond the watermark, or any record after a generation
change, stay excluded and counted instead of clearing retained measurements.
Reanalysis remains an explicit paid action and never hides the previous result.

The domain memoizes at most two compact analytical snapshots in a fixed LRU cache,
keyed by owner (including the global view), filters and committed ledger audit revision.
Account and global views can alternate without evicting each other. A miss evicts
before calculation when both slots are occupied; account/date fan-out cannot grow
the number of cached snapshots. Both slots share the existing calculation lock.
This is a count bound, not a constant-byte or constant-process-memory claim. It retains project, day, task and source summaries, never a
whole-ledger array of event contributions. Session listings use source summaries.
Task attribution requests contributions for one source through the same accounting
calculator, preserving global consumption and interaction deduplication and session
price tiers. Source reads serialize their transient scans rather than multiplying
large identity maps across concurrent jobs.

No expression indexes are added by this cache change. An isolated experiment showed
that an owner/kind/time index can change the existing unordered request-route scan:
for one task with conflicting project references, the selected project changed.
Any future index proposal must explicitly preserve the baseline account primary-key
order and global rowid order, with conflicting-project and tie-order regression tests;
real-corpus output equality alone is insufficient evidence.

`ledger_scan.py` replays SQLite cursors in deterministic event or request-priority
order. One read transaction covers classification, corrections, deduplication,
context and allocation. Decoded rows do not accumulate in a Python list. SQLite
sorts use file-backed temporary storage and a 4 MiB page-cache budget; this budget
does not cap Python maps or SQLite sorter allocations. Python retains classification
routes, deduplication identities, per-session context/previous state, unpaired tools
and output aggregates. Target-source contributions and normalized IR remain sized
by that source. A large source or many unmatched calls still require explicit
capacity measurement; this design does not claim constant process memory.

Usage, price and project-correction commits invalidate the aggregate snapshot,
while raw uploads and request traces do not. Authorization is checked before every
request and is never cached here. Source collection progress is distinct from price
coverage and does not prove alignment between generations. The retired internal
`overview(contributions=True)` interface has no current implementation or caller.

## Model invocation authority

Semantic analysis calls Jindu's authenticated chat-completion route through an independent native machine account. Jindu owns upstream credentials, route policy and the invocation ledger. Trajectory stores only the Jindu API base, route, machine Key and model selection. Supplier-direct and Responses transports have been removed; there is no direct fallback.

Each job, chunk and attempt determines a stable X-Jindu-Call-ID. The stored analysis provenance contains route, call ID, receipt ID, per-request elapsed time and reported usage, including failed bounded repairs. Only received model output that fails structural validation permits one repair with a distinct attempt ID. HTTP errors, disconnects and uncertain outcomes stop the job for reconciliation rather than automatically creating another charge. Existing completed analyses retain their historical provenance.

The current membership wire uses window-local integer indices. The model must
assign each index exactly once; validation maps indices to unchanged canonical
operation IDs. Canonical packing boundaries are retained when migrating an
unfinished v1 checkpoint, and the migration records its original digest and
completed prefix. A private, fsynced call journal records preparation before
dispatch and the received response before decoding. Replaying a journal uses the
saved response, never another upstream request. Source text and model responses
remain outside HTTP errors and public diagnostics.

Before preparing its first call, each analysis durably freezes its complete packed
input beside its checkpoint. This execution artifact binds the exact title, ordered
operation windows, source revision, IR body digest, model configuration and prompt
digest. It is installed without replacement and verified on every resume. New jobs
read raw IR through `SemanticStore.session_record`; mutable display attribution,
task membership and current usage never become their model input. Legacy jobs may
freeze their original display projection only when its full identity exactly
matches the existing checkpoint. A mismatch requires reviewed recovery of the
original input, rather than changing paid window boundaries or request digests.
The source IR remains the content authority; the frozen artifact is the immutable
input of one execution, not another editable IR store.

The domain authorizes at most three continuations of a failed job with confirmed
invalid output. Each continuation preserves job, batch, source and configuration
identity, keeps every measured call, and uses later attempt IDs for unfinished
windows. Uncertain or missing receipts block continuation. The same operation
and eligibility projection serve the workbench and external Agents. Closing the
worker gate parks active analysis at the next durable window boundary after its
current request finishes; reopening the gate continues that same checkpoint
without consuming another failure-recovery authorization.

Lost responses have a separate explicit operator operation. Before authorizing
another attempt, the service uses its own native Jindu read key to verify the
exact call, receipt, account, route, model and terminal uncertain state. The
operator must acknowledge possible duplicate charging. A transaction rechecks
the original job snapshot and persists the verification proof, actor, decision
and continuation generation. The original uncertain record and unknown usage
remain intact. Later continuations inherit only those audited authorizations;
they cannot bypass a different unknown call. This path currently rejects known
provider usage because reconciling that measurement requires a separate policy.

## Analysis workbench and scheduling

The single workbench preserves directory, activity-time, search and analysis-state filters.
Its `analyzed` state requires an actual stored analysis; a measured-only `partial`
session is not an analysis. Display metadata comes from the canonical worker and
bounded migration of old IR. `session_metadata` owns the effective-prompt filter for
both worker metadata and prompt operations: known injected instruction/context records
never supply display names. Without an effective prompt, names use directory and date;
the first-message field remains null. Existing abstracts are reused without a model call.
The v2 metadata index replaces older versions in place, at most 32 IR records or a
16 Mi-character read budget per listing. Each record acquires `BEGIN IMMEDIATE` before
reading and rechecks its index version, so a concurrent parser's newer metadata wins.
Old indexes awaiting migration receive the same conservative display projection on
session and batch reads; this path reads no IR and creates no second stored index.
Raw IR, source offsets, usage and model jobs remain unchanged.
Session ordering uses original activity time, never import time.

Batch and individual submissions share the same owner-bound job queue and stable
mutation receipts. The runtime owns an exclusive coordinator lease and dispatches
independent sessions to a bounded pool. Within a session, model windows remain
sequential so task identities can continue across windows. Successful windows are
fsynced before checkpoint replacement, and execution configuration is pinned.
A standby gate stops new claims while active sessions drain naturally; a second
coordinator cannot steal a live lease. Unknown gateway outcomes require receipt
reconciliation before a fresh paid invocation.

An authenticated parser refresh reads the existing archive without uploading it
again or calling a model. Changed normalized operations invalidate the current
analysis membership while retaining its historical body. Concurrent queued or
running analysis prevents refresh. A later analysis request cannot reuse an old
completed job whose result is stale.

Pi source measurements use the same Domain `events` and `sources` ledger as other
collectors. The native worker exposes normalized recorded fields with original
provider/response and branch identities. `Domain.import_native_measurements`
runs inside the archive/session transaction, verifies owner, revision and original
byte-prefix hash, and persists an idempotent receipt. It exclusively owns that
source's ledger; a statistical producer cannot append a second interpretation.
Provider response identities deduplicate usage across inherited copies. Missing
provider identity stays session-scoped with an explicit gap, and copied text is
never proof of duplicate consumption. User-role messages without explicit origin
remain unknown; available original text still supplies exact character counts.

Daily analysis plans live in `analysis_schedules` and immutable draws in
`analysis_schedule_runs`, owned by the same account and SQLite domain as semantic
jobs. `AnalysisSchedules` reuses `SemanticStore.queue_batch` inside one immediate
transaction: the sampled revisions, draw evidence and stable batch receipt either
all commit or none do. Only `AnalysisRuntime`'s existing gated exclusive lease
invokes periodic ticks; there is no second cron worker or model client. Per-local-day
slots prevent repeated selection after restart and concurrent triggers. The queue's
existing bounded pool and Jindu receipt/checkpoint rules remain authoritative.

Inactivity compares metadata activity with `source_content_activity`, whose clock
advances only when the durable generation/cursor changes. Replay upload timestamps
do not reset it. A legacy writer or unobserved cursor falls back conservatively to
the archive update time. All copies of a native ID inherit its newest observed
activity. Known non-self fork parents and previously attempted native copies are
excluded conservatively; this is not complete shared-prefix reconstruction.
Weights use canonical operation counts after other eligibility filters, cached only
by immutable revision. Image bytes and cached token accounting do not affect weights.
Seeded exponential clocks select without replacement; selected and excluded inputs
are retained per draw. Counts above the configured operation guard are excluded;
the guard is not an estimated bill. Budget/routing decisions reuse the actual
analysis worker and its configured authenticated Jindu route.

A daily run catches up once only for the current local date after the plan was
enabled. Enabling after the configured time begins on the next date; missed disabled
or older dates are not replayed. A daylight-saving fold still has one local-date
slot; a skipped clock time becomes due after the gap. Disabling or archiving a plan
does not cancel already queued or running paid jobs. Failed jobs are never silently
resampled or resumed. Historical study snapshots are unaffected by new draws.

Analysis automation delegation is an explicit owner-controlled ACL keyed by the
real native machine UUID and service client. Provisioning a machine key alone does
not grant a user's resources. The operator must grant the binding through the
registered business interface. Delegated analysis requests provide `resource_owner`;
the authorizer retains the real machine principal for key checks, revocation and
access traces, separately verifies the resource owner's current service authority,
and resolves only an allowed analysis operation. Grants cannot authorize ledger,
prices, collectors, backup or arbitrary account administration. Revoking a grant
rejects the next delegated request. Saving a daily plan persists the authorized
business intent; normal disabling/archival controls its future executions.
