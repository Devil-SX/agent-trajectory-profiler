# BatCave Trajectory

Trajectory analyzes Agent usage by project: daily tokens, estimated activity time, API-equivalent cost and evidence of slow or failed tools. Human users and Agents use the same authenticated HTTP service.

Open `/trajectory/` on your BatCave host. The brand and main tabs remain visible while scrolling. Each tab shows one view, with its controls inside that view. Task Analysis loads its session list only when opened. Its search, filters and selection controls live in the left session sidebar. Expand real working-directory branches to browse sessions; full-scope directory counts include results beyond the current page. Use a directory’s filter action or load another page to retrieve its remaining sessions. Entries show titles, activity times and accessible compact agent/status icons. Missing directories and unknown agent lineage remain explicit, and searches temporarily expand matching branches. Overview, human investment, daily trends and detail views preserve independent project/date conditions, reusing the same summary response when their dates match. Collection coverage has an independent checkpoint reader and refresh; opening it does not calculate usage or costs. It has no ineffective project/date controls. Research has its own filters. Browser Back restores tab navigation; returning to a loaded scope reuses its last successful statistics snapshot. Loading skeletons, a quiet progress animation and inline retry feedback keep the current context visible; reduced-motion preferences are respected. Use the persistent “Only analyzed” status filter to find stored results, or filter by source directory and sort by original session activity. Select a session in Task Analysis to inspect an expandable task tree, non-contiguous execution segments, a cost flamegraph and original evidence. Task names and groupings can be revised without changing original records. The dashboard also shows collection coverage, daily token and activity charts, project comparisons, partial API cost estimates, exact detail tables and anomalies. Human investment cards and daily charts count only proven human inputs. Input characters mean non-whitespace Unicode characters in submitted text, including pasted or reused text, not tokens or actual typed keystrokes. Missing text and unknown origins remain explicit gaps; these counts do not estimate actual human working time. Date filters use Shanghai time. Project filtering applies to project summaries and evidence; daily charts require all projects because the HTTP overview does not publish per-project daily aggregates. Names come from the live Ops service catalogue and icons reuse the shared Ops assets. Unknown values remain unknown. Activity estimates do not represent human working hours; API-equivalent estimates do not represent a subscription bill.

Usage overview, human investment, daily trends and statistics details read one persistent account/date snapshot. New uploads mark the snapshot stale and do not make reading wait for recalculation. Statistics refresh every day at **01:00 Asia/Shanghai**. Select **更新统计** for an authenticated background refresh; the last successful charts stay readable while it runs or if it fails. The page shows the last successful time, stale state and failure feedback. The first read of an unbuilt date range shows a building state instead of zero counters. At most 12 date scopes per account are retained, including the full range. Project selection uses published project summaries; it does not start another calculation. Collection progress, analysis-job status and original evidence remain current rather than following this daily schedule. This schedule does not enable paid random analysis.

Session lists contain navigation metadata; read the selected analysis or overview for token, human-input and cost metrics. Pagination stays on one metadata snapshot until refreshed; if a snapshot expires, the workbench reloads its first page. Task Analysis keeps a visible search field and places additional filters in a compact disclosure, with removable active-filter chips. Filtering and sorting happen before server pagination. Select a task to see its metrics and descendants in the compact context strip; choose “View session totals” to return to whole-session metrics. Detailed counters remain available below the visualization. Background batch progress appears in a compact status drawer and does not push results down the page. Task selection and tree expansion survive switching among the three task views.

Session names use the first effective original prompt, excluding injected agent instructions. Sessions without an effective prompt use their directory and date. Sources without captured request measurements show unknown human-interaction and input-character counts; token measurements alone cannot establish zero interactions.

Sparkstead uploads supported log metadata through the open collector protocol. In Sparkstead Settings > Trajectory, enable background collection and configure the batch HTTP URL, origin-bound credential file and remote sync toggle. Collection runs in a worker and persists checkpoints with pending batches. The historical metadata-only stream does not contain enough content for semantic segmentation. A separately authorized source synchronizer can supply execution records for remote analysis while preserving the original collector progress. Historical content gaps remain visible. Sparkstead has no local analysis interface.

Any conforming collector may upload. Discover current endpoints, scopes and input schemas through `/trajectory/help`; obtain the protocol JSON Schema at `/trajectory/protocol`. Each collector requires an enabled native machine account and an API Key with the upload scope, bound to its authenticated owner. Revoked keys or disabled clients are rejected on subsequent requests.

Requests receive a request ID. Bounded request traces distinguish verified accounts and machines, scope denials, unrecognized credentials, and public discovery or health access. Administrators discover the trace reader through authenticated Help. Trace metadata excludes query values, bodies and credentials.

The service provides account-scoped project corrections and dated prices through the same HTTP API. Operators may read platform summaries with a separate read-all grant. Prices are not invented when source metadata is missing.

Developer architecture and protocol details are in [ARCHITECTURE.md](ARCHITECTURE.md) and [docs/PROTOCOL.md](docs/PROTOCOL.md). Current production maintenance instructions are independently published and discovered through BatCave Ops Help. Installation, release and runtime credentials are administered by BatCave; they are not user-facing CLI business interfaces.

