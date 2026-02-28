# Changelog

All notable changes to **Agent Trajectory Profiler** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Canonical `agent_vis` Python package namespace mirroring existing `claude_vis` modules via compatibility wrappers.
- Canonical `agent-vis` CLI entry point in `pyproject.toml`, while preserving `claude-vis` for backward compatibility.
- Installation/uninstallation scripts now manage both global commands (`agent-vis` canonical, `claude-vis` legacy alias).
- Namespace compatibility regression tests to ensure canonical and legacy imports expose equivalent symbols.
- Canonical parser middle layer (`claude_vis.parsers.canonical`) with adapter contract (`TrajectoryEventAdapter`), neutral event models (`CanonicalEvent` / `CanonicalSession`), and ecosystem adapter registry.
- Canonical conversion contract tests covering registry extension, source-to-canonical normalization, and canonical-to-message compatibility behavior.
- New `CodexParser` with Codex rollout adapter for local files under `~/.codex/sessions/**/rollout-*.jsonl`.
- Mixed-ecosystem API/session tests covering Codex fixture ingestion and `/api/sessions?ecosystem=` filtering.
- Rule-based tool error taxonomy module (`claude_vis.parsers.error_taxonomy`) with versioned categories and `uncategorized` fallback for unmatched failures.
- Session-level tool error timeline records (`timestamp`, `tool_name`, `category`, `matched_rule`, `preview`, `detail`) and per-category counters in `SessionStatistics`.
- Regression fixtures/tests for taxonomy precision and fallback behavior (`tests/fixtures/error_taxonomy_examples.json`, `tests/test_error_taxonomy.py`).
- Playwright smoke tests for tool error timeline rendering, expand/collapse details, and table scroll-container behavior on metrics dashboard.
- Compact session table mode in session browser with row-based selection, ecosystem column, and dense cross-session scan layout.
- Active-time analytics enhancements: explicit `active_time_ratio` in session time breakdown and cross-session overview API payloads.
- Trajectory file-size and character analytics (`character_breakdown`) for per-session statistics and cross-session aggregates.
- User-efficiency yield ratios for tokens/chars (`user_yield_ratio_tokens`, `user_yield_ratio_chars`) with cross-session mean/median/p90 aggregates.
- Model throughput metrics (`tok/s`) for average/read/output/cache rates plus cache-read/cache-creation splits at session and cross-session levels.
- Sync control capability: new `POST /api/sync/run` endpoint plus expanded `GET /api/sync/status` payload with last-run detail (`parsed/skipped/errors`), per-ecosystem stats, and scanned file sizes.
- Session browser sync panel with manual trigger button, last sync timestamp, and Claude/Codex breakdown cards.
- Playwright smoke coverage for sync panel rendering and manual sync trigger flow (`tests/sync-control.spec.ts`).
- CI frontend jobs (`frontend-static-checks`, `frontend-e2e-smoke`) and `npm run test:e2e:smoke` script.
- Playwright smoke coverage for IA refactor: cross-session access without session preselection, tab/session state persistence, and session list view preference persistence.
- Playwright smoke coverage for readability upgrades: readable project rendering in session table and copy-to-clipboard behavior for session IDs.
- Cross-session day/night analytics fields in `/api/analytics/overview` with fixed local-night window (`01:00-09:00`) and per-category (`model/tool/user/inactive`) duration buckets.
- Playwright smoke coverage for day/night analytics rendering and chart/table consistency checks (`tests/day-night-analytics.spec.ts`).
- Leverage analytics API fields for session/cross-session views (`leverage_ratio_*`, `leverage_*_mean|median|p90`) plus aggregated `total_tool_output_tokens`.
- Project-level leverage aggregates in cross-session overview (`top_projects[*].leverage_tokens_mean`, `leverage_chars_mean`) for per-project comparison.
- New analytics APIs for project-level exploration: `GET /api/analytics/project-comparison` and `GET /api/analytics/project-swimlane`.
- Cross-session project swimlane E2E coverage with project filtering and mobile usability assertions (`tests/project-swimlane.spec.ts`).
- Theme-mode persistence and runtime resolution (`system` / `light` / `dark`) via app-level controls and `localStorage`.
- New Playwright theme regressions (`@visual`) with light and dark baselines, plus accessibility assertions (`@a11y`) for keyboard focus visibility and text contrast.
- Nightly frontend workflow (`frontend-e2e-full`, `frontend-visual-regression`, `frontend-a11y`) to enforce non-smoke quality gates.
- Two-layer navigation E2E coverage for overview-first flow, table drill-down, browser back/forward, and URL deep-link restore (`tests/tab-navigation.spec.ts`).
- Session table UX regression coverage for semantic tags and default table behavior across smoke/visual/accessibility suites.
- Cross-session source-segmentation coverage for ecosystem-specific breakdowns (`codex` vs `claude_code`) across backend integration and frontend smoke/visual tests.

