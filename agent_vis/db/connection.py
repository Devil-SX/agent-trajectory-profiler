"""SQLite connection management with WAL mode."""

import sqlite3
from pathlib import Path

from agent_vis.db.schema import create_tables

_DEFAULT_DB_DIR = Path.home() / ".agent-vis"
_DEFAULT_DB_NAME = "profiler.db"


def get_connection(
    db_path: Path | None = None,
    *,
    create: bool = True,
) -> sqlite3.Connection:
    """
    Open (or create) a SQLite database with WAL mode enabled.

    Args:
        db_path: Explicit path to the database file.
                 Defaults to ``~/.agent-vis/profiler.db``.
        create: If True, create the directory and tables if they don't exist.

    Returns:
        A sqlite3.Connection with WAL mode and foreign keys enabled.
    """
    if db_path is None:
        db_path = _DEFAULT_DB_DIR / _DEFAULT_DB_NAME

    if create:
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    if create:
        create_tables(conn)

    return conn
