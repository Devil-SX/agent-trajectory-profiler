# Architecture

Developer documentation for the Agent Trajectory Profiler.

## Data Flow

```
.jsonl session files
    → SessionParser (claude_vis/parsers/session_parser.py)
    → Pydantic models (claude_vis/models.py)
    → FastAPI API (claude_vis/api/)
    → React frontend (frontend/)
```

## Model Hierarchy

```
MessageRecord          # Single JSONL line from a session file
  → Session            # All messages + metadata + subagent sessions
    → SessionStatistics  # Computed analytics
      → TimeBreakdown     # Model / tool / user time attribution
      → TokenBreakdown    # Input / output / cache token percentages
      → ToolCallStatistics # Per-tool counts, tokens, latency, errors
```

## Parser Design

The parser in `session_parser.py` uses a **single-pass loop** over all messages:

1. **Message counting** — user, assistant, system counts
2. **Token accumulation** — input, output, cache read, cache creation
3. **Tool tracking** — `tool_use_map` maps `tool_use_id → (tool_name, timestamp)`. When a matching `tool_result` arrives, latency is computed as `result_timestamp - use_timestamp` and accumulated per-tool.
4. **Time attribution** — For each message, the gap from the previous message's timestamp is attributed:
   - Gap → assistant message: **model inference time**
   - Gap → user message with `tool_result` content: **tool execution time**
   - Gap → user message without `tool_result`: **user idle time**
   - Negative gap: skipped (out-of-order timestamps)
5. **Post-loop** — `TimeBreakdown` and `TokenBreakdown` are built from accumulators, per-tool avg latency computed.

## API Layer

- **FastAPI app**: `claude_vis/api/app.py`
- **Configuration**: `claude_vis/api/config.py` (Settings with environment variable overrides)
- **Session service**: `claude_vis/api/services/session_service.py` (caching, session lookup)
- **Endpoints**:
  - `GET /api/sessions` — paginated session list
  - `GET /api/sessions/{id}` — full session detail with messages
  - `GET /api/sessions/{id}/statistics` — computed statistics (includes `time_breakdown`, `token_breakdown`)
  - `GET /health` — health check

## Frontend

- **React 19** + TypeScript + Recharts + TailwindCSS 4
- **Component tree**:
  - `App` → `SessionList` + `SessionDetail` (messages, subagents) + `StatisticsDashboard` + `AdvancedAnalytics`
- **React Query hooks** (`useSessionsQuery.ts`) for data fetching with caching
- **`analyticsComputer.ts`** — client-side derivation of heatmaps, expensive operations, tool patterns, bottlenecks, recommendations
- **`exportData.ts`** — CSV/JSON export of statistics and analytics

## Time Metric Caveats

- **Batched tool calls**: When the assistant invokes multiple tools in a single message, all `tool_use` blocks share the same message timestamp. The latency computed for each tool reflects the gap from that shared timestamp to the `tool_result` message, which may overcount for the first tools in a batch.
- **Subagent timing**: Subagent messages are interleaved in the main message stream. Time attribution treats them the same as main-session messages, so subagent time is folded into the model/tool/user buckets rather than tracked separately.
- **User idle time**: Includes any time the user spends reading output, thinking, or is AFK. It does not distinguish active thinking from idle time.
