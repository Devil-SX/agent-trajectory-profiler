"""
SyncEngine — incremental file detection and parsing.

Compares file mtime/size against the tracked_files table to determine
which files need (re-)parsing, then delegates to a TrajectoryParser.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from agent_vis.db.repository import SessionRepository
from agent_vis.exceptions import SessionParseError
from agent_vis.parsers.base import TrajectoryParser

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Outcome of a sync run."""

    parsed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.parsed + self.skipped + len(self.errors)


class SyncEngine:
    """
    Orchestrates incremental directory scanning + parsing.

    Usage::

        engine = SyncEngine(repo, parser)
        result = engine.sync(Path("~/.claude/projects"))
    """

    def __init__(self, repo: SessionRepository, parser: TrajectoryParser) -> None:
        self._repo = repo
        self._parser = parser

    def sync(self, directory: Path, *, force: bool = False) -> SyncResult:
        """
        Scan *directory* for trajectory files and parse any new or changed ones.

        Args:
            directory: Root directory to scan.
            force: If True, re-parse all files regardless of mtime/size.

        Returns:
            SyncResult with counts.
        """
        result = SyncResult()

        try:
            files = self._parser.find_session_files(directory)
        except SessionParseError as exc:
            result.errors.append(str(exc))
            return result

        for file_path in files:
            abs_path = str(file_path.resolve())
            try:
                stat = file_path.stat()
            except OSError as exc:
                result.errors.append(f"{file_path.name}: {exc}")
                continue

            current_size = stat.st_size
            current_mtime = stat.st_mtime

            if not force:
                existing = self._repo.get_tracked_file(abs_path)
                if existing is not None:
                    if (
                        existing["file_size"] == current_size
                        and existing["file_mtime"] == current_mtime
                        and existing["parse_status"] == "parsed"
                    ):
                        result.skipped += 1
                        continue

            # File is new or changed — parse it
            try:
                session = self._parser.parse_session(file_path)
            except SessionParseError as exc:
                result.errors.append(f"{file_path.name}: {exc}")
                self._repo.upsert_tracked_file(
                    abs_path,
                    current_size,
                    current_mtime,
                    ecosystem=self._parser.ecosystem_name,
                    parse_status="error",
                )
                continue
            except Exception as exc:
                result.errors.append(f"{file_path.name}: unexpected error: {exc}")
                self._repo.upsert_tracked_file(
                    abs_path,
                    current_size,
                    current_mtime,
                    ecosystem=self._parser.ecosystem_name,
                    parse_status="error",
                )
                continue

            # Persist
            file_id = self._repo.upsert_tracked_file(
                abs_path,
                current_size,
                current_mtime,
                ecosystem=self._parser.ecosystem_name,
                parse_status="parsed",
            )

            meta = session.metadata
            stats = session.statistics

            # Compute bottleneck and automation ratio
            bottleneck: str | None = None
            automation_ratio: float | None = None
            if stats and stats.time_breakdown:
                tbd = stats.time_breakdown
                categories = [
                    ("Model", tbd.model_time_percent),
                    ("Tool", tbd.tool_time_percent),
                    ("User", tbd.user_time_percent),
                ]
                bottleneck = max(categories, key=lambda x: x[1])[0]
                if tbd.user_interaction_count > 0 and stats:
                    automation_ratio = round(stats.total_tool_calls / tbd.user_interaction_count, 2)

            created_at_str = meta.created_at.isoformat() if meta.created_at else None
            updated_at_str = meta.updated_at.isoformat() if meta.updated_at else None

            self._repo.upsert_session(
                session_id=meta.session_id,
                file_id=file_id,
                ecosystem=self._parser.ecosystem_name,
                project_path=meta.project_path,
                git_branch=meta.git_branch,
                created_at=created_at_str,
                updated_at=updated_at_str,
                total_messages=meta.total_messages,
                total_tokens=meta.total_tokens,
                duration_seconds=stats.session_duration_seconds if stats else None,
                total_tool_calls=stats.total_tool_calls if stats else 0,
                bottleneck=bottleneck,
                automation_ratio=automation_ratio,
                version=meta.version,
            )

            if stats:
                self._repo.upsert_statistics(meta.session_id, stats)

            result.parsed += 1
            logger.debug("Parsed %s -> session %s", file_path.name, meta.session_id)

        return result
