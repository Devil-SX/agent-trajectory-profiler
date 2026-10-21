# Persistent statistics snapshots

## Reads and updates

`GET /api/overview?since=YYYY-MM-DD&until=YYYY-MM-DD` requires current `read`
authorization. It returns the most recent successful canonical statistics payload
plus `statistics_snapshot`. Empty date bounds mean the full account range. The
privileged platform counterpart requires `read_all`. Authentication and account
isolation run on every request; responses are `private, no-store` HTTP responses.
Persistent server snapshots are not browser or proxy authorization caches.

`statistics_snapshot.available=false` means no successful publication exists.
Consumers must show building/not-ready/error feedback and must not manufacture
empty arrays or zero resource counters. `available=true` retains the established
projects, daily, pricing, coverage and anomaly payload. Its `generated_at`, opaque
`source_watermark`, `source_observed_at` and `published_at` refer to one calculation.
`current_watermark` and `stale` report that newer ledger activity may exist, without
starting another calculation. Watermarks are owner/algorithm-bound hashes rather
than exposing the shared audit sequence. `age_seconds` measures successful-result
age, not source completeness. Stale is not a failure, and ready is not proof that
a producer has uploaded everything.

`POST /api/statistics/refresh` requires `configure` and `read`; the platform
counterpart requires `configure` and `read_all`. Supply a stable `mutation_id` and
the exact date bounds. Replays return the durable original receipt. Uncertain
responses must be retried with that same ID and payload. Concurrent distinct
requests for the same owner/date/algorithm coalesce onto one active job. A known
failed job can be retried deliberately with a new mutation. Updates never call a
model. Discover the current schemas and effects through authenticated Help.

## Persistent schedule and execution

The existing sole coordinator checks schedules every 30 seconds. Registered
scopes refresh once per local date at or after 01:00 Asia/Shanghai, with a durable
`daily:YYYY-MM-DD` receipt. An already queued/running build covers that daily slot;
it does not create a second build. Downtime is recovered on the next coordinator
check, rather than replaying every missed historical day. Busy analysis may delay
execution beyond 01:00: a paid window completes and commits before statistics
runs. A single builder uses the existing pool and lease, without paid analysis
futures concurrently executing. After completion or failure, a durable 30-second
cooldown allows normal analysis dispatch before another statistics build starts.
The builder also occupies one slot in the existing two-slot ledger scan budget
shared with cold source-contribution reads, limiting concurrent heavy HTTP and
background scans. Cached snapshot reads do not acquire that budget. The advertised
next run is the next scheduled slot, not a completion promise.

Each job captures actual requesting account, Key and native client metadata.
Stored authority is rechecked before calculation and before publication using the
shared live Identity/Key registry reader. Revocation fails the refresh; successful
old results remain available only to currently authorized readers. Automatic jobs
retain the registered scope's actual requesting authority. Updating a scope through
a manual request renews that authority. A disabled creator must authorize a new
manual update before its automatic jobs can succeed again.

Scope keys include resource owner, exact date bounds and algorithm schema.
Twelve scopes per owner are bounded, reserving capacity for the full range;
extra ranges are rejected explicitly. Arbitrary dates are not reconstructed from
daily sums because that could change interval, deduplication or pricing semantics.
Project-only presentation filters existing project summaries. It cannot invent
per-project daily totals. No unbounded query cache or old synchronous GET fallback
remains. The builder uses the existing canonical global attribution and preserves
same-native/fork context, missing measurements, costs and source winner rules.

## Atomicity and recovery

The canonical ledger watermark and entire payload are calculated in one SQLite
read transaction. New ingest can proceed in WAL while the builder reads that
snapshot. Only the final payload/job completion publication uses a short write
transaction. A restart requeues interrupted running jobs under the exclusive
coordinator lease; attempt guards prevent an obsolete builder publishing after
recovery. Successful bodies survive service restarts and deployment because they
reside in the Domain database and its normal online backups. Schema/algorithm
versions do not silently read retired snapshot bodies.

First reads queue initial work but return promptly. Updating reads keep serving the
old successful body. Failures preserve that body and expose only an error type,
not source contents. The browser polls active work only in a statistics tab,
retains project/date choices, and renders all totals and breakdowns from the same
publication. It does not combine fresh counters with stale breakdowns.

## Other read boundaries

Collection checkpoints, live paid-job progress, account/Key checks and original
revision-pinned evidence remain live. Completed analysis details already use bounded
per-revision caching; their large first contribution calculation is a separate
optimization opportunity, not silently made daily. Research study summaries remain
independent immutable snapshot readers with their current filters and CSV numeric
precision. Statistics snapshots do not change study data or enable random paid
analysis plans. Native sampling schedules and statistics refreshes use distinct
job kinds and receipts even when both have a 01:00 slot.
