# Canonical to DB Sync Contract v1

Status: normative  
Contract ID: `agent-vis.canonical-db-sync`  
Version: `1.0`

This document defines Path 2: how canonical/unified session objects are synchronized into SQLite with incremental/idempotent behavior.

## 1. Scope

Covers:

- table-level write contract (`tracked_files`, `sessions`, `session_statistics`)
- incremental sync decision logic
- idempotency and deduplication rules
- parse/skipped/error semantics
- sync status observability alignment with `/api/sync/status`

Does not cover API query payload contracts (Path 3).

## 2. Write Model

Sync is file-driven:

1. discover source files via ecosystem parser
2. compare `(file_path, file_size, file_mtime, parse_status)` against `tracked_files`
3. parse changed/new files into unified `Session`
4. upsert `tracked_files` -> upsert `sessions` -> upsert `session_statistics`

## 3. Table Mapping Contract

## 3.1 `tracked_files`

Natural key: `file_path` (unique)

| Column | Source | Required | Notes |
| --- | --- | --- | --- |
| `file_path` | resolved absolute source path | yes | uniqueness key for incremental sync |
| `file_size` | source stat size | yes | compared for change detection |
| `file_mtime` | source stat mtime | yes | compared for change detection |
| `ecosystem` | parser ecosystem name | yes | e.g. `claude_code`, `codex` |
| `last_parsed_at` | sync runtime timestamp | no | updated on every upsert |
| `parse_status` | sync outcome | yes | `parsed` or `error` (default `pending`) |

## 3.2 `sessions`

Natural key: `session_id` (primary key)

| Column | Source | Required | Notes |
| --- | --- | --- | --- |
| `session_id` | `Session.metadata.session_id` | yes | stable API/session key |
| `physical_session_id` | metadata physical ID | yes | defaults to `session_id` when absent |
| `logical_session_id` | metadata logical ID | yes | defaults to physical/session ID when absent |
| `parent_session_id` | metadata lineage | no | nullable |
| `root_session_id` | metadata lineage | no | nullable |
| `file_id` | FK to `tracked_files.id` | yes | source linkage |
| `ecosystem` | parser ecosystem | yes | source segmentation |
| `project_path` | metadata project path | yes | analytics/project grouping |
| `git_branch` | metadata branch | no | nullable |
| `created_at` | metadata created_at | no | ISO string |
| `updated_at` | metadata updated_at | no | ISO string |
| `total_messages` | metadata total_messages | no | summary |
| `total_tokens` | metadata total_tokens | no | summary |
| `parsed_at` | sync runtime timestamp | yes | upsert timestamp |
| `duration_seconds` | statistics duration | no | nullable |
| `total_tool_calls` | statistics total_tool_calls | yes | defaults to `0` |
| `bottleneck` | derived from time breakdown | no | `Model|Tool|User` |
| `automation_ratio` | derived `tool_calls/user_interactions` | no | nullable |
| `version` | metadata version | no | defaults to empty string |

## 3.3 `session_statistics`

Natural key: `session_id` (primary key)

| Column | Source | Required | Notes |
| --- | --- | --- | --- |
| `session_id` | `Session.metadata.session_id` | yes | joins with `sessions` |
| `statistics_json` | `SessionStatistics.model_dump_json()` | yes | full structured metrics blob |
| `computed_at` | sync runtime timestamp | yes | refresh timestamp |

## 4. Incremental and Idempotent Behavior

## 4.1 Change Detection

Default (`force=false`) skip condition:

- tracked row exists for `file_path`
- `file_size` unchanged
- `file_mtime` unchanged
- previous `parse_status == "parsed"`

If all match, file is counted as `skipped` and not parsed again.

## 4.2 Re-parse Conditions

File is reparsed when any of the following is true:

- new file path (no tracked row)
- `file_size` changed
- `file_mtime` changed
- previous `parse_status != "parsed"`
- manual sync uses `force=true`

## 4.3 Upsert Idempotency

- `tracked_files`: `ON CONFLICT(file_path) DO UPDATE`
- `sessions`: `ON CONFLICT(session_id) DO UPDATE`
- `session_statistics`: `ON CONFLICT(session_id) DO UPDATE`

Repeated sync with identical input must converge to same persisted business values (except runtime timestamps like `last_parsed_at`, `parsed_at`, `computed_at`).

## 5. Logical vs Physical Session Rule

Write layer stores both physical and logical identity in each `sessions` row. No deduplication occurs during write.

Deduplication by logical session is a query/view concern (`view=logical`) and must not mutate stored physical records.

## 6. Parse Outcome Semantics

`SyncResult` counters:

- `parsed`: files successfully parsed and persisted
- `skipped`: unchanged files skipped by incremental policy
- `errors`: per-file parse or read errors

`tracked_files.parse_status` meanings:

- `parsed`: last processing succeeded
- `error`: last processing failed
- `pending`: initial/default pre-parse state

## 7. Failure Scenarios and Required Behavior

## 7.1 Malformed JSONL

Example: invalid JSON at line N.

Expected behavior:

- append human-readable error entry (`<filename>: <error>`)
- upsert tracked file with `parse_status="error"`
- continue processing other files

## 7.2 Missing Required Fields / No Valid Messages

Example: file parses but no records survive adapter/model validation.

Expected behavior:

- treat as parse failure (`SessionParseError`)
- set file status to `error`
- do not write/overwrite `sessions` or `session_statistics` for that run

## 7.3 File IO Failure / Permission Error

Example: `stat()` or read fails due to permissions or transient IO.

Expected behavior:

- report error in sync result
- if parse did not run, tracked row may remain unchanged or move to `error` if upsert path executed
- continue processing remaining files

## 7.4 Duplicate Logical Session Across Multiple Physical Files

Example: Codex parent/sub-agent physical files share one logical lineage.

Expected behavior:

- persist each physical file/session row independently
- keep shared `logical_session_id` for downstream logical-view dedupe
- no destructive merge in write layer

## 8. Observability Contract (`/api/sync/status`)

The sync status endpoint must stay consistent with persisted sync behavior.

`GET /api/sync/status` fields:

| Field | Source |
| --- | --- |
| `total_files` | `COUNT(*) FROM tracked_files` |
| `total_sessions` | repository `count_sessions()` |
| `last_parsed_at` | `MAX(last_parsed_at) WHERE parse_status='parsed'` |
| `sync_running` | service runtime sync flag |
| `last_sync` | last in-memory detailed run snapshot (`parsed/skipped/errors/file bytes/ecosystem detail`) |

`POST /api/sync/run` returns detailed execution payload matching the same `last_sync` schema.

## 9. Change Control

Any change to sync semantics must update:

- this contract document
- `tests/test_sync.py`
- API integration tests covering `/api/sync/status` and manual trigger behavior
- changelog entries describing behavior changes
