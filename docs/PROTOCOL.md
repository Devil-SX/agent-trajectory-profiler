# Trajectory HTTP protocol

The runtime `/trajectory/protocol` endpoint publishes the JSON Schema generated from `trajectory/product/contracts.py`. That module is the authoritative wire contract. `/trajectory/help` publishes the current operation registry and required scopes.

A producer reads its source logs, extracts supported fields, and assigns stable source and event IDs. Sparkstead is the concrete producer in this workspace. Producers do not calculate cost or expose analysis UI. Project attribution, dated pricing, activity estimates and anomaly interpretation belong to the remote service.

Send `trajectory-batch/1` batches to `POST /trajectory/api/batches` with a native machine account's scoped API Key. Bind the collector to an authenticated owner before uploading. Source revisions strictly increase. `replace` replaces the physical source's projection after a rewrite or parser migration. Persist the checkpoint and pending batch in one local transaction. Retrying a batch uses the same mutation ID and exact body. A conflicting body under the same mutation ID is rejected.

The server responds with `mutation_id`, `durable: true` and a receipt timestamp only after the domain transaction commits. The producer clears its outbox only after validating that receipt. A network failure leaves the batch pending. Account, service-client and key revocation are checked on each request.

Missing timestamps, models, prices and counters remain unknown. Explicit target identifiers and the repository name may be transmitted as attribution evidence. Prompts, tool arguments, raw outputs, absolute local paths, code and credentials are excluded from measured-event record bodies. Producers may report parse failures and unsupported events without transporting their raw contents.

Sparkstead runs collection in a resource-limited worker. Each read slice is at most 512 KiB. Its pending outbox is bounded at 32 MiB; collection stops advancing when the outbox fills. HTTP synchronization uses a timeout and exponential backoff. Diagnostic logs rotate at 1 MiB with three retained files. Remote synchronization is disabled until configured. Settings may enable collection, enable synchronization, set the batch URL, credential file, source home directories and scan interval.

The credential file stores `origin` and `api_key`. Changing the server origin requires matching credentials; credentials are never forwarded during redirects. Measured-event collection retains its original local logs. The separately configured content synchronization described below uploads raw source records for semantic analysis; source records can contain prompts, code, tool outputs and sensitive text. Credentials authenticate this transfer and are never inserted into its payload by the client.

## API equivalent reference cost

`Price` accepts audited account-scoped `effective_historical` rates or
`current_reference` rates. Current references require timezone-aware `verified_at`
and revalue older usage using the verified rate; `effective_from` is not a claim
that this reference was historically charged. Optional `long_context_threshold`
and `long_context` rates must be supplied together. Standard rates are the only
supported tier. Request input length or the highest observed session input length
selects the context tier. Incomplete session histories can understate this tier.

Overview buckets return nullable `estimated_usd` for complete estimates,
`known_subtotal_usd` for known cost components, `priced_calls`, `unpriced_calls`,
`cost_status` and `unknown_reason_counts`. Missing paid counters never become zero.
The subtotal excludes missing components and must not be presented as a full bill.
Overview `pricing.prices` includes rate provenance and verification time.

`input_includes_cache` describes inclusion of cached reads. The additional nullable
`input_includes_cache_write` describes inclusion of cache writes. Native Codex
usage input totals include both categories; Claude input counters are separate.
Ordinary input equals total input minus included cached reads and cache writes.
Missing paid writes in an unsplit total input make its ordinary-input component
unknown. A positive write count with unknown inclusion semantics leaves that input
component unknown. Zero writes do not require an inclusion assumption.

Source: [OpenAI prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching),
verified 2026-10-12. Reference estimates exclude actual subscription bills,
region adjustments, discounts and unrecorded service tiers.

## Recorded human input

Only request records may provide `input_origin` (`human`, `agent`, `system`,
`unknown`), `input_chars` or `interaction_id`. Missing origin remains unknown;
a request is not automatically evidence of human input. Character counts use
non-whitespace Unicode code points from textual input, without transmitting the
text. Images and other attachments have no inferred character count.

