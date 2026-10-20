# Read paths and measurement boundaries

## Session directory

The session reader returns navigation metadata, analysis state, source collection
status and request-measurement availability. It declares `metrics_included=false`;
it does not return resource metrics. Read the selected session analysis or the
account overview for authoritative measurements. This is a breaking change from
the previous list response; there is no legacy heavy-list switch.

The source directory reads indexed source identities and the account's request
routing context through `LedgerScan`. It reuses the existing conservative project
classifier and corrections. It does not replay usage winners, price records or
reconstruct tool durations. An index covers the narrow `semantic_sessions` display
projection, keeping large IR bodies out of this read. The source representative is
navigation metadata, not a resource contribution or a claim that the whole session
belongs to one project. Detailed attribution remains in the existing domain.

Account authorization precedes all reads. A single SQLite read transaction loads
compact source/display state. Directory, date, search, analysis-state and ordering
conditions are applied before paging. Counts and directory/project facets describe
the same compact read scope rather than a separate usage replay.

A paginated result pins its complete filtered metadata set in the existing bounded
read cache. The opaque cursor is bound to the account, complete filter scope and
page size. New uploads cannot shift rows across pages. A fresh first page sees
current state. Eviction or a service restart makes an old cursor unavailable;
the API returns `session_cursor_expired` and the workbench refreshes its first
page. The cache is bounded to 16 MiB and eight snapshots. A single oversized
paginated scope must be narrowed; it cannot silently return an unusable cursor.
No cursor writes a domain table or creates an Agent session.

Metadata migrations do not run inside GET. The existing coordinator lease performs
bounded migration when idle, checking at most once every five seconds. Each pass
retains the existing 32-record/16-Mi-character budget and transactional parser
recheck. Missing display metadata has a conservative name until that migration
or the normal parser supplies it.

## Collection coverage

The separate account-scoped source-coverage reader reports checkpoints, parse
errors, unknown events and missing timestamps. It does not calculate costs,
usage deduplication or task attribution. The coverage tab loads this reader only
when opened and preserves its own refresh/error state. Ledger deduplication
statistics remain in the account overview, rather than being duplicated in this
checkpoint interface. Source progress cannot prove that a producer's local queue
is empty.

## Remaining reads

The four usage/statistics tabs share the existing account/date overview. An
uncached overview still calculates global winner selection, provenance, prices
and active intervals. Neither a cached tab switch nor the separate checkpoint
reader proves that a fresh overview is fast. Project-only presentation uses the
published project summaries; per-project daily aggregates are not invented.

The selected analysis still uses globally authoritative contributions, including
same-native-session and fork dependencies, to avoid changing deduplication or
pricing merely because the list was paged. Event-only session details explicitly
load those contributions instead of inheriting counters from the directory.
Operation bodies and original raw evidence remain authenticated, revision-pinned
reads. Some paths resolve a complete IR before projecting one operation; this is
a retained optimization opportunity, not an N+1 fetch hidden inside the list.

Research uses its independent study readers and requests stage rows only when
expanded. Its filtered summaries and CSV preserve the snapshot's existing unknown
values, attribution and uncertainty restrictions. Reading them does not call a
model. Full study calculations and immutable snapshots are unchanged here.

## Timing evidence

Measure click-to-real-content separately from HTTP waiting, download and browser
rendering. Record response bytes and item counts. A fresh browser context does not
establish cold database or filesystem caches; do not clear production caches or
restart services to manufacture that condition. Same-page tab revisits may use
in-page data and issue no HTTP request.

Compare baseline and candidate on the same isolated durable backup, machine and
sample in alternating order. Report profiler instrumentation overhead, unrelated
load, process-cache state and uncontrolled filesystem caches. Profiling a copied
immutable backup is distinct from production HTTP timing; neither should be
presented as the other. Keep raw business payloads and private backup manifests
outside the repository.
