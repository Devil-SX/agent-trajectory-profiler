"""Telegram incremental summary reporting utilities."""

from __future__ import annotations

import importlib
import json
import sys
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python <3.11 fallback
    tomllib = importlib.import_module("tomli")

from agent_vis.db.connection import get_connection
from agent_vis.db.repository import SessionRepository

DEFAULT_CONFIG_PATH = Path.home() / ".agent-vis" / "config" / "telegram.toml"
DEFAULT_STATE_PATH = Path.home() / ".agent-vis" / "state" / "report-state.json"


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool
    bot_token: str
    chat_id: str
    timezone: str = "UTC"
    disable_web_page_preview: bool = True


@dataclass(frozen=True)
class ReportState:
    last_report_sent_at: str | None = None
    last_report_status: str | None = None
    last_report_error: str | None = None


@dataclass(frozen=True)
class IncrementalSummary:
    session_count: int
    source_counts: dict[str, int]
    bottleneck_counts: dict[str, int]
    total_tool_errors: int
    error_category_counts: dict[str, int]


@dataclass(frozen=True)
class TelegramReportResult:
    status: str
    chat_id: str
    window_start: str | None
    window_end: str
    summary: IncrementalSummary
    response_excerpt: str


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_telegram_config(config_path: Path = DEFAULT_CONFIG_PATH) -> TelegramConfig:
    """Load telegram config from TOML file."""
    path = config_path.expanduser().resolve()
    if not path.exists():
        raise ValueError(f"Telegram config file not found: {path}")

    try:
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # toml parser type varies between implementations
        raise ValueError(f"Failed to parse telegram config: {exc}") from exc

    payload = parsed.get("telegram", parsed)
    if not isinstance(payload, dict):
        raise ValueError("Invalid telegram config structure: expected table/object")

    enabled = payload.get("enabled", False)
    bot_token = payload.get("bot_token", "")
    chat_id = payload.get("chat_id", "")
    tz = payload.get("timezone", "UTC")
    disable_preview = payload.get("disable_web_page_preview", True)

    if not isinstance(enabled, bool):
        raise ValueError("telegram.enabled must be a boolean")
    if not isinstance(bot_token, str) or not bot_token.strip():
        raise ValueError("telegram.bot_token is required")
    if not isinstance(chat_id, str) or not chat_id.strip():
        raise ValueError("telegram.chat_id is required")
    if not isinstance(tz, str) or not tz.strip():
        raise ValueError("telegram.timezone must be a non-empty string")
    if not isinstance(disable_preview, bool):
        raise ValueError("telegram.disable_web_page_preview must be a boolean")

    return TelegramConfig(
        enabled=enabled,
        bot_token=bot_token.strip(),
        chat_id=chat_id.strip(),
        timezone=tz.strip(),
        disable_web_page_preview=disable_preview,
    )


def load_report_state(state_path: Path = DEFAULT_STATE_PATH) -> ReportState:
    """Load report-state JSON. Missing file returns default state."""
    path = state_path.expanduser().resolve()
    if not path.exists():
        return ReportState()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to read report state: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("Invalid report state payload")

    return ReportState(
        last_report_sent_at=(
            str(raw.get("last_report_sent_at")) if raw.get("last_report_sent_at") else None
        ),
        last_report_status=(
            str(raw.get("last_report_status")) if raw.get("last_report_status") else None
        ),
        last_report_error=(
            str(raw.get("last_report_error")) if raw.get("last_report_error") else None
        ),
    )


def save_report_state_atomic(state: ReportState, state_path: Path = DEFAULT_STATE_PATH) -> None:
    """Atomically persist report state JSON with private file permissions."""
    path = state_path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass

    payload = {
        "last_report_sent_at": state.last_report_sent_at,
        "last_report_status": state.last_report_status,
        "last_report_error": state.last_report_error,
    }

    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        temp_path.chmod(0o600)
    except OSError:
        pass

    temp_path.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def build_incremental_summary(
    repo: SessionRepository,
    *,
    since: datetime | None,
) -> IncrementalSummary:
    """Build summary metrics for sessions created strictly after `since`."""
    conn = repo._conn
    rows = conn.execute(
        "SELECT session_id, ecosystem, created_at, bottleneck FROM sessions ORDER BY created_at ASC"
    ).fetchall()

    source_counts: Counter[str] = Counter()
    bottleneck_counts: Counter[str] = Counter()
    error_category_counts: Counter[str] = Counter()
    total_tool_errors = 0
    included_session_ids: list[str] = []

    for row in rows:
        created = _parse_iso_datetime(str(row["created_at"]))
        if created is None:
            continue
        if since is not None and created <= since:
            continue

        session_id = str(row["session_id"])
        included_session_ids.append(session_id)

        ecosystem = str(row["ecosystem"] or "unknown")
        source_counts[ecosystem] += 1

        bottleneck = str(row["bottleneck"] or "unknown")
        bottleneck_counts[bottleneck.lower()] += 1

        statistics = repo.get_statistics(session_id)
        if statistics is None:
            continue
        total_tool_errors += len(statistics.tool_error_records)
        for category, count in statistics.tool_error_category_counts.items():
            error_category_counts[category] += int(count)

    return IncrementalSummary(
        session_count=len(included_session_ids),
        source_counts=dict(source_counts),
        bottleneck_counts=dict(bottleneck_counts),
        total_tool_errors=total_tool_errors,
        error_category_counts=dict(error_category_counts),
    )


