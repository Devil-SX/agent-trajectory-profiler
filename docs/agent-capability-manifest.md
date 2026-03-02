# Agent Capability Manifest Specification

This document defines the contract for `Agent Capability Manifest` so new ecosystems can be integrated with explicit, versioned capabilities instead of implicit parser assumptions.

## Status

- Contract type: normative specification (implementation-facing)
- Intended consumers: parser/ingestion layer, analytics layer, frontend explanation layer
- Scope boundary: this document defines format, versioning, and validation rules; it does not implement parser behavior.

## 1) Top-level Schema

Manifest format uses JSON (or YAML with equivalent fields). The canonical persisted form should be JSON.

Required top-level fields:

- `schema_version`: `string`
- `ecosystem`: `string` (for example `codex`, `claude_code`)
- `manifest_version`: `string` (version of ecosystem manifest content)
- `display_name`: `string`
- `parser`: `object`
- `capabilities`: `object`
- `known_limitations`: `array<string>`

Optional top-level fields:

- `docs_url`: `string`
- `notes`: `string`
- `deprecated`: `boolean` (default `false`)

### 1.1 parser object

Required fields:

- `adapter`: `string` (internal parser adapter id)
- `session_id_strategy`: `string` (`filename` | `event_field` | `composite`)
- `supports_logical_session`: `boolean`
- `supports_physical_session`: `boolean`

Optional fields:

- `minimum_agent_version`: `string`
- `default_roots`: `array<string>` (for documentation/UX only)

### 1.2 capabilities object

Required fields:

- `event_shape_support`: `object`
- `token_field_support`: `object`
- `tool_error_taxonomy_support`: `object`
- `fallback_behavior`: `object`

#### event_shape_support

Required fields:

- `message_events`: `boolean`
- `tool_call_events`: `boolean`
- `tool_result_events`: `boolean`
- `session_boundary_events`: `boolean`
- `timeline_timestamps`: `boolean`

Optional fields:

- `subagent_events`: `boolean`
- `parent_child_session_links`: `boolean`
- `streaming_partial_events`: `boolean`

#### token_field_support

Required fields:

- `input_tokens`: `boolean`
- `output_tokens`: `boolean`
- `cache_read_tokens`: `boolean`
- `cache_creation_tokens`: `boolean`

Optional fields:

- `reasoning_tokens`: `boolean`
- `tool_output_tokens`: `boolean`
- `token_units`: `string` (default `token`)

#### tool_error_taxonomy_support

Required fields:

- `categorization_available`: `boolean`
- `rule_version`: `string` (use `none` if unsupported)
- `error_preview_available`: `boolean`
- `error_detail_available`: `boolean`

Optional fields:

- `supports_timestamped_error_timeline`: `boolean`
- `supports_tool_name_mapping`: `boolean`

#### fallback_behavior

Required fields:

- `missing_token_fields`: `string` (`zero_fill` | `null_fill` | `skip_metric`)
- `missing_timestamps`: `string` (`skip_timing_metrics` | `infer_best_effort`)
- `unknown_tool_errors`: `string` (`uncategorized` | `drop`)

## 2) Version Strategy and Compatibility

Two independent versions are required:

- `schema_version`: version of this contract
- `manifest_version`: version of one ecosystem manifest instance

Rules:

1. `schema_version` follows `MAJOR.MINOR`.
2. Parser must reject manifests with a higher `MAJOR` than supported.
3. Parser must accept equal `MAJOR` and higher/equal `MINOR` by ignoring unknown additive fields.
4. Removing or renaming required fields requires `schema_version` major bump.
5. Additive optional fields require minor bump.
6. `manifest_version` follows SemVer and tracks ecosystem capability updates.

Backward compatibility rules:

- Unknown optional fields: ignore.
- Missing optional fields: apply defaults.
- Missing required fields: validation error (hard fail for manifest load).

## 3) Capability Dimensions

The contract must explicitly describe these dimensions:

- Event shape support: what event structures are reliably parseable.
- Token field support: which token counters are authoritative vs unavailable.
- Tool error taxonomy support: whether tool failures can be categorized and traced.
- Known limitations and fallback behavior: what the system does when source data is incomplete.

## 4) Example Manifest: codex

