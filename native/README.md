# Native analysis components

`session-worker` depends on the upstream `agent-session = 0.5.17` crate. It
does not contain a copied Codex/Claude parser. Run it as a persistent process;
each stdin line is one JSON request, each stdout line one response. Requests
are internal service messages, never an unauthenticated public file API.

```json
{"id":"job-1","op":"parse","source_id":"machine/session","agent":"codex","input_file":"/private/artifacts/source.jsonl"}
```

For fixtures, replace `input_file` with `content`. `source_path` optionally
preserves the original logical path. `op: health` reports the protocol/parser.
Errors preserve the request ID and do not terminate the process. Errors never
echo private source content or filesystem error details.

The result includes the upstream `AgentSession` plus uniform `operations`
derived from upstream prompts, responses and tools. Prompt/reply text is
available up to upstream's 64 KiB per-message limit. Source record metadata contains byte ranges, hashes, native IDs,
timestamps, lineage and usage evidence. Original tool results and other fields
not retained by upstream remain in the authoritative source archive. Location
is null when matching is not unique; callers must not invent a source position.

Operations' `metrics` are intentionally empty: populate them only from the
service's measured-usage ledger. Upstream response totals can contain text
estimates; zero-valued fields do not prove a source reported zero. Likewise,
upstream cache aggregation is insufficient for pricing cache reads/writes.
The worker never calls `token_components()` or converts estimates into billing.

This upstream API parses complete snapshots, O(source size) per changed
snapshot. The service should debounce appends and cache by
`(source_id, source_sha256, parser_version)`; a replay needs no parsing. It must
not invoke parsing for each upload chunk. JSONL incomplete final records are
held for the next snapshot, and malformed complete records fail the job rather
than disappearing silently. Source identity and operation IDs are stable on
replay; cross-session inherited context still requires source-native lineage
and the service's consumption identity rules, rather than content-only dedup.

`scripts/native/build-workers.sh` also builds the research AgentPProf CLI at
commit `60cc321ceb4b677fec1a69df6ec055a456b75675`. That version implements
the `--annotation-file` workspace contract (`trace.jsonl`, `annotation.json`,
`stacks.folded`) and emits standard pprof. Its transitive native parser is the
upstream research version; Trajectory must use the modern worker for canonical
parsing and feed prepared trace nodes to the CLI, not ask the CLI to parse
source logs a second time. The CLI consumes annotations; it does not itself
provide the paper's external Codex annotator. LLM annotation must remain an
explicit asynchronous service stage with recorded model/prompt provenance.

Build and run `cargo test --locked --manifest-path native/session-worker/Cargo.toml`
on `batcave-wsl` in an isolated directory under `/home/saveer/BatCave/tests`.
The build requires Rust 1.87 or later. Install both binaries and the emitted
upstream MIT license with the release. No submodule or runtime Git fetch is
required in production.
