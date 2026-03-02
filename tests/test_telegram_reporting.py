from __future__ import annotations

import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_vis.db.connection import get_connection
from agent_vis.reporting.telegram import (
    ReportState,
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


def test_send_telegram_message_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "telegram.toml"
    _write_config(config_path)
    config = load_telegram_config(config_path)

    monkeypatch.setattr(
        "agent_vis.reporting.telegram.urllib.request.urlopen",
        lambda request, timeout=15.0: _DummyResponse(b'{"ok": true}'),
    )

    ok, excerpt = send_telegram_message(config, "hello")
    assert ok is True
    assert "ok" in excerpt


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

    def sender_ok(config, text):  # type: ignore[no-untyped-def]
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

    def sender_fail(config, text):  # type: ignore[no-untyped-def]
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
