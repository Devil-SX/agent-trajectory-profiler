"""Abstract base class for trajectory parsers."""

from abc import ABC, abstractmethod
from pathlib import Path

from claude_vis.models import (
    MessageRecord,
    Session,
    SessionMetadata,
    SessionStatistics,
)


class TrajectoryParser(ABC):
    """
    Abstract base class for agent trajectory parsers.

    Each ecosystem (Claude Code, etc.) implements this interface to parse
    its specific trajectory file format into a common data model.
    """

    @property
    @abstractmethod
    def ecosystem_name(self) -> str:
        """Unique identifier for this parser's ecosystem (e.g. 'claude_code')."""
        ...

    @abstractmethod
    def parse_file(self, file_path: Path) -> list[MessageRecord]:
        """
        Parse a single trajectory file into message records.

        Args:
            file_path: Path to the trajectory file.

        Returns:
            List of MessageRecord objects.

        Raises:
            SessionParseError: If the file cannot be parsed.
        """
        ...

    @abstractmethod
    def extract_metadata(
        self, messages: list[MessageRecord], session_id: str, file_path: Path
    ) -> SessionMetadata:
        """
        Extract session metadata from parsed messages.

        Args:
            messages: List of parsed message records.
            session_id: Session identifier.
            file_path: Path to the source file.

        Returns:
            SessionMetadata object.
        """
        ...

    @abstractmethod
    def calculate_statistics(self, messages: list[MessageRecord]) -> SessionStatistics:
        """
        Calculate comprehensive statistics for a session.

        Args:
            messages: List of parsed message records.

        Returns:
            SessionStatistics object.
        """
        ...

    @abstractmethod
    def find_session_files(self, directory: Path) -> list[Path]:
        """
        Discover trajectory files in a directory.

        Args:
            directory: Directory to search.

        Returns:
            List of paths to trajectory files.

        Raises:
            SessionParseError: If the directory is invalid.
        """
        ...

    def parse_session(self, file_path: Path) -> Session:
        """
        Orchestrate full session parsing: parse file, extract metadata,
        calculate statistics, and return a complete Session object.

        Subclasses may override for ecosystem-specific post-processing.

        Args:
            file_path: Path to the trajectory file.

        Returns:
            Complete Session object.
        """
        session_id = file_path.stem
        messages = self.parse_file(file_path)
        if not messages:
            from claude_vis.exceptions import SessionParseError

            raise SessionParseError(f"No valid messages found in {file_path}")

        metadata = self.extract_metadata(messages, session_id, file_path)
        statistics = self.calculate_statistics(messages)
        subagent_sessions = self._extract_subagent_sessions(messages)

        return Session(
            metadata=metadata,
            messages=messages,
            subagent_sessions=subagent_sessions,
            statistics=statistics,
        )

    def _extract_subagent_sessions(
        self, messages: list[MessageRecord]
    ) -> list["SubagentSession"]:  # noqa: F821
        """Default implementation returns empty list. Override for subagent support."""
        return []
