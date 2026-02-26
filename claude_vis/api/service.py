"""
Session service for managing and accessing session data.

Provides a centralized service layer that reads from SQLite and falls
back to on-the-fly parsing when the database is empty.
"""

import asyncio
import functools
import json
import sqlite3
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import mean
from typing import Any, Literal, cast

from claude_vis.api.models import (
    AnalyticsBucket,
    AnalyticsDistributionResponse,
    AnalyticsOverviewResponse,
    AnalyticsTimeseriesPoint,
    AnalyticsTimeseriesResponse,
    ProjectAggregate,
    SessionSummary,
    ToolAggregate,
)
from claude_vis.db.connection import get_connection
from claude_vis.db.repository import SessionRepository
from claude_vis.db.sync import SyncEngine
from claude_vis.models import Session, SessionStatistics
from claude_vis.parsers import SessionParseError, get_parser

AnalyticsDimension = Literal[
    "bottleneck",
    "project",
    "branch",
    "automation_band",
    "tool",
    "session_token_share",
]
AnalyticsInterval = Literal["day", "week"]


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
        codex_session_path: Path | None = None,
        single_session: str | None = None,
        db_path: Path | None = None,
        inactivity_threshold: float = 1800.0,
        model_timeout_threshold: float = 600.0,
    ) -> None:
        self.session_path = session_path
        self.codex_session_path = (
            codex_session_path
            if codex_session_path is not None
            else Path.home() / ".codex" / "sessions"
        )
        self.single_session = single_session
        self._db_path = db_path
        self._inactivity_threshold = inactivity_threshold
        self._model_timeout_threshold = model_timeout_threshold
        self._conn: sqlite3.Connection | None = None
        self._repo: SessionRepository | None = None
        self._sessions: dict[str, Session] = {}
        self._session_ecosystem: dict[str, str] = {}
        self._initialized = False

    def _sync_targets(self) -> list[tuple[str, Path]]:
        return [
            ("claude_code", self.session_path),
            ("codex", self.codex_session_path),
        ]

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

        loop = asyncio.get_event_loop()
        for ecosystem, path in self._sync_targets():
            if not path.exists():
                continue
            try:
                parser = get_parser(ecosystem)
            except KeyError:
                continue

            if hasattr(parser, "inactivity_threshold"):
                parser.inactivity_threshold = self._inactivity_threshold  # type: ignore[attr-defined]
            if hasattr(parser, "model_timeout_threshold"):
                parser.model_timeout_threshold = self._model_timeout_threshold  # type: ignore[attr-defined]

            engine = SyncEngine(self._repo, parser)
            _sync = functools.partial(engine.sync, path)
            await loop.run_in_executor(None, _sync)

    async def _load_sessions_in_memory(self) -> None:
        """Legacy fallback: load all sessions into memory."""
        try:
            loop = asyncio.get_event_loop()
            all_sessions: dict[str, Session] = {}
            all_ecosystems: dict[str, str] = {}

            for ecosystem, path in self._sync_targets():
                if not path.exists():
                    continue
                try:
                    parser = get_parser(ecosystem)
                except KeyError:
                    continue

                if hasattr(parser, "inactivity_threshold"):
                    parser.inactivity_threshold = self._inactivity_threshold  # type: ignore[attr-defined]
                if hasattr(parser, "model_timeout_threshold"):
                    parser.model_timeout_threshold = self._model_timeout_threshold  # type: ignore[attr-defined]

                try:
                    files = await loop.run_in_executor(None, parser.find_session_files, path)
                except SessionParseError:
                    continue

                for file_path in files:
                    try:
                        session = await loop.run_in_executor(None, parser.parse_session, file_path)
                    except SessionParseError:
                        continue
                    sid = session.metadata.session_id
                    all_sessions[sid] = session
                    all_ecosystems[sid] = ecosystem

            if self.single_session:
                if self.single_session in all_sessions:
                    self._sessions = {self.single_session: all_sessions[self.single_session]}
                    self._session_ecosystem = {
                        self.single_session: all_ecosystems.get(self.single_session, "claude_code")
                    }
                else:
                    self._sessions = {}
                    self._session_ecosystem = {}
            else:
                self._sessions = all_sessions
                self._session_ecosystem = all_ecosystems
        except SessionParseError:
            self._sessions = {}
            self._session_ecosystem = {}

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
        start_date: str | None = None,
        end_date: str | None = None,
        ecosystem: str | None = None,
    ) -> tuple[list[SessionSummary], int]:
        """
        Get list of all available sessions with pagination.

        Reads from DB when available, otherwise from in-memory cache.
        """
        if self._repo is not None and self._repo.count_sessions() > 0:
            return self._list_from_db(
                page,
                page_size,
                sort_by,
                sort_order,
                start_date,
                end_date,
                ecosystem,
            )
        return self._list_from_memory(page, page_size, start_date, end_date, ecosystem)

    def _list_from_db(
        self,
        page: int,
        page_size: int,
        sort_by: str,
        sort_order: str,
        start_date: str | None = None,
        end_date: str | None = None,
        ecosystem: str | None = None,
    ) -> tuple[list[SessionSummary], int]:
        assert self._repo is not None
        total_count = self._repo.count_sessions(
            start_date=start_date,
            end_date=end_date,
            ecosystem=ecosystem,
        )
        offset = (page - 1) * page_size
        rows = self._repo.list_sessions(
            sort_by=sort_by, sort_order=sort_order,
            limit=page_size, offset=offset,
            start_date=start_date, end_date=end_date,
            ecosystem=ecosystem,
        )
        summaries = []
        for row in rows:
            summaries.append(
                SessionSummary(
                    session_id=row["session_id"],
                    ecosystem=row["ecosystem"] or "claude_code",
                    project_path=row["project_path"] or "",
                    created_at=row["created_at"] or "",
                    updated_at=row["updated_at"],
                    total_messages=row["total_messages"] or 0,
                    total_tokens=row["total_tokens"] or 0,
                    git_branch=row["git_branch"],
                    version=row["version"] or "",
                    parsed_at=row["parsed_at"],
                    duration_seconds=row["duration_seconds"],
                    bottleneck=row["bottleneck"],
                    automation_ratio=row["automation_ratio"],
                )
            )
        return summaries, total_count

    def _list_from_memory(
        self,
        page: int,
        page_size: int,
        start_date: str | None = None,
        end_date: str | None = None,
        ecosystem: str | None = None,
    ) -> tuple[list[SessionSummary], int]:
        summaries = []
        for session in self._sessions.values():
            sid = session.metadata.session_id
            session_ecosystem = self._session_ecosystem.get(sid, "claude_code")
            if ecosystem and ecosystem != session_ecosystem:
                continue

            # Apply date filtering on in-memory sessions
            created = str(session.metadata.created_at) if session.metadata.created_at else ""
            if start_date and created < start_date:
                continue
            if end_date:
                from datetime import datetime, timedelta

                end_dt = datetime.fromisoformat(end_date)
                next_day = (end_dt + timedelta(days=1)).isoformat()[:10]
                if created >= next_day:
                    continue

            summary = SessionSummary(
                session_id=sid,
                ecosystem=session_ecosystem,
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
                    ecosystem = "claude_code"
                    row = self._repo.get_session(session_id)
                    if row is not None and isinstance(row["ecosystem"], str):
                        ecosystem = row["ecosystem"]
                    parser = get_parser(ecosystem)
                    if hasattr(parser, "inactivity_threshold"):
                        parser.inactivity_threshold = self._inactivity_threshold  # type: ignore[attr-defined]
                    if hasattr(parser, "model_timeout_threshold"):
                        parser.model_timeout_threshold = self._model_timeout_threshold  # type: ignore[attr-defined]

                    _parse_file = functools.partial(parser.parse_session, file_path)
                    loop = asyncio.get_event_loop()
                    session = await loop.run_in_executor(None, _parse_file)
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

    async def get_analytics_overview(
        self, start_date: str, end_date: str
    ) -> AnalyticsOverviewResponse:
        """Compute cross-session overview metrics for a date range."""
        rows = self._get_analytics_rows(start_date, end_date)
        total_sessions = len(rows)

        if total_sessions == 0:
            return AnalyticsOverviewResponse(
                start_date=start_date,
                end_date=end_date,
                total_sessions=0,
                total_messages=0,
                total_tokens=0,
                total_tool_calls=0,
                total_input_tokens=0,
                total_output_tokens=0,
                total_cache_read_tokens=0,
                total_cache_creation_tokens=0,
                avg_automation_ratio=0.0,
                avg_session_duration_seconds=0.0,
                model_time_seconds=0.0,
                tool_time_seconds=0.0,
                user_time_seconds=0.0,
                inactive_time_seconds=0.0,
                active_time_ratio=0.0,
                model_timeout_count=0,
                bottleneck_distribution=[],
                top_projects=[],
                top_tools=[],
            )

        total_messages = sum(int(row.get("total_messages") or 0) for row in rows)
        total_tokens = sum(int(row.get("total_tokens") or 0) for row in rows)
        total_tool_calls = sum(int(row.get("total_tool_calls") or 0) for row in rows)

        automation_values = [
            float(row["automation_ratio"])
            for row in rows
            if row.get("automation_ratio") is not None
        ]
        duration_values = [
            float(row["duration_seconds"])
            for row in rows
            if row.get("duration_seconds") is not None
        ]

        bottleneck_counter: dict[str, int] = {"Model": 0, "Tool": 0, "User": 0, "Unknown": 0}
        project_acc: dict[str, dict[str, float | int | str]] = {}

        total_input_tokens = 0
        total_output_tokens = 0
        total_cache_read_tokens = 0
        total_cache_creation_tokens = 0
        model_time_seconds = 0.0
        tool_time_seconds = 0.0
        user_time_seconds = 0.0
        inactive_time_seconds = 0.0
        model_timeout_count = 0

        tool_acc: dict[str, dict[str, float | int | set[str]]] = defaultdict(
            lambda: {
                "total_calls": 0,
                "sessions_using_tool": set(),
                "error_count": 0,
                "latency_total": 0.0,
                "latency_count": 0,
            }
        )

        for row in rows:
            bottleneck = (row.get("bottleneck") or "Unknown").strip().title()
            if bottleneck not in bottleneck_counter:
                bottleneck = "Unknown"
            bottleneck_counter[bottleneck] += 1

            project_path = row.get("project_path") or ""
            if project_path not in project_acc:
                project_name = Path(project_path).name if project_path else "(unknown)"
                project_acc[project_path] = {
                    "project_name": project_name,
                    "sessions": 0,
                    "total_tokens": 0,
                    "total_messages": 0,
                }
            project_acc[project_path]["sessions"] = int(project_acc[project_path]["sessions"]) + 1
            project_acc[project_path]["total_tokens"] = int(project_acc[project_path]["total_tokens"]) + int(
                row.get("total_tokens") or 0
            )
            project_acc[project_path]["total_messages"] = int(project_acc[project_path]["total_messages"]) + int(
                row.get("total_messages") or 0
            )

            stats = row.get("statistics") or {}
            total_input_tokens += int(stats.get("total_input_tokens") or 0)
            total_output_tokens += int(stats.get("total_output_tokens") or 0)
            total_cache_read_tokens += int(stats.get("cache_read_tokens") or 0)
            total_cache_creation_tokens += int(stats.get("cache_creation_tokens") or 0)

            time_breakdown = stats.get("time_breakdown") or {}
            model_time_seconds += float(time_breakdown.get("total_model_time_seconds") or 0.0)
            tool_time_seconds += float(time_breakdown.get("total_tool_time_seconds") or 0.0)
            user_time_seconds += float(time_breakdown.get("total_user_time_seconds") or 0.0)
            inactive_time_seconds += float(time_breakdown.get("total_inactive_time_seconds") or 0.0)
            model_timeout_count += int(time_breakdown.get("model_timeout_count") or 0)

            for tool in stats.get("tool_calls") or []:
                tool_name = str(tool.get("tool_name") or "").strip()
                if not tool_name:
                    continue
                bucket = tool_acc[tool_name]
                bucket["total_calls"] = int(bucket["total_calls"]) + int(tool.get("count") or 0)
                bucket["error_count"] = int(bucket["error_count"]) + int(tool.get("error_count") or 0)
                bucket["latency_total"] = float(bucket["latency_total"]) + float(
                    tool.get("total_latency_seconds") or 0.0
                )
                bucket["latency_count"] = int(bucket["latency_count"]) + int(tool.get("count") or 0)
                cast_set = bucket["sessions_using_tool"]
                if isinstance(cast_set, set):
                    cast_set.add(str(row.get("session_id")))

        bottleneck_distribution = [
            AnalyticsBucket(
                key=key.lower(),
                label=key,
                count=count,
                value=float(count),
                percent=(count / total_sessions * 100.0) if total_sessions else 0.0,
            )
            for key, count in bottleneck_counter.items()
            if count > 0
        ]
        bottleneck_distribution.sort(key=lambda item: item.count, reverse=True)

        top_projects: list[ProjectAggregate] = []
        for project_path, agg in project_acc.items():
            project_tokens = int(agg["total_tokens"])
            project_sessions = int(agg["sessions"])
            top_projects.append(
                ProjectAggregate(
                    project_path=project_path,
                    project_name=str(agg["project_name"]),
                    sessions=project_sessions,
                    total_tokens=project_tokens,
                    total_messages=int(agg["total_messages"]),
                    percent_sessions=(project_sessions / total_sessions * 100.0),
                    percent_tokens=(project_tokens / total_tokens * 100.0) if total_tokens else 0.0,
                )
            )
        top_projects.sort(key=lambda item: (item.sessions, item.total_tokens), reverse=True)
        top_projects = top_projects[:10]

        total_tool_call_volume = sum(int(v["total_calls"]) for v in tool_acc.values())
        top_tools: list[ToolAggregate] = []
        for tool_name, agg in tool_acc.items():
            sessions_using_tool = (
                len(agg["sessions_using_tool"])
                if isinstance(agg["sessions_using_tool"], set)
                else 0
            )
            call_count = int(agg["total_calls"])
            latency_count = int(agg["latency_count"])
            avg_latency = float(agg["latency_total"]) / latency_count if latency_count else 0.0
            top_tools.append(
                ToolAggregate(
                    tool_name=tool_name,
                    total_calls=call_count,
                    sessions_using_tool=sessions_using_tool,
                    error_count=int(agg["error_count"]),
                    avg_latency_seconds=avg_latency,
                    percent_of_tool_calls=(
                        call_count / total_tool_call_volume * 100.0
                        if total_tool_call_volume
                        else 0.0
                    ),
                )
            )
        top_tools.sort(key=lambda item: item.total_calls, reverse=True)
        top_tools = top_tools[:15]

        total_active_time = model_time_seconds + tool_time_seconds + user_time_seconds
        total_span_time = total_active_time + inactive_time_seconds
        active_time_ratio = total_active_time / total_span_time if total_span_time > 0 else 0.0

        return AnalyticsOverviewResponse(
            start_date=start_date,
            end_date=end_date,
            total_sessions=total_sessions,
            total_messages=total_messages,
            total_tokens=total_tokens,
            total_tool_calls=total_tool_calls,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_cache_read_tokens=total_cache_read_tokens,
            total_cache_creation_tokens=total_cache_creation_tokens,
            avg_automation_ratio=mean(automation_values) if automation_values else 0.0,
            avg_session_duration_seconds=mean(duration_values) if duration_values else 0.0,
            model_time_seconds=model_time_seconds,
            tool_time_seconds=tool_time_seconds,
            user_time_seconds=user_time_seconds,
            inactive_time_seconds=inactive_time_seconds,
            active_time_ratio=active_time_ratio,
            model_timeout_count=model_timeout_count,
            bottleneck_distribution=bottleneck_distribution,
            top_projects=top_projects,
            top_tools=top_tools,
        )

    async def get_analytics_distribution(
        self, dimension: str, start_date: str, end_date: str
    ) -> AnalyticsDistributionResponse:
        """Compute a distribution breakdown for one dimension."""
        rows = self._get_analytics_rows(start_date, end_date)
        buckets: list[AnalyticsBucket] = []
        total_value = 0.0

        if dimension == "bottleneck":
            counter: dict[str, int] = defaultdict(int)
            for row in rows:
                key = (row.get("bottleneck") or "Unknown").strip().title()
                counter[key] += 1
            total_value = float(sum(counter.values()))
            buckets = [
                AnalyticsBucket(
                    key=k.lower(),
                    label=k,
                    count=v,
                    value=float(v),
                    percent=(v / total_value * 100.0) if total_value else 0.0,
                )
                for k, v in counter.items()
            ]
        elif dimension == "project":
            counter: dict[str, int] = defaultdict(int)
            for row in rows:
                key = row.get("project_path") or "(unknown)"
                counter[key] += 1
            total_value = float(sum(counter.values()))
            buckets = [
                AnalyticsBucket(
                    key=k,
                    label=Path(k).name if k != "(unknown)" else k,
                    count=v,
                    value=float(v),
                    percent=(v / total_value * 100.0) if total_value else 0.0,
                )
                for k, v in counter.items()
            ]
        elif dimension == "branch":
            counter: dict[str, int] = defaultdict(int)
            for row in rows:
                key = row.get("git_branch") or "(none)"
                counter[key] += 1
            total_value = float(sum(counter.values()))
            buckets = [
                AnalyticsBucket(
                    key=k,
                    label=k,
                    count=v,
                    value=float(v),
                    percent=(v / total_value * 100.0) if total_value else 0.0,
                )
                for k, v in counter.items()
            ]
        elif dimension == "automation_band":
            bands: dict[str, int] = {"0-1": 0, "1-3": 0, "3-5": 0, "5+": 0}
            for row in rows:
                ratio = float(row.get("automation_ratio") or 0.0)
                if ratio < 1:
                    bands["0-1"] += 1
                elif ratio < 3:
                    bands["1-3"] += 1
                elif ratio < 5:
                    bands["3-5"] += 1
                else:
                    bands["5+"] += 1
            total_value = float(sum(bands.values()))
            buckets = [
                AnalyticsBucket(
                    key=k,
                    label=k,
                    count=v,
                    value=float(v),
                    percent=(v / total_value * 100.0) if total_value else 0.0,
                )
                for k, v in bands.items()
                if v > 0
            ]
        elif dimension == "tool":
            tool_counter: dict[str, dict[str, int]] = defaultdict(
                lambda: {"calls": 0, "sessions": 0}
            )
            for row in rows:
                stats = row.get("statistics") or {}
                seen_in_session: set[str] = set()
                for tool in stats.get("tool_calls") or []:
                    tool_name = str(tool.get("tool_name") or "").strip()
                    if not tool_name:
                        continue
                    tool_counter[tool_name]["calls"] += int(tool.get("count") or 0)
                    if tool_name not in seen_in_session:
                        tool_counter[tool_name]["sessions"] += 1
                        seen_in_session.add(tool_name)
            total_value = float(sum(v["calls"] for v in tool_counter.values()))
            buckets = [
                AnalyticsBucket(
                    key=tool_name,
                    label=tool_name,
                    count=vals["sessions"],
                    value=float(vals["calls"]),
                    percent=(vals["calls"] / total_value * 100.0) if total_value else 0.0,
                )
                for tool_name, vals in tool_counter.items()
            ]
        elif dimension == "session_token_share":
            total_value = float(sum(int(r.get("total_tokens") or 0) for r in rows))
            buckets = []
            for row in rows:
                token_value = int(row.get("total_tokens") or 0)
                label = str(row.get("session_id") or "")[:8]
                buckets.append(
                    AnalyticsBucket(
                        key=str(row.get("session_id") or ""),
                        label=label,
                        count=1,
                        value=float(token_value),
                        percent=(token_value / total_value * 100.0) if total_value else 0.0,
                    )
                )
        else:
            raise ValueError(f"Unsupported distribution dimension: {dimension}")

        buckets.sort(key=lambda b: b.value, reverse=True)
        if dimension in {"tool", "session_token_share"}:
            buckets = buckets[:20]

        return AnalyticsDistributionResponse(
            dimension=cast(AnalyticsDimension, dimension),
            start_date=start_date,
            end_date=end_date,
            total=total_value,
            buckets=buckets,
        )

    async def get_analytics_timeseries(
        self, start_date: str, end_date: str, interval: str = "day"
    ) -> AnalyticsTimeseriesResponse:
        """Compute time-series aggregates across sessions."""
        rows = self._get_analytics_rows(start_date, end_date)
        buckets: dict[str, dict[str, float]] = {}

        for row in rows:
            created = self._parse_created_date(row.get("created_at"))
            if created is None:
                continue

            if interval == "week":
                iso_year, iso_week, _ = created.isocalendar()
                period = f"{iso_year}-W{iso_week:02d}"
            else:
                period = created.isoformat()

            if period not in buckets:
                buckets[period] = {
                    "sessions": 0.0,
                    "tokens": 0.0,
                    "tool_calls": 0.0,
                    "automation_sum": 0.0,
                    "automation_count": 0.0,
                    "duration_sum": 0.0,
                    "duration_count": 0.0,
                }

            bucket = buckets[period]
            bucket["sessions"] += 1.0
            bucket["tokens"] += float(row.get("total_tokens") or 0)
            bucket["tool_calls"] += float(row.get("total_tool_calls") or 0)

            if row.get("automation_ratio") is not None:
                bucket["automation_sum"] += float(row["automation_ratio"])
                bucket["automation_count"] += 1.0
            if row.get("duration_seconds") is not None:
                bucket["duration_sum"] += float(row["duration_seconds"])
                bucket["duration_count"] += 1.0

        points: list[AnalyticsTimeseriesPoint] = []
        for period in sorted(buckets.keys()):
            data = buckets[period]
            points.append(
                AnalyticsTimeseriesPoint(
                    period=period,
                    sessions=int(data["sessions"]),
                    tokens=int(data["tokens"]),
                    tool_calls=int(data["tool_calls"]),
                    avg_automation_ratio=(
                        data["automation_sum"] / data["automation_count"]
                        if data["automation_count"]
                        else 0.0
                    ),
                    avg_duration_seconds=(
                        data["duration_sum"] / data["duration_count"]
                        if data["duration_count"]
                        else 0.0
                    ),
                )
            )

        return AnalyticsTimeseriesResponse(
            interval=cast(AnalyticsInterval, interval),
            start_date=start_date,
            end_date=end_date,
            points=points,
        )

    def _get_analytics_rows(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict[str, Any]]:
        """Return normalized rows for cross-session analytics."""
        if self._repo is not None and self._repo.count_sessions() > 0:
            rows = self._repo.list_statistics_for_analytics(
                start_date=start_date, end_date=end_date
            )
            normalized: list[dict[str, Any]] = []
            for row in rows:
                stats = {}
                raw_stats = row["statistics_json"]
                if raw_stats:
                    try:
                        stats = json.loads(raw_stats)
                    except json.JSONDecodeError:
                        stats = {}
                normalized.append(
                    {
                        "session_id": row["session_id"],
                        "ecosystem": row["ecosystem"] if "ecosystem" in row.keys() else "claude_code",
                        "project_path": row["project_path"] or "",
                        "git_branch": row["git_branch"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "total_messages": row["total_messages"] or 0,
                        "total_tokens": row["total_tokens"] or 0,
                        "total_tool_calls": row["total_tool_calls"] or 0,
                        "duration_seconds": row["duration_seconds"],
                        "bottleneck": row["bottleneck"],
                        "automation_ratio": row["automation_ratio"],
                        "statistics": stats,
                    }
                )
            return normalized

        # In-memory fallback
        rows: list[dict[str, Any]] = []
        for session in self._sessions.values():
            created_at = session.metadata.created_at.isoformat()
            if not self._is_within_date_range(created_at, start_date, end_date):
                continue
            rows.append(
                {
                    "session_id": session.metadata.session_id,
                    "ecosystem": self._session_ecosystem.get(
                        session.metadata.session_id, "claude_code"
                    ),
                    "project_path": session.metadata.project_path,
                    "git_branch": session.metadata.git_branch,
                    "created_at": created_at,
                    "updated_at": (
                        session.metadata.updated_at.isoformat()
                        if session.metadata.updated_at
                        else None
                    ),
                    "total_messages": session.metadata.total_messages,
                    "total_tokens": session.metadata.total_tokens,
                    "total_tool_calls": (
                        session.statistics.total_tool_calls if session.statistics else 0
                    ),
                    "duration_seconds": (
                        session.statistics.session_duration_seconds
                        if session.statistics
                        else None
                    ),
                    "bottleneck": (
                        self._derive_bottleneck(session.statistics)
                        if session.statistics
                        else None
                    ),
                    "automation_ratio": (
                        self._derive_automation_ratio(session.statistics)
                        if session.statistics
                        else None
                    ),
                    "statistics": (
                        session.statistics.model_dump()
                        if session.statistics
                        else {}
                    ),
                }
            )
        return rows

    @staticmethod
    def _derive_bottleneck(statistics: SessionStatistics) -> str | None:
        if not statistics.time_breakdown:
            return None
        tbd = statistics.time_breakdown
        categories = [
            ("Model", tbd.model_time_percent),
            ("Tool", tbd.tool_time_percent),
            ("User", tbd.user_time_percent),
        ]
        return max(categories, key=lambda x: x[1])[0]

    @staticmethod
    def _derive_automation_ratio(statistics: SessionStatistics) -> float | None:
        tbd = statistics.time_breakdown
        if not tbd or tbd.user_interaction_count <= 0:
            return None
        return round(statistics.total_tool_calls / tbd.user_interaction_count, 2)

    @staticmethod
    def _parse_created_date(created_at: Any) -> date | None:
        if created_at is None:
            return None
        text = str(created_at).strip()
        if not text:
            return None
        try:
            if len(text) >= 10:
                return datetime.fromisoformat(text[:10]).date()
        except ValueError:
            return None
        return None

    @classmethod
    def _is_within_date_range(
        cls, created_at: str, start_date: str | None, end_date: str | None
    ) -> bool:
        created = cls._parse_created_date(created_at)
        if created is None:
            return False
        if start_date:
            start = datetime.fromisoformat(start_date).date()
            if created < start:
                return False
        if end_date:
            end = datetime.fromisoformat(end_date).date()
            if created > end:
                return False
        return True

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
