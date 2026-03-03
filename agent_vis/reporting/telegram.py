"""Telegram incremental summary reporting utilities."""

from __future__ import annotations

import html
import importlib
import json
import sys
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python <3.11 fallback
    tomllib = importlib.import_module("tomli")

from agent_vis.db.connection import get_connection
from agent_vis.db.repository import SessionRepository

DEFAULT_CONFIG_PATH = Path.home() / ".agent-vis" / "config" / "telegram.toml"
DEFAULT_STATE_PATH = Path.home() / ".agent-vis" / "state" / "report-state.json"

WINDOW_PRESET_DAYS: dict[str, int] = {
    "1d": 1,
    "3d": 3,
    "7d": 7,
    "14d": 14,
    "30d": 30,
    "90d": 90,
}
REPORT_STYLE_CHOICES = {"advanced", "compact"}
REPORT_FORMAT_CHOICES = {"markdownv2", "html", "plain"}
DETAIL_LEVEL_CHOICES = {"low", "medium", "high"}
SPLIT_MODE_CHOICES = {"auto", "single"}


@dataclass(frozen=True)
class TelegramReportOptions:
    style: str = "advanced"
    format: str = "markdownv2"
    detail_level: str = "medium"
    split_mode: str = "auto"
    max_message_chars: int = 3800
    send_details: bool = True


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool
    bot_token: str
    chat_id: str
    timezone: str = "UTC"
    disable_web_page_preview: bool = True
    report: TelegramReportOptions = field(default_factory=TelegramReportOptions)


@dataclass(frozen=True)
class ReportState:
    last_report_sent_at: str | None = None
    last_report_status: str | None = None
    last_report_error: str | None = None


@dataclass(frozen=True)
class ToolErrorExcerpt:
    timestamp: str
    tool_name: str
    category: str
    preview: str


@dataclass(frozen=True)
class IncrementalSummary:
    session_count: int
    source_counts: dict[str, int]
    bottleneck_counts: dict[str, int]
    total_tool_errors: int
    error_category_counts: dict[str, int]
    total_messages: int = 0
    total_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tool_calls: int = 0
    total_trajectory_file_size_bytes: int = 0
    total_chars: int = 0
    total_cjk_chars: int = 0
    total_latin_chars: int = 0
    model_time_seconds: float = 0.0
    tool_time_seconds: float = 0.0
    user_time_seconds: float = 0.0
    inactive_time_seconds: float = 0.0
    active_time_ratio: float = 0.0
    model_timeout_count: int = 0
    error_excerpts: list[ToolErrorExcerpt] = field(default_factory=list)


@dataclass(frozen=True)
class TelegramReportResult:
    status: str
    chat_id: str
    window_mode: str
    window_start: str | None
    window_end: str
    state_updated: bool
    summary: IncrementalSummary
    response_excerpt: str
    render_format: str = "plain"
    message_count: int = 0
    sections_sent: list[str] = field(default_factory=list)
    truncated: bool = False


@dataclass(frozen=True)
class _ReportSection:
    key: str
    title: str
    body: str


SenderCallable = Callable[[TelegramConfig, str, str | None], tuple[bool, str]]


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


def _parse_choice(
    value: object,
    *,
    key: str,
    choices: set[str],
    default: str,
    aliases: dict[str, str] | None = None,
) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    normalized = value.strip().lower()
    if aliases:
        normalized = aliases.get(normalized, normalized)
    if normalized not in choices:
        valid = ", ".join(sorted(choices))
        raise ValueError(f"{key} must be one of: {valid}")
    return normalized


