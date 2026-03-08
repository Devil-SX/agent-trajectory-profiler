from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import agent_vis.cli.main as cli_main
from agent_vis.api.models import (
    CapabilityListResponse,
    FrontendPreferences,
    SessionDetailResponse,
    SessionListResponse,
    SessionStatisticsResponse,
    SyncStatusResponse,
)
from agent_vis.api.service import SessionService
from agent_vis.db.connection import get_connection


def _load_json_output(result_output: str) -> dict[str, object]:
    return json.loads(result_output)


def test_sessions_list_matches_service_response(
    initialized_session_service_sync: SessionService,
) -> None:
    sessions, total_count = asyncio.run(
        initialized_session_service_sync.list_sessions(page=1, page_size=5)
    )
    expected = SessionListResponse(
        sessions=sessions,
        count=total_count,
        page=1,
        page_size=5,
        total_pages=(total_count + 5 - 1) // 5 if total_count > 0 else 0,
    ).model_dump(mode="json")

    runner = CliRunner()
    result = runner.invoke(
        cli_main.main,
        [
            "sessions",
            "list",
            "--page-size",
            "5",
            "--db-path",
            str(initialized_session_service_sync._db_path),
        ],
    )

    assert result.exit_code == 0
    assert _load_json_output(result.output) == expected


def test_sessions_get_and_statistics_match_service_payloads(
    initialized_session_service_sync: SessionService,
) -> None:
    sessions, _ = asyncio.run(initialized_session_service_sync.list_sessions(page=1, page_size=1))
    session_id = sessions[0].session_id

    expected_detail = SessionDetailResponse(
        session=asyncio.run(initialized_session_service_sync.get_session(session_id))
    ).model_dump(mode="json")
    expected_statistics = SessionStatisticsResponse(
        session_id=session_id,
        statistics=asyncio.run(initialized_session_service_sync.get_session_statistics(session_id)),
    ).model_dump(mode="json")

    runner = CliRunner()
    detail_result = runner.invoke(
        cli_main.main,
        [
            "sessions",
            "get",
            session_id,
            "--db-path",
            str(initialized_session_service_sync._db_path),
        ],
    )
    stats_result = runner.invoke(
        cli_main.main,
        [
            "sessions",
            "statistics",
            session_id,
            "--db-path",
            str(initialized_session_service_sync._db_path),
        ],
    )

    assert detail_result.exit_code == 0
    assert stats_result.exit_code == 0
    assert _load_json_output(detail_result.output) == expected_detail
    assert _load_json_output(stats_result.output) == expected_statistics


def test_stats_json_mode_matches_session_statistics_response(
    initialized_session_service_sync: SessionService,
) -> None:
    sessions, _ = asyncio.run(initialized_session_service_sync.list_sessions(page=1, page_size=1))
    session_id = sessions[0].session_id
    expected = SessionStatisticsResponse(
        session_id=session_id,
        statistics=asyncio.run(initialized_session_service_sync.get_session_statistics(session_id)),
    ).model_dump(mode="json")

    runner = CliRunner()
    result = runner.invoke(
        cli_main.main,
        [
            "stats",
            "--session-id",
            session_id,
            "--json",
            "--db-path",
            str(initialized_session_service_sync._db_path),
        ],
    )

    assert result.exit_code == 0
    assert _load_json_output(result.output) == expected


def test_sync_status_capabilities_and_frontend_preferences_match_service_models(
    initialized_session_service_sync: SessionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview_service = cli_main._build_readonly_session_service(
        initialized_session_service_sync._db_path
    )
    preview_service._last_sync_detail = initialized_session_service_sync._last_sync_detail
    preview_service._sync_running = initialized_session_service_sync._sync_running
    try:
        expected_sync = SyncStatusResponse(**preview_service.get_sync_status()).model_dump(
            mode="json"
        )
        expected_capabilities = CapabilityListResponse(
            capabilities=preview_service.get_capabilities()
        ).model_dump(mode="json")
        expected_preferences = FrontendPreferences(
            **preview_service.get_frontend_preferences().model_dump()
        ).model_dump(mode="json")
    finally:
        if getattr(preview_service, "_conn", None) is not None:
            preview_service._conn.close()

    original_builder = cli_main._build_readonly_session_service

    def _fresh_builder(_db_path: Path | None) -> SessionService:
        service = original_builder(initialized_session_service_sync._db_path)
        service._last_sync_detail = initialized_session_service_sync._last_sync_detail
        service._sync_running = initialized_session_service_sync._sync_running
        return service

    monkeypatch.setattr(cli_main, "_build_readonly_session_service", _fresh_builder)

    runner = CliRunner()
    sync_result = runner.invoke(
        cli_main.main,
        ["sync-status", "--db-path", str(initialized_session_service_sync._db_path)],
    )
    capabilities_result = runner.invoke(
        cli_main.main,
        ["capabilities", "--db-path", str(initialized_session_service_sync._db_path)],
    )
    preferences_result = runner.invoke(
        cli_main.main,
        ["frontend-preferences", "--db-path", str(initialized_session_service_sync._db_path)],
    )

    assert sync_result.exit_code == 0
    assert capabilities_result.exit_code == 0
    assert preferences_result.exit_code == 0
    assert _load_json_output(sync_result.output) == expected_sync
    assert _load_json_output(capabilities_result.output) == expected_capabilities
    assert _load_json_output(preferences_result.output) == expected_preferences


def test_sessions_list_rejects_invalid_filter_range() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli_main.main,
        ["sessions", "list", "--min-tokens", "10", "--max-tokens", "5"],
    )

    assert result.exit_code == 1
    assert "min_tokens must be <= max_tokens" in result.output


def test_stats_json_requires_session_id(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    conn = get_connection(db_path)
    conn.close()

    runner = CliRunner()
    result = runner.invoke(cli_main.main, ["stats", "--json", "--db-path", str(db_path)])

    assert result.exit_code == 1
    assert "--json requires --session-id" in result.output
