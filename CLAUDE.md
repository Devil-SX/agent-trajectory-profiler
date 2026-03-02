# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Reference

- Language: Python 3.10+ (backend), TypeScript 5.9+ (frontend)
- Package manager: `uv` (Python), `npm` (frontend)
- Test command: `uv run pytest`
- Lint command: `uv run ruff check .`
- Format command: `uv run black .`
- Type check: `uv run mypy .`
- Build command: `uv sync && ./install.sh`

## Project Index

- [README.md](README.md) — User guide, installation, usage (English)
- [README.zh.md](README.zh.md) — User guide, installation, usage (Chinese)
- [ARCHITECTURE.md](ARCHITECTURE.md) — Code map, module descriptions, parser design
- [CHANGELOG.md](CHANGELOG.md) — Version history (Keep a Changelog)
- [docs/claude-jsonl-format.md](docs/claude-jsonl-format.md) — Claude Code JSONL format spec (English)
- [docs/claude-jsonl-format.zh.md](docs/claude-jsonl-format.zh.md) — Claude Code JSONL format spec (Chinese)
- [docs/output-levels.md](docs/output-levels.md) — Output detail levels guide (L1/L2/L3)
- [docs/agent-vis-home-layout.md](docs/agent-vis-home-layout.md) — `~/.agent-vis` local directory naming and permission specification
- [docs/agent-capability-manifest.md](docs/agent-capability-manifest.md) — Capability manifest schema, compatibility rules, examples, and onboarding checklist

## Commands

```bash
# Install
uv sync && ./install.sh

# Run dev server (backend + auto-built frontend)
agent-vis serve --reload                    # Auto-finds available port if 8000 is taken
agent-vis serve --reload --port 8080        # Use specific port (fails if taken)

# Frontend dev (separate terminal)
cd frontend && npm install && npm run dev    # Auto-finds available port if 5173 is taken

# CLI usage
agent-vis parse --file session.jsonl --human            # Human-readable stats
agent-vis parse --file session.jsonl --human --level 1  # One-line summary
agent-vis parse --file session.jsonl --human --level 3  # Detailed output
agent-vis parse --file session.jsonl                    # JSON output
agent-vis sync                                          # Incremental sync to SQLite
agent-vis sync --force                                  # Force full re-parse
agent-vis stats --level 1                               # DB query: all sessions summary
agent-vis stats --session-id abc123 --level 3           # DB query: one session detailed
agent-vis analyze --file session.jsonl --lang cn        # AI analysis report

# Python tests
uv run pytest                                       # All tests
uv run pytest tests/test_parser.py -v               # Single file
uv run pytest --cov=agent_vis tests/               # With coverage

# Frontend E2E tests
cd frontend && npm run test:e2e

# Lint & format
uv run ruff check .              # Lint (--fix to auto-fix)
uv run black .                   # Format (line length 100)
uv run mypy .                    # Type check (strict, disallow_untyped_defs)
cd frontend && npm run lint      # ESLint
cd frontend && npm run type-check  # tsc --noEmit
cd frontend && npm run format    # Prettier
```

## Development Notes

- Python: type hints required everywhere, `ruff` + `black` (100 char lines), Pydantic v2 models
- Private functions: `_leading_underscore()`
- Custom exceptions: `SessionParseError` in `agent_vis/exceptions.py` (not generic Exception)
- CLI error output goes to stderr (`click.echo(..., err=True)`), data to stdout
- Test fixtures in `tests/conftest.py`, composable; test data dir `tests/fixtures/` is gitignored
- Frontend: strict TypeScript, named exports, props interfaces per component, React Query for all API calls
- Commits: conventional commits (`feat:`, `fix:`, `refactor:`, etc.)
- MCP tools named `mcp__<server>__<method>` are grouped into `<server> (MCP)` for aggregated statistics
- Parser logic lives in `parsers/claude_code.py`; `session_parser.py` is a backward-compatibility shim
- SQLite DB at `~/.agent-vis/profiler.db` (WAL mode); system falls back to in-memory when DB unavailable
- **VS Code Tasks**: When adding new commands or changing server startup, update `.vscode/tasks.json` to keep IDE launch configurations in sync