### Changed

- API branding and metadata text to ecosystem-neutral naming (`Agent Trajectory Visualizer API`) instead of Claude-only wording.
- CLI user-facing branding and examples now prefer `agent-vis` as canonical command.
- README (EN/CN) now includes explicit migration notes and deprecation path for `claude_vis` -> `agent_vis`.
- Claude parser ingestion path now uses the canonical adapter pipeline (`JSONL -> CanonicalEvent -> MessageRecord`) without changing downstream statistics logic.
- Session sync and service initialization now support mixed local roots (Claude + Codex), and session list responses now expose ecosystem metadata.
- Statistics dashboard now includes taxonomy-aware tool error timeline table with category chips and expandable raw error detail rows.
- Session browser supports explicit card/table mode toggle while reusing existing search/sort/date filters and selection behavior in both views.
- Time breakdown visualization now presents Model/Tool/User metric cards, excludes inactive time from pie-chart denominator, and displays active-time ratio directly.
- Resource views now surface trajectory bytes and mixed-language character metrics (CJK/Latin plus user/model/tool attribution) in both session and cross-session dashboards.
- Automation panels now expose per-session and aggregated token/char yield ratios to measure output efficiency per unit of user input.
- Model analytics panels now expose mean/median/p90 throughput with explicit `tok/s` units and denominator semantics (model active time).
- Session browser now renders sync controls across loading/error/empty/data states so sync remains accessible regardless list state.
- Backend formatting baseline has been normalized with Black so CI format checks run consistently across Python versions.
- `mypy` CI now applies targeted overrides for legacy high-debt modules and tests, keeping type checks active on maintained paths while avoiding unrelated blockers.
- App navigation now separates `Session Detail` from `Cross-Session Analytics`, and cross-session analytics is available without requiring a selected session.
- Session list default view is now `Table View` and persists user preference via local storage across reloads.
- Frontend labels and E2E expectations now consistently use `Cross-Session Analytics` instead of `Advanced Analytics`.
- Session table now prioritizes human-readable project names and unified relative+absolute timestamp formatting, with session ID/hash downgraded to a compact copyable field.
- Cross-session token-share chart now truncates long session labels for readability while preserving full values in tooltip context.
- Cross-session overview now includes a dedicated Day vs Night section (stacked chart + table) with explicit local-time night-window labeling.
- Session and cross-session UI copy now uses "Leverage" terminology, with a configurable code-capacity estimate card (assumption-based, non-exact).
- Cross-session analytics now includes interactive multi-project comparison controls and a project swimlane heatmap with tooltip, no-data state, and large-project truncation hint.
- Unified design-token theming across app shell and critical analytics surfaces (`App`, `SessionBrowser`, `StatisticsDashboard`, `CrossSessionOverview`) with consistent light/dark contrast behavior.
- App information architecture now defaults to an overview layer (cross-session analytics + session table) and drills down to session detail via row click with explicit back navigation and URL state (`view`/`session`/`tab`).
- Overview layout now renders advanced cross-session analytics above the session table to enforce top-down global-to-detail scanning flow.
- Session table rows now render semantic color tags for ecosystem, bottleneck, and automation bands with theme-safe contrast in light/dark modes.
- Cross-session overview now exposes and visualizes source-level aggregates with dedicated ecosystem distribution chart and comparison table.

