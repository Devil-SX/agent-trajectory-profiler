# Changelog

All notable changes to **Agent Trajectory Profiler** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
