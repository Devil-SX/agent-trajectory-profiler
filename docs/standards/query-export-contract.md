# Query and Export Contract v1

Status: normative  
Contract ID: `agent-vis.query-export`  
Version: `1.0`

This document defines Path 3: stable data-access contracts for UI, CLI, and external consumers.

## 1. Scope

Path 3 exposes three payload classes:

1. `analytics_summary`: session/cross-session aggregated metrics
2. `trajectory_full`: full message/event timeline for a specific session
3. `timestamp_annotations`: key timeline markers (errors, stalls, boundaries, compacts)

The contract is consumer-facing and must not depend on frontend component internals.

## 2. Common Query Semantics

## 2.1 Date Range

- Date format: `YYYY-MM-DD`
- `start_date`, `end_date` are inclusive day bounds from consumer perspective
- API normalizes missing range to default windows (typically last 7 days for cross-session endpoints)

## 2.2 Filtering

- `ecosystem` optional source filter (`claude_code`, `codex`, future values)
- Session list view mode:
  - `view=logical`: deduplicate by logical session identity
  - `view=physical`: raw physical files/sessions

## 2.3 Pagination and Limits

- Session list: `page`, `page_size` (`1..200`)
- Some analytics endpoints expose explicit limits (`limit`, `project_limit`)

## 2.4 Null and N/A Semantics

- Unsupported capability fields must be represented as `null` or omitted only when contract allows omission.
- Do not silently coerce unsupported values to zero.
- Consumers should render `N/A` with capability-based reason when a dimension is unsupported.

## 3. Payload Class: `analytics_summary`

## 3.1 Purpose

Aggregated quantitative metrics over one session or across many sessions.

## 3.2 Required Top-Level Fields

| Field | Type | Description |
| --- | --- | --- |
| `start_date` | `string` | range start |
| `end_date` | `string` | range end |
| `total_sessions` | `int` | sessions in window/filter |
| `total_tokens` | `int` | total token volume |
| `total_tool_calls` | `int` | total tool call volume |
| `source_breakdown` | `EcosystemAggregate[]` | per-ecosystem aggregate |
| `role_source_breakdown` | `RoleSourceAggregate[]` | role x source breakdown |
| `control_plane` | `ControlPlaneOverview` | ingestion/sync state |
| `runtime_plane` | `RuntimePlaneOverview` | behavior/runtime state |

## 3.3 Existing Endpoints

- `GET /api/analytics/overview`
- `GET /api/analytics/distributions`
- `GET /api/analytics/timeseries`
- `GET /api/analytics/project-comparison`
- `GET /api/analytics/project-swimlane`
- `GET /api/sessions` (session summary list class)
- `GET /api/sessions/{id}/statistics` (single-session summary class)

## 3.4 Example

Request:

```http
GET /api/analytics/overview?start_date=2026-03-01&end_date=2026-03-03&ecosystem=codex
```

Response (truncated):

```json
{
  "start_date": "2026-03-01",
  "end_date": "2026-03-03",
  "total_sessions": 42,
  "total_tokens": 1280000,
  "total_tool_calls": 930,
  "source_breakdown": [
    {"ecosystem": "codex", "sessions": 42, "total_tokens": 1280000, "percent_sessions": 100.0}
  ],
  "role_source_breakdown": [
    {"ecosystem": "codex", "role": "model", "token_count": 810000, "token_percent": 63.3}
  ],
  "control_plane": {"logical_sessions": 30, "physical_sessions": 42},
  "runtime_plane": {"active_time_ratio": 0.82, "avg_automation_ratio": 1.6}
}
```

## 4. Payload Class: `trajectory_full`

## 4.1 Purpose

Complete session detail for replay, debugging, and export.

## 4.2 Required Top-Level Fields

| Field | Type | Description |
| --- | --- | --- |
| `session.metadata` | `SessionMetadata` | identity/context envelope |
| `session.messages` | `MessageRecord[]` | ordered full message stream |
| `session.subagent_sessions` | `SubagentSession[]` | nested sessions if available |
| `session.statistics` | `SessionStatistics \\| null` | optional precomputed stats |

## 4.3 Existing Endpoint

- `GET /api/sessions/{session_id}`

## 4.4 Example

Request:

```http
GET /api/sessions/39672551-xxxx-xxxx-xxxx
```

Response (truncated):

```json
{
  "session": {
    "metadata": {
      "session_id": "39672551-xxxx-xxxx-xxxx",
      "logical_session_id": "39672551-xxxx-xxxx-xxxx"
    },
    "messages": [
      {"type": "user", "timestamp": "2026-03-03T09:00:00Z"},
      {"type": "assistant", "timestamp": "2026-03-03T09:00:02Z"}
    ],
    "subagent_sessions": [],
    "statistics": {}
  }
}
```

## 5. Payload Class: `timestamp_annotations`

## 5.1 Purpose

Provide normalized key timeline markers for downstream visualizations and incident/debug workflows.

## 5.2 Contract Shape

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `session_id` | `string` | yes | target session |
| `annotations` | `Annotation[]` | yes | ordered marker list |
| `generated_at` | `string` | yes | generation timestamp |

`Annotation` fields:

- `timestamp` (ISO 8601, required)
- `annotation_type` (required, e.g. `tool_error`, `model_timeout`, `compact`)
- `severity` (required: `info|warning|error`)
- `source` (required: `user|model|tool|system`)
- `label` (required short label)
- `detail` (optional long text)
- `reference_id` (optional linking ID)

## 5.3 Current Coverage and Gap

Current data sources exist but are not exposed as a dedicated endpoint:

- `tool_error_records` in `GET /api/sessions/{id}/statistics`
  - includes `timestamp`, `tool_name`, optional `tool_call_id`, concise `summary/preview`,
    and expandable `detail` (`detail_snippet` available for bounded UI rendering)
- `compact_events` in `GET /api/sessions/{id}/statistics`
- model timeout counters in `time_breakdown`

Gap:

- no single normalized `/api/sessions/{id}/annotations` endpoint yet
- no shared schema export endpoint for cross-session annotation timelines

## 5.4 Proposed Endpoint (Next Increment)

- `GET /api/sessions/{session_id}/annotations`
- optional filters: `types`, `severity`, `source`, `start_ts`, `end_ts`
- return contract defined in 5.2

## 6. Endpoint Mapping Matrix (Current State)

| Payload class | Endpoint(s) | Status |
| --- | --- | --- |
| `analytics_summary` | `/api/analytics/*`, `/api/sessions`, `/api/sessions/{id}/statistics` | implemented |
| `trajectory_full` | `/api/sessions/{id}` | implemented |
| `timestamp_annotations` | derived from `/api/sessions/{id}/statistics` fields | partial (no dedicated endpoint) |

## 7. External Export Minimum Guide

For third-party integrations, minimum export flow:

1. list sessions (`/api/sessions`) with desired `view` and `ecosystem` filters
2. fetch session detail (`/api/sessions/{id}`) for raw trajectory replay/export
3. fetch statistics (`/api/sessions/{id}/statistics`) for aggregate and annotation candidates
4. if annotation endpoint is unavailable, derive annotation records from `tool_error_records`, `compact_events`, and timeout signals using section 5 schema

## 8. Change Control

Any Path 3 contract update must include:

- updates to this document
- API model/schema test updates (`tests/test_api_integration.py`)
- frontend adapter/test updates for N/A handling where capability is missing
