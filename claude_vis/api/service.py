"""
Session service for managing and accessing session data.

Provides a centralized service layer for loading, caching, and
retrieving session data for the API endpoints.
"""

import asyncio
from pathlib import Path

from claude_vis.api.models import SessionSummary
from claude_vis.models import Session, SessionStatistics
from claude_vis.parsers import SessionParseError, parse_session_directory


class SessionService:
    """
    Service for managing session data.

    This service handles loading session files from disk, caching them in memory,
    and providing access methods for the API endpoints.
    """

    def __init__(self, session_path: Path, single_session: str | None = None) -> None:
        """
        Initialize session service.

        Args:
            session_path: Path to the directory containing session files
            single_session: Optional session ID to load only a specific session
        """
        self.session_path = session_path
        self.single_session = single_session
        self._sessions: dict[str, Session] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """
        Initialize the service by loading sessions from disk.

        This should be called on application startup.
        """
        await self._load_sessions()
        self._initialized = True

    async def _load_sessions(self) -> None:
        """Load all sessions from the session directory."""
        try:
            # Run synchronous parser in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            parsed_data = await loop.run_in_executor(
                None, parse_session_directory, self.session_path
            )

            # Cache sessions by session_id
            all_sessions = {
                session.metadata.session_id: session for session in parsed_data.sessions
            }

            # Filter for single session if specified
            if self.single_session:
                if self.single_session in all_sessions:
                    self._sessions = {self.single_session: all_sessions[self.single_session]}
                    print(f"Loaded single session: {self.single_session}")
                else:
                    print(f"Warning: Session {self.single_session} not found")
                    self._sessions = {}
            else:
                self._sessions = all_sessions

        except SessionParseError as e:
            # Log error but don't fail startup - allow API to run with empty sessions
            print(f"Warning: Failed to load sessions from {self.session_path}: {e}")
            self._sessions = {}

    async def refresh_sessions(self) -> None:
        """Reload sessions from disk (useful for development/testing)."""
        await self._load_sessions()

    async def list_sessions(
        self, page: int = 1, page_size: int = 50
    ) -> tuple[list[SessionSummary], int]:
        """
        Get list of all available sessions with pagination.

        Args:
            page: Page number (1-indexed)
            page_size: Number of items per page

        Returns:
            Tuple of (list of SessionSummary objects, total count)
        """
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

        # Sort by created_at descending (newest first)
        summaries.sort(key=lambda x: x.created_at, reverse=True)

        # Apply pagination
        total_count = len(summaries)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_summaries = summaries[start_idx:end_idx]

        return paginated_summaries, total_count

    async def get_session(self, session_id: str) -> Session | None:
        """
        Get detailed session data by ID.

        Args:
            session_id: Session identifier

        Returns:
            Session object or None if not found
        """
        return self._sessions.get(session_id)

    async def get_session_statistics(self, session_id: str) -> SessionStatistics | None:
        """
        Get session statistics by ID.

        Args:
            session_id: Session identifier

        Returns:
            SessionStatistics object or None if session not found
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None

        return session.statistics

    @property
    def session_count(self) -> int:
        """Get total number of loaded sessions."""
        return len(self._sessions)

    @property
    def is_initialized(self) -> bool:
        """Check if service has been initialized."""
        return self._initialized
