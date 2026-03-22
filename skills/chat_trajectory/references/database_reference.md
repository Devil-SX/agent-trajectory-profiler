# Database Reference

This repository uses SQLite as a local metadata store. The implementation style is direct SQL through Python's `sqlite3` module.

## Source of Truth Files

Read these in order:

1. `agent_vis/api/config.py`
   - Defines the default DB path: `~/.agent-vis/profiler.db`
2. `agent_vis/db/schema.py`
   - Defines tables, indexes, foreign keys, and migration-added columns
3. `agent_vis/db/repository.py`
   - Defines the actual query and persistence patterns
4. `tests/test_repository.py`
   - Shows usage examples and expected behavior

## Core Tables

### `tracked_files`

Purpose:
- Records discovered source files that were parsed into sessions

Important fields:
- `id`
- `file_path`
- `file_size`
- `file_mtime`
- `ecosystem`
- `last_parsed_at`
- `parse_status`

What you can learn:
- which source JSONL/state files were ingested
- parse freshness
- parse success/error status

### `sessions`

Purpose:
- Main session metadata table

Important fields:
- `session_id`
- `physical_session_id`
- `logical_session_id`
- `parent_session_id`
- `root_session_id`
- `file_id`
- `ecosystem`
- `project_path`
- `git_branch`
- `created_at`
- `updated_at`
- `parsed_at`
- `total_messages`
- `total_tokens`
- `duration_seconds`
- `total_tool_calls`
- `bottleneck`
- `automation_ratio`
- `version`
- `git_sha`
- `cli_version`
- `title`
- `first_user_message`
- `model_provider`
- `session_source`
- `is_archived`

What you can learn:
- session lineage
- source ecosystem such as Claude/Codex
- timing and token usage
- project and branch metadata
- coarse automation and bottleneck analysis

### `session_statistics`

Purpose:
- Stores computed statistics payloads per session

Important fields:
- `session_id`
- `statistics_json`
- `computed_at`

What you can learn:
- richer computed analytics serialized as JSON

### `session_summaries`

Purpose:
- Stores persisted AI-generated summaries for sessions

Important fields:
- `session_id`
- `synopsis_hash`
- `prompt_version`
- `model_id`
- `generation_status`
- `summary_text`
- `summary_chars`
- `generated_at`
- `error_message`

What you can learn:
- whether a summary exists
- which model and prompt version produced it
- the persisted summary text
- failure state if generation failed

### `session_summary_embeddings`

Purpose:
- Stores vectorized embeddings derived from completed summaries

Important fields:
- `session_id`
- `summary_hash`
- `model_id`
- `provider_name`
- `generation_status`
- `embedding_dimension`
- `vector_json`
- `generated_at`
- `error_message`

What you can learn:
- whether embedding materialization has completed
- which embedding model/provider was used
- the serialized embedding vector

Notes:
- `vector_json` is stored as JSON text, not a native vector column
- downstream code deserializes it with JSON parsing

### `session_cluster_runs`

Purpose:
- Stores clustering run metadata for the latest embedding clustering snapshot

Important fields:
- `run_id`
- `generated_at`
- `algorithm`
- `algorithm_version`
- `source_model_id`
- `similarity_threshold`
- `session_count`
- `cluster_count`

### `session_cluster_memberships`

Purpose:
- Stores per-session cluster assignment for a clustering run

Important fields:
- `run_id`
- `cluster_id`
- `session_id`

What you can learn from clustering tables:
- which run produced the current grouping
- which sessions belong to which cluster

## Repository Query Style

The repo does not use an ORM. It uses plain SQL with parameter binding and explicit transactions.

Typical patterns:

- point lookup
```sql
SELECT * FROM sessions WHERE session_id = ?;
```

- upsert with conflict handling
```sql
INSERT INTO session_summaries (...)
VALUES (...)
ON CONFLICT(session_id) DO UPDATE SET ...;
```

- filtered materialization query
```sql
SELECT session_id, summary_text, synopsis_hash, prompt_version, model_id
FROM session_summaries
WHERE generation_status = 'completed'
  AND summary_text IS NOT NULL
  AND TRIM(summary_text) != '';
```

## Common Questions and SQL

### List recent sessions

```sql
SELECT session_id, ecosystem, created_at, total_messages, total_tokens
FROM sessions
ORDER BY created_at DESC
LIMIT 20;
```

### Find sessions for one project

```sql
SELECT session_id, created_at, git_branch, title
FROM sessions
WHERE project_path = ?
ORDER BY created_at DESC;
```

### Check which sessions already have summaries

```sql
SELECT s.session_id, s.created_at, ss.generation_status, ss.model_id, ss.generated_at
FROM sessions s
LEFT JOIN session_summaries ss ON ss.session_id = s.session_id
ORDER BY s.created_at DESC
LIMIT 50;
```

### Read completed summaries

```sql
SELECT session_id, model_id, summary_text, generated_at
FROM session_summaries
WHERE generation_status = 'completed'
ORDER BY generated_at DESC;
```

### Read completed embeddings

```sql
SELECT session_id, model_id, provider_name, embedding_dimension, vector_json
FROM session_summary_embeddings
WHERE generation_status = 'completed';
```

### Read clustering assignments

```sql
SELECT m.run_id, m.cluster_id, m.session_id, r.algorithm, r.generated_at
FROM session_cluster_memberships m
JOIN session_cluster_runs r ON r.run_id = m.run_id
ORDER BY r.generated_at DESC, m.cluster_id, m.session_id;
```

## Practical Guidance For Other Programs

- Another program can use this DB directly with SQLite.
- The safest contract is read-only SQL unless that program intentionally participates in the same materialization flow.
- If writing into this DB, mirror the repository's field meanings and upsert behavior in `agent_vis/db/repository.py`.
- Do not assume every string column has strict enum validation at the DB layer. Some semantics live in repository code.
- Treat `schema.py` plus `repository.py` as the effective database interface documentation.

## Important Path Clarification

The repository code uses:

```text
~/.agent-vis/profiler.db
```

If a user or another tool refers to:

```text
~/.agent_vis/profiler.db
```

verify whether that is:
- a typo
- a wrapper-level alias
- a copied path from external notes

Do not silently state that underscore form is the repository default unless the code has changed.
