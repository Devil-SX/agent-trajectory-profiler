"""SQLite DDL and table creation."""

import sqlite3

_DDL = """\
CREATE TABLE IF NOT EXISTS tracked_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path   TEXT    UNIQUE NOT NULL,
    file_size   INTEGER NOT NULL,
    file_mtime  REAL    NOT NULL,
    ecosystem   TEXT    NOT NULL DEFAULT 'claude_code',
    last_parsed_at TEXT,
    parse_status   TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id       TEXT PRIMARY KEY,
    physical_session_id TEXT,
    logical_session_id  TEXT,
    parent_session_id   TEXT,
    root_session_id     TEXT,
    file_id          INTEGER REFERENCES tracked_files(id),
    ecosystem        TEXT,
    project_path     TEXT,
    git_branch       TEXT,
    created_at       TEXT,
    updated_at       TEXT,
    total_messages   INTEGER,
    total_tokens     INTEGER,
    parsed_at        TEXT,
    duration_seconds REAL,
    total_tool_calls INTEGER,
    bottleneck       TEXT,
    automation_ratio REAL,
    version          TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS session_statistics (
    session_id      TEXT PRIMARY KEY,
    statistics_json TEXT NOT NULL,
    computed_at     TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS session_summaries (
    session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
    synopsis_hash TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model_id TEXT NOT NULL,
    generation_status TEXT NOT NULL,
    summary_text TEXT,
    summary_chars INTEGER,
    generated_at TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_session_summaries_status ON session_summaries(generation_status);

CREATE TABLE IF NOT EXISTS session_summary_embeddings (
    session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
    summary_hash TEXT NOT NULL,
    model_id TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    generation_status TEXT NOT NULL,
    embedding_dimension INTEGER,
    vector_json TEXT,
    generated_at TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_session_summary_embeddings_status
    ON session_summary_embeddings(generation_status);
CREATE INDEX IF NOT EXISTS idx_session_summary_embeddings_model
    ON session_summary_embeddings(model_id);

CREATE INDEX IF NOT EXISTS idx_sessions_created_at  ON sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_updated_at  ON sessions(updated_at);
CREATE INDEX IF NOT EXISTS idx_sessions_parsed_at   ON sessions(parsed_at);
CREATE INDEX IF NOT EXISTS idx_sessions_logical_id  ON sessions(logical_session_id);
CREATE INDEX IF NOT EXISTS idx_tracked_files_path   ON tracked_files(file_path);
"""


def _ensure_sessions_columns(conn: sqlite3.Connection) -> None:
    """Backfill newly introduced session columns for existing databases."""
    cur = conn.execute("PRAGMA table_info(sessions)")
    existing_columns = {row[1] for row in cur.fetchall()}
    required_columns: dict[str, str] = {
        "physical_session_id": "TEXT",
        "logical_session_id": "TEXT",
        "parent_session_id": "TEXT",
        "root_session_id": "TEXT",
        "version": "TEXT DEFAULT ''",
    }
    for column, ddl in required_columns.items():
        if column in existing_columns:
            continue
        conn.execute(f"ALTER TABLE sessions ADD COLUMN {column} {ddl}")


def create_tables(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes if they don't exist."""
    conn.executescript(_DDL)
    _ensure_sessions_columns(conn)
    conn.commit()