### Fixed

- Session statistics API payload now includes computed `average_tokens_per_message`, restoring full-stack round-trip compatibility.
- Integration test settings patching now targets the API app module object directly, fixing Python 3.10 compatibility for API/full-stack test fixtures.
- Session detail timeline no longer auto-jumps to the bottom on entry/session switch; default behavior now starts at top with an explicit "Jump to latest" action.

## [0.6.0] - 2026-02-26

> **Code Stats** | Total: 44,586 lines | Delta: +11,705 (-1,920) = **+9,785 net** | Change: **+28.8%** vs v0.3.0

### Added

- Cross-session analytics API endpoints: `GET /api/analytics/overview`, `/api/analytics/distributions`, and `/api/analytics/timeseries` with default last-7-days range normalization.
- New analytics response schemas and service aggregation logic for bottleneck distribution, project/tool rollups, and time-series trends.
- Frontend cross-session overview panel in Advanced Analytics with range presets (7/30/90/custom), KPI cards, distribution charts, trend charts, and top project/tool/session-share tables.
- Frontend API client and React Query hooks for cross-session analytics (`fetchAnalyticsOverview`, `fetchAnalyticsDistribution`, `fetchAnalyticsTimeseries` and matching hooks/query keys).
- Integration tests for analytics endpoints covering default date window behavior, explicit range queries, weekly interval, and invalid parameter handling.

### Changed

- Reorganized single-session metrics into user-oriented dimensions: Automation & Interaction, Tool Execution, Time & Stability, and Resource Consumption.
- Refactored session browser interaction model: comparison session pick/clear controls, automatic selection recovery after filtering, and improved state messaging.
- Updated session list virtualization to use responsive container-measured height instead of fixed list height.
- Improved global frontend layout and scrolling behavior by removing rigid viewport locks and nested overflow constraints that could truncate content.
- Improved session card readability and accessibility with semantic button interaction and dual relative/absolute timestamp display.
- Expanded `.gitignore` to ignore local generated artifacts (`.sisyphus/`, Playwright test outputs).

### Fixed

- Metrics/statistics page viewport clipping and missing-scroll scenarios on smaller screens and constrained desktop windows.
- Multi-panel frontend overflow behavior that could hide portions of analytics content.

## [0.5.0] - 2026-02-26

> **Code Stats** | Total: 43,421 lines | Delta: +9,864 (-1,467) = **+8,397 net** | Change: **+24.6%** vs v0.3.0

### Added

- **Configurable inactivity threshold**: `--inactivity-threshold` CLI option on `parse` and `sync` commands (default 1800s). Also configurable via `CLAUDE_VIS_INACTIVITY_THRESHOLD` env var and API settings.
- **Model inference timeout detection**: flag gaps before assistant messages exceeding a threshold (default 600s) as model timeouts. New `model_timeout_count` and `model_timeout_threshold_seconds` fields on `TimeBreakdown`. CLI option `--model-timeout` on `parse` and `sync`.
- **Session Browser UI** replacing dropdown selection with virtualized session cards, search, sort, bottleneck filter, and date-range filtering controls.
- New dashboard components: `BashCommandTable`, `BottleneckInsight`, `TimeBreakdownChart`, and `MetricComparison`.
- `GET /api/sessions` now supports `start_date` / `end_date` filtering with format validation.
- DB migration script `claude_vis/db/migrations/add_version_column.py` and persisted `version` field in session summaries.
- `docs/output-levels.md` documenting `--human --level 1/2/3` output format with examples
- `docs/port-handling.md` documenting backend/frontend port conflict behavior and troubleshooting
- Features section with Mermaid data-flow diagram in both READMEs
- Model timeout display in `--human` output (Time Breakdown section, shown when count > 0)
- Tests for custom inactivity threshold and model timeout detection (`test_statistics.py`)
- New Playwright suites for session browser, card interactions, filtering, date range, loading flow, and tab navigation.

### Changed

