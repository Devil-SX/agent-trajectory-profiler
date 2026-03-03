# Codex Ecosystem Profile

Ecosystem ID: `codex`  
Parser: `agent_vis/parsers/codex.py`  
Adapter: `CodexEventAdapter`

## 1. Source Discovery

- Default root: `~/.codex/sessions`
- Discovery rule: recursive `rollout-*.jsonl`
- Implementation entry: `find_codex_session_files()`

## 2. Session Identity Model

- Physical session ID:
  - preferred: parsed `session_meta.payload.id` when present
  - fallback: UUID tail extracted from `rollout-*.jsonl` filename stem
- Logical lineage resolution:
  - inspect `session_meta.payload.lineage` (or flat payload keys)
  - keys: `parent_session_id|parent_thread_id|parent_id|...` and `root_session_id|root_thread_id|root_id|...`
  - `logical_session_id = root_session_id or parent_session_id or physical_session_id`
- Supports both logical and physical session dimensions.
- Manifest reference: `agent_vis/parsers/manifests/codex.json`

## 3. Raw Event Shapes

Top-level source event types accepted by adapter:

- `session_meta`
- `response_item`
- `event_msg`

All other top-level types are ignored.

### Event Coverage Matrix

| Event key | Status | Current behavior |
| --- | --- | --- |
| `session_meta` | supported | mapped to synthetic metadata marker message |
| `event_msg:user_message` | supported | mapped to user text message |
| `event_msg:token_count` | supported | mapped to assistant `token_count` message with usage |
| `event_msg:turn_context` | ignored_expected | not mapped to `MessageRecord`; counted in diagnostics |
| `response_item:message` | supported | mapped to role-preserving user/assistant message |
| `response_item:function_call` | supported | mapped to assistant `tool_use` |
| `response_item:custom_tool_call` | supported | mapped to assistant `tool_use` |
| `response_item:function_call_output` | supported | mapped to user `tool_result` |
| `response_item:custom_tool_call_output` | supported | mapped to user `tool_result` |
| `response_item:reasoning` | pending | currently unmapped; counted in diagnostics |
| `<unknown_top_level>` | ignored_expected | dropped before canonical conversion; counted in diagnostics |

## 4. Mapping to Canonical and Unified Model

### Raw -> CanonicalEvent

- accepted only for `session_meta|response_item|event_msg`
- `event_kind = top-level type`
- `timestamp = raw timestamp or deterministic fallback`
- `payload = raw_event` (preserved)

### CanonicalEvent -> MessageRecord

Mapping logic by source subtype:

| Source shape | Mapping result |
| --- | --- |
| `session_meta` | synthetic user-side message with session metadata marker text |
| `event_msg` + `user_message` | user text message |
| `event_msg` + `token_count` | assistant message containing normalized usage counters |
| `response_item` + `message` | assistant/user message (role-preserving) |
| `response_item` + `function_call` / `custom_tool_call` | assistant `tool_use` content block |
| `response_item` + `function_call_output` / `custom_tool_call_output` | user `tool_result` content block with error inference |

### User Prompt De-duplication Rule

Codex may represent one user prompt through both:

- `event_msg.user_message`
- `response_item.message(role=user)`

Current parser behavior:

- de-duplicates only when these two channels overlap with:
  - same normalized text
  - timestamp distance within `<= 2s`
- keeps `event_msg.user_message` as canonical
- does **not** dedupe same-channel repeats or repeats outside the short window

## 5. Fallback and Error Handling

- Missing timestamp is replaced with deterministic ISO fallback to keep ordering.
- Non-dict payload sections are normalized to empty dicts where needed.
- Tool-call output strings are parsed best-effort; invalid JSON remains as raw text.
- Error detection for tool output uses:
  - explicit `metadata.exit_code` when available
  - fallback regex on output text (`Process exited with code ...`)
- Missing fields follow manifest fallback policy (`infer_best_effort` for timestamps).

### Drop Diagnostics (Observable Output)

`parse_codex_jsonl_file_with_diagnostics()` exposes:

- `raw_event_count`
- `raw_event_kind_counts`
- `dropped_top_level_counts`
- `unmapped_event_counts` (by `top_level[:subtype]`)
- `deduped_user_prompt_count`
- `dropped_samples` (minimal `{line_number, event_type, reason}` entries)

`parse_codex_jsonl_file()` logs this summary when any dropped/unmapped/deduped events are present.

## 6. Known Limitations

- Streaming partial chunks can omit stable IDs in some rollout variants.
- Nested sub-agent activity may appear as multiple physical files under one logical lineage.
- Synthetic records are introduced for some source event types to preserve a unified model contract.
