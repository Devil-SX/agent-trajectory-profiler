from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

import agent_vis.cli.main as cli_main


class _FakeAnalyticsService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get_analytics_overview(
        self,
        start_date: str | None,
        end_date: str | None,
        *,
        ecosystem: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "overview",
                {
                    "start_date": start_date,
                    "end_date": end_date,
                    "ecosystem": ecosystem,
                },
            )
        )
        return {
            "start_date": start_date,
            "end_date": end_date,
            "total_sessions": 3,
            "ecosystem": ecosystem,
        }

    async def get_analytics_distribution(
        self,
        dimension: str,
        start_date: str | None,
        end_date: str | None,
        *,
        ecosystem: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "distributions",
                {
                    "dimension": dimension,
                    "start_date": start_date,
                    "end_date": end_date,
                    "ecosystem": ecosystem,
                },
            )
        )
        return {
            "dimension": dimension,
            "start_date": start_date,
            "end_date": end_date,
            "total": 100.0,
            "buckets": [],
        }

    async def get_analytics_timeseries(
        self,
        start_date: str | None,
        end_date: str | None,
        interval: str,
        *,
        ecosystem: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "timeseries",
                {
                    "interval": interval,
                    "start_date": start_date,
                    "end_date": end_date,
                    "ecosystem": ecosystem,
                },
            )
        )
        return {
            "interval": interval,
            "start_date": start_date,
            "end_date": end_date,
            "points": [],
        }

    async def get_project_comparison(
        self,
        start_date: str | None,
        end_date: str | None,
        limit: int,
        *,
        ecosystem: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "project-comparison",
                {
                    "start_date": start_date,
                    "end_date": end_date,
                    "limit": limit,
                    "ecosystem": ecosystem,
                },
            )
        )
        return {
            "start_date": start_date,
            "end_date": end_date,
            "total_projects": 1,
            "projects": [
                {
                    "project_path": "/tmp/demo",
                    "project_name": "demo",
                    "sessions": 1,
                    "total_tokens": 10,
                    "active_ratio": 0.5,
                    "leverage_tokens_mean": 1.0,
                    "leverage_chars_mean": 1.0,
                }
            ],
        }

    async def get_project_swimlane(
        self,
        start_date: str | None,
        end_date: str | None,
        interval: str,
        project_limit: int,
        *,
        ecosystem: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "project-swimlane",
                {
                    "interval": interval,
                    "start_date": start_date,
                    "end_date": end_date,
                    "project_limit": project_limit,
                    "ecosystem": ecosystem,
                },
            )
        )
        return {
            "interval": interval,
            "start_date": start_date,
            "end_date": end_date,
            "project_limit": project_limit,
            "truncated_project_count": 0,
            "periods": [],
            "projects": [],
            "points": [],
        }


def test_analytics_overview_uses_default_last_7_days(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _FakeAnalyticsService()
    monkeypatch.setattr(cli_main, "_build_readonly_session_service", lambda _: service)

    runner = CliRunner()
    result = runner.invoke(cli_main.main, ["analytics", "overview"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    expected_end = date.today()
    expected_start = expected_end - timedelta(days=6)
    assert payload["start_date"] == expected_start.isoformat()
    assert payload["end_date"] == expected_end.isoformat()
    assert service.calls == [
        (
            "overview",
            {
                "start_date": expected_start.isoformat(),
                "end_date": expected_end.isoformat(),
                "ecosystem": None,
            },
        )
    ]


def test_analytics_distributions_passes_dimension_and_filters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _FakeAnalyticsService()
    seen_db_paths: list[Path | None] = []

    def _fake_builder(db_path: Path | None) -> _FakeAnalyticsService:
        seen_db_paths.append(db_path)
        return service

    monkeypatch.setattr(cli_main, "_build_readonly_session_service", _fake_builder)

    runner = CliRunner()
    result = runner.invoke(
        cli_main.main,
        [
            "analytics",
            "distributions",
            "--dimension",
            "tool",
            "--start-date",
            "2026-03-01",
            "--end-date",
            "2026-03-07",
            "--ecosystem",
            "codex",
            "--db-path",
            str(tmp_path / "profiler.db"),
        ],
    )

    assert result.exit_code == 0
    assert seen_db_paths == [tmp_path / "profiler.db"]
    payload = json.loads(result.output)
    assert payload["dimension"] == "tool"
    assert service.calls == [
        (
            "distributions",
            {
                "dimension": "tool",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
                "ecosystem": "codex",
            },
        )
    ]


@pytest.mark.parametrize(
    ("argv", "expected_call"),
    [
        (
            [
                "analytics",
                "timeseries",
                "--interval",
                "week",
                "--ecosystem",
                "claude_code",
            ],
            (
                "timeseries",
                {
                    "interval": "week",
                    "start_date": (date.today() - timedelta(days=6)).isoformat(),
                    "end_date": date.today().isoformat(),
                    "ecosystem": "claude_code",
                },
            ),
        ),
        (
            [
                "analytics",
                "project-comparison",
                "--start-date",
                "2026-02-01",
                "--end-date",
                "2026-02-29",
                "--limit",
                "7",
            ],
            (
                "project-comparison",
                {
                    "start_date": "2026-02-01",
                    "end_date": "2026-02-29",
                    "limit": 7,
                    "ecosystem": None,
                },
            ),
        ),
        (
            [
                "analytics",
                "project-swimlane",
                "--interval",
                "week",
                "--project-limit",
                "5",
                "--ecosystem",
                "codex",
            ],
            (
                "project-swimlane",
                {
                    "interval": "week",
                    "start_date": (date.today() - timedelta(days=6)).isoformat(),
                    "end_date": date.today().isoformat(),
                    "project_limit": 5,
                    "ecosystem": "codex",
                },
            ),
        ),
    ],
)
def test_analytics_subcommands_forward_expected_arguments(
    argv: list[str],
    expected_call: tuple[str, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeAnalyticsService()
    monkeypatch.setattr(cli_main, "_build_readonly_session_service", lambda _: service)

    runner = CliRunner()
    result = runner.invoke(cli_main.main, argv)

    assert result.exit_code == 0
    assert service.calls == [expected_call]


def test_analytics_rejects_invalid_date() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli_main.main,
        ["analytics", "overview", "--start-date", "03-01-2026"],
    )

    assert result.exit_code == 1
    assert "Invalid --start-date format" in result.output