```json
{
  "schema_version": "1.0",
  "ecosystem": "codex",
  "manifest_version": "1.0.0",
  "display_name": "Codex",
  "parser": {
    "adapter": "codex.rollout",
    "session_id_strategy": "event_field",
    "supports_logical_session": true,
    "supports_physical_session": true,
    "default_roots": ["~/.codex/sessions"]
  },
  "capabilities": {
    "event_shape_support": {
      "message_events": true,
      "tool_call_events": true,
      "tool_result_events": true,
      "session_boundary_events": true,
      "timeline_timestamps": true,
      "subagent_events": true,
      "parent_child_session_links": true,
      "streaming_partial_events": true
    },
    "token_field_support": {
      "input_tokens": true,
      "output_tokens": true,
      "cache_read_tokens": true,
      "cache_creation_tokens": true,
      "reasoning_tokens": false,
      "tool_output_tokens": true,
      "token_units": "token"
    },
    "tool_error_taxonomy_support": {
      "categorization_available": true,
      "rule_version": "1.0.0",
      "error_preview_available": true,
      "error_detail_available": true,
      "supports_timestamped_error_timeline": true,
      "supports_tool_name_mapping": true
    },
    "fallback_behavior": {
      "missing_token_fields": "zero_fill",
      "missing_timestamps": "infer_best_effort",
      "unknown_tool_errors": "uncategorized"
    }
  },
  "known_limitations": [
    "Some streaming partial chunks may omit stable tool identifiers.",
    "Nested sub-agent sessions can appear as multiple physical sessions under one logical session."
  ]
}
```

## 5) Example Manifest: claude_code

```json
{
  "schema_version": "1.0",
  "ecosystem": "claude_code",
  "manifest_version": "1.0.0",
  "display_name": "Claude Code",
  "parser": {
    "adapter": "claude_code.jsonl",
    "session_id_strategy": "filename",
    "supports_logical_session": true,
    "supports_physical_session": false,
    "default_roots": ["~/.claude/projects"]
  },
  "capabilities": {
    "event_shape_support": {
      "message_events": true,
      "tool_call_events": true,
      "tool_result_events": true,
      "session_boundary_events": true,
      "timeline_timestamps": true,
      "subagent_events": false,
      "parent_child_session_links": false,
      "streaming_partial_events": true
    },
    "token_field_support": {
      "input_tokens": true,
      "output_tokens": true,
      "cache_read_tokens": true,
      "cache_creation_tokens": true,
      "reasoning_tokens": false,
      "tool_output_tokens": true,
      "token_units": "token"
    },
    "tool_error_taxonomy_support": {
      "categorization_available": true,
      "rule_version": "1.0.0",
      "error_preview_available": true,
      "error_detail_available": true,
      "supports_timestamped_error_timeline": true,
      "supports_tool_name_mapping": true
    },
    "fallback_behavior": {
      "missing_token_fields": "zero_fill",
      "missing_timestamps": "skip_timing_metrics",
      "unknown_tool_errors": "uncategorized"
    }
  },
  "known_limitations": [
    "Physical session lineage is not represented as parent/child graph.",
    "Session metadata shape can vary across local client versions."
  ]
}
```

## 6) Consumption Contract

### 6.1 Parser/Ingestion layer

- Validate manifest before parser registration.
- If manifest validation fails, parser registration must fail fast.
- Parser behavior must follow `fallback_behavior` when source fields are missing.

### 6.2 Frontend analytics layer

- UI can surface capability-aware explanations for derived metrics.
- If a capability is unsupported, UI should show explicit `N/A` + reason instead of silent zero.
- Source/ecosystem comparison views should annotate known limitations to avoid false comparisons.

## 7) New Ecosystem Onboarding Checklist

When adding a new ecosystem, all of the following are required:

1. Add parser adapter implementation under `agent_vis/parsers/`.
2. Add one manifest file with this schema contract.
3. Add parser-level tests for event normalization and fallback behavior.
4. Add API integration tests that include the new ecosystem in overview/source breakdown.
5. Add frontend rendering tests for ecosystem tags and capability-aware metric explanation.
6. Update docs (README/architecture/manifest examples if behavior differs).

## 8) Validation Entry Points (Local + CI)

Local validation commands:

```bash
uv run ruff check .
uv run black --check .
uv run mypy .
uv run pytest --tb=short
cd frontend && npm run lint
cd frontend && npm run type-check
cd frontend && npm run build
cd frontend && npm run test:e2e:smoke
```

CI gates to keep green:

- `backend-quality`
- `frontend-static-checks`
- `frontend-e2e-smoke`

Nightly extended gates:

- `frontend-e2e-full`
- `frontend-visual-regression`
- `frontend-a11y`
