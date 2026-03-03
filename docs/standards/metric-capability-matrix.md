# Metric Capability Matrix (By Ecosystem)

Status: normative  
Version: `1.0`

This matrix answers: "Is metric X reliable for ecosystem Y?"

## Legend

- `supported`: metric is directly available and considered reliable
- `partial`: metric is derivable but with caveats or best-effort assumptions
- `unsupported`: metric is not available from current source + parser contract
- Confidence: `high`, `medium`, `low`

UI rule:

- `unsupported` -> show `N/A` with explicit reason
- `partial` -> show value with caveat tooltip
- never silently render unsupported values as zero

## Matrix

| Metric family | Metric key | claude_code | codex | Source fields / parser basis | Fallback behavior | UI guidance |
| --- | --- | --- | --- | --- | --- | --- |
| Session identity | `session_id` | supported (high) | supported (high) | metadata/session envelope | none | show normally |
| Session identity | `logical_session_id` | supported (medium) | supported (high) | claude: filename-based logical view; codex lineage parsing | claude falls back to session_id | show, with source-specific tooltip |
| Session identity | `physical_session_id` | unsupported (high) | supported (high) | codex session meta + filename extraction | claude has no physical lineage graph | claude show N/A reason |
| Tokens | `total_input_tokens` | supported (high) | supported (medium) | `message.usage.input_tokens` / token_count events | missing fields follow manifest policy | codex tooltip: derived from rollout token events |
| Tokens | `total_output_tokens` | supported (high) | supported (medium) | usage/output counters | zero/null fill per manifest | same as above |
| Tokens | `cache_read_tokens` | supported (high) | supported (medium) | usage/cache fields | manifest-controlled fallback | show caveat when sparse |
| Tokens | `cache_creation_tokens` | supported (high) | supported (medium) | usage/cache fields | manifest-controlled fallback | show caveat when sparse |
| Tokens | `reasoning_tokens` | unsupported (high) | unsupported (high) | no authoritative field in manifests | N/A | always N/A + reason |
| Tokens | `tool_output_tokens` | partial (medium) | partial (medium) | derived from tool result payload text | approximation only | label as derived |
| Characters | `total_chars` | supported (high) | supported (medium) | parsed text classification | non-text blocks ignored | codex show caveat |
| Characters | `cjk/latin/other` split | supported (high) | supported (medium) | script classifier over normalized text | depends on normalized text availability | show caveat for non-text-heavy sessions |
| Time | `model/tool/user time` | supported (medium) | supported (medium) | timestamp gap attribution | missing timestamp fallback differs by manifest | always show methodology tooltip |
| Time | `inactive_time` | supported (medium) | supported (medium) | inactivity threshold heuristic | threshold-config dependent | show threshold in tooltip |
| Time | `active_time_ratio` | supported (medium) | supported (medium) | derived from time buckets | inherits timestamp caveats | show derived badge |
| Time | `model_timeout_count` | partial (medium) | partial (medium) | gap > model-timeout threshold | no explicit provider event | mark as inferred |
| Throughput | `avg_tokens_per_second` | partial (medium) | partial (low) | token totals / model-active time | denominator quality depends on timestamp fidelity | codex show low-confidence hint |
| Throughput | `read/output/cache token/s` | partial (medium) | partial (low) | per-token-bucket over model-active time | same as above | same as above |
| Tool | `total_tool_calls` | supported (high) | supported (high) | normalized tool_use events | none | show normally |
| Tool | `tool latency` | partial (medium) | partial (medium) | tool_use/tool_result timestamp pairing | batched/shared timestamp caveat | add latency caveat tooltip |
| Tool | `tool error count` | supported (high) | supported (high) | taxonomy classification on tool results | unknown -> uncategorized | show normally |
| Leverage/Yield | `user_yield_ratio_tokens` | partial (medium) | partial (medium) | `(model+tool output tokens)/user input tokens` | null when denominator zero | show N/A on zero-input |
| Leverage/Yield | `user_yield_ratio_chars` | partial (medium) | partial (medium) | char-based ratio | null when denominator zero | show N/A on zero-input |
| Cross-session | `source_breakdown` | supported (high) | supported (high) | aggregated by `ecosystem` | none | show normally |
| Cross-session | `role_source_breakdown` | supported (medium) | supported (medium) | role x ecosystem derived aggregation | inherits role/time/token caveats | include caveat badge |

## Capability Source of Truth

Primary source: `agent_vis/parsers/manifests/*.json`  
Secondary source: parser behavior/tests and `SessionStatistics` computed fields.

If matrix and manifest disagree, treat as a contract bug and fix both in the same PR.

## Required Update Process for New Metrics

When introducing or changing any metric:

1. update parser logic and/or API aggregation implementation
2. update ecosystem capability manifest fields (`agent_vis/parsers/manifests/*.json`) if support semantics changed
3. update this matrix with support state, confidence, source fields, and UI guidance
4. add/update tests:
   - parser/statistics tests
   - API integration tests
   - frontend rendering tests for supported/partial/unsupported behavior
5. update changelog
