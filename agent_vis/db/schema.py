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

CREATE TABLE IF NOT EXISTS session_sections (
    section_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    section_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    start_message_uuid TEXT NOT NULL,
    end_message_uuid TEXT NOT NULL,
    start_timestamp TEXT,
    end_timestamp TEXT,
    total_messages INTEGER NOT NULL,
    user_message_count INTEGER NOT NULL,
    assistant_message_count INTEGER NOT NULL,
    tool_call_count INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    char_count INTEGER NOT NULL,
    duration_seconds REAL,
    UNIQUE(session_id, section_index)
);

CREATE INDEX IF NOT EXISTS idx_session_sections_session
    ON session_sections(session_id, section_index);

CREATE TABLE IF NOT EXISTS session_section_materializations (
    session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
    session_hash TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model_id TEXT NOT NULL,
    generation_status TEXT NOT NULL,
    section_count INTEGER NOT NULL DEFAULT 0,
    generated_at TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_session_section_materializations_status
    ON session_section_materializations(generation_status);
CREATE INDEX IF NOT EXISTS idx_session_section_materializations_model
    ON session_section_materializations(model_id);

CREATE TABLE IF NOT EXISTS session_section_summaries (
    section_id TEXT PRIMARY KEY REFERENCES session_sections(section_id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    section_hash TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model_id TEXT NOT NULL,
    generation_status TEXT NOT NULL,
    summary_text TEXT,
    summary_json TEXT,
    summary_chars INTEGER,
    generated_at TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_session_section_summaries_session
    ON session_section_summaries(session_id, section_id);
CREATE INDEX IF NOT EXISTS idx_session_section_summaries_status
    ON session_section_summaries(generation_status);
CREATE INDEX IF NOT EXISTS idx_session_section_summaries_model
    ON session_section_summaries(model_id);

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

CREATE TABLE IF NOT EXISTS session_cluster_runs (
    run_id TEXT PRIMARY KEY,
    generated_at TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    source_model_id TEXT NOT NULL,
    similarity_threshold REAL NOT NULL,
    session_count INTEGER NOT NULL,
    cluster_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS session_cluster_memberships (
    run_id TEXT NOT NULL REFERENCES session_cluster_runs(run_id) ON DELETE CASCADE,
    cluster_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    PRIMARY KEY (run_id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_session_cluster_memberships_cluster
    ON session_cluster_memberships(cluster_id);

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
        "git_sha": "TEXT",
        "cli_version": "TEXT",
        "title": "TEXT",
        "first_user_message": "TEXT",
        "model_provider": "TEXT",
        "session_source": "TEXT",
        "is_archived": "INTEGER DEFAULT 0",
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