- Split bilingual `README.md` into `README.md` (English) + `README.zh.md` (Chinese) with hyperlink switcher
- Split `docs/claude-jsonl-format.md` into English + Chinese (`docs/claude-jsonl-format.zh.md`) with hyperlink switcher
- Updated CLAUDE.md Project Index with split file references and output-levels doc
- Replaced `SessionSelector` with `SessionBrowser` in the frontend app shell.
- `ClaudeCodeParser.__init__` now accepts `inactivity_threshold` and `model_timeout_threshold` params
- `calculate_session_statistics()`, `parse_session_file()`, `parse_session_directory()` accept threshold keyword args
- `SessionService` threads thresholds from API settings to parser
- Backend `serve` command now auto-finds an available port when default port is occupied; explicit `--port` remains strict.
- Frontend Vite dev server configured for non-strict port fallback during development.

## [0.4.0] - 2026-02-24

### Added

- **SQLite persistence layer** (`claude_vis/db/`): incremental file detection via mtime + size, WAL-mode connection management, `SessionRepository` CRUD, `SyncEngine` for batch sync
- `sync` CLI command: scan session directories, detect new/changed files, parse and persist to SQLite (`~/.claude-vis/profiler.db`)
- `stats` CLI command: query session statistics from the database with `--session-id`, `--level`, `--sort-by`, `--limit`
- `--level [1|2|3]` flag on `parse` command for output detail control (summary/standard/detailed)
- `GET /api/sync/status` endpoint returning sync database status
- `TrajectoryParser` ABC (`parsers/base.py`) defining the interface for ecosystem-specific parsers
- `ClaudeCodeParser` class (`parsers/claude_code.py`) wrapping existing parser functions into the ABC
- Parser registry (`parsers/registry.py`) with `register_parser()` / `get_parser()` for ecosystem extensibility
- Multi-level formatters (`formatters/human.py`): `OutputLevel` enum (SUMMARY/STANDARD/DETAILED) and `format_session_stats()`
- `exceptions.py` centralizing `SessionParseError`
- `SessionSummary` fields: `parsed_at`, `duration_seconds`, `bottleneck`, `automation_ratio`
- Frontend: session dropdown now shows duration and bottleneck labels
- Core Methodology section in README (EN/CN): Time Attribution, Bottleneck Analysis, Automation Ratio, Output Levels
- `test_repository.py` (13 tests) and `test_sync.py` (9 tests)

### Changed

- `api/service.py`: rewritten to read from SQLite with in-memory fallback
- `api/app.py`: passes `db_path` to service, auto-syncs on empty DB
- `session_parser.py` → backward-compatibility shim re-exporting from `parsers/claude_code.py`
- `cli/main.py`: extracted formatting logic to `formatters/human.py`
- `analyze` CLI subcommand: invoke `claude -p` headless to generate AI-powered Markdown analysis reports with bottleneck analysis, automation degree rating, and improvement recommendations
- `claude_vis/prompts/` module with EN/CN prompt templates and `build_analyze_prompt()` function
- `--model`, `--lang`, `--output` options for `analyze` command
- Bilingual README (English + Chinese) with language switcher
- Updated CLAUDE.md, ARCHITECTURE.md with new package structure

### Removed

- `api/main.py` (dead code)

## [0.3.0] - 2026-02-18

### Added

- Bash command breakdown: parse sub-commands from Bash tool calls by splitting on shell operators (`&&`, `||`, `;`, `|`) with quote-aware parsing
- Per-command statistics: count, latency (distributed equally among sub-commands per call), and output character count for each extracted command name
- `BashCommandStats` and `BashBreakdown` models with `total_latency_seconds`, `avg_latency_seconds`, `total_output_chars`, `avg_output_chars` fields
- `bash_breakdown` field on `SessionStatistics` with commands-per-call distribution and ranked command stats
- Auto-compact event detection: extract `compact_boundary` system messages from raw JSONL with trigger type and pre-compact token count
- `CompactEvent` model and `compact_count` / `compact_events` fields on `SessionStatistics`
- `extract_compact_events()` parser function for reading compact metadata directly from JSONL (bypasses `MessageRecord` validation since `type: "system"` is not in `MessageType`)
- CLI `--human` output: Bash Breakdown section with commands/call distribution, top 10 commands table (count, latency, output), and Auto Compacts count
- `_format_chars()` CLI helper for human-readable character counts (e.g., `100.9K`)
- `_split_bash_on_operators()` and `_parse_bash_sub_commands()` parser helpers with quote-aware shell command splitting
- Frontend TypeScript interfaces: `CompactEvent`, `BashCommandStats`, `BashBreakdown`
- `.gitignore` entry for `tests/fixtures/*.jsonl` (private session data)

