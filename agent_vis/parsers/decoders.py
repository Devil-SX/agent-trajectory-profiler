"""Pluggable JSONL line decoders for parser pipelines."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

_JSON_DECODER_ENV = "AGENT_VIS_JSON_DECODER"


@dataclass(frozen=True)
class StdlibJSONLineDecoder:
    name: str = "json"
    read_mode: Literal["text", "binary"] = "text"

    def decode(self, line: str | bytes) -> Any:
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        return json.loads(line)


@dataclass(frozen=True)
class OrjsonLineDecoder:
    name: str = "orjson"
    read_mode: Literal["text", "binary"] = "binary"

    def decode(self, line: str | bytes) -> Any:
        import orjson

        if isinstance(line, str):
            line = line.encode("utf-8")
        return orjson.loads(line)


def _resolve_decoder_name(name: str | None = None) -> str:
    resolved = name if name is not None else (os.getenv(_JSON_DECODER_ENV) or "json")
    return resolved.strip().lower()


JSONLineDecoder: TypeAlias = StdlibJSONLineDecoder | OrjsonLineDecoder


def available_json_line_decoders() -> list[str]:
    decoders = ["json"]
    try:
        import orjson  # noqa: F401
    except ImportError:
        return decoders
    return decoders + ["orjson"]


def get_json_line_decoder(name: str | None = None) -> JSONLineDecoder:
    """Return the configured JSONL decoder implementation."""
    resolved = _resolve_decoder_name(name)
    if resolved in {"", "json", "stdlib"}:
        return StdlibJSONLineDecoder()
    if resolved == "orjson":
        try:
            import orjson  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "The 'orjson' decoder was requested but orjson is not installed. "
                "Install project dependencies with the optional fast decoder support."
            ) from exc
        return OrjsonLineDecoder()
    raise ValueError(
        f"Unsupported JSON decoder '{resolved}'. Available decoders: "
        f"{', '.join(available_json_line_decoders())}"
    )


__all__ = [
    "JSONLineDecoder",
    "available_json_line_decoders",
    "get_json_line_decoder",
]
