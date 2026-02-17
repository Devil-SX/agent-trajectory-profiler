# Changelog

All notable changes to **Agent Trajectory Profiler** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
