# Canonical Trajectory Schema v1

Status: normative  
Schema ID: `agent-vis.canonical-trajectory`  
Schema Version: `1.0`

This document defines the agent-neutral canonical trajectory contract used between parser adapters (Path 1) and downstream sync/query layers (Path 2/3).

## 1. Scope

This schema standardizes:

- session identity envelope
- message/event stream contract
- tool call and tool result payload shapes
- token usage counters
- timestamp annotation records for key timeline events

It does not define DB table layout or API pagination behavior; those are covered by dedicated Path 2/3 standards.

## 2. Layer Mapping

Pipeline mapping:

1. ecosystem raw events -> `CanonicalEvent` / `CanonicalSession`
2. canonical events -> unified domain model (`MessageRecord`, `Session`, `SessionStatistics`)
3. unified domain model -> DB/API contracts

Implementation anchors:

- canonical adapter contract: `agent_vis/parsers/canonical.py`
- unified model: `agent_vis/models.py`
- ecosystem capability declaration: `agent_vis/parsers/manifests/*.json`

## 3. Versioning and Compatibility

- Schema version format: `MAJOR.MINOR`
- Backward-compatible additions: increment `MINOR`
- Breaking changes (remove/rename required fields, semantic redefinition): increment `MAJOR`
- Consumers must reject unsupported higher `MAJOR`
- Consumers must ignore unknown additive fields

## 4. Canonical Entities

## 4.1 CanonicalSession

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `ecosystem` | `string` | yes | Ecosystem ID (`claude_code`, `codex`, ...) |
| `source_path` | `string` | yes | Absolute/normalized source file path |
| `events` | `CanonicalEvent[]` | yes | Ordered canonical events |

## 4.2 CanonicalEvent

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `ecosystem` | `string` | yes | Event ecosystem namespace |
| `source_path` | `string` | yes | Event origin file path |
| `line_number` | `int >= 1` | yes | Source file line number |
| `event_kind` | `string` | yes | Source event kind (adapter-defined normalized string) |
| `timestamp` | `string \\| null` | yes | ISO 8601 timestamp or null |
| `actor` | `string \\| null` | yes | Source actor/type marker |
| `payload` | `object` | yes | Lossless source payload snapshot |

## 4.3 Unified Session Envelope

Canonical conversion must materialize a unified session envelope with identity semantics:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `session_id` | `string` | yes | Stable session identifier used by API and DB |
| `physical_session_id` | `string \\| null` | yes | Physical file/session identity (if supported) |
| `logical_session_id` | `string \\| null` | yes | Deduplicated logical thread identity |
| `parent_session_id` | `string \\| null` | yes | Parent lineage identity |
| `root_session_id` | `string \\| null` | yes | Root lineage identity |
| `project_path` | `string` | yes | Working project path |
| `created_at` | `datetime` | yes | First message timestamp |
| `updated_at` | `datetime \\| null` | yes | Last message timestamp |

## 4.4 Unified Message Contract

The canonical stream is converted into `MessageRecord` with the following required minimum set:

| Field | Type | Required | Description | Claude source example | Codex source example |
| --- | --- | --- | --- | --- | --- |
| `sessionId` | `string` | yes | session key for message | top-level `sessionId` | `session_meta.payload.id` or filename-derived ID |
| `uuid` | `string` | yes | message/event unique ID | top-level `uuid` | synthesized (`<session>-msg-<line>`, call IDs) |
| `timestamp` | `ISO 8601 string` | yes | event timestamp | top-level `timestamp` | top-level `timestamp` or deterministic fallback |
| `type` | `user \\| assistant \\| ...` | yes | message type | top-level `type` | mapped from `response_item`/`event_msg` |
| `message.role` | `user \\| assistant \\| system` | conditional | logical speaker role | `message.role` | mapped from `response_item.role`/synthetic role |
| `message.content` | `string \\| content[]` | conditional | text/tool blocks | `message.content` | normalized from `payload.content` or tool events |

