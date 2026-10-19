"""Shared reference-price selection and measured-usage valuation, never billing."""

from datetime import datetime
from typing import Any


def select_price(candidates: list[dict[str, Any]], timestamp: str | None) -> dict[str, Any] | None:
    references = [p for p in candidates if p.get("basis") == "current_reference"]
    price = max(references, key=lambda p: datetime.fromisoformat(p["verified_at"]), default=None)
    if price is None and timestamp:
        for candidate in candidates:
            if candidate.get("basis", "effective_historical") == "effective_historical" and (
                datetime.fromisoformat(candidate["effective_from"])
                <= datetime.fromisoformat(timestamp)
            ):
                price = candidate
    return price


def quote_record(
    record: dict[str, Any], price: dict[str, Any] | None, context: int | None
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    subtotal = 0.0
    if not price:
        reasons.append("missing_price" if record.get("timestamp") else "missing_timestamp")
    else:
        rates = price
        threshold = price.get("long_context_threshold")
        if threshold and context is None:
            reasons.append("missing_context_length")
        elif threshold and context is not None and context > threshold:
            rates = price["long_context"]
        if "missing_context_length" not in reasons:
            for field in ("input", "output", "cached", "cache_write"):
                value = record.get(field)
                if value is None:
                    if rates[field] != 0:
                        reasons.append("missing_" + field)
                    continue
                if field == "input":
                    if record.get("input_includes_cache"):
                        if record.get("cached") is None:
                            if rates["input"] != 0:
                                reasons.append("missing_cached")
                            continue
                        value -= record["cached"]
                    write_included = record.get("input_includes_cache_write")
                    if (
                        write_included is None
                        and record.get("input_includes_cache")
                        and record.get("cache_write") is None
                        and rates["cache_write"] != 0
                    ):
                        reasons.append("missing_cache_write")
                        continue
                    if write_included is True:
                        if record.get("cache_write") is None:
                            if rates["input"] != 0:
                                reasons.append("missing_cache_write")
                            continue
                        value -= record["cache_write"]
                    elif (
                        write_included is None
                        and record.get("cache_write")
                        and rates["cache_write"]
                    ):
                        reasons.append("input_cache_write_semantics")
                        continue
                    if value < 0:
                        reasons.append("invalid_cache_counts")
                        continue
                subtotal += value * rates[field] / 1_000_000
    return subtotal, sorted(set(reasons))


def usage_record(usage: dict[str, Any], timestamp: str | None) -> dict[str, Any]:
    """Map explicit OpenAI-compatible counters without inventing absent zeros."""

    def counter(value: Any) -> int | None:
        return (
            value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
        )

    details = usage.get("prompt_tokens_details")
    details = details if isinstance(details, dict) else {}
    cached = counter(details.get("cached_tokens"))
    if cached is None:
        cached = counter(usage.get("prompt_cache_hit_tokens"))
    return {
        "timestamp": timestamp,
        "input": counter(usage.get("prompt_tokens")),
        "output": counter(usage.get("completion_tokens")),
        "cached": cached,
        "cache_write": counter(usage.get("cache_creation_input_tokens")),
        "input_includes_cache": True,
        "input_includes_cache_write": None,
    }
