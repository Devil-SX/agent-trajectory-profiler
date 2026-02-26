[English](claude-jsonl-format.md) | [中文](claude-jsonl-format.zh.md)

# Claude Code JSONL Session Format

Claude Code stores each session as a JSONL file at `~/.claude/projects/<project-slug>/<session-id>.jsonl`. Each line is an independent JSON object.

## Record Types

Each record is distinguished by the `type` field:

| type | Description | Has `message` | Has `usage` |
|------|-------------|:------------:|:-----------:|
| `user` | User input or tool return results | Yes | No |
| `assistant` | A single content block output by the model | Yes | Yes |
| `progress` | Hook execution progress, tool execution progress | No | No |
| `system` | System events (hook summary, stop signals) | No | No |
| `file-history-snapshot` | File history snapshot (used for undo) | No | No |
| `queue-operation` | Background task queue operations (enqueue/dequeue) | No | No |

> **Important**: There is no explicit "session open/close" event. Session boundaries can only be inferred from message timestamp gaps.

## Message Granularity: One Content Block = One JSONL Record

This is the most critical point for understanding the JSONL format. **A single model response (API turn) is not one record but multiple records**, with each content block on its own line.

### Example: Model reads 6 files in one response

```
User sends message:
  {"type":"user", "message":{"role":"user","content":[{"type":"text","text":"Help me refactor the code"}]}}

Model output (1 API turn -> 7 JSONL records):
  {"type":"assistant", "message":{"content":[{"type":"text","text":"Let me read the files..."}], "usage":{...}}}       <- text block
  {"type":"assistant", "message":{"content":[{"type":"tool_use","name":"Read","id":"toolu_01A..."}], "usage":{...}}}  <- tool_use
  {"type":"assistant", "message":{"content":[{"type":"tool_use","name":"Read","id":"toolu_01B..."}], "usage":{...}}}  <- tool_use
  {"type":"assistant", "message":{"content":[{"type":"tool_use","name":"Read","id":"toolu_01C..."}], "usage":{...}}}  <- tool_use
  {"type":"assistant", "message":{"content":[{"type":"tool_use","name":"Read","id":"toolu_01D..."}], "usage":{...}}}  <- tool_use
  {"type":"assistant", "message":{"content":[{"type":"tool_use","name":"Read","id":"toolu_01E..."}], "usage":{...}}}  <- tool_use
  {"type":"assistant", "message":{"content":[{"type":"tool_use","name":"Read","id":"toolu_01F..."}], "usage":{...}}}  <- tool_use

Tool results returned (6 user records, one per tool_result):
  {"type":"user", "message":{"content":[{"type":"tool_result","tool_use_id":"toolu_01A...","content":"..."}]}}
  {"type":"user", "message":{"content":[{"type":"tool_result","tool_use_id":"toolu_01B...","content":"..."}]}}
  ...
```

### Timestamp Characteristics

- Multiple assistant records within the same API turn have incrementing timestamps, spaced ~0.3-1s apart (streaming output intervals)
- Tool result user records have nearly simultaneous timestamps (<0.01s apart, returned in the same batch)
- **Actual user interactions** are `user` records without `tool_result`

## Content Block Types

### Content blocks in assistant messages

| type | Description | Key fields |
|------|-------------|-----------|
| `text` | Text output | `text` |
| `thinking` | Internal reasoning (extended thinking) | `thinking`, `signature` |
| `tool_use` | Tool invocation | `id`, `name`, `input` |

### Content blocks in user messages

| type | Description | Key fields |
|------|-------------|-----------|
| `text` | User input text | `text` |
| `tool_result` | Tool execution result | `tool_use_id`, `content`, `is_error` |

## Token Usage

Only `assistant` records contain `message.usage`:

```json
{
  "usage": {
    "input_tokens": 3,
    "output_tokens": 469,
    "cache_creation_input_tokens": 12345,
    "cache_read_input_tokens": 67890,
    "service_tier": "standard"
  }
}
```

- `input_tokens`: Non-cached input tokens
- `output_tokens`: Model output tokens
- `cache_read_input_tokens`: Tokens read from cache
- `cache_creation_input_tokens`: Tokens written to cache

> Among multiple assistant records within the same turn, only the last one's `usage` contains the true cumulative values; earlier ones are intermediate streaming states. However, we currently sum the `usage` across all assistant records, since each record's incremental values are also meaningful.

## Common Top-Level Fields

```json
{
  "type": "user|assistant|progress|system|...",
  "sessionId": "39672551-...",
  "uuid": "unique-record-id",
  "parentUuid": "parent-record-id",
  "timestamp": "2026-02-11T04:17:06.684Z",
  "isSidechain": false,
  "userType": "external",
  "cwd": "/home/user/project",
  "version": "2.1.34",
  "gitBranch": "main",
  "message": { ... }
}
```

| Field | Description |
|-------|-------------|
| `sessionId` | Session ID, corresponds to the filename |
| `uuid` | Unique ID for this record |
| `parentUuid` | Parent record ID (used to build the message tree) |
| `timestamp` | ISO 8601 timestamp |
| `isSidechain` | Whether this is a subagent message |
| `agentId` | Subagent ID (only present in subagent messages) |
| `cwd` | Current working directory |
| `version` | Claude Code version number |

## Subagent Messages

When Claude uses the `Task` tool to create a subagent, the subagent's messages are interleaved within the main session JSONL, distinguished by `isSidechain: true` and `agentId`. Subagent JSONL files are also stored separately at `<session-id>/subagents/agent-<id>.jsonl`.

---

# How This Repository Processes Sessions

## Parser Filtering Rules

The `parse_jsonl_file()` function in `session_parser.py` only parses records that pass `MessageRecord` Pydantic validation. In practice, only `type=user` and `type=assistant` records pass, because `progress`, `system`, and other types lack the fields required by `MessageRecord`.

Therefore:
- **Parsed**: `user` (1241 records) + `assistant` (1906 records) = 3147 records
- **Skipped**: `progress` (11391) + `system` (116) + `file-history-snapshot` (97) + `queue-operation` (44) = 11648 records

## Message Counts

In the current statistics, `assistant_message_count` is the **number of JSONL records** (one per content block), not the number of API turns. For example:

- 1906 assistant records ≈ 1009 actual model turns (average of 1.9 records per turn)

## Time Attribution Algorithm

For each pair of adjacent messages, the time gap is calculated as `gap = timestamp[i] - timestamp[i-1]`:

```
gap > 30min (inactivity threshold)
  -> Inactive (application closed / user away)

gap <= 30min:
  next record is assistant  -> Model time (model inference + streaming output)
  next record is user + tool_result  -> Tool time (tool execution)
  next record is user + text  -> User time (user thinking / typing)
```

### Known Limitations

1. **Streaming intervals within the same turn**: The 0.3-1s intervals between assistant->assistant records are counted as Model time; strictly speaking this is network transfer time, but the impact is small (~4%)
2. **Batch tool calls share timestamps**: Multiple tool_use blocks within the same turn share the assistant message timestamp, causing the first tool's latency to be overestimated
3. **Interleaved subagent messages**: Subagent messages are sorted by timestamp and mixed with main messages for calculation, not tracked separately

## Tool Latency Calculation

`tool_use_map` stores `tool_use_id -> (tool_name, timestamp)`. When the corresponding `tool_result` is encountered:

```
latency = tool_result_timestamp - tool_use_timestamp
```

This is accumulated into each tool's `total_latency`, and finally `avg_latency = total_latency / count` is computed.
