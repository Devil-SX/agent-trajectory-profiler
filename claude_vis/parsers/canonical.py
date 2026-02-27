"""Canonical multi-agent conversion layer for trajectory ingestion.

This module defines an adapter contract and an agent-neutral canonical event
model used to normalize source JSONL records before converting them into the
internal ``MessageRecord`` model.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from claude_vis.exceptions import SessionParseError
from claude_vis.models import MessageRecord


class CanonicalEvent(BaseModel):
    """Agent-neutral normalized event representation."""

    ecosystem: str
    source_path: str
    line_number: int = Field(ge=1)
    event_kind: str = "message"
    timestamp: str | None = None
    actor: str | None = None
    payload: dict[str, Any]


class CanonicalSession(BaseModel):
    """Canonical event stream for a source trajectory file."""

    ecosystem: str
    source_path: str
    events: list[CanonicalEvent]


class TrajectoryEventAdapter(ABC):
    """Adapter contract: source JSON record <-> canonical event/message."""

    @property
    @abstractmethod
    def ecosystem_name(self) -> str:
        """Stable ecosystem identifier (for example, ``claude_code``)."""
        ...

    @abstractmethod
    def to_canonical_event(
        self, raw_event: dict[str, Any], *, source_path: Path, line_number: int
    ) -> CanonicalEvent | None:
        """Convert one source JSON object into a canonical event."""
        ...

    @abstractmethod
    def canonical_to_message(self, event: CanonicalEvent) -> MessageRecord | None:
        """Convert canonical event into internal message model."""
        ...


_adapter_registry: dict[str, type[TrajectoryEventAdapter]] = {}


def register_adapter(
    adapter_cls: type[TrajectoryEventAdapter],
) -> type[TrajectoryEventAdapter]:
    """Register an adapter class by ecosystem name."""
    ecosystem_name = adapter_cls.__dict__.get("ecosystem_name")
    if ecosystem_name is None or isinstance(ecosystem_name, property):
        instance = object.__new__(adapter_cls)
        ecosystem_name = instance.ecosystem_name  # type: ignore[attr-defined]

    if not isinstance(ecosystem_name, str):
        raise TypeError(
            "Adapter ecosystem_name must be a string or property returning string"
        )

    _adapter_registry[ecosystem_name] = adapter_cls
    return adapter_cls


def get_adapter(ecosystem: str) -> TrajectoryEventAdapter:
    """Get an adapter instance for a specific ecosystem."""
    if ecosystem not in _adapter_registry:
        available = ", ".join(sorted(_adapter_registry.keys())) or "(none)"
        raise KeyError(
            f"No canonical adapter registered for ecosystem '{ecosystem}'. "
            f"Available: {available}"
        )
    return _adapter_registry[ecosystem]()


def list_adapters() -> list[str]:
    """List registered ecosystem adapter names."""
    return sorted(_adapter_registry.keys())


def parse_jsonl_to_canonical(
    file_path: Path, adapter: TrajectoryEventAdapter
) -> CanonicalSession:
    """Parse JSONL file into canonical events via adapter conversion."""
    events: list[CanonicalEvent] = []

    try:
        with open(file_path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                stripped = line.strip()
                if not stripped:
                    continue

                try:
                    data = json.loads(stripped)
                except json.JSONDecodeError as e:
                    raise SessionParseError(
                        f"Invalid JSON at {file_path}:{line_num}: {e}"
                    ) from e

                if not isinstance(data, dict):
                    continue

                event = adapter.to_canonical_event(
                    data,
                    source_path=file_path,
                    line_number=line_num,
                )
                if event is not None:
                    events.append(event)
    except FileNotFoundError as e:
        raise SessionParseError(f"Session file not found: {file_path}") from e
    except OSError as e:
        raise SessionParseError(f"Error reading file {file_path}: {e}") from e

    return CanonicalSession(
        ecosystem=adapter.ecosystem_name,
        source_path=str(file_path),
        events=events,
    )


def canonical_to_messages(
    canonical_session: CanonicalSession, adapter: TrajectoryEventAdapter
) -> list[MessageRecord]:
    """Convert canonical events to internal messages, skipping invalid records."""
    messages: list[MessageRecord] = []

    for event in canonical_session.events:
        try:
            message = adapter.canonical_to_message(event)
        except ValidationError:
            continue

        if message is not None:
            messages.append(message)

    return messages
