"""Reader for Codex state_5.sqlite thread metadata database."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CodexThreadRow:
    """One row from the Codex ``threads`` table."""

    id: str
    rollout_path: str
    created_at: int  # epoch seconds
    updated_at: int
    title: str
    cwd: str
    tokens_used: int
    git_sha: str | None
    git_branch: str | None
    git_origin_url: str | None
    cli_version: str
    source: str  # "cli", "app", etc.
    model_provider: str
    first_user_message: str
    archived: bool
    sandbox_policy: str
    approval_mode: str


# Columns we SELECT from the threads table.  Order must match the
# CodexThreadRow constructor.
_THREAD_COLUMNS = (
    "id",
    "rollout_path",
    "created_at",
    "updated_at",
    "title",
    "cwd",
    "tokens_used",
    "git_sha",
    "git_branch",
    "git_origin_url",
    "cli_version",
    "source",
    "model_provider",
    "first_user_message",
    "archived",
    "sandbox_policy",
    "approval_mode",
)

_SELECT_COLUMNS = ", ".join(_THREAD_COLUMNS)


def _row_to_thread(row: tuple[Any, ...]) -> CodexThreadRow:
    """Convert a raw SQLite row tuple into a ``CodexThreadRow``."""
    (
        id_,
        rollout_path,
        created_at,
        updated_at,
        title,
        cwd,
        tokens_used,
        git_sha,
        git_branch,
        git_origin_url,
        cli_version,
        source,
        model_provider,
        first_user_message,
        archived,
        sandbox_policy,
        approval_mode,
    ) = row
    return CodexThreadRow(
        id=str(id_ or ""),
        rollout_path=str(rollout_path or ""),
        created_at=int(created_at) if created_at else 0,
        updated_at=int(updated_at) if updated_at else 0,
        title=str(title or ""),
        cwd=str(cwd or ""),
        tokens_used=int(tokens_used) if tokens_used else 0,
        git_sha=str(git_sha) if git_sha else None,
        git_branch=str(git_branch) if git_branch else None,
        git_origin_url=str(git_origin_url) if git_origin_url else None,
        cli_version=str(cli_version or ""),
        source=str(source or ""),
        model_provider=str(model_provider or ""),
        first_user_message=str(first_user_message or ""),
        archived=bool(archived),
        sandbox_policy=str(sandbox_policy or ""),
        approval_mode=str(approval_mode or ""),
    )


class CodexStateDB:
    """Read-only accessor for the Codex ``state_5.sqlite`` metadata database.

    Opens the database with ``?mode=ro`` to avoid taking write locks.
    All public methods return empty results (rather than raising) when the
    database file is missing, unreadable, or has an incompatible schema.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def _open_connection(self) -> sqlite3.Connection | None:
        """Open a read-only connection, returning ``None`` on failure."""
        if not self._db_path.exists():
            return None
        uri = f"file:{self._db_path}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=5)
            # Verify the expected table exists.
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='threads'"
            )
            if cur.fetchone() is None:
                conn.close()
                return None
            return conn
        except (sqlite3.Error, OSError) as exc:
            logger.debug("Cannot open Codex state DB at %s: %s", self._db_path, exc)
            return None

    def list_threads(self, *, include_archived: bool = False) -> list[CodexThreadRow]:
        """Return all thread rows, optionally including archived ones."""
        conn = self._open_connection()
        if conn is None:
            return []
        try:
            sql = f"SELECT {_SELECT_COLUMNS} FROM threads"
            if not include_archived:
                sql += " WHERE archived = 0"
            sql += " ORDER BY created_at DESC"
            cur = conn.execute(sql)
            return [_row_to_thread(row) for row in cur.fetchall()]
        except sqlite3.Error as exc:
            logger.debug("Error querying Codex state DB: %s", exc)
            return []
        finally:
            conn.close()

    def get_thread(self, thread_id: str) -> CodexThreadRow | None:
        """Return a single thread row by ID, or ``None``."""
        conn = self._open_connection()
        if conn is None:
            return None
        try:
            cur = conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM threads WHERE id = ?",
                (thread_id,),
            )
            row = cur.fetchone()
            return _row_to_thread(row) if row else None
        except sqlite3.Error as exc:
            logger.debug("Error querying Codex state DB for thread %s: %s", thread_id, exc)
            return None
        finally:
            conn.close()

    def find_rollout_path(self, thread_id: str) -> Path | None:
        """Return the rollout file path for a thread, or ``None``."""
        thread = self.get_thread(thread_id)
        if thread is None or not thread.rollout_path:
            return None
        path = Path(thread.rollout_path)
        return path if path.exists() else None