## 4.5 Tool Content Blocks

Tool operations must normalize to these content block contracts:

### ToolUse block

| Field | Type | Required |
| --- | --- | --- |
| `type` | `"tool_use"` | yes |
| `id` | `string` | yes |
| `name` | `string` | yes |
| `input` | `object` | yes |

### ToolResult block

| Field | Type | Required |
| --- | --- | --- |
| `type` | `"tool_result"` | yes |
| `tool_use_id` | `string` | yes |
| `content` | `string \\| object[]` | yes |
| `is_error` | `bool \\| null` | yes |

## 4.6 Token Usage Contract

Token usage fields are unified in `message.usage` and session-level aggregates:

| Field | Type | Required | Default/Fallback |
| --- | --- | --- | --- |
| `input_tokens` | `int` | yes | `0` when absent and policy is `zero_fill` |
| `output_tokens` | `int` | yes | `0` when absent and policy is `zero_fill` |
| `cache_read_input_tokens` | `int \\| null` | yes | `null` or `0` per capability fallback |
| `cache_creation_input_tokens` | `int \\| null` | yes | `null` or `0` per capability fallback |

Capability support for each ecosystem is normative via `agent_vis/parsers/manifests/*.json`.

## 4.7 Timestamp Annotation Contract

Timestamp annotations represent key timeline markers derived from sessions.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `timestamp` | `ISO 8601 string` | yes | Event time |
| `annotation_type` | `string` | yes | Canonical category (`tool_error`, `model_timeout`, `compact`, `sync_error`, ...) |
| `severity` | `info \\| warning \\| error` | yes | Visualization/alert severity |
| `source` | `model \\| tool \\| user \\| system` | yes | Attribution dimension |
| `label` | `string` | yes | Short user-facing label |
| `detail` | `string` | no | Expanded detail payload |
| `reference_id` | `string \\| null` | yes | Optional linkage (tool call id, message uuid, etc.) |

Current concrete sources in repository include:

- tool error records (`SessionStatistics.tool_error_records`)
- model timeout counters (`TimeBreakdown.model_timeout_count`) with inferred annotation potential
- compact events (`SessionStatistics.compact_events`)

## 5. Source-to-Canonical Examples

## 5.1 Claude Code example

Source snippet:

```json
{
  "type": "assistant",
  "sessionId": "abc-123",
  "timestamp": "2026-03-03T10:00:00Z",
  "message": {
    "role": "assistant",
    "content": [{"type": "tool_use", "id": "toolu_1", "name": "Read", "input": {"file_path": "a.py"}}]
  }
}
```

Canonical result highlights:

- `event_kind = "assistant"`
- unified `MessageRecord.type = "assistant"`
- tool use block preserved as canonical tool operation

## 5.2 Codex example

Source snippet:

```json
{
  "type": "response_item",
  "timestamp": "2026-03-03T10:00:01Z",
  "payload": {
    "type": "function_call",
    "name": "Read",
    "call_id": "call_1",
    "arguments": "{\"file_path\":\"a.py\"}"
  }
}
```

Canonical result highlights:

- `event_kind = "response_item"`
- unified `MessageRecord.type = "assistant"`
- normalized tool use block:
  - `id = "call_1"`
  - `name = "Read"`
  - `input = {"file_path": "a.py"}`

## 6. Validation Requirements

A schema-compliant ecosystem integration must provide:

1. adapter conversion tests (`raw -> canonical -> MessageRecord`)
2. capability manifest alignment tests for token/timestamp/tool-error support
3. integration tests validating session identity semantics (logical/physical lineage)
4. query layer tests that preserve N/A behavior for unsupported capability dimensions

## 7. Change Control

Any PR that changes canonical field meaning must update:

- this schema document
- ecosystem capability manifests (if impact exists)
- parser tests and API contract tests
- changelog entries under `Changed` (or `Removed` for breaking behavior)
