"""Backend performance benchmark runner for API + sync + parser hotspots."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from typing import Any

from agent_vis.api.service import SessionService
from agent_vis.db.connection import get_connection
from agent_vis.db.repository import SessionRepository
from agent_vis.db.sync import SyncEngine
from agent_vis.parsers.claude_code import (
    ClaudeCodeParser,
    calculate_session_statistics,
    parse_jsonl_file,
)
from agent_vis.perf.framework import (
    BudgetEvaluationReport,
    evaluate_metrics,
    load_metric_budgets,
    render_markdown_summary,
    serialize_report,
)


@dataclass(frozen=True)
class PerfProfile:
    """Benchmark dataset and iteration profile."""

    session_count: int
    turns_per_session: int
    api_iterations: int
    stats_iterations: int


PROFILES: dict[str, PerfProfile] = {
    "quick": PerfProfile(
        session_count=28,
        turns_per_session=14,
        api_iterations=12,
        stats_iterations=20,
    ),
    "full": PerfProfile(
        session_count=80,
        turns_per_session=28,
        api_iterations=24,
        stats_iterations=40,
    ),
}


def _percentile50(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(median(values))


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row) + "\n")


def _build_session_records(
    session_id: str, *, base_time: datetime, turns: int
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for turn in range(turns):
        user_time = base_time + timedelta(seconds=turn * 16)
        tool_use_time = user_time + timedelta(seconds=2)
        tool_result_time = user_time + timedelta(seconds=6)
        assistant_time = user_time + timedelta(seconds=8)
        tool_id = f"tool-{session_id}-{turn:04d}"

        records.append(
            {
                "type": "user",
                "sessionId": session_id,
                "uuid": f"u-{turn:04d}",
                "timestamp": user_time.isoformat().replace("+00:00", "Z"),
                "message": {
                    "role": "user",
                    "content": f"Please inspect module {turn}",
                },
            }
        )
        records.append(
            {
                "type": "assistant",
                "sessionId": session_id,
                "uuid": f"a-tool-{turn:04d}",
                "timestamp": tool_use_time.isoformat().replace("+00:00", "Z"),
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Running command"},
                        {
                            "type": "tool_use",
                            "id": tool_id,
                            "name": "Bash",
                            "input": {"command": f"rg -n module_{turn} src"},
                        },
                    ],
                    "usage": {
                        "input_tokens": 90 + (turn % 11),
                        "output_tokens": 35 + (turn % 7),
                        "cache_read_input_tokens": turn % 5,
                    },
                },
            }
        )
        records.append(
            {
                "type": "user",
                "sessionId": session_id,
                "uuid": f"tool-result-{turn:04d}",
                "timestamp": tool_result_time.isoformat().replace("+00:00", "Z"),
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "is_error": False,
                            "content": f"module_{turn}.py:1: class Example{turn}: pass",
                        }
                    ],
                },
            }
        )
        records.append(
            {
                "type": "assistant",
                "sessionId": session_id,
                "uuid": f"a-answer-{turn:04d}",
                "timestamp": assistant_time.isoformat().replace("+00:00", "Z"),
                "message": {
                    "role": "assistant",
                    "content": f"Found references for module {turn}.",
                    "usage": {
                        "input_tokens": 70 + (turn % 9),
                        "output_tokens": 42 + (turn % 5),
                        "cache_creation_input_tokens": turn % 3,
                    },
                },
            }
        )

    return records


def _create_dataset(
    base_dir: Path, *, session_count: int, turns_per_session: int
) -> tuple[Path, str, str]:
    sessions_dir = base_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    start_dt = datetime(2026, 2, 1, 8, 0, 0, tzinfo=timezone.utc)
    end_dt = start_dt

    for idx in range(session_count):
        session_id = f"perf-session-{idx:04d}"
        session_start = start_dt + timedelta(minutes=idx * 13)
        records = _build_session_records(
            session_id,
            base_time=session_start,
            turns=turns_per_session,
        )
        end_dt = max(end_dt, session_start + timedelta(seconds=turns_per_session * 16 + 8))
        _write_jsonl(sessions_dir / f"{session_id}.jsonl", records)

    return sessions_dir, start_dt.date().isoformat(), end_dt.date().isoformat()


def _measure_statistics_hotpath(sample_file: Path, *, iterations: int) -> list[float]:
    messages = parse_jsonl_file(sample_file)
    samples_ms: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        _ = calculate_session_statistics(messages)
        samples_ms.append((time.perf_counter() - started) * 1000.0)
    return samples_ms


async def _measure_api_calls(
    *,
    sessions_dir: Path,
    codex_dir: Path,
    db_path: Path,
    start_date: str,
    end_date: str,
    iterations: int,
) -> tuple[list[float], list[float]]:
    service = SessionService(
        session_path=sessions_dir,
        codex_session_path=codex_dir,
        db_path=db_path,
    )
    await service.initialize()

    overview_samples_ms: list[float] = []
    timeseries_samples_ms: list[float] = []

    for _ in range(iterations):
        started = time.perf_counter()
        _ = await service.get_analytics_overview(start_date, end_date)
        overview_samples_ms.append((time.perf_counter() - started) * 1000.0)

        started = time.perf_counter()
        _ = await service.get_analytics_timeseries(start_date, end_date, interval="day")
        timeseries_samples_ms.append((time.perf_counter() - started) * 1000.0)

    return overview_samples_ms, timeseries_samples_ms


def _resolve_profile(
    mode: str,
    *,
    session_count: int | None,
    turns_per_session: int | None,
    api_iterations: int | None,
    stats_iterations: int | None,
) -> PerfProfile:
    if mode not in PROFILES:
        raise ValueError(f"Unsupported mode '{mode}'. Expected one of: {', '.join(PROFILES)}")

    profile = PROFILES[mode]
    return PerfProfile(
        session_count=session_count or profile.session_count,
        turns_per_session=turns_per_session or profile.turns_per_session,
        api_iterations=api_iterations or profile.api_iterations,
        stats_iterations=stats_iterations or profile.stats_iterations,
    )


def run_backend_performance(
    *,
    mode: str,
    output_dir: Path,
    budgets_path: Path,
    session_count: int | None = None,
    turns_per_session: int | None = None,
    api_iterations: int | None = None,
    stats_iterations: int | None = None,
) -> tuple[BudgetEvaluationReport, dict[str, Any], Path, Path]:
    """Run backend performance benchmarks and write JSON/Markdown artifacts."""
    profile = _resolve_profile(
        mode,
        session_count=session_count,
        turns_per_session=turns_per_session,
        api_iterations=api_iterations,
        stats_iterations=stats_iterations,
    )

    with TemporaryDirectory(prefix="agent-vis-perf-") as tmp:
        tmp_root = Path(tmp)
        sessions_dir, start_date, end_date = _create_dataset(
            tmp_root,
            session_count=profile.session_count,
            turns_per_session=profile.turns_per_session,
        )
        codex_dir = tmp_root / "codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        db_path = tmp_root / "perf.db"

        conn = get_connection(db_path)
        repo = SessionRepository(conn)
        parser = ClaudeCodeParser()
        sync_engine = SyncEngine(repo, parser)

        sync_started = time.perf_counter()
        sync_result = sync_engine.sync(sessions_dir, force=True)
        sync_elapsed = time.perf_counter() - sync_started
        conn.close()

        if sync_result.parsed <= 0:
            raise RuntimeError("Sync benchmark dataset did not produce parsed sessions")

        statistics_samples_ms = _measure_statistics_hotpath(
            sessions_dir / "perf-session-0000.jsonl",
            iterations=profile.stats_iterations,
        )
        overview_samples_ms, timeseries_samples_ms = asyncio.run(
            _measure_api_calls(
                sessions_dir=sessions_dir,
                codex_dir=codex_dir,
                db_path=db_path,
                start_date=start_date,
                end_date=end_date,
                iterations=profile.api_iterations,
            )
        )

    measured_metrics = {
        "sync_full_parse_seconds": sync_elapsed,
        "sync_sessions_per_second": sync_result.parsed / sync_elapsed if sync_elapsed > 0 else 0.0,
        "parser_statistics_p50_ms": _percentile50(statistics_samples_ms),
        "api_overview_p50_ms": _percentile50(overview_samples_ms),
        "api_timeseries_p50_ms": _percentile50(timeseries_samples_ms),
    }

    budgets = load_metric_budgets(budgets_path, mode)
    report = evaluate_metrics(measured_metrics, budgets, mode=mode)

    generated_at = datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "generated_at": generated_at,
        "mode": mode,
        "profile": {
            "session_count": profile.session_count,
            "turns_per_session": profile.turns_per_session,
            "api_iterations": profile.api_iterations,
            "stats_iterations": profile.stats_iterations,
        },
        "metrics": measured_metrics,
        "samples": {
            "parser_statistics_ms": statistics_samples_ms,
            "api_overview_ms": overview_samples_ms,
            "api_timeseries_ms": timeseries_samples_ms,
        },
        "sync": {
            "parsed": sync_result.parsed,
            "skipped": sync_result.skipped,
            "errors": sync_result.errors,
            "elapsed_seconds": sync_elapsed,
        },
        "budget": serialize_report(report),
    }

    markdown = render_markdown_summary(report, title="Backend Performance Summary")

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    json_latest = output_dir / "backend-perf-results.json"
    md_latest = output_dir / "backend-perf-summary.md"
    json_archive = output_dir / f"backend-perf-results-{mode}-{stamp}.json"
    md_archive = output_dir / f"backend-perf-summary-{mode}-{stamp}.md"

    json_latest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_latest.write_text(markdown, encoding="utf-8")
    json_archive.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_archive.write_text(markdown, encoding="utf-8")

    return report, payload, json_latest, md_latest
