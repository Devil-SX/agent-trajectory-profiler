from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from click.testing import CliRunner

from agent_vis.cli.main import main
from agent_vis.db.connection import get_connection


def _write_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "[telegram]",
                "enabled = true",
                'bot_token = "test-token"',
                'chat_id = "12345"',
                'timezone = "UTC"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _insert_session(db_path: Path, session_id: str) -> None:
    now = datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc).isoformat()
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
                "claude_code",
                "/tmp/project",
                now,
                now,
                1,
                10,
                now,
                10.0,
                0,
                "model",
                0.0,
                "1.0.0",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_report_telegram_dry_run_command(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = tmp_path / "telegram.toml"
    state_path = tmp_path / "report-state.json"
    db_path = tmp_path / "profiler.db"

    _write_config(config_path)
    _insert_session(db_path, "session-1")

    result = runner.invoke(
        main,
        [
            "report",
            "telegram",
            "--dry-run",
            "--config-path",
            str(config_path),
            "--state-path",
            str(state_path),
            "--db-path",
            str(db_path),
        ],
    )

    assert result.exit_code == 0
    assert "Telegram Incremental Report" in result.output
    assert "Status:         dry-run" in result.output
    assert "Target chat:    12345" in result.output
    assert "Window end:" in result.output
