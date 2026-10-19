"""Display metadata from the canonical parser output, never model-generated abstracts."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

VERSION = 2


def _text(value: Any, limit: int = 8000) -> str | None:
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def effective_prompt(value: Any) -> str | None:
    """Exclude known injected context records without asserting human origin."""
    text = _text(value)
    if text and not text.startswith(
        ("# AGENTS.md instructions", "<environment_context>", "<codex_internal_context")
    ):
        return text
    return None


def _display_title(first: str | None, cwd: Any, started: Any) -> str:
    if first:
        return " ".join(first.split())[:120]
    directory = _text(cwd, 4096)
    directory = re.split(r"[/\\]", directory.rstrip("/\\"))[-1] if directory else None
    date = _text(started, 10)
    return " ".join(part for part in (directory, date) if part) or "会话"


def read(value: dict[str, Any]) -> dict[str, Any]:
    """Project old indexes safely while bounded migration refreshes their IR."""
    if value.get("metadata_version") == VERSION:
        return value
    first = effective_prompt(value.get("first_user_message"))
    return {
        **value,
        "first_user_message": first,
        "display_title": _display_title(first, value.get("cwd"), value.get("started_at")),
    }


def _timestamp(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, UTC).isoformat()
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(UTC).isoformat() if parsed.tzinfo else None
        except ValueError:
            pass
    return None


def extract(parsed: dict[str, Any], source_name: str = "") -> dict[str, Any]:
    """Read parser metadata, with conservative fallbacks for persisted older IR."""
    metadata = parsed.get("metadata") or {}
    session = parsed.get("session") or {}
    source_records = parsed.get("source_records") or []
    lineage: dict[str, Any] = next(
        (r["lineage"] for r in source_records if isinstance(r.get("lineage"), dict)), {}
    )
    native_id = _text(metadata.get("native_session_id") or lineage.get("id") or session.get("id"))
    if native_id is None:
        match = re.search(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", source_name)
        native_id = match.group() if match else None
    source = lineage.get("source") or {}
    spawn = source.get("subagent", {}).get("thread_spawn", {}) if isinstance(source, dict) else {}
    parent = _text(
        metadata.get("parent_session_id")
        or lineage.get("parent_thread_id")
        or lineage.get("forked_from_id")
        or spawn.get("parent_thread_id")
    )
    first = effective_prompt(metadata.get("first_user_message"))
    operations = parsed.get("operations") or []
    if first is None:
        for operation in operations:
            if operation.get("kind") != "prompt":
                continue
            candidate = effective_prompt(operation.get("text"))
            if candidate:
                first = candidate
                break
    times = [
        stamp
        for record in source_records + operations
        if (stamp := _timestamp(record.get("timestamp") or record.get("timestamp_ms")))
    ]
    started = _timestamp(metadata.get("started_at")) or (min(times) if times else None)
    last = _timestamp(metadata.get("last_activity_at")) or (max(times) if times else None)
    summary = _text(metadata.get("abstract") or metadata.get("summary"))
    cwd = _text(metadata.get("cwd") or session.get("cwd"), 4096)
    title = _display_title(first, cwd, started)
    return {
        "metadata_version": VERSION,
        "native_session_id": native_id,
        "parent_native_session_id": parent,
        "cwd": cwd,
        "started_at": started,
        "last_activity_at": last,
        "first_user_message": first,
        "summary": summary,
        "display_title": title,
        "agent_path": _text(metadata.get("agent_path") or spawn.get("agent_path"), 512),
    }
