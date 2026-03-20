---
name: trajectory_database
description: 其他程序想要理解 ~/.agent_vis/profiler.db 的格式、字段、可读取信息和 SQL 访问方式时使用。适用于 Claude Code / Codex 等 agent，需要快速判断这个仓库的 SQLite 数据库存了什么、去哪里看 schema、如何直接查询 session、summary、embedding、cluster 等信息。
---

# trajectory_database

Use this skill when an agent needs to understand or query the repository's SQLite metadata database directly, without going through the repository CLI.

The practical source of truth is:

1. `agent_vis/db/schema.py`
2. `agent_vis/db/repository.py`
3. `agent_vis/api/config.py`
4. `tests/test_repository.py`

## Quick Rules

- The repository uses direct `sqlite3 + SQL`. There is no ORM layer to learn first.
- The real default DB path in code is `~/.agent-vis/profiler.db`, defined in `agent_vis/api/config.py`.
- If another tool mentions `~/.agent_vis/profiler.db`, treat that as a user-facing alias or typo until verified. The repo source of truth uses `agent-vis`, not `agent_vis`.
- Another program can read this DB directly with SQLite-compatible libraries in Python, Node.js, Go, Rust, Java, or the `sqlite3` CLI.
- For schema questions, open `agent_vis/db/schema.py` first.
- For query/write behavior, open `agent_vis/db/repository.py` next.
- For expected semantics and examples, inspect `tests/test_repository.py`.

## What This DB Contains

At a high level, the DB stores a materialization chain:

1. tracked source files
2. parsed sessions
3. computed session statistics
4. generated session summaries
5. generated summary embeddings
6. clustering outputs over embeddings

See `references/database_reference.md` for the table map, common queries, and field semantics.

## Minimal Workflow

When asked what can be read from the DB, do this:

1. Confirm the actual DB file path from `agent_vis/api/config.py`.
2. Read `agent_vis/db/schema.py` to list tables, indexes, and migration-added columns.
3. Read `agent_vis/db/repository.py` to see how the project reads and writes those tables.
4. If behavior is ambiguous, confirm with `tests/test_repository.py`.

When asked how another program should access the DB:

- Recommend direct SQLite access.
- Explain that the stable interface is the schema plus SQL query patterns in `repository.py`.
- Mention that API/CLI are optional convenience layers, not the only access path.

## Inspection Commands

Use these commands when local inspection is needed:

```bash
sqlite3 ~/.agent-vis/profiler.db ".tables"
sqlite3 ~/.agent-vis/profiler.db ".schema sessions"
sqlite3 ~/.agent-vis/profiler.db ".schema session_summaries"
sqlite3 ~/.agent-vis/profiler.db "SELECT COUNT(*) FROM sessions;"
sqlite3 ~/.agent-vis/profiler.db "SELECT session_id, created_at, total_tokens FROM sessions ORDER BY created_at DESC LIMIT 20;"
```

For column-level inspection:

```sql
PRAGMA table_info(sessions);
PRAGMA table_info(session_summaries);
PRAGMA table_info(session_summary_embeddings);
```

## Answer Shape

When responding, prefer this structure:

1. actual DB path
2. whether direct SQLite access is supported
3. which tables hold the requested information
4. which repository files are the source of truth
5. one or two concrete SQL examples

Do not claim there is a separate ORM schema or a standalone DB spec unless such a file is actually added later.
