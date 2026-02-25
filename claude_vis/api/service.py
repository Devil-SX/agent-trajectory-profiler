"""
Session service for managing and accessing session data.

Provides a centralized service layer that reads from SQLite and falls
back to on-the-fly parsing when the database is empty.
"""

import asyncio
import sqlite3
from pathlib import Path

from claude_vis.api.models import SessionSummary
from claude_vis.db.connection import get_connection
from claude_vis.db.repository import SessionRepository
from claude_vis.db.sync import SyncEngine
from claude_vis.models import Session, SessionStatistics
from claude_vis.parsers import SessionParseError, parse_session_directory, parse_session_file
from claude_vis.parsers.claude_code import ClaudeCodeParser


class SessionService:
    """
    Service for managing session data.

    When a DB is available, reads from SQLite for list/stats queries.
    Falls back to full in-memory parsing for session detail (messages).
    On first startup with an empty DB, triggers an automatic sync.
    """

    def __init__(
        self,
        session_path: Path,
        single_session: str | None = None,
        db_path: Path | None = None,
    ) -> None:
        self.session_path = session_path
        self.single_session = single_session
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._repo: SessionRepository | None = None
        self._sessions: dict[str, Session] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """
        Initialize the service.

        Opens the DB and runs an auto-sync if the DB is empty.
        """
        try:
            self._conn = get_connection(self._db_path)
            self._repo = SessionRepository(self._conn)
        except Exception:
            self._conn = None
            self._repo = None

        # If DB is empty, auto-sync from disk
        if self._repo is not None and self._repo.count_sessions() == 0:
            await self._auto_sync()

        # Fallback: if still no DB or DB is empty, load in-memory
        if self._repo is None or self._repo.count_sessions() == 0:
            await self._load_sessions_in_memory()

        self._initialized = True

    async def _auto_sync(self) -> None:
        """Run sync engine to populate DB from disk."""
        if self._repo is None:
            return

        parser = ClaudeCodeParser()
        engine = SyncEngine(self._repo, parser)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, engine.sync, self.session_path)

    async def _load_sessions_in_memory(self) -> None:
        """Legacy fallback: load all sessions into memory."""
        try:
            loop = asyncio.get_event_loop()
            parsed_data = await loop.run_in_executor(
                None, parse_session_directory, self.session_path
            )
            all_sessions = {
                session.metadata.session_id: session for session in parsed_data.sessions
            }

            if self.single_session:
                if self.single_session in all_sessions:
                    self._sessions = {self.single_session: all_sessions[self.single_session]}
                else:
                    self._sessions = {}
            else:
                self._sessions = all_sessions
        except SessionParseError:
            self._sessions = {}

    async def refresh_sessions(self) -> None:
        """Re-sync from disk."""
        if self._repo is not None:
            await self._auto_sync()
        else:
            await self._load_sessions_in_memory()

    async def list_sessions(
        self,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "created_at",
        sort_order: str = "DESC",
    ) -> tuple[list[SessionSummary], int]:
        """
        Get list of all available sessions with pagination.

        Reads from DB when available, otherwise from in-memory cache.
        """
        if self._repo is not None and self._repo.count_sessions() > 0:
            return self._list_from_db(page, page_size, sort_by, sort_order)
        return self._list_from_memory(page, page_size)

    def _list_from_db(
        self, page: int, page_size: int, sort_by: str, sort_order: str
    ) -> tuple[list[SessionSummary], int]:
        assert self._repo is not None
        total_count = self._repo.count_sessions()
        offset = (page - 1) * page_size
        rows = self._repo.list_sessions(
            sort_by=sort_by, sort_order=sort_order,
            limit=page_size, offset=offset,
        )
        summaries = []
        for row in rows:
            summaries.append(
                SessionSummary(
                    session_id=row["session_id"],
                    project_path=row["project_path"] or "",
                    created_at=row["created_at"] or "",
                    updated_at=row["updated_at"],
                    total_messages=row["total_messages"] or 0,
                    total_tokens=row["total_tokens"] or 0,
                    git_branch=row["git_branch"],
                    parsed_at=row["parsed_at"],
                    duration_seconds=row["duration_seconds"],
                    bottleneck=row["bottleneck"],
                    automation_ratio=row["automation_ratio"],
                )
            )
        return summaries, total_count

    def _list_from_memory(
        self, page: int, page_size: int
    ) -> tuple[list[SessionSummary], int]:
        summaries = []
        for session in self._sessions.values():
            summary = SessionSummary(
                session_id=session.metadata.session_id,
                project_path=session.metadata.project_path,
                created_at=session.metadata.created_at,
                updated_at=session.metadata.updated_at,
                total_messages=session.metadata.total_messages,
                total_tokens=session.metadata.total_tokens,
                git_branch=session.metadata.git_branch,
                version=session.metadata.version,
            )
            summaries.append(summary)

        summaries.sort(key=lambda x: str(x.created_at), reverse=True)
        total_count = len(summaries)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        return summaries[start_idx:end_idx], total_count

    async def get_session(self, session_id: str) -> Session | None:
        """
        Get detailed session data by ID.

        If sessions are in memory, return from cache.
        Otherwise, find the file path from DB and parse on demand.
        """
        if session_id in self._sessions:
            return self._sessions[session_id]

        # Parse on-demand from file path stored in DB
        if self._repo is not None:
            file_path = self._repo.get_file_path_for_session(session_id)
            if file_path is not None and file_path.exists():
                try:
                    loop = asyncio.get_event_loop()
                    session = await loop.run_in_executor(
                        None, parse_session_file, file_path
                    )
                    return session
                except SessionParseError:
                    return None
        return None

    async def get_session_statistics(self, session_id: str) -> SessionStatistics | None:
        """
        Get session statistics by ID.

        Reads from DB when available, otherwise from in-memory cache.
        """
        # Try DB first
        if self._repo is not None:
            stats = self._repo.get_statistics(session_id)
            if stats is not None:
                return stats

        # Fallback to in-memory
        session = self._sessions.get(session_id)
        if session is not None:
            return session.statistics
        return None

    def get_sync_status(self) -> dict:
        """Return sync status info for the /api/sync/status endpoint."""
        if self._repo is None:
            return {"total_files": 0, "total_sessions": len(self._sessions), "last_parsed_at": None}

        total_sessions = self._repo.count_sessions()
        conn = self._repo._conn
        cur = conn.execute("SELECT COUNT(*) FROM tracked_files")
        total_files = cur.fetchone()[0]
        cur = conn.execute("SELECT MAX(last_parsed_at) FROM tracked_files WHERE parse_status = 'parsed'")
        row = cur.fetchone()
        last_parsed_at = row[0] if row else None
        return {
            "total_files": total_files,
            "total_sessions": total_sessions,
            "last_parsed_at": last_parsed_at,
        }

    @property
    def session_count(self) -> int:
        """Get total number of available sessions."""
        if self._repo is not None:
            count = self._repo.count_sessions()
            if count > 0:
                return count
        return len(self._sessions)

    @property
    def is_initialized(self) -> bool:
        return self._initialized