Project, daily and task aggregates include `human_interactions`,
`human_input_chars`, `missing_human_input_chars`, `unknown_origin_interactions`,
`agent_interactions` and `system_interactions`. A human request with missing text
count contributes one interaction and one missing-count record. Explicit zero
characters are known zero. Human-input totals measure recorded submissions and
text, and do not estimate elapsed human work time. Date filters follow the same
Asia/Shanghai calendar as usage metrics; undated input remains in the unknown day.

`interaction_id` is a digest of provider message identity and revision, never the
message body. Explicit human originals take precedence over inherited system or
Agent copies sharing an identity. A new edit revision denotes a new submission.
The server deduplicates request identities per account and ecosystem separately
from usage consumption identities. If the producer lacks a reliable provider
identity, IDs are deduplicated within collector and source only; cross-source
copies may remain and are not claimed as distinct verified human submissions.
Stable event IDs and source replacement retain counts across retries and replays.
Historical records need producer replay with the new fields before origin and
character coverage can become complete.

## Source content and shared synchronization

`trajectory-source-chunk/1` sends original UTF-8 JSONL bytes in bounded base64 ranges
through authenticated `POST /trajectory/api/source-chunks`. Its authoritative
schema is `SourceChunk`; live Help also advertises progress and analysis routes.
A receipt means the exact bytes, digest, generation and next offset were committed
atomically. It does not mean parsing or semantic analysis has completed. Progress
is readable only by the registered machine bound to that collector.

`tools/trajectory_source_sync.py` is the single source-content synchronizer for
manual Agent calls and automatic scheduling. Both use the same private config,
SQLite state and OS lock. A second caller returns without advancing state while
the first holds the lock. The outbox holds the exact mutation/body until a matching
durable receipt. A missing local checkpoint is checked against server progress; existing remote
content requires explicit recovery and is never silently re-uploaded under a new
generation. The current API has no prefix digest for automatic recovery. A new
server origin/collector requires a different state binding. Full-prefix hashing detects
rewrites: a new generation begins at zero; an old generation cannot be reactivated.
Existing Sparkstead source IDs are discovered through its read-only source
registry, with the original collector ID and exact legacy path mapping.

The measured-event batch and source-content stream represent different data.
Only the existing domain usage ledger can contribute token, price, tool-duration
or human-input totals. Uploading raw bytes, reparsing or rerunning presentation
never inserts usage. Historical measured-event rows are retained as the single
ledger, without copying them into a new format or manufacturing missing text.
Content-only sessions show unknown usage; event-only sessions show missing content.

The automatic timer can operate while Sparkstead's foreground stays open. It and
manual calls invoke the same CLI/config. Future Sparkstead-triggered content sync
must invoke this CLI rather than keep a second checkpoint or uploader. The running
Sparkstead measured-event worker remains the sole producer of measured batches.

## Segmentation and evidence

The pinned agent-session worker normalizes a completed source snapshot into
operations, source byte locations and source metadata. A configured headless model
API assigns each operation directly to exactly one task; parents include their
children, and tasks can contain non-contiguous operations. Output is validated for
coverage and cycles; one bounded repair call is allowed per invalid chunk. Input
and output budgets, truncated-operation counts and provider usage are recorded.
There is no automatic paid analysis of every uploaded session: an authorized
configure request creates an asynchronous analysis job.

AgentPProf consumes normalized operations plus validated task annotations.
Profiles use authoritative tokens when available, otherwise operation counts;
operation counts are not tokens or money. Task metrics roll up the existing usage
ledger exactly once. A matching provider call ID is preferred; unmatched events
use source-record position and are marked as estimated attribution. Missing
ledger, paid counters and prices remain explicit gaps.

Opaque source and analysis revisions protect asynchronous results and human edits.
Evidence lookup verifies the active source revision before reading bounded raw
bytes. Task edits mark an older profile artifact stale; the current browser derives
task metrics from current membership rather than treating that artifact as current.
