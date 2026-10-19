"""Project normalized native-worker evidence into the existing measured ledger."""

import hashlib
from datetime import UTC, datetime
from typing import Any

from trajectory.product.contracts import Record


def _identity(*parts: object) -> str:
    return hashlib.sha256(":".join(str(part) for part in parts).encode()).hexdigest()


def pi_records(
    source: dict[str, Any], parsed: dict[str, Any]
) -> tuple[list[Record], dict[str, int]]:
    """No raw transcript interpretation and no estimated counters or origins."""
    metadata = parsed.get("metadata", {})
    session = str(metadata.get("native_session_id") or source["source"])
    workspace = metadata.get("cwd")
    parent = metadata.get("parent_session_id")
    result = []
    gaps = {
        "unknown_origins": 0,
        "missing_text": 0,
        "scoped_consumption_identity": 0,
        "invalid_counters": 0,
        "missing_usage": 0,
    }
    for native in parsed.get("source_records", []):
        role = native.get("role")
        if role not in ("user", "assistant"):
            continue
        stamp = native.get("timestamp_ms")
        timestamp = datetime.fromtimestamp(stamp / 1000, UTC) if type(stamp) is int else None
        native_id = native.get("native_id")
        stable = native_id or native["event_id"]
        common = {
            "id": _identity(source["source"], role, stable, stamp),
            "session": session,
            "parent": parent,
            "task": _identity(source["collector"], source["source"]),
            "ecosystem": "pi",
            "timestamp": timestamp,
            "source_line": native["source_line"],
            "workspace": workspace,
        }
        if role == "user":
            origin = native.get("human_origin")
            if origin not in ("human", "agent", "system"):
                origin = "unknown"
                gaps["unknown_origins"] += 1
            text = native.get("input_text")
            chars = sum(not char.isspace() for char in text) if isinstance(text, str) else None
            gaps["missing_text"] += int(chars is None)
            # Native entry IDs are session-scoped. No text hashes imply human identity.
            interaction = _identity("pi", session, native_id, stamp) if native_id else None
            result.append(
                Record(
                    **common,
                    kind="request",
                    input_origin=origin,
                    interaction_id=interaction,
                    input_chars=chars,
                )
            )
            continue
        usage = native.get("measured_usage")
        if not isinstance(usage, dict):
            gaps["missing_usage"] += 1
            usage = {}
        counters: dict[str, Any] = {}
        for key in ("input", "output", "cached", "cache_write", "reasoning"):
            value = usage.get(key)
            valid = type(value) is int and 0 <= value <= 9_007_199_254_740_991
            counters[key] = value if valid else None
            gaps["invalid_counters"] += int(value is not None and not valid)
        provider, response = native.get("provider"), native.get("response_id")
        consumption: str | None
        if isinstance(provider, str) and provider and isinstance(response, str) and response:
            consumption = _identity("pi-provider", provider, response)
        else:
            # Conservative local namespace; identical copied text is never dedup evidence.
            consumption = _identity("pi-session", session, native_id, stamp) if native_id else None
            gaps["scoped_consumption_identity"] += 1
        result.append(
            Record(
                **common,
                kind="usage",
                model=native.get("model"),
                consumption=consumption,
                input_includes_cache=False,
                input_includes_cache_write=False,
                output_includes_reasoning=True,
                **counters,
            )
        )
    return result, gaps
