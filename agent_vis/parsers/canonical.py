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

from agent_vis.exceptions import SessionParseError
from agent_vis.models import MessageRecord


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


class CanonicalDropSample(BaseModel):
    """Minimal diagnostic sample for a dropped record/event."""

    line_number: int = Field(ge=1)
    event_kind: str
    reason: str


class CanonicalParseDiagnostics(BaseModel):
    """Diagnostics for source JSONL -> canonical conversion."""

    raw_event_count: int = 0
    raw_event_kind_counts: dict[str, int] = Field(default_factory=dict)
    dropped_event_kind_counts: dict[str, int] = Field(default_factory=dict)
    dropped_samples: list[CanonicalDropSample] = Field(default_factory=list)


class CanonicalMessageDiagnostics(BaseModel):
    """Diagnostics for canonical event -> MessageRecord conversion."""

    mapped_count: int = 0
    dropped_event_kind_counts: dict[str, int] = Field(default_factory=dict)
    dropped_samples: list[CanonicalDropSample] = Field(default_factory=list)


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
        raise TypeError("Adapter ecosystem_name must be a string or property returning string")

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


def parse_jsonl_to_canonical(file_path: Path, adapter: TrajectoryEventAdapter) -> CanonicalSession:
    """Parse JSONL file into canonical events via adapter conversion."""
    session, _ = parse_jsonl_to_canonical_with_diagnostics(file_path, adapter)
    return session


def parse_jsonl_to_canonical_with_diagnostics(
    file_path: Path,
    adapter: TrajectoryEventAdapter,
    *,
    sample_limit: int = 12,
) -> tuple[CanonicalSession, CanonicalParseDiagnostics]:
    """Parse JSONL file into canonical events and capture drop diagnostics."""
    events: list[CanonicalEvent] = []
    diagnostics = CanonicalParseDiagnostics()

    try:
        with open(file_path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                stripped = line.strip()
                if not stripped:
                    continue

                try:
                    data = json.loads(stripped)
                except json.JSONDecodeError as e:
                    raise SessionParseError(f"Invalid JSON at {file_path}:{line_num}: {e}") from e

                if not isinstance(data, dict):
                    continue
                diagnostics.raw_event_count += 1
                event_kind = str(data.get("type") or "<missing>")
                diagnostics.raw_event_kind_counts[event_kind] = (
                    diagnostics.raw_event_kind_counts.get(event_kind, 0) + 1
                )

                event = adapter.to_canonical_event(
                    data,
                    source_path=file_path,
                    line_number=line_num,
                )
                if event is not None:
                    events.append(event)
                else:
                    diagnostics.dropped_event_kind_counts[event_kind] = (
                        diagnostics.dropped_event_kind_counts.get(event_kind, 0) + 1
                    )
                    if len(diagnostics.dropped_samples) < sample_limit:
                        diagnostics.dropped_samples.append(
                            CanonicalDropSample(
                                line_number=line_num,
                                event_kind=event_kind,
                                reason="adapter_to_canonical_returned_none",
                            )
                        )
    except FileNotFoundError as e:
        raise SessionParseError(f"Session file not found: {file_path}") from e
    except OSError as e:
        raise SessionParseError(f"Error reading file {file_path}: {e}") from e

    return (
        CanonicalSession(
            ecosystem=adapter.ecosystem_name,
            source_path=str(file_path),
            events=events,
        ),
        diagnostics,
    )


def canonical_to_messages(
    canonical_session: CanonicalSession, adapter: TrajectoryEventAdapter
) -> list[MessageRecord]:
    """Convert canonical events to internal messages, skipping invalid records."""
    messages, _ = canonical_to_messages_with_diagnostics(canonical_session, adapter)
    return messages


def canonical_to_messages_with_diagnostics(
    canonical_session: CanonicalSession,
    adapter: TrajectoryEventAdapter,
    *,
    sample_limit: int = 12,
) -> tuple[list[MessageRecord], CanonicalMessageDiagnostics]:
    """Convert canonical events to messages and capture unmapped diagnostics."""
    messages: list[MessageRecord] = []
    diagnostics = CanonicalMessageDiagnostics()

    for event in canonical_session.events:
        try:
            message = adapter.canonical_to_message(event)
        except ValidationError:
            diagnostics.dropped_event_kind_counts[event.event_kind] = (
                diagnostics.dropped_event_kind_counts.get(event.event_kind, 0) + 1
            )
            if len(diagnostics.dropped_samples) < sample_limit:
                diagnostics.dropped_samples.append(
                    CanonicalDropSample(
                        line_number=event.line_number,
                        event_kind=event.event_kind,
                        reason="validation_error",
                    )
                )
            continue

        if message is not None:
            messages.append(message)
            diagnostics.mapped_count += 1
        else:
            diagnostics.dropped_event_kind_counts[event.event_kind] = (
                diagnostics.dropped_event_kind_counts.get(event.event_kind, 0) + 1
            )
            if len(diagnostics.dropped_samples) < sample_limit:
                diagnostics.dropped_samples.append(
                    CanonicalDropSample(
                        line_number=event.line_number,
                        event_kind=event.event_kind,
                        reason="adapter_canonical_to_message_returned_none",
                    )
                )

    return messages, diagnostics
