"""SessionRepository — CRUD operations for session data in SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from agent_vis.models import SessionStatistics

SessionViewMode = Literal["logical", "physical"]


class SessionRepository:
    """
    CRUD layer for tracked files, session summaries, and full statistics.

    All write operations use explicit transactions via ``conn.execute`` +
    ``conn.commit`` so callers don't need to manage them.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # tracked_files
    # ------------------------------------------------------------------

    def get_tracked_file(self, file_path: str) -> sqlite3.Row | None:
        """Return tracked file row or None."""
        cur = self._conn.execute(
            "SELECT * FROM tracked_files WHERE file_path = ?",
            (file_path,),
        )
        return cur.fetchone()

    def upsert_tracked_file(
        self,
        file_path: str,
        file_size: int,
        file_mtime: float,
        ecosystem: str = "claude_code",
        parse_status: str = "pending",
    ) -> int:
        """Insert or update a tracked file and return its row id."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """\
            INSERT INTO tracked_files (
                file_path, file_size, file_mtime, ecosystem, last_parsed_at, parse_status
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                file_size      = excluded.file_size,
                file_mtime     = excluded.file_mtime,
                last_parsed_at = excluded.last_parsed_at,
                parse_status   = excluded.parse_status
            """,
            (file_path, file_size, file_mtime, ecosystem, now, parse_status),
        )
        self._conn.commit()

        row = self.get_tracked_file(file_path)
        assert row is not None
        return int(row["id"])

    def mark_file_status(self, file_path: str, status: str) -> None:
        """Update parse_status for a tracked file."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE tracked_files SET parse_status = ?, last_parsed_at = ? WHERE file_path = ?",
            (status, now, file_path),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # sessions
    # ------------------------------------------------------------------

    def upsert_session(
        self,
        session_id: str,
        file_id: int,
        ecosystem: str,
        project_path: str,
        git_branch: str | None,
        created_at: str | None,
        updated_at: str | None,
        total_messages: int,
        total_tokens: int,
        duration_seconds: float | None,
        total_tool_calls: int,
        bottleneck: str | None,
        automation_ratio: float | None,
        version: str = "",
        physical_session_id: str | None = None,
        logical_session_id: str | None = None,
        parent_session_id: str | None = None,
        root_session_id: str | None = None,
    ) -> None:
        """Insert or update a session summary row."""
        now = datetime.now(timezone.utc).isoformat()
        physical_id = physical_session_id or session_id
        logical_id = logical_session_id or physical_id
        self._conn.execute(
            """\
            INSERT INTO sessions (
                session_id, physical_session_id, logical_session_id,
                parent_session_id, root_session_id,
                file_id, ecosystem, project_path, git_branch,
                created_at, updated_at, total_messages, total_tokens,
                parsed_at, duration_seconds, total_tool_calls,
                bottleneck, automation_ratio, version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                physical_session_id = excluded.physical_session_id,
                logical_session_id  = excluded.logical_session_id,
                parent_session_id   = excluded.parent_session_id,
                root_session_id     = excluded.root_session_id,
                file_id          = excluded.file_id,
                ecosystem        = excluded.ecosystem,
                project_path     = excluded.project_path,
                git_branch       = excluded.git_branch,
                created_at       = excluded.created_at,
                updated_at       = excluded.updated_at,
                total_messages   = excluded.total_messages,
                total_tokens     = excluded.total_tokens,
                parsed_at        = excluded.parsed_at,
                duration_seconds = excluded.duration_seconds,
                total_tool_calls = excluded.total_tool_calls,
                bottleneck       = excluded.bottleneck,
                automation_ratio = excluded.automation_ratio,
                version          = excluded.version
            """,
            (
                session_id,
                physical_id,
                logical_id,
                parent_session_id,
                root_session_id,
                file_id,
                ecosystem,
                project_path,
                git_branch,
                created_at,
                updated_at,
                total_messages,
                total_tokens,
                now,
                duration_seconds,
                total_tool_calls,
                bottleneck,
                automation_ratio,
                version,
            ),
        )
        self._conn.commit()

    def get_session(self, session_id: str) -> sqlite3.Row | None:
        """Return session summary row or None."""
        cur = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        return cur.fetchone()

    def list_sessions(
        self,
        sort_by: str = "created_at",
        sort_order: str = "DESC",
        limit: int = 200,
        offset: int = 0,
        start_date: str | None = None,
        end_date: str | None = None,
        ecosystem: str | None = None,
        bottleneck: str | None = None,
        min_tokens: int | None = None,
        max_tokens: int | None = None,
        min_messages: int | None = None,
        max_messages: int | None = None,
        min_automation: float | None = None,
        max_automation: float | None = None,
        view_mode: SessionViewMode = "physical",
    ) -> list[sqlite3.Row]:
        """
        List session summaries with sorting, pagination, and optional date filtering.

        Args:
            sort_by: Column to sort by. Must be one of the allowed columns.
            sort_order: 'ASC' or 'DESC'.
            limit: Maximum rows to return.
            offset: Number of rows to skip.
            start_date: Include sessions created on or after this date (YYYY-MM-DD).
            end_date: Include sessions created on or before this date (YYYY-MM-DD).
        """
        allowed_sort_map = {
            "created_at": "created_at",
            "updated_at": "COALESCE(updated_at, created_at)",
            "parsed_at": "parsed_at",
            "total_tokens": "total_tokens",
            "duration_seconds": "duration_seconds",
            "total_messages": "total_messages",
            "automation_ratio": "automation_ratio",
            "session_id": "session_id",
        }
        sort_expr = allowed_sort_map.get(sort_by, "created_at")
        if sort_order.upper() not in ("ASC", "DESC"):
            sort_order = "DESC"
        sort_order = sort_order.upper()

        where_clauses, params = self._build_date_filter(
            start_date,
            end_date,
            ecosystem=ecosystem,
            bottleneck=bottleneck,
            min_tokens=min_tokens,
            max_tokens=max_tokens,
            min_messages=min_messages,
            max_messages=max_messages,
            min_automation=min_automation,
            max_automation=max_automation,
        )
        where_sql = f"WHERE {' AND '.join(where_clauses)} " if where_clauses else ""

        if view_mode == "logical":
            all_rows = self._fetch_sessions(
                sort_by=sort_expr,
                sort_order=sort_order,
                where_sql=where_sql,
                params=params,
            )
            deduped = self._dedupe_logical_sessions(all_rows)
            return deduped[offset : offset + limit]

        params.extend([limit, offset])
        cur = self._conn.execute(
            f"SELECT * FROM sessions {where_sql}ORDER BY {sort_expr} {sort_order} LIMIT ? OFFSET ?",
            params,
        )
        return cur.fetchall()

    def count_sessions(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        ecosystem: str | None = None,
        bottleneck: str | None = None,
        min_tokens: int | None = None,
        max_tokens: int | None = None,
        min_messages: int | None = None,
        max_messages: int | None = None,
        min_automation: float | None = None,
        max_automation: float | None = None,
        view_mode: SessionViewMode = "physical",
    ) -> int:
        """Return total number of sessions, optionally filtered by date range."""
        where_clauses, params = self._build_date_filter(
            start_date,
            end_date,
            ecosystem=ecosystem,
            bottleneck=bottleneck,
            min_tokens=min_tokens,
            max_tokens=max_tokens,
            min_messages=min_messages,
            max_messages=max_messages,
            min_automation=min_automation,
            max_automation=max_automation,
        )
        where_sql = f"WHERE {' AND '.join(where_clauses)} " if where_clauses else ""

        if view_mode == "logical":
            rows = self._fetch_sessions(
                sort_by="created_at",
                sort_order="DESC",
                where_sql=where_sql,
                params=params,
            )
            return len(self._dedupe_logical_sessions(rows))

        cur = self._conn.execute(f"SELECT COUNT(*) FROM sessions {where_sql}", params)
        return cur.fetchone()[0]

    def list_sessions_for_analytics(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        ecosystem: str | None = None,
    ) -> list[sqlite3.Row]:
        """Return all session summary rows used by analytics endpoints."""
        where_clauses, params = self._build_date_filter(
            start_date,
            end_date,
            ecosystem=ecosystem,
            created_col="s.created_at",
            ecosystem_col="s.ecosystem",
        )
        where_sql = f"WHERE {' AND '.join(where_clauses)} " if where_clauses else ""
        cur = self._conn.execute(
            f"""\
            SELECT
                s.session_id,
                s.physical_session_id,
                s.logical_session_id,
                s.ecosystem,
                s.project_path,
                s.git_branch,
                s.created_at,
                s.updated_at,
                s.total_messages,
                s.total_tokens,
                s.total_tool_calls,
                s.duration_seconds,
                s.bottleneck,
                s.automation_ratio,
                s.version
            FROM sessions s
            {where_sql}
            ORDER BY s.created_at DESC
            """,
            params,
        )
        return cur.fetchall()

    def list_statistics_for_analytics(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        ecosystem: str | None = None,
    ) -> list[sqlite3.Row]:
        """Return session rows joined with statistics JSON for analytics."""
        where_clauses, params = self._build_date_filter(
            start_date,
            end_date,
            ecosystem=ecosystem,
            created_col="s.created_at",
            ecosystem_col="s.ecosystem",
        )
        where_sql = f"WHERE {' AND '.join(where_clauses)} " if where_clauses else ""
        cur = self._conn.execute(
            f"""\
            SELECT
                s.session_id,
                s.physical_session_id,
                s.logical_session_id,
                s.ecosystem,
                s.project_path,
                s.git_branch,
                s.created_at,
                s.updated_at,
                s.total_messages,
                s.total_tokens,
                s.total_tool_calls,
                s.duration_seconds,
                s.bottleneck,
                s.automation_ratio,
                s.version,
                ss.statistics_json
            FROM sessions s
            LEFT JOIN session_statistics ss
            ON ss.session_id = s.session_id
            {where_sql}
            ORDER BY s.created_at DESC
            """,
            params,
        )
        return cur.fetchall()

    @staticmethod
    def _build_date_filter(
        start_date: str | None,
        end_date: str | None,
        *,
        ecosystem: str | None = None,
        bottleneck: str | None = None,
        min_tokens: int | None = None,
        max_tokens: int | None = None,
        min_messages: int | None = None,
        max_messages: int | None = None,
        min_automation: float | None = None,
        max_automation: float | None = None,
        created_col: str = "created_at",
        ecosystem_col: str = "ecosystem",
        bottleneck_col: str = "bottleneck",
        total_tokens_col: str = "total_tokens",
        total_messages_col: str = "total_messages",
        automation_col: str = "automation_ratio",
    ) -> tuple[list[str], list[object]]:
        """Build WHERE clause fragments for date filtering on created_at.

        Returns (clauses, params) for parameterized queries.
        Raises ValueError if date strings are not valid ISO format (YYYY-MM-DD).
        """
        from datetime import timedelta

        clauses: list[str] = []
        params: list[object] = []

        if start_date:
            datetime.fromisoformat(start_date)  # Validate format
            clauses.append(f"{created_col} >= ?")
            params.append(start_date)

        if end_date:
            end_dt = datetime.fromisoformat(end_date)  # Validate format
            next_day = (end_dt + timedelta(days=1)).isoformat()[:10]
            clauses.append(f"{created_col} < ?")
            params.append(next_day)

        if ecosystem:
            clauses.append(f"{ecosystem_col} = ?")
            params.append(ecosystem)

        if bottleneck:
            clauses.append(f"LOWER(COALESCE({bottleneck_col}, '')) = ?")
            params.append(bottleneck.strip().lower())

        if min_tokens is not None:
            clauses.append(f"COALESCE({total_tokens_col}, 0) >= ?")
            params.append(min_tokens)
        if max_tokens is not None:
            clauses.append(f"COALESCE({total_tokens_col}, 0) <= ?")
            params.append(max_tokens)

        if min_messages is not None:
            clauses.append(f"COALESCE({total_messages_col}, 0) >= ?")
            params.append(min_messages)
        if max_messages is not None:
            clauses.append(f"COALESCE({total_messages_col}, 0) <= ?")
            params.append(max_messages)

        if min_automation is not None:
            clauses.append(f"{automation_col} >= ?")
            params.append(min_automation)
        if max_automation is not None:
            clauses.append(f"{automation_col} <= ?")
            params.append(max_automation)

        return clauses, params

    def delete_session(self, session_id: str) -> None:
        """Delete a session and its statistics."""
        self._conn.execute("DELETE FROM session_statistics WHERE session_id = ?", (session_id,))
        self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        self._conn.commit()

    # ------------------------------------------------------------------
    # session_statistics
    # ------------------------------------------------------------------

    def upsert_statistics(self, session_id: str, statistics: SessionStatistics) -> None:
        """Store full statistics JSON for a session."""
        now = datetime.now(timezone.utc).isoformat()
        json_str = statistics.model_dump_json()
        self._conn.execute(
            """\
            INSERT INTO session_statistics (session_id, statistics_json, computed_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                statistics_json = excluded.statistics_json,
                computed_at     = excluded.computed_at
            """,
            (session_id, json_str, now),
        )
        self._conn.commit()

    def get_statistics(self, session_id: str) -> SessionStatistics | None:
        """Load and deserialize statistics for a session."""
        cur = self._conn.execute(
            "SELECT statistics_json FROM session_statistics WHERE session_id = ?",
            (session_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return SessionStatistics.model_validate_json(row["statistics_json"])

    # ------------------------------------------------------------------
    # Compound helpers
    # ------------------------------------------------------------------

    def get_file_path_for_session(self, session_id: str) -> Path | None:
        """Return the file path associated with a session."""
        cur = self._conn.execute(
            """\
            SELECT tf.file_path
            FROM sessions s
            JOIN tracked_files tf ON s.file_id = tf.id
            WHERE s.session_id = ?
            """,
            (session_id,),
        )
        row = cur.fetchone()
        return Path(row["file_path"]) if row else None

    def _fetch_sessions(
        self,
        *,
        sort_by: str,
        sort_order: str,
        where_sql: str,
        params: list[object],
    ) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            f"SELECT * FROM sessions {where_sql}ORDER BY {sort_by} {sort_order}",
            params,
        )
        return cur.fetchall()

    def _dedupe_logical_sessions(self, rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
        deduped: dict[str, sqlite3.Row] = {}
        for row in rows:
            logical_id = row["logical_session_id"] or row["session_id"]
            existing = deduped.get(logical_id)
            if existing is None:
                deduped[logical_id] = row
                continue

            existing_is_root = existing["session_id"] == logical_id
            row_is_root = row["session_id"] == logical_id
            if row_is_root and not existing_is_root:
                deduped[logical_id] = row
        return list(deduped.values())
