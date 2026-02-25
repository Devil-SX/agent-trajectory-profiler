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
    automation_ratio REAL
);

CREATE TABLE IF NOT EXISTS session_statistics (
    session_id      TEXT PRIMARY KEY,
    statistics_json TEXT NOT NULL,
    computed_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_parsed_at  ON sessions(parsed_at);
CREATE INDEX IF NOT EXISTS idx_tracked_files_path  ON tracked_files(file_path);
"""


def create_tables(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes if they don't exist."""
    conn.executescript(_DDL)
