# Timestamp Annotation Capability Matrix (By Ecosystem)

Status: normative  
Version: `1.0`

This matrix defines capability coverage for timeline marker generation and visualization.

## Normalized Annotation Contract

Each annotation record should follow:

- `timestamp` (ISO 8601)
- `annotation_type` (e.g. `tool_error`, `model_timeout`, `compact`, `sync_error`)
- `severity` (`info|warning|error`)
- `source` (`user|model|tool|system`)
- `label` (short text)
- `detail` (optional expanded text)
- `reference_id` (optional link target)

## Legend

- `supported`: explicit timestamped records are currently available
- `partial`: derivable but not fully normalized or lacks dedicated endpoint
- `unsupported`: no reliable source in current parser contract
- Confidence: `high`, `medium`, `low`

## Matrix

| Annotation type | claude_code | codex | Current source(s) | Notes / caveats | UI guidance |
| --- | --- | --- | --- | --- | --- |
| `tool_error` | supported (high) | supported (high) | `SessionStatistics.tool_error_records` | taxonomy + tool call id + summary/detail snippet available | show directly in timeline/events table |
| `tool_call` start/end | partial (medium) | partial (medium) | tool_use/tool_result pairing in message stream | shared timestamps can skew latency start | show as derived markers with caveat |
| `model_timeout` | partial (medium) | partial (medium) | `time_breakdown.model_timeout_count` + gap analysis | count exists; explicit per-event list not yet normalized | show count + optional inferred marker toggle |
| `compact` | supported (high) | unsupported (high) | claude: `compact_events`; codex: none | codex currently has no compact boundary extraction | codex show N/A reason |
| `session_boundary_open/close` | unsupported (high) | unsupported (high) | no explicit boundary events | only inferred via inactivity heuristics | avoid hard boundary markers |
| `sync_error` | partial (medium) | partial (medium) | `/api/sync/status.last_sync.error_samples` | sync errors not yet joined into per-session annotation stream | show in control-plane diagnostics |
| `subagent_spawn/link` | partial (medium) | partial (medium) | claude subagent extraction, codex lineage fields | not unified as timestamp annotations endpoint yet | show optional lineage markers |
| `inactivity_gap` | partial (medium) | partial (medium) | timestamp gap > inactivity threshold | heuristic-derived | use subdued warning markers |

## Endpoint Coverage Status

- Dedicated annotation endpoint (`/api/sessions/{id}/annotations`): not yet implemented
- Current practical extraction:
  - `GET /api/sessions/{id}/statistics` for tool errors + compact events + timeout counts
  - `GET /api/sync/status` for sync-error context

## Unsupported/Partial Display Policy

- `unsupported`: always show `N/A` with ecosystem-specific reason
- `partial`: show derived values with "inferred" marker and tooltip
- never hide capability gaps; missing support must be explicit in UI

## Required Update Process for New Annotation Types

When adding/changing annotation categories:

1. define annotation semantics and severity mapping
2. update parser extraction and/or API normalization
3. update ecosystem manifests if support dimensions changed
4. update this matrix with support state and caveats
5. add/update tests:
   - parser/statistics extraction tests
   - API contract tests for annotation payloads
   - frontend tests for supported + N/A behavior
6. update changelog
