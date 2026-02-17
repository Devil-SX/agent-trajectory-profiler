# Agent Trajectory Profiler

Visualize and analyze Claude Code agent sessions — run as a **web dashboard** or use **headless CLI** for batch processing.

Parses `.jsonl` session files from `~/.claude/projects/`, computes analytics (message stats, tool usage, token consumption, subagent tracking), and presents them through an interactive React frontend or structured JSON output.

## Installation

### Prerequisites

- Python 3.10+
- [UV](https://github.com/astral-sh/uv) package manager
- Node.js 18+ (only needed for web dashboard)

### Install globally

```bash
git clone https://github.com/Devil-SX/agent-trajectory-profiler.git
cd agent-trajectory-profiler
uv sync
./install.sh
```

After installation, `claude-vis` is available globally from any directory.

To uninstall:
```bash
./uninstall.sh
```

### Install locally (without global command)

```bash
git clone https://github.com/Devil-SX/agent-trajectory-profiler.git
cd agent-trajectory-profiler
uv sync
```

Use `uv run claude-vis` instead of `claude-vis` in all commands below.

## Usage

### Mode 1: Web Dashboard (`serve`)

Start a web server with an interactive visualization UI.

```bash
claude-vis serve
```

Opens at `http://localhost:8000` with:
- Session list with search and sorting
- Message timeline (user/assistant conversation flow)
- Subagent visualization with status indicators
- Statistics dashboard: message counts, tool usage charts, token consumption, timing heatmaps
- Responsive layout for desktop/tablet/mobile

**Options:**

```bash
claude-vis serve --port 8080                    # custom port
claude-vis serve --path /path/to/sessions       # custom session directory
claude-vis serve --single-session abc123        # load one session only
claude-vis serve --reload --log-level debug     # dev mode with hot reload
```

Frontend is auto-built on first run (requires Node.js). API docs available at `/docs`.

### Mode 2: Headless CLI (`parse`)

Parse session data and output structured JSON — no server, no browser needed.

```bash
claude-vis parse
```

Reads all `.jsonl` files from `~/.claude/projects/` and writes JSON to stdout.

**Options:**

```bash
claude-vis parse --pretty                          # human-readable output
claude-vis parse --output sessions.json            # write to file
claude-vis parse --path /path/to/sessions --pretty # custom directory
claude-vis parse --pretty | jq '.sessions[0]'      # pipe to jq
```

This mode is useful for:
- Scripting and automation pipelines
- Batch processing multiple sessions
- Exporting data for external analysis tools
- CI/CD integration

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) for developer documentation.

## API Endpoints

When running in `serve` mode:

| Endpoint | Description |
|---|---|
| `GET /api/sessions` | List all sessions |
| `GET /api/sessions/{id}` | Session detail with messages and subagents |
| `GET /api/sessions/{id}/statistics` | Computed analytics for a session |
| `GET /health` | Health check |
| `GET /docs` | Interactive Swagger UI |

## Development

```bash
# Backend with hot reload
claude-vis serve --reload --log-level debug

# Frontend dev server (separate terminal)
cd frontend && npm run dev

# Run tests
uv run pytest

# Lint & format
uv run ruff check .
uv run black .
uv run mypy .
```

## License

MIT