## [0.2.0] - 2026-02-17

### Added

- Time breakdown metrics: model inference time, tool execution time, and user idle time computed from message timestamp diffs
- Token breakdown percentages: input, output, cache read, and cache creation as fraction of all tokens
- Per-tool average latency tracking in `ToolCallStatistics` (`avg_latency_seconds`, `total_latency_seconds`)
- Inactivity threshold (30 min) to separate active work from AFK/sleep gaps; inactive time reported separately from model/tool/user time
- Active time statistics: `total_active_time_seconds`, `user_interaction_count`, `interactions_per_hour` in `TimeBreakdown`
- MCP tool grouping: `tool_group` field on `ToolCallStatistics` and `ToolGroupStatistics` model for aggregating tools by MCP server (e.g., all WaveTool methods grouped as "WaveTool (MCP)")
- Tool Groups (MCP) section in CLI `--human` output showing aggregated multi-tool groups
- Time Breakdown PieChart in StatisticsDashboard (Model / Tool / User, with inactive time note)
- Avg Latency column in tool statistics tables (CLI, StatisticsDashboard, AdvancedAnalytics)
- Bottleneck identification in CLI output (highest time category)
- Time-based bottleneck detection in AdvancedAnalytics (warns when a category exceeds 60%)
- Time breakdown and latency data in CSV/JSON exports
- `ARCHITECTURE.md` developer documentation covering data flow, model hierarchy, parser design, API layer, frontend, and time metric caveats
- `docs/claude-jsonl-format.md` documenting Claude Code JSONL session format and processing approach
- `install.sh` and `uninstall.sh` for global CLI installation
- `output/` added to `.gitignore`

### Changed

- CLI `--human` tokens section now shows percentage next to each token count
- CLI tool calls table reformatted with aligned columns (Tool, Count, Avg Lat, Errors)
- CLI MCP tool names shortened to method name only in individual tool table
- CLI time breakdown shows active time header, inactive time row, and interaction rate
- Token distribution pie chart in StatisticsDashboard now includes cache tokens when present
- Duration stat card shows model/tool/user time percentages when available
- Active-time percentages computed over active time only (excluding inactive gaps)
- README.md project structure section replaced with link to ARCHITECTURE.md

## [0.1.0] - 2026-02-04

### Added

- **US-001**: Project setup with UV environment, pyproject.toml, and dependency management
- **US-002**: Session data parser schema with Pydantic models for messages, subagents, and sessions
- **US-003**: Session file parser CLI for reading `.jsonl` session files
- **US-004**: Session statistics calculator for computing analytics from parsed data
- **US-005**: Web backend API setup with FastAPI, REST endpoints, and CORS support
- **US-006**: Frontend project setup with React 19, TypeScript, Vite, and TailwindCSS 4
- **US-007**: Session selector component for browsing and filtering sessions
- **US-008**: Message timeline UI component with chronological message display
- **US-009**: Subagent session visualization with status indicators
- **US-010**: Session metadata sidebar with overview panel
- **US-011**: Statistics dashboard panel with message stats, token usage, and tool usage charts
- **US-012**: Tool call visualization with execution counts and success/failure rates
- **US-013**: Advanced analytics features including timeline charts and heatmaps
- **US-014**: Responsive layout implementation for desktop, tablet, and mobile
- **US-015**: Playwright visual testing for E2E UI validation
- **US-016**: CLI integration mode (`serve` and `parse` subcommands)
- **US-017**: Error handling and user feedback with graceful error messages
- **US-018**: Documentation and README
- **US-019**: End-to-end integration testing
- **US-020**: Performance optimization