def format_telegram_report(
    summary: IncrementalSummary,
    *,
    window_start: datetime | None,
    window_end: datetime,
) -> str:
    """Format an incremental summary message for Telegram."""
    start_text = window_start.isoformat() if window_start else "initial-sync"
    source_text = (
        "\n".join(f"- {name}: {count}" for name, count in sorted(summary.source_counts.items()))
        or "- (no new source data)"
    )
    bottleneck_text = (
        "\n".join(f"- {name}: {count}" for name, count in sorted(summary.bottleneck_counts.items()))
        or "- (no bottleneck data)"
    )
    error_text = (
        "\n".join(
            f"- {name}: {count}" for name, count in sorted(summary.error_category_counts.items())
        )
        or "- (no categorized errors)"
    )

    return (
        "Agent Vis Incremental Summary\n"
        f"Window: {start_text} -> {window_end.isoformat()}\n"
        f"New sessions: {summary.session_count}\n\n"
        "Source distribution:\n"
        f"{source_text}\n\n"
        "Bottleneck distribution:\n"
        f"{bottleneck_text}\n\n"
        f"Tool errors (total): {summary.total_tool_errors}\n"
        "Tool error categories:\n"
        f"{error_text}"
    )


def send_telegram_message(
    config: TelegramConfig,
    text: str,
    *,
    timeout_seconds: float = 15.0,
) -> tuple[bool, str]:
    """Send one message through Telegram bot API."""
    url = f"https://api.telegram.org/bot{config.bot_token}/sendMessage"
    payload = {
        "chat_id": config.chat_id,
        "text": text,
        "disable_web_page_preview": config.disable_web_page_preview,
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Telegram HTTP error: {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Telegram URL error: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("Telegram request timed out") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Telegram response is not valid JSON") from exc

    if not isinstance(parsed, dict) or not bool(parsed.get("ok")):
        description = "unknown"
        if isinstance(parsed, dict):
            description = str(parsed.get("description") or "unknown")
        raise RuntimeError(f"Telegram API returned failure: {description}")

    return True, body[:240]


def run_telegram_incremental_report(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    db_path: Path | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
    sender: Callable[[TelegramConfig, str], tuple[bool, str]] = send_telegram_message,
) -> TelegramReportResult:
    """Run incremental telegram report workflow (load -> summarize -> send -> persist state)."""
    config = load_telegram_config(config_path)
    if not config.enabled:
        raise RuntimeError("Telegram report is disabled in config (telegram.enabled=false)")

    state = load_report_state(state_path)
    since = _parse_iso_datetime(state.last_report_sent_at)
    window_end_dt = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    conn = get_connection(db_path)
    repo = SessionRepository(conn)
    try:
        summary = build_incremental_summary(repo, since=since)
    finally:
        conn.close()

    message_text = format_telegram_report(summary, window_start=since, window_end=window_end_dt)

    if dry_run:
        return TelegramReportResult(
            status="dry-run",
            chat_id=config.chat_id,
            window_start=since.isoformat() if since else None,
            window_end=window_end_dt.isoformat(),
            summary=summary,
            response_excerpt="dry-run: not sent",
        )

    sender(config, message_text)

    # State is updated only after successful send.
    save_report_state_atomic(
        ReportState(
            last_report_sent_at=window_end_dt.isoformat(),
            last_report_status="success",
            last_report_error=None,
        ),
        state_path=state_path,
    )

    return TelegramReportResult(
        status="sent",
        chat_id=config.chat_id,
        window_start=since.isoformat() if since else None,
        window_end=window_end_dt.isoformat(),
        summary=summary,
        response_excerpt="sent",
    )
