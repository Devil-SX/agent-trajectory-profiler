# Claude Code Ecosystem Profile

Ecosystem ID: `claude_code`  
Parser: `agent_vis/parsers/claude_code.py`  
Adapter: `ClaudeCodeEventAdapter`

## 1. Source Discovery

- Default root: `~/.claude/projects`
- Discovery rule: recursive `*.jsonl`
- Exclusions:
  - files under `subagents/`
  - `history.jsonl`
- Implementation entry: `find_session_files()`

## 2. Session Identity Model

- Primary session ID: filename stem (`<session-id>.jsonl`)
- Logical session support: yes
- Physical session support: no (no parent/child physical lineage graph exposed)
- Manifest reference: `agent_vis/parsers/manifests/claude_code.json`

## 3. Raw Event Shapes

Common top-level `type` values in source JSONL:

- `user`
- `assistant`
- `progress`
- `system`
- `file-history-snapshot`
- `queue-operation`

Only records that validate as `MessageRecord` are materialized into analytics input.

## 4. Mapping to Canonical and Unified Model

The Claude parser now uses a staged internal pipeline:

1. `decode`
2. `normalize` into `NormalizedEventIR` / `NormalizedRecordIR`
3. `materialize` into `MessageRecord` / `CompactEvent`

### Raw -> CanonicalEvent

- `event_kind` and `timestamp` are derived from the normalized event stage
- `actor = raw_event["type"]` if string
- `payload = raw_event` (preserved)

### NormalizedEventIR -> MessageRecord

- Message-bearing events normalize into `NormalizedRecordIR`
- `NormalizedRecordIR.to_message_record()` materializes the public `MessageRecord`
- Compact-boundary events are normalized as side-channel `NormalizedCompactEventIR` instances

### Decoder Selection

- Default decoder: `orjson` when installed, otherwise stdlib `json`
- Character metrics are computed through the required native Rust classifier exposed by `agent_vis._native`
- Optional decoder override: `orjson`
- Override path: `AGENT_VIS_JSON_DECODER=json|orjson`

### CanonicalEvent -> MessageRecord

- Adapter path reuses the same normalization stage as the parser
- Invalid payloads are skipped when normalization cannot build a `NormalizedRecordIR`
- Downstream metadata/statistics are computed from the resulting message stream

## 5. Fallback and Error Handling

- Malformed JSON lines raise `SessionParseError` with line number.
- Non-object JSON lines are skipped.
- Missing/invalid records are ignored when conversion cannot produce valid `MessageRecord`.
- Missing timestamps follow capability fallback policy (`skip_timing_metrics` semantics in manifest).

## 6. Known Limitations

- No explicit physical session parent/child graph in current source contract.
- Some record types are intentionally filtered out for analytics compatibility.
- Tool latency can be overestimated in batched tool-call turns that share timestamps.

## 7. Compatibility Notes

- Backward compatibility shim: `agent_vis/parsers/session_parser.py` re-exports Claude parser APIs.
- Deep raw-format walkthrough remains in `docs/claude-jsonl-format.md` and `.zh.md`.
