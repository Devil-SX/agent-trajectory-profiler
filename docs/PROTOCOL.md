# Trajectory HTTP protocol

Status: implementation candidate, not yet deployed. The runtime `/trajectory/protocol` endpoint publishes the JSON Schema generated from `trajectory/product/contracts.py`. That module is the authoritative wire contract. `/trajectory/help` publishes the current operation registry and required scopes.

A producer reads its source logs, extracts supported fields, and assigns stable source and event IDs. Sparkstead is the concrete producer in this workspace. Producers do not calculate cost or expose analysis UI. Project attribution, dated pricing, activity estimates and anomaly interpretation belong to the remote service.

Send `trajectory-batch/1` batches to `POST /trajectory/api/batches` with a native machine account's scoped API Key. Bind the collector to an authenticated owner before uploading. Source revisions strictly increase. `replace` replaces the physical source's projection after a rewrite or parser migration. Persist the checkpoint and pending batch in one local transaction. Retrying a batch uses the same mutation ID and exact body. A conflicting body under the same mutation ID is rejected.

The server responds with `mutation_id`, `durable: true` and a receipt timestamp only after the domain transaction commits. The producer clears its outbox only after validating that receipt. A network failure leaves the batch pending. Account, service-client and key revocation are checked on each request.

Missing timestamps, models, prices and counters remain unknown. Explicit target identifiers and the repository name may be transmitted as attribution evidence. Prompts, tool arguments, raw outputs, absolute local paths, code and credentials are excluded from record bodies. Producers may report parse failures and unsupported events without transporting their raw contents.

Sparkstead runs collection in a resource-limited worker. Each read slice is at most 512 KiB. Its pending outbox is bounded at 32 MiB; collection stops advancing when the outbox fills. HTTP synchronization uses a timeout and exponential backoff. Diagnostic logs rotate at 1 MiB with three retained files. Remote synchronization is disabled until configured. Settings may enable collection, enable synchronization, set the batch URL, credential file, source home directories and scan interval.

The credential file stores `origin` and `api_key`. Changing the server origin requires matching credentials; credentials are never forwarded during redirects. The source logs and historical profiler databases remain on the local machine.

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
