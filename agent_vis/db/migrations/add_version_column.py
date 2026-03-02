"""Migration: add version column to sessions table.

Idempotent -- safe to run multiple times.
"""

import sqlite3
import sys
from pathlib import Path


def migrate(conn: sqlite3.Connection) -> bool:
    """Add ``version TEXT DEFAULT ''`` to sessions if it doesn't exist.

    Returns True if the column was added, False if it already existed.
    """
    cur = conn.execute("PRAGMA table_info(sessions)")
    columns = {row[1] for row in cur.fetchall()}
    if "version" in columns:
        return False

    conn.execute("ALTER TABLE sessions ADD COLUMN version TEXT DEFAULT ''")
    conn.commit()
    return True


def main() -> None:
    """Run migration against the default profiler database."""
    from agent_vis.db.connection import get_connection

    db_path = Path.home() / ".agent-vis" / "profiler.db"
    if not db_path.exists():
        print(f"Database not found at {db_path}; nothing to migrate.")
        sys.exit(0)

    conn = get_connection(db_path)
    try:
        added = migrate(conn)
        if added:
            print("Added 'version' column to sessions table.")
        else:
            print("'version' column already exists; nothing to do.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