def _resolve_window_start(
    *,
    now_utc: datetime,
    state: ReportState,
    window: str,
    days: int | None,
) -> tuple[datetime | None, str, bool]:
    if days is not None:
        return now_utc - timedelta(days=days), f"manual:{days}d", True

    normalized = window.strip().lower()
    if normalized == "auto":
        return _parse_iso_datetime(state.last_report_sent_at), "auto", False
    if normalized == "all":
        return None, "manual:all", True

    preset_days = WINDOW_PRESET_DAYS.get(normalized)
    if preset_days is None:
        valid = ", ".join(["auto", "all", *WINDOW_PRESET_DAYS.keys()])
        raise ValueError(f"Invalid window mode: {window}. Valid values: {valid}")
    return now_utc - timedelta(days=preset_days), f"manual:{normalized}", True


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

    report_payload_raw = payload.get("report", {})
    if report_payload_raw is None:
        report_payload: dict[str, object] = {}
    elif isinstance(report_payload_raw, dict):
        report_payload = cast(dict[str, object], report_payload_raw)
    else:
        raise ValueError("telegram.report must be an object/table")

    style = _parse_choice(
        report_payload.get("style"),
        key="telegram.report.style",
        choices=REPORT_STYLE_CHOICES,
        default="advanced",
    )
    report_format = _parse_choice(
        report_payload.get("format"),
        key="telegram.report.format",
        choices=REPORT_FORMAT_CHOICES,
        default="markdownv2",
        aliases={"md": "markdownv2", "markdown": "markdownv2", "text": "plain"},
    )
    detail_level = _parse_choice(
        report_payload.get("detail_level"),
        key="telegram.report.detail_level",
        choices=DETAIL_LEVEL_CHOICES,
        default="medium",
    )
    split_mode = _parse_choice(
        report_payload.get("split_mode"),
        key="telegram.report.split_mode",
        choices=SPLIT_MODE_CHOICES,
        default="auto",
    )

    max_message_chars_raw = report_payload.get("max_message_chars", 3800)
    if not isinstance(max_message_chars_raw, int):
        raise ValueError("telegram.report.max_message_chars must be an integer")
    if max_message_chars_raw < 512 or max_message_chars_raw > 4096:
        raise ValueError("telegram.report.max_message_chars must be between 512 and 4096")

    send_details_raw = report_payload.get("send_details", True)
    if not isinstance(send_details_raw, bool):
        raise ValueError("telegram.report.send_details must be a boolean")

    report = TelegramReportOptions(
        style=style,
        format=report_format,
        detail_level=detail_level,
        split_mode=split_mode,
        max_message_chars=max_message_chars_raw,
        send_details=send_details_raw,
    )

    return TelegramConfig(
        enabled=enabled,
        bot_token=bot_token.strip(),
        chat_id=chat_id.strip(),
        timezone=tz.strip(),
        disable_web_page_preview=disable_preview,
        report=report,
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


def _truncate_text(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def build_incremental_summary(
    repo: SessionRepository,
    *,
    since: datetime | None,
) -> IncrementalSummary:
    """Build summary metrics for sessions created strictly after `since`."""
    conn = repo._conn
    rows = conn.execute("""
        SELECT
            session_id,
            ecosystem,
            created_at,
            bottleneck,
            total_messages,
            total_tokens,
            total_tool_calls
        FROM sessions
        ORDER BY created_at ASC
        """).fetchall()

    source_counts: Counter[str] = Counter()
    bottleneck_counts: Counter[str] = Counter()
    error_category_counts: Counter[str] = Counter()
    total_tool_errors = 0
    included_session_ids: list[str] = []
    total_messages = 0
    total_tokens = 0
    total_tool_calls = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_trajectory_file_size_bytes = 0
    total_chars = 0
    total_cjk_chars = 0
    total_latin_chars = 0
    model_time_seconds = 0.0
    tool_time_seconds = 0.0
    user_time_seconds = 0.0
    inactive_time_seconds = 0.0
    model_timeout_count = 0
    error_excerpts: list[ToolErrorExcerpt] = []

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

        total_messages += int(row["total_messages"] or 0)
        total_tokens += int(row["total_tokens"] or 0)
        total_tool_calls += int(row["total_tool_calls"] or 0)

        statistics = repo.get_statistics(session_id)
        if statistics is None:
            continue

        total_input_tokens += int(statistics.total_input_tokens or 0)
        total_output_tokens += int(statistics.total_output_tokens or 0)
        total_trajectory_file_size_bytes += int(statistics.trajectory_file_size_bytes or 0)

        char_stats = statistics.character_breakdown
        total_chars += int(char_stats.total_chars or 0)
        total_cjk_chars += int(char_stats.cjk_chars or 0)
        total_latin_chars += int(char_stats.latin_chars or 0)

        time_breakdown = statistics.time_breakdown
        if time_breakdown:
            model_time_seconds += float(time_breakdown.total_model_time_seconds or 0.0)
            tool_time_seconds += float(time_breakdown.total_tool_time_seconds or 0.0)
            user_time_seconds += float(time_breakdown.total_user_time_seconds or 0.0)
            inactive_time_seconds += float(time_breakdown.total_inactive_time_seconds or 0.0)
            model_timeout_count += int(time_breakdown.model_timeout_count or 0)

        total_tool_errors += len(statistics.tool_error_records)
        for category, count in statistics.tool_error_category_counts.items():
            error_category_counts[category] += int(count)

        if len(error_excerpts) < 8:
            for record in statistics.tool_error_records:
                if len(error_excerpts) >= 8:
                    break
                error_excerpts.append(
                    ToolErrorExcerpt(
                        timestamp=record.timestamp,
                        tool_name=record.tool_name,
                        category=record.category,
                        preview=_truncate_text(record.preview, 120),
                    )
                )

    total_span = model_time_seconds + tool_time_seconds + user_time_seconds + inactive_time_seconds
    active_time = model_time_seconds + tool_time_seconds + user_time_seconds
    active_time_ratio = active_time / total_span if total_span > 0 else 0.0

    return IncrementalSummary(
        session_count=len(included_session_ids),
        source_counts=dict(source_counts),
        bottleneck_counts=dict(bottleneck_counts),
        total_tool_errors=total_tool_errors,
        error_category_counts=dict(error_category_counts),
        total_messages=total_messages,
        total_tokens=total_tokens,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        total_tool_calls=total_tool_calls,
        total_trajectory_file_size_bytes=total_trajectory_file_size_bytes,
        total_chars=total_chars,
        total_cjk_chars=total_cjk_chars,
        total_latin_chars=total_latin_chars,
        model_time_seconds=model_time_seconds,
        tool_time_seconds=tool_time_seconds,
        user_time_seconds=user_time_seconds,
        inactive_time_seconds=inactive_time_seconds,
        active_time_ratio=active_time_ratio,
        model_timeout_count=model_timeout_count,
        error_excerpts=error_excerpts,
    )


def _format_short_number(value: int) -> str:
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs_value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def _format_duration(seconds: float) -> str:
    if seconds <= 0:
        return "0s"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _format_size(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(num_bytes)
    unit = units[0]
    for candidate in units:
        unit = candidate
        if value < 1024 or candidate == units[-1]:
            break
        value /= 1024
    if unit == "B":
        return f"{int(value)} {unit}"
    return f"{value:.1f} {unit}"


def _format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _sorted_counter_text(data: dict[str, int]) -> str:
    if not data:
        return "(none)"
    parts = [f"{k}={v}" for k, v in sorted(data.items(), key=lambda item: item[1], reverse=True)]
    return ", ".join(parts)


def _compose_overview_section(
    summary: IncrementalSummary,
    *,
    window_start: datetime | None,
    window_end: datetime,
    window_mode: str,
    detail_level: str,
    style: str,
) -> _ReportSection:
    start_text = window_start.isoformat() if window_start else "initial-sync"
    sessions_and_messages = (
        f"Sessions: {_format_short_number(summary.session_count)}"
        f" | Messages: {_format_short_number(summary.total_messages)}"
    )
    token_summary = (
        f"Tokens: {_format_short_number(summary.total_tokens)}"
        f" (in {_format_short_number(summary.total_input_tokens)}"
        f" / out {_format_short_number(summary.total_output_tokens)})"
    )
    tool_summary = (
        f"Tool calls: {_format_short_number(summary.total_tool_calls)}"
        f" | Tool errors: {_format_short_number(summary.total_tool_errors)}"
    )
    char_summary = (
        f" (CJK {_format_short_number(summary.total_cjk_chars)}"
        f" / Latin {_format_short_number(summary.total_latin_chars)})"
    )
    lines = [
        f"Window: {start_text} -> {window_end.isoformat()} ({window_mode})",
        sessions_and_messages,
        token_summary,
        tool_summary,
        f"Active ratio: {_format_percent(summary.active_time_ratio)}",
        f"Source: {_sorted_counter_text(summary.source_counts)}",
        f"Bottleneck: {_sorted_counter_text(summary.bottleneck_counts)}",
    ]

    if style == "advanced" and detail_level in {"medium", "high"}:
        lines.append(
            f"Trajectory size: {_format_size(summary.total_trajectory_file_size_bytes)}"
            f" | Chars: {_format_short_number(summary.total_chars)}"
            f"{char_summary}"
        )
    if detail_level == "high":
        lines.append(f"Error categories: {_sorted_counter_text(summary.error_category_counts)}")

    return _ReportSection(
        key="overview",
        title="Agent Vis Advanced Report",
        body="\n".join(lines),
    )


def _compose_role_section(summary: IncrementalSummary) -> _ReportSection:
    active_total = (
        summary.model_time_seconds + summary.tool_time_seconds + summary.user_time_seconds
    )

    def _role_line(label: str, seconds: float) -> str:
        ratio = (seconds / active_total) if active_total > 0 else 0.0
        return f"{label}: {_format_duration(seconds)} ({_format_percent(ratio)})"

    lines = [
        _role_line("Model", summary.model_time_seconds),
        _role_line("Tool", summary.tool_time_seconds),
        _role_line("User", summary.user_time_seconds),
        f"Inactive: {_format_duration(summary.inactive_time_seconds)} (excluded from role share)",
        f"Model timeouts: {_format_short_number(summary.model_timeout_count)}",
    ]
    return _ReportSection(
        key="role_breakdown",
        title="User / Model / Tool Breakdown",
        body="\n".join(lines),
    )


def _compose_anomaly_section(summary: IncrementalSummary, *, detail_level: str) -> _ReportSection:
    top_n = 3 if detail_level == "low" else 6
    categories = sorted(
        summary.error_category_counts.items(),
        key=lambda item: item[1],
        reverse=True,
    )[:top_n]
    lines = ["Error categories:"]
    if categories:
        lines.extend([f"- {name}: {count}" for name, count in categories])
    else:
        lines.append("- (none)")

    if detail_level in {"medium", "high"}:
        sample_limit = 3 if detail_level == "medium" else 6
        lines.append("")
        lines.append("Recent error excerpts:")
        if summary.error_excerpts:
            for sample in summary.error_excerpts[:sample_limit]:
                timestamp = _truncate_text(sample.timestamp, 26)
                preview = _truncate_text(sample.preview, 80 if detail_level == "high" else 56)
                lines.append(f"- {timestamp} | {sample.tool_name} | {sample.category} | {preview}")
        else:
            lines.append("- (none)")

    return _ReportSection(
        key="anomalies",
        title="Tool Error Signals",
        body="\n".join(lines),
    )


def _compose_report_sections(
    summary: IncrementalSummary,
    *,
    window_start: datetime | None,
    window_end: datetime,
    window_mode: str,
    settings: TelegramReportOptions,
) -> list[_ReportSection]:
    sections = [
        _compose_overview_section(
            summary,
            window_start=window_start,
            window_end=window_end,
            window_mode=window_mode,
            detail_level=settings.detail_level,
            style=settings.style,
        )
    ]
    if not settings.send_details:
        return sections

    sections.append(_compose_role_section(summary))
    sections.append(_compose_anomaly_section(summary, detail_level=settings.detail_level))
    return sections


def _escape_markdown_v2(text: str) -> str:
    special = set(r"_*[]()~`>#+-=|{}.!")
    escaped = []
    for char in text:
        if char in special:
            escaped.append(f"\\{char}")
        elif char == "\\":
            escaped.append("\\\\")
        else:
            escaped.append(char)
    return "".join(escaped)


def _escape_markdown_code_block(text: str) -> str:
    return text.replace("\\", "\\\\").replace("`", "\\`")


def _render_section(section: _ReportSection, report_format: str) -> str:
    if report_format == "markdownv2":
        title = _escape_markdown_v2(section.title)
        body = _escape_markdown_code_block(section.body)
        return f"*{title}*\n```text\n{body}\n```"
    if report_format == "html":
        return f"<b>{html.escape(section.title)}</b>\n<pre>{html.escape(section.body)}</pre>"
    return f"{section.title}\n{section.body}"


def _split_plain_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    lines = text.splitlines(keepends=True)
    current = ""
    for line in lines:
        if len(line) > max_chars:
            if current:
                chunks.append(current.rstrip("\n"))
                current = ""
            start = 0
            while start < len(line):
                chunks.append(line[start : start + max_chars].rstrip("\n"))
                start += max_chars
            continue

        if len(current) + len(line) > max_chars:
            chunks.append(current.rstrip("\n"))
            current = line
        else:
            current += line

    if current:
        chunks.append(current.rstrip("\n"))
    return chunks


def _build_rendered_messages(
    sections: list[_ReportSection],
    settings: TelegramReportOptions,
) -> tuple[list[str], bool, list[str]]:
    if not sections:
        return [], False, []

    max_chars = settings.max_message_chars
    section_keys = [section.key for section in sections]

    if settings.split_mode == "single":
        combined = "\n\n".join(_render_section(section, settings.format) for section in sections)
        truncated = False
        if len(combined) > max_chars:
            suffix = "\n\n(truncated)"
            keep = max(max_chars - len(suffix), 1)
            combined = combined[:keep].rstrip() + suffix
            truncated = True
        return [combined], truncated, section_keys

    # Auto split by section/body to avoid malformed Markdown/HTML wrappers.
    body_max_chars = max(400, max_chars - 96)
    messages: list[str] = []
    for section in sections:
        body_chunks = _split_plain_text(section.body, body_max_chars)
        if len(body_chunks) == 1:
            messages.append(_render_section(section, settings.format))
            continue

        for index, chunk in enumerate(body_chunks):
            title = section.title if index == 0 else f"{section.title} (part {index + 1})"
            messages.append(
                _render_section(_ReportSection(section.key, title, chunk), settings.format)
            )

    return messages, False, section_keys


def _resolve_report_options(
    *,
    config_options: TelegramReportOptions,
    style: str | None,
    report_format: str | None,
    detail_level: str | None,
    split_mode: str | None,
    max_message_chars: int | None,
    send_details: bool | None,
) -> TelegramReportOptions:
    resolved_style = config_options.style
    if style is not None:
        resolved_style = _parse_choice(
            style,
            key="style",
            choices=REPORT_STYLE_CHOICES,
            default=config_options.style,
        )

    resolved_format = config_options.format
    if report_format is not None:
        resolved_format = _parse_choice(
            report_format,
            key="format",
            choices=REPORT_FORMAT_CHOICES,
            default=config_options.format,
            aliases={"md": "markdownv2", "markdown": "markdownv2", "text": "plain"},
        )

    resolved_detail_level = config_options.detail_level
    if detail_level is not None:
        resolved_detail_level = _parse_choice(
            detail_level,
            key="detail_level",
            choices=DETAIL_LEVEL_CHOICES,
            default=config_options.detail_level,
        )

    resolved_split_mode = config_options.split_mode
    if split_mode is not None:
        resolved_split_mode = _parse_choice(
            split_mode,
            key="split_mode",
            choices=SPLIT_MODE_CHOICES,
            default=config_options.split_mode,
        )

    resolved_max_chars = config_options.max_message_chars
    if max_message_chars is not None:
        if max_message_chars < 512 or max_message_chars > 4096:
            raise ValueError("max_message_chars must be between 512 and 4096")
        resolved_max_chars = max_message_chars

    resolved_send_details = config_options.send_details if send_details is None else send_details

    return TelegramReportOptions(
        style=resolved_style,
        format=resolved_format,
        detail_level=resolved_detail_level,
        split_mode=resolved_split_mode,
        max_message_chars=resolved_max_chars,
        send_details=resolved_send_details,
    )


def _telegram_parse_mode(report_format: str) -> str | None:
    if report_format == "markdownv2":
        return "MarkdownV2"
    if report_format == "html":
        return "HTML"
    return None


def send_telegram_message(
    config: TelegramConfig,
    text: str,
    parse_mode: str | None = None,
    *,
    timeout_seconds: float = 15.0,
) -> tuple[bool, str]:
    """Send one message through Telegram bot API."""
    url = f"https://api.telegram.org/bot{config.bot_token}/sendMessage"
    payload: dict[str, object] = {
        "chat_id": config.chat_id,
        "text": text,
        "disable_web_page_preview": config.disable_web_page_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

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


def _invoke_sender(
    sender: SenderCallable,
    config: TelegramConfig,
    text: str,
    parse_mode: str | None,
) -> tuple[bool, str]:
    try:
        return sender(config, text, parse_mode)
    except TypeError:
        legacy_sender = cast(Callable[[TelegramConfig, str], tuple[bool, str]], sender)
        return legacy_sender(config, text)


def _send_with_markdown_fallback(
    sender: SenderCallable,
    config: TelegramConfig,
    text: str,
    parse_mode: str | None,
) -> tuple[bool, str]:
    try:
        return _invoke_sender(sender, config, text, parse_mode)
    except RuntimeError as exc:
        if parse_mode == "MarkdownV2" and "parse entities" in str(exc).lower():
            return _invoke_sender(sender, config, text, None)
        raise


def run_telegram_incremental_report(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    db_path: Path | None = None,
    dry_run: bool = False,
    window: str = "auto",
    days: int | None = None,
    style: str | None = None,
    report_format: str | None = None,
    detail_level: str | None = None,
    split_mode: str | None = None,
    max_message_chars: int | None = None,
    send_details: bool | None = None,
    now: datetime | None = None,
    sender: SenderCallable = send_telegram_message,
) -> TelegramReportResult:
    """Run incremental telegram report workflow (load -> summarize -> send -> persist state)."""
    config = load_telegram_config(config_path)
    if not config.enabled:
        raise RuntimeError("Telegram report is disabled in config (telegram.enabled=false)")

    if days is not None and days < 1:
        raise ValueError("days must be >= 1")

    settings = _resolve_report_options(
        config_options=config.report,
        style=style,
        report_format=report_format,
        detail_level=detail_level,
        split_mode=split_mode,
        max_message_chars=max_message_chars,
        send_details=send_details,
    )

    state = load_report_state(state_path)
    window_end_dt = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    since, window_mode, is_manual_window = _resolve_window_start(
        now_utc=window_end_dt,
        state=state,
        window=window,
        days=days,
    )

    conn = get_connection(db_path)
    repo = SessionRepository(conn)
    try:
        summary = build_incremental_summary(repo, since=since)
    finally:
        conn.close()

    sections = _compose_report_sections(
        summary,
        window_start=since,
        window_end=window_end_dt,
        window_mode=window_mode,
        settings=settings,
    )
    messages, truncated, section_keys = _build_rendered_messages(sections, settings)
    if not messages:
        messages = [
            _render_section(_ReportSection("overview", "Agent Vis Report", "(empty)"), "plain")
        ]
        section_keys = ["overview"]

    parse_mode = _telegram_parse_mode(settings.format)
    if dry_run:
        preview = messages[0] if messages else "dry-run: not sent"
        return TelegramReportResult(
            status="dry-run",
            chat_id=config.chat_id,
            window_mode=window_mode,
            window_start=since.isoformat() if since else None,
            window_end=window_end_dt.isoformat(),
            state_updated=False,
            summary=summary,
            response_excerpt=preview[:240],
            render_format=settings.format,
            message_count=len(messages),
            sections_sent=section_keys,
            truncated=truncated,
        )

    response_excerpt = "sent"
    for index, message in enumerate(messages):
        ok, excerpt = _send_with_markdown_fallback(sender, config, message, parse_mode=parse_mode)
        if ok and index == 0:
            response_excerpt = excerpt

    state_updated = False
    if not is_manual_window:
        # Auto-incremental mode updates checkpoint only after successful send.
        save_report_state_atomic(
            ReportState(
                last_report_sent_at=window_end_dt.isoformat(),
                last_report_status="success",
                last_report_error=None,
            ),
            state_path=state_path,
        )
        state_updated = True

    return TelegramReportResult(
        status="sent",
        chat_id=config.chat_id,
        window_mode=window_mode,
        window_start=since.isoformat() if since else None,
        window_end=window_end_dt.isoformat(),
        state_updated=state_updated,
        summary=summary,
        response_excerpt=response_excerpt,
        render_format=settings.format,
        message_count=len(messages),
        sections_sent=section_keys,
        truncated=truncated,
    )
