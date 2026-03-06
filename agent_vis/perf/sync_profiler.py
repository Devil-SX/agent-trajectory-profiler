"""Real-data sync profiling helpers for private local analysis."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from agent_vis.db.connection import get_connection
from agent_vis.db.repository import SessionRepository
from agent_vis.exceptions import SessionParseError
from agent_vis.models import Session
from agent_vis.parsers.capabilities import get_capability_warnings
from agent_vis.parsers.claude_code import (
    ClaudeCodeParser,
    calculate_session_statistics,
    extract_compact_events,
    extract_session_metadata,
    extract_subagent_sessions,
    parse_jsonl_file,
)

PRIVATE_SYNC_ROOT_ENV = "AGENT_VIS_PRIVATE_SYNC_ROOT"
PRIVATE_SYNC_FILE_ENV = "AGENT_VIS_PRIVATE_SYNC_FILE"
_STAGE_ORDER = [
    "find_session_files_ms",
    "file_stat_ms",
    "parse_jsonl_file_ms",
    "extract_session_metadata_ms",
    "extract_subagent_sessions_ms",
    "calculate_session_statistics_ms",
    "extract_compact_events_ms",
    "build_session_ms",
    "upsert_tracked_file_ms",
    "capability_warnings_ms",
    "upsert_session_ms",
    "upsert_statistics_ms",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_private_root() -> Path:
    return _repo_root() / "tests" / "fixtures" / "private" / "claude_sync_root"


def _default_private_file() -> Path:
    return _repo_root() / "tests" / "fixtures" / "private" / "claude_sync_long_session.jsonl"


def resolve_private_sync_root() -> Path:
    raw = os.getenv(PRIVATE_SYNC_ROOT_ENV)
    if raw:
        return Path(raw).expanduser()
    return _default_private_root()


def resolve_private_sync_file() -> Path:
    raw = os.getenv(PRIVATE_SYNC_FILE_ENV)
    if raw:
        return Path(raw).expanduser()
    return _default_private_file()


def _count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def _relative_label(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return path.name


def _measure(callable_obj: Any, *args: Any, **kwargs: Any) -> tuple[Any, float]:
    started = time.perf_counter()
    value = callable_obj(*args, **kwargs)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return value, elapsed_ms


def profile_session_file(
    file_path: Path,
    *,
    parser: ClaudeCodeParser | None = None,
    file_size_bytes: int | None = None,
) -> dict[str, Any]:
    parser = parser or ClaudeCodeParser()
    stage_timings: dict[str, float] = {}

    started = time.perf_counter()
    if file_size_bytes is None:
        stat_result, stat_ms = _measure(file_path.stat)
        stage_timings["file_stat_ms"] = stat_ms
        file_size_bytes = stat_result.st_size

    messages, parse_ms = _measure(parse_jsonl_file, file_path)
    stage_timings["parse_jsonl_file_ms"] = parse_ms
    if not messages:
        raise SessionParseError(f"No valid messages found in {file_path}")

    session_id = file_path.stem
    metadata, metadata_ms = _measure(extract_session_metadata, messages, session_id, file_path)
    stage_timings["extract_session_metadata_ms"] = metadata_ms

    subagent_sessions, subagent_ms = _measure(extract_subagent_sessions, messages)
    stage_timings["extract_subagent_sessions_ms"] = subagent_ms

    statistics, stats_ms = _measure(
        calculate_session_statistics,
        messages,
        inactivity_threshold=parser.inactivity_threshold,
        model_timeout_threshold=parser.model_timeout_threshold,
        trajectory_file_size_bytes=file_size_bytes,
    )
    stage_timings["calculate_session_statistics_ms"] = stats_ms

    compact_events, compact_ms = _measure(extract_compact_events, file_path)
    stage_timings["extract_compact_events_ms"] = compact_ms
    statistics.compact_count = len(compact_events)
    statistics.compact_events = compact_events

    session, build_ms = _measure(
        Session,
        metadata=metadata,
        messages=messages,
        subagent_sessions=subagent_sessions,
        statistics=statistics,
    )
    stage_timings["build_session_ms"] = build_ms

    total_ms = (time.perf_counter() - started) * 1000.0
    return {
        "session": session,
        "file_path": str(file_path),
        "line_count": _count_lines(file_path),
        "file_size_bytes": file_size_bytes,
        "message_count": len(messages),
        "stage_timings_ms": stage_timings,
        "total_ms": total_ms,
    }


def _persist_session_profile(
    repo: SessionRepository,
    session: Session,
    *,
    file_path: Path,
    file_size: int,
    file_mtime: float,
    ecosystem: str,
) -> dict[str, float]:
    stage_timings: dict[str, float] = {}
    abs_path = str(file_path.resolve())

    file_id, tracked_ms = _measure(
        repo.upsert_tracked_file,
        abs_path,
        file_size,
        file_mtime,
        ecosystem,
        "parsed",
    )
    stage_timings["upsert_tracked_file_ms"] = tracked_ms

    meta = session.metadata
    stats = session.statistics

    warnings_started = time.perf_counter()
    if stats is not None:
        get_capability_warnings(
            ecosystem,
            total_tool_calls=stats.total_tool_calls,
            cache_read_tokens=stats.cache_read_tokens,
            cache_creation_tokens=stats.cache_creation_tokens,
            has_tool_error_records=bool(stats.tool_error_records),
            has_subagent_sessions=bool(session.subagent_sessions),
        )
    stage_timings["capability_warnings_ms"] = (time.perf_counter() - warnings_started) * 1000.0

    bottleneck: str | None = None
    automation_ratio: float | None = None
    if stats and stats.time_breakdown:
        tbd = stats.time_breakdown
        categories = [
            ("Model", tbd.model_time_percent),
            ("Tool", tbd.tool_time_percent),
            ("User", tbd.user_time_percent),
        ]
        bottleneck = max(categories, key=lambda item: item[1])[0]
        if tbd.user_interaction_count > 0:
            automation_ratio = round(stats.total_tool_calls / tbd.user_interaction_count, 2)

    created_at_str = meta.created_at.isoformat() if meta.created_at else None
    updated_at_str = meta.updated_at.isoformat() if meta.updated_at else None

    _, session_ms = _measure(
        repo.upsert_session,
        session_id=meta.session_id,
        file_id=file_id,
        ecosystem=ecosystem,
        physical_session_id=meta.physical_session_id,
        logical_session_id=meta.logical_session_id,
        parent_session_id=meta.parent_session_id,
        root_session_id=meta.root_session_id,
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
    stage_timings["upsert_session_ms"] = session_ms

    if stats is not None:
        _, stats_write_ms = _measure(repo.upsert_statistics, meta.session_id, stats)
    else:
        stats_write_ms = 0.0
    stage_timings["upsert_statistics_ms"] = stats_write_ms
    return stage_timings


def render_sync_profile_markdown(payload: dict[str, Any], *, title: str) -> str:
    summary = payload["summary"]
    lines = [
        f"## {title}",
        "",
        f"- Source: `{payload['source']}`",
        f"- Profiled at: `{payload['generated_at']}`",
        f"- Files selected: `{summary['selected_files']}` / `{summary['discovered_files']}`",
        f"- Parsed files: `{summary['parsed_files']}`",
        f"- Error count: `{summary['error_count']}`",
        f"- Total sync time: `{summary['total_sync_ms']:.2f} ms`",
        f"- Avg per file: `{summary['avg_file_ms']:.2f} ms`",
        "",
        "### Stage Breakdown",
        "",
        "| Stage | Total ms | Share | Calls | Avg ms/call |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in payload["stage_breakdown"]:
        lines.append(
            "| "
            f"`{row['stage']}` | {row['total_ms']:.2f} | {row['share_percent']:.1f}% | "
            f"{row['calls']} | {row['avg_ms_per_call']:.2f} |"
        )

    lines.extend(
        [
            "",
            "### Slow Files",
            "",
            "| File | Total ms | Lines | Messages | Parse ms | Stats ms | Persist ms |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in payload["slow_files"]:
        lines.append(
            "| "
            f"`{row['file']}` | {row['total_ms']:.2f} | {row['line_count']} | "
            f"{row['message_count']} | {row['parse_ms']:.2f} | {row['stats_ms']:.2f} | "
            f"{row['persist_ms']:.2f} |"
        )

    if payload["errors"]:
        lines.extend(["", "### Errors", ""])
        for item in payload["errors"][:10]:
            lines.append(f"- `{item['file']}`: {item['error']}")

    return "\n".join(lines) + "\n"


def write_sync_profile_artifacts(
    payload: dict[str, Any],
    output_dir: Path,
    *,
    prefix: str = "real-sync-profile",
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_latest = output_dir / f"{prefix}-results.json"
    md_latest = output_dir / f"{prefix}-summary.md"
    json_archive = output_dir / f"{prefix}-results-{stamp}.json"
    md_archive = output_dir / f"{prefix}-summary-{stamp}.md"

    markdown = render_sync_profile_markdown(payload, title="Real Sync Profile Summary")
    serialized = json.dumps(payload, indent=2, ensure_ascii=False)
    json_latest.write_text(serialized, encoding="utf-8")
    md_latest.write_text(markdown, encoding="utf-8")
    json_archive.write_text(serialized, encoding="utf-8")
    md_archive.write_text(markdown, encoding="utf-8")
    return json_latest, md_latest


def profile_sync_directory(
    directory: Path,
    *,
    parser: ClaudeCodeParser | None = None,
    max_files: int | None = None,
    top_n: int = 10,
    output_dir: Path | None = None,
) -> tuple[dict[str, Any], Path | None, Path | None]:
    parser = parser or ClaudeCodeParser()
    stage_totals = dict.fromkeys(_STAGE_ORDER, 0.0)
    stage_calls = dict.fromkeys(_STAGE_ORDER, 0)
    errors: list[dict[str, str]] = []
    file_profiles: list[dict[str, Any]] = []

    total_started = time.perf_counter()
    files, find_ms = _measure(parser.find_session_files, directory)
    stage_totals["find_session_files_ms"] += find_ms
    stage_calls["find_session_files_ms"] += 1

    discovered_files = len(files)
    if max_files is not None:
        files = files[:max_files]

    with TemporaryDirectory(prefix="agent-vis-real-sync-profile-") as tmp:
        db_path = Path(tmp) / "profile.db"
        conn = get_connection(db_path)
        repo = SessionRepository(conn)
        try:
            with repo.transaction():
                for file_path in files:
                    file_label = _relative_label(directory, file_path)
                    file_started = time.perf_counter()
                    try:
                        stat_result, stat_ms = _measure(file_path.stat)
                        stage_totals["file_stat_ms"] += stat_ms
                        stage_calls["file_stat_ms"] += 1

                        session_profile = profile_session_file(
                            file_path,
                            parser=parser,
                            file_size_bytes=stat_result.st_size,
                        )
                        for stage, elapsed_ms in session_profile["stage_timings_ms"].items():
                            stage_totals[stage] += elapsed_ms
                            stage_calls[stage] += 1

                        persist_timings = _persist_session_profile(
                            repo,
                            session_profile["session"],
                            file_path=file_path,
                            file_size=stat_result.st_size,
                            file_mtime=stat_result.st_mtime,
                            ecosystem=parser.ecosystem_name,
                        )
                        for stage, elapsed_ms in persist_timings.items():
                            stage_totals[stage] += elapsed_ms
                            stage_calls[stage] += 1

                        total_ms = (time.perf_counter() - file_started) * 1000.0
                        file_profiles.append(
                            {
                                "file": file_label,
                                "line_count": session_profile["line_count"],
                                "file_size_bytes": session_profile["file_size_bytes"],
                                "message_count": session_profile["message_count"],
                                "total_ms": total_ms,
                                "parse_ms": session_profile["stage_timings_ms"][
                                    "parse_jsonl_file_ms"
                                ],
                                "stats_ms": session_profile["stage_timings_ms"][
                                    "calculate_session_statistics_ms"
                                ],
                                "persist_ms": sum(persist_timings.values()),
                                "stage_timings_ms": {
                                    "file_stat_ms": stat_ms,
                                    **session_profile["stage_timings_ms"],
                                    **persist_timings,
                                },
                            }
                        )
                    except Exception as exc:
                        errors.append({"file": file_label, "error": str(exc)})
        finally:
            conn.close()

    total_sync_ms = (time.perf_counter() - total_started) * 1000.0
    parsed_files = len(file_profiles)
    total_lines = sum(item["line_count"] for item in file_profiles)
    total_bytes = sum(item["file_size_bytes"] for item in file_profiles)
    avg_file_ms = total_sync_ms / parsed_files if parsed_files else 0.0
    avg_lines_per_file = total_lines / parsed_files if parsed_files else 0.0
    avg_bytes_per_file = total_bytes / parsed_files if parsed_files else 0.0

    stage_breakdown = []
    for stage in _STAGE_ORDER:
        total_ms = stage_totals[stage]
        calls = stage_calls[stage]
        if total_ms <= 0 and calls == 0:
            continue
        stage_breakdown.append(
            {
                "stage": stage,
                "total_ms": total_ms,
                "share_percent": (total_ms / total_sync_ms * 100.0) if total_sync_ms else 0.0,
                "calls": calls,
                "avg_ms_per_call": total_ms / calls if calls else 0.0,
            }
        )
    stage_breakdown.sort(key=lambda item: cast(float, item["total_ms"]), reverse=True)

    slow_files = sorted(
        file_profiles, key=lambda item: cast(float, item["total_ms"]), reverse=True
    )[:top_n]

    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(directory.resolve()),
        "summary": {
            "discovered_files": discovered_files,
            "selected_files": len(files),
            "parsed_files": parsed_files,
            "error_count": len(errors),
            "total_sync_ms": total_sync_ms,
            "avg_file_ms": avg_file_ms,
            "total_lines": total_lines,
            "avg_lines_per_file": avg_lines_per_file,
            "total_bytes": total_bytes,
            "avg_bytes_per_file": avg_bytes_per_file,
        },
        "stage_breakdown": stage_breakdown,
        "slow_files": slow_files,
        "errors": errors,
    }

    json_path = None
    md_path = None
    if output_dir is not None:
        json_path, md_path = write_sync_profile_artifacts(payload, output_dir)
    return payload, json_path, md_path