The former local profiler, its database-query CLI and its React dashboard are retired from the current source. Their history remains in Git; historical user databases and source logs are preserved. Current release status is reported by authenticated service discovery rather than this document.

Developer validation and remote-runner prerequisites are described in [ARCHITECTURE.md](ARCHITECTURE.md#development-validation).

Model-based task analysis uses the BatCave Jindu gateway. Administrators configure an independent native machine account with the selected route and `jindu.invoke`/`jindu.read`; the service holds no upstream supplier credential. Discover allowed routes through authenticated Jindu Help. Analysis provenance records Jindu call/receipt IDs, per-request duration and provider-reported usage.

Batch analysis is available in the workbench and through the same authenticated
HTTP interface discovered in Help. Select sessions and a bounded concurrency;
progress, errors, model usage and elapsed time remain available after reload.
The server configuration selects the Jindu model and reasoning effort. Recorded
provenance identifies the configuration actually used by each analysis.

Failed analyses with confirmed invalid model output can continue from saved
windows in the workbench. The same authenticated resume operation appears in
Help. Continuation keeps the original job and batch, reuses completed windows,
and retains unsuccessful call usage. Uncertain calls remain blocked for receipt
reconciliation. Refreshing the page does not restart paid analysis.

If a verified terminal call has lost its response, an operator can make a
separate explicit decision through the Help-discovered lost-window operation.
This can incur an additional charge for that window. The service preserves the
original unknown usage and the recorded decision; ordinary recovery never makes
this decision automatically.

Saved analyses retain their referenced parsed input when a later append is parsed.
Old inputs once referenced by a saved analysis or unfinished job move into immutable
history; the current input has one canonical row. Unreferenced intermediate parses
are replaced without making history copies. Retained audit snapshots are not
subject to automatic garbage collection. Historical task trees and original evidence remain readable without
another model call. Their execution costs stay unknown when no snapshot-bound
ledger exists; recorded analysis-call costs remain available. `source_pending`
means the latest received archive still awaits parsing, independently of whether
the displayed analysis is historical.

The authenticated analysis and operation-evidence GET endpoints accept an optional
`source_revision` query parameter. Pin it to the detail response's `source_revision`
to read the same account-owned snapshot after an asynchronous parse. Omitting it
selects an active analysis job's input, then the saved analysis input, then the
latest parsed content. Help describes the same shared interface. Runtime analysis
always pins its own job input. Changing parser operations at an already referenced
raw revision requires an explicit parser migration and is rejected by normal refresh.

These fields are additive for the 3.3.1 UI. Older UIs without revision pins select
whatever snapshot is current for their request and cannot guarantee the original
rendered revision across navigation. A 3.3.1 backend does not resolve retained IR
history; after history is populated, rollback must preserve that table and restore
a history-aware reader before claiming historical-result availability. Legacy HTTP
reads and statistical ingestion remain schema-compatible, but an old backend's parse
and analysis worker gates must remain closed; its writer does not preserve history.

Session analysis responses contain operation metadata, usage and source locations without execution bodies. Expanding execution evidence loads one operation through the authenticated operation reader, pinned to the displayed source revision. Original raw evidence remains a separate bounded read. Discover both operations and permissions through current HTTP Help.

### Query saved task phases

Discover `task_query` through authenticated Help. `GET /trajectory/api/tasks`
returns saved task titles, hierarchy, session identity and source/analysis
revisions without execution text, ledger scans or model calls. Filter by
`batch_id`, `session_id`, `cwd` (including subdirectories), `q` (title, ID or
ancestor title) and `depth` (`0` session root, `1` main phases). Use `limit`
(1–500, default 100) and the returned `next_cursor`; restart pagination if the
query revision changes. A batch whose saved source was replaced reports an
explicit skipped session. Direct operation counts are structure counts, not
fees or elapsed time; use `analysis_read` for measured task costs.

Research statistics are available in the **研究统计** dashboard tab. See [stage study methodology and API semantics](docs/STAGE-STUDIES.md) for hierarchy, mixed labels, uncertainty and explicit measurement gaps. Reading the tab does not start model calls.

### Daily weighted session analysis

The workbench's background analysis controls support account-owned daily plans.
Set explicit directory subtrees, IANA timezone and local time, number of sessions,
quiet/recent windows and a maximum operation count. Defaults are 01:00 in
Asia/Shanghai, three sessions, a 24-hour quiet period and a 30-day recent window.
Plans use weighted random sampling without replacement, proportional to normalized
operation count. They exclude known forks, active/updated records, incomplete sources
and previously attempted native copies. This conservative policy can exclude a
new revision of an already attempted native session; explicit ordinary analysis
remains available after review. A quiet window estimates inactivity and cannot
prove that a frontend process has closed. No model is called by previews.

Discover plan CRUD, candidate previews and manual draws through authenticated
Help. Save enables or disables the plan using its expected revision; archival
preserves all draw and paid-job receipts. Manual submission and daily execution
share the same authenticated business rules, queue and Jindu route. Each draw
records the seed, algorithm, candidate/exclusion snapshot, immutable input revisions
and batch status. Candidates below the requested number are not duplicated to fill
it. Failed or uncertain paid requests require existing receipt review, never blind
retry. An operation-count guard limits input size, not the actual dollar bill.
