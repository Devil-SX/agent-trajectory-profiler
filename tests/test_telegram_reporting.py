from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_vis.db.connection import get_connection
from agent_vis.reporting.telegram import (
    IncrementalSummary,
    ReportState,
    ToolErrorExcerpt,
    load_report_state,
    load_telegram_config,
    run_telegram_incremental_report,
    save_report_state_atomic,
    send_telegram_message,
)


def _write_config(path: Path, *, enabled: bool = True) -> None:
    path.write_text(
        "\n".join(
            [
                "[telegram]",
                f"enabled = {'true' if enabled else 'false'}",
                'bot_token = "test-token"',
                'chat_id = "12345"',
                'timezone = "UTC"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _insert_session(
    db_path: Path,
    session_id: str,
    created_at: datetime,
    ecosystem: str,
    bottleneck: str,
) -> None:
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sessions (
                session_id, ecosystem, project_path, created_at, updated_at,
                total_messages, total_tokens, parsed_at, duration_seconds,
                total_tool_calls, bottleneck, automation_ratio, version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                ecosystem,
                "/tmp/project",
                created_at.isoformat(),
                created_at.isoformat(),
                1,
                10,
                created_at.isoformat(),
                10.0,
                0,
                bottleneck,
                0.0,
                "1.0.0",
            ),
        )
        conn.commit()
    finally:
        conn.close()


class _DummyResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _DummyResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        return False

    def read(self) -> bytes:
        return self._body


def test_load_telegram_config_validation(tmp_path: Path) -> None:
    config_path = tmp_path / "telegram.toml"
    config_path.write_text("[telegram]\nenabled=true\nchat_id='123'\n", encoding="utf-8")

    with pytest.raises(ValueError, match="bot_token"):
        load_telegram_config(config_path)

    _write_config(config_path)
    config = load_telegram_config(config_path)
    assert config.enabled is True
    assert config.chat_id == "12345"
    assert config.report.format == "markdownv2"


def test_load_telegram_config_report_defaults_and_override(tmp_path: Path) -> None:
    config_path = tmp_path / "telegram.toml"
    config_path.write_text(
        "\n".join(
            [
                "[telegram]",
                "enabled = true",
                'bot_token = "test-token"',
                'chat_id = "12345"',
                "",
                "[telegram.report]",
                'style = "compact"',
                'format = "plain"',
                'detail_level = "low"',
                'split_mode = "single"',
                "max_message_chars = 1024",
                "send_details = false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config = load_telegram_config(config_path)
    assert config.report.style == "compact"
    assert config.report.format == "plain"
    assert config.report.detail_level == "low"
    assert config.report.split_mode == "single"
    assert config.report.max_message_chars == 1024
    assert config.report.send_details is False


def test_send_telegram_message_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "telegram.toml"
    _write_config(config_path)
    config = load_telegram_config(config_path)
    captured_payloads: list[dict[str, object]] = []

    def fake_urlopen(request, timeout=15.0):  # type: ignore[no-untyped-def]
        payload = json.loads(request.data.decode("utf-8"))
        captured_payloads.append(payload)
        return _DummyResponse(b'{"ok": true}')

    monkeypatch.setattr(
        "agent_vis.reporting.telegram.urllib.request.urlopen",
        fake_urlopen,
    )

    ok, excerpt = send_telegram_message(config, "hello", parse_mode="MarkdownV2")
    assert ok is True
    assert "ok" in excerpt
    assert captured_payloads[0]["parse_mode"] == "MarkdownV2"


def test_send_telegram_message_failure_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "telegram.toml"
    _write_config(config_path)
    config = load_telegram_config(config_path)

    def raise_http_error(request, timeout=15.0):  # type: ignore[no-untyped-def]
        raise urllib.error.HTTPError(
            url="https://example.com",
            code=500,
            msg="error",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("agent_vis.reporting.telegram.urllib.request.urlopen", raise_http_error)
    with pytest.raises(RuntimeError, match="HTTP error"):
        send_telegram_message(config, "hello")

    def raise_timeout(request, timeout=15.0):  # type: ignore[no-untyped-def]
        raise TimeoutError("timed out")

    monkeypatch.setattr("agent_vis.reporting.telegram.urllib.request.urlopen", raise_timeout)
    with pytest.raises(RuntimeError, match="timed out"):
        send_telegram_message(config, "hello")


def test_incremental_window_and_state_update_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "telegram.toml"
    state_path = tmp_path / "report-state.json"
    db_path = tmp_path / "profiler.db"
    _write_config(config_path)

    now = datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc)
    old = now - timedelta(hours=4)
    new = now - timedelta(hours=1)

    _insert_session(db_path, "old-session", old, "claude_code", "model")
    _insert_session(db_path, "new-session", new, "codex", "tool")

    save_report_state_atomic(
        ReportState(last_report_sent_at=(now - timedelta(hours=2)).isoformat()),
        state_path,
    )

    dry_run = run_telegram_incremental_report(
        config_path=config_path,
        state_path=state_path,
        db_path=db_path,
        dry_run=True,
        now=now,
    )
    assert dry_run.status == "dry-run"
    assert dry_run.summary.session_count == 1
    assert dry_run.summary.source_counts.get("codex") == 1

    def sender_ok(config, text, parse_mode=None):  # type: ignore[no-untyped-def]
        return True, "ok"

    sent = run_telegram_incremental_report(
        config_path=config_path,
        state_path=state_path,
        db_path=db_path,
        dry_run=False,
        now=now,
        sender=sender_ok,
    )
    assert sent.status == "sent"
    persisted = load_report_state(state_path)
    assert persisted.last_report_sent_at == now.isoformat()


def test_failed_send_does_not_advance_last_report_timestamp(tmp_path: Path) -> None:
    config_path = tmp_path / "telegram.toml"
    state_path = tmp_path / "report-state.json"
    db_path = tmp_path / "profiler.db"
    _write_config(config_path)

    initial_timestamp = "2026-03-01T00:00:00+00:00"
    save_report_state_atomic(ReportState(last_report_sent_at=initial_timestamp), state_path)

    def sender_fail(config, text, parse_mode=None):  # type: ignore[no-untyped-def]
        raise RuntimeError("network failure")

    with pytest.raises(RuntimeError, match="network failure"):
        run_telegram_incremental_report(
            config_path=config_path,
            state_path=state_path,
            db_path=db_path,
            dry_run=False,
            now=datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc),
            sender=sender_fail,
        )

    persisted = load_report_state(state_path)
    assert persisted.last_report_sent_at == initial_timestamp


def test_manual_preset_window_does_not_advance_last_report_timestamp(tmp_path: Path) -> None:
    config_path = tmp_path / "telegram.toml"
    state_path = tmp_path / "report-state.json"
    db_path = tmp_path / "profiler.db"
    _write_config(config_path)

    now = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
    initial_timestamp = "2026-03-09T00:00:00+00:00"
    save_report_state_atomic(ReportState(last_report_sent_at=initial_timestamp), state_path)

    _insert_session(db_path, "older-than-7d", now - timedelta(days=9), "claude_code", "model")
    _insert_session(db_path, "within-7d", now - timedelta(days=2), "codex", "tool")

    def sender_ok(config, text, parse_mode=None):  # type: ignore[no-untyped-def]
        return True, "ok"

    sent = run_telegram_incremental_report(
        config_path=config_path,
        state_path=state_path,
        db_path=db_path,
        dry_run=False,
        window="7d",
        now=now,
        sender=sender_ok,
    )
    assert sent.status == "sent"
    assert sent.window_mode == "manual:7d"
    assert sent.summary.session_count == 1
    assert sent.state_updated is False

    persisted = load_report_state(state_path)
    assert persisted.last_report_sent_at == initial_timestamp


def test_manual_days_overrides_auto_window_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "telegram.toml"
    state_path = tmp_path / "report-state.json"
    db_path = tmp_path / "profiler.db"
    _write_config(config_path)

    now = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
    save_report_state_atomic(
        ReportState(last_report_sent_at=(now - timedelta(hours=1)).isoformat()),
        state_path,
    )

    _insert_session(db_path, "within-3d", now - timedelta(days=2), "claude_code", "user")
    _insert_session(db_path, "within-1h", now - timedelta(minutes=30), "codex", "tool")

    def sender_ok(config, text, parse_mode=None):  # type: ignore[no-untyped-def]
        return True, "ok"

    sent = run_telegram_incremental_report(
        config_path=config_path,
        state_path=state_path,
        db_path=db_path,
        dry_run=False,
        window="auto",
        days=3,
        now=now,
        sender=sender_ok,
    )
    assert sent.window_mode == "manual:3d"
    assert sent.summary.session_count == 2
    assert sent.state_updated is False


def test_report_auto_split_sends_multiple_messages(tmp_path: Path) -> None:
    config_path = tmp_path / "telegram.toml"
    state_path = tmp_path / "report-state.json"
    db_path = tmp_path / "profiler.db"
    _write_config(config_path)

    now = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
    _insert_session(db_path, "within-1d", now - timedelta(hours=2), "claude_code", "tool")

    sent_payloads: list[tuple[str, str | None]] = []

    def sender_ok(config, text, parse_mode=None):  # type: ignore[no-untyped-def]
        sent_payloads.append((text, parse_mode))
        return True, "ok"

    result = run_telegram_incremental_report(
        config_path=config_path,
        state_path=state_path,
        db_path=db_path,
        dry_run=False,
        window="1d",
        now=now,
        sender=sender_ok,
        max_message_chars=620,
        split_mode="auto",
        send_details=True,
    )
    assert result.status == "sent"
    assert result.message_count >= 2
    assert all(mode == "MarkdownV2" for _, mode in sent_payloads)
    assert "overview" in result.sections_sent
    assert "role_breakdown" in result.sections_sent


def test_report_single_mode_truncates_when_over_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "telegram.toml"
    state_path = tmp_path / "report-state.json"
    db_path = tmp_path / "profiler.db"
    _write_config(config_path)
    now = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
    _insert_session(db_path, "within-1d", now - timedelta(hours=2), "claude_code", "tool")

    oversized_summary = IncrementalSummary(
        session_count=12,
        source_counts={"claude_code": 8, "codex": 4},
        bottleneck_counts={"model": 7, "tool": 3, "user": 2},
        total_tool_errors=14,
        error_category_counts={
            "network_timeout": 6,
            "permission_denied": 4,
            "schema_error": 4,
        },
        total_messages=2200,
        total_tokens=4_300_000,
        total_input_tokens=1_800_000,
        total_output_tokens=2_500_000,
        total_tool_calls=1800,
        total_trajectory_file_size_bytes=42_000_000,
        total_chars=10_000_000,
        total_cjk_chars=1_200_000,
        total_latin_chars=8_100_000,
        model_time_seconds=18_000,
        tool_time_seconds=6_000,
        user_time_seconds=2_000,
        inactive_time_seconds=500,
        active_time_ratio=0.98,
        model_timeout_count=9,
        error_excerpts=[
            ToolErrorExcerpt(
                timestamp="2026-03-10T10:00:00+00:00",
                tool_name="very_long_tool_name_for_telemetry_pipeline",
                category="network_timeout",
                preview="x" * 260,
            ),
            ToolErrorExcerpt(
                timestamp="2026-03-10T10:02:00+00:00",
                tool_name="very_long_tool_name_for_telemetry_pipeline",
                category="network_timeout",
                preview="y" * 260,
            ),
        ],
    )

    monkeypatch.setattr(
        "agent_vis.reporting.telegram.build_incremental_summary",
        lambda repo, since: oversized_summary,
    )

    dry = run_telegram_incremental_report(
        config_path=config_path,
        state_path=state_path,
        db_path=db_path,
        dry_run=True,
        window="1d",
        now=now,
        split_mode="single",
        detail_level="high",
        max_message_chars=512,
        send_details=True,
    )
    assert dry.message_count == 1
    assert dry.truncated is True
