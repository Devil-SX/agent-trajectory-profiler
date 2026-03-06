"""Pluggable JSON decode helpers for parser pipelines."""

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

    def decode(self, payload: str | bytes) -> Any:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return json.loads(payload)


@dataclass(frozen=True)
class OrjsonLineDecoder:
    name: str = "orjson"
    read_mode: Literal["text", "binary"] = "binary"

    def decode(self, payload: str | bytes) -> Any:
        import orjson

        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        return orjson.loads(payload)


def _resolve_decoder_name(name: str | None = None) -> str:
    resolved = name if name is not None else (os.getenv(_JSON_DECODER_ENV) or "orjson")
    return resolved.strip().lower()


def _has_orjson() -> bool:
    try:
        import orjson  # noqa: F401
    except ImportError:
        return False
    return True


JSONLineDecoder: TypeAlias = StdlibJSONLineDecoder | OrjsonLineDecoder


def available_json_line_decoders() -> list[str]:
    decoders = ["json"]
    if _has_orjson():
        decoders.append("orjson")
    return decoders


def get_json_line_decoder(name: str | None = None) -> JSONLineDecoder:
    """Return the configured JSON decoder implementation."""
    resolved = _resolve_decoder_name(name)
    env_override = os.getenv(_JSON_DECODER_ENV)
    explicit_orjson_request = resolved == "orjson" and (
        name is not None or env_override is not None
    )

    if resolved in {"", "orjson"}:
        if _has_orjson():
            return OrjsonLineDecoder()
        if explicit_orjson_request:
            raise RuntimeError(
                "The 'orjson' decoder was requested but orjson is not installed. "
                "Install project dependencies with the optional fast decoder support."
            )
        return StdlibJSONLineDecoder()

    if resolved in {"json", "stdlib"}:
        return StdlibJSONLineDecoder()

    raise ValueError(
        f"Unsupported JSON decoder '{resolved}'. Available decoders: "
        f"{', '.join(available_json_line_decoders())}"
    )


def decode_json_value(payload: str | bytes, name: str | None = None) -> Any:
    """Decode an inline JSON payload through the shared decoder selection path."""
    return get_json_line_decoder(name).decode(payload)


__all__ = [
    "JSONLineDecoder",
    "available_json_line_decoders",
    "decode_json_value",
    "get_json_line_decoder",
]
