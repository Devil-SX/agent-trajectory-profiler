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

- [README.md](README.md) — User guide, installation, usage (EN/CN)
- [ARCHITECTURE.md](ARCHITECTURE.md) — Code map, module descriptions, parser design
- [CHANGELOG.md](CHANGELOG.md) — Version history (Keep a Changelog)
- [docs/claude-jsonl-format.md](docs/claude-jsonl-format.md) — Claude Code JSONL format spec

## Commands

```bash
# Install
uv sync && ./install.sh

# Run dev server (backend + auto-built frontend)
claude-vis serve --reload

# Frontend dev (separate terminal)
cd frontend && npm install && npm run dev

# CLI usage
claude-vis parse --file session.jsonl --human            # Human-readable stats
claude-vis parse --file session.jsonl --human --level 1  # One-line summary
claude-vis parse --file session.jsonl --human --level 3  # Detailed output
claude-vis parse --file session.jsonl                    # JSON output
claude-vis sync                                          # Incremental sync to SQLite
claude-vis sync --force                                  # Force full re-parse
claude-vis stats --level 1                               # DB query: all sessions summary
claude-vis stats --session-id abc123 --level 3           # DB query: one session detailed
claude-vis analyze --file session.jsonl --lang cn        # AI analysis report

# Python tests
uv run pytest                                       # All tests
uv run pytest tests/test_parser.py -v               # Single file
uv run pytest --cov=claude_vis tests/               # With coverage

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
- Custom exceptions: `SessionParseError` in `claude_vis/exceptions.py` (not generic Exception)
- CLI error output goes to stderr (`click.echo(..., err=True)`), data to stdout
- Test fixtures in `tests/conftest.py`, composable; test data dir `tests/fixtures/` is gitignored
- Frontend: strict TypeScript, named exports, props interfaces per component, React Query for all API calls
- Commits: conventional commits (`feat:`, `fix:`, `refactor:`, etc.)
- MCP tools named `mcp__<server>__<method>` are grouped into `<server> (MCP)` for aggregated statistics
- Parser logic lives in `parsers/claude_code.py`; `session_parser.py` is a backward-compatibility shim
- SQLite DB at `~/.claude-vis/profiler.db` (WAL mode); system falls back to in-memory when DB unavailable
