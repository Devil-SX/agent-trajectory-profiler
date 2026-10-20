"""Authoritative contracts for measured events, source evidence and analysis."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(min_length=16, max_length=128)
    session: str = Field(min_length=1, max_length=200)
    parent: str | None = Field(default=None, max_length=200)
    task: str = Field(min_length=1, max_length=128)
    ecosystem: Literal["codex", "claude_code", "pi"]
    timestamp: datetime | None
    kind: Literal["request", "usage", "tool_start", "tool_end", "notice"]
    input_origin: Literal["human", "agent", "system", "unknown"] | None = None
    interaction_id: str | None = Field(default=None, min_length=16, max_length=128)
    input_chars: int | None = Field(default=None, ge=0, le=9_007_199_254_740_991, strict=True)
    model: str | None = Field(default=None, max_length=200)
    input: int | None = Field(default=None, ge=0, le=9_007_199_254_740_991)
    output: int | None = Field(default=None, ge=0, le=9_007_199_254_740_991)
    cached: int | None = Field(default=None, ge=0, le=9_007_199_254_740_991)
    cache_write: int | None = Field(default=None, ge=0, le=9_007_199_254_740_991)
    reasoning: int | None = Field(default=None, ge=0, le=9_007_199_254_740_991)
    input_includes_cache: bool = False
    input_includes_cache_write: bool | None = None
    output_includes_reasoning: bool = True
    consumption: str | None = Field(default=None, max_length=128)
    workspace: str | None = Field(default=None, max_length=200)
    references: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def request_input_only(self) -> "Record":
        if self.kind != "request" and (
            self.input_origin is not None
            or self.input_chars is not None
            or self.interaction_id is not None
        ):
            raise ValueError(
                "Interaction identity, input origin and character counts "
                "are only valid on request records"
            )
        return self

    @field_validator("references")
    @classmethod
    def reference_lengths(cls, values: list[str]) -> list[str]:
        if any(len(value) > 200 for value in values):
            raise ValueError("Reference exceeds 200 characters")
        return values

    tool: str | None = Field(default=None, max_length=100)
    call: str | None = Field(default=None, max_length=200)
    error: bool = False
    source_line: int = Field(ge=1)

    @field_validator("timestamp")
    @classmethod
    def timestamp_zone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Timezone is required")
        return value.astimezone(UTC) if value else None


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_id: Literal["trajectory-batch/1"] = "trajectory-batch/1"
    mutation_id: str = Field(min_length=16, max_length=128)
    collector: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=16, max_length=128)
    revision: int = Field(ge=1)
    source_bytes: int = Field(ge=0, le=9_007_199_254_740_991)
    read_bytes: int = Field(ge=0, le=9_007_199_254_740_991)
    parser_version: str = Field(max_length=100)
    records: list[Record] = Field(max_length=5000)
    replace: bool = False
    parse_errors: int = Field(default=0, ge=0, le=9_007_199_254_740_991)
    unknown_events: int = Field(default=0, ge=0, le=9_007_199_254_740_991)


class Correction(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mutation_id: str = Field(min_length=16, max_length=128)
    task: str = Field(min_length=1, max_length=128)
    project: str = Field(min_length=1, max_length=200)
    project_name: str = Field(min_length=1, max_length=200)


class SourceChunk(BaseModel):
    """A replayable source range; content does not create a second usage ledger."""

    model_config = ConfigDict(extra="forbid")
    schema_id: Literal["trajectory-source-chunk/1"]
    mutation_id: str = Field(min_length=16, max_length=128)
    collector: str = Field(min_length=1, max_length=100)
    source: str = Field(pattern=r"^[a-f0-9]{64}$")
    ecosystem: Literal["codex", "claude_code", "pi"]
    generation: str = Field(min_length=1, max_length=128)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    source_bytes: int = Field(ge=0)
    content: str = Field(max_length=710000)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_name: str = Field(default="session.jsonl", max_length=250)


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mutation_id: str = Field(min_length=16, max_length=128)


class LostWindowRecomputeRequest(AnalysisRequest):
    call_id: str = Field(pattern=r"^trajectory:[0-9a-f]{64}$")
    receipt_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    accept_possible_duplicate_charge: bool = Field(strict=True)
    reason: str = Field(min_length=10, max_length=1000)
    receipt_checked_at: datetime

    @model_validator(mode="after")
    def explicit_acceptance(self) -> "LostWindowRecomputeRequest":
        if self.accept_possible_duplicate_charge is not True:
            raise ValueError("Explicit acceptance of possible duplicate charge is required")
        if self.receipt_checked_at.tzinfo is None:
            raise ValueError("Receipt check requires an explicit timezone")
        return self


class AnalysisBatchRequest(AnalysisRequest):
    session_ids: list[str] = Field(min_length=1, max_length=200)
    concurrency: int = Field(default=4, ge=1, le=8)


class TaskEdit(AnalysisRequest):
    analysis_revision: str = Field(min_length=1, max_length=128)
    action: Literal["rename", "merge", "split"]
    task_id: str = Field(min_length=1, max_length=128)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    other_task_id: str | None = Field(default=None, max_length=128)
    operation_id: str | None = Field(default=None, max_length=128)


class PriceRates(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    input: float = Field(ge=0, le=9_007_199_254_740_991)
    output: float = Field(ge=0, le=9_007_199_254_740_991)
    cached: float = Field(ge=0, le=9_007_199_254_740_991)
    cache_write: float = Field(ge=0, le=9_007_199_254_740_991)


class Price(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mutation_id: str = Field(min_length=16, max_length=128)
    model: str = Field(min_length=1, max_length=200)
    input: float = Field(ge=0, le=9_007_199_254_740_991)
    output: float = Field(ge=0, le=9_007_199_254_740_991)
    cached: float = Field(ge=0, le=9_007_199_254_740_991)
    cache_write: float = Field(ge=0, le=9_007_199_254_740_991)
    effective_from: datetime
    source_url: str = Field(min_length=8, max_length=500)

    basis: Literal["effective_historical", "current_reference"] = "effective_historical"
    verified_at: datetime | None = None
    service_tier: Literal["standard"] = "standard"
    context_scope: Literal["request", "session"] = "request"
    long_context_threshold: int | None = Field(default=None, gt=0)
    long_context: PriceRates | None = None

    @model_validator(mode="after")
    def complete_reference(self) -> "Price":
        if self.basis == "current_reference" and self.verified_at is None:
            raise ValueError("Current reference prices require verified_at")
        if (self.long_context_threshold is None) != (self.long_context is None):
            raise ValueError("Long context threshold and rates must be supplied together")
        return self

    @field_validator("effective_from", "verified_at")
    @classmethod
    def price_zone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Timezone is required")
        return value


class RequestMeasurementRepair(BaseModel):
    """Replay request measurements against a byte-pinned archived source.

    This mutation never advances the collector checkpoint or replaces usage.
    """

    model_config = ConfigDict(extra="forbid")
    mutation_id: str = Field(min_length=16, max_length=128)
    collector: str = Field(min_length=1, max_length=100)
    source: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_ledger_revision: int = Field(ge=1)
    source_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    complete_bytes: int = Field(ge=1)
    parser_version: Literal["sparkstead-trajectory/3"]
    projector_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    records: list[Record] = Field(max_length=5000)
    quarantined_source_lines: list[int] = Field(default_factory=list, max_length=10000)

    @model_validator(mode="after")
    def requests_only(self) -> "RequestMeasurementRepair":
        if any(type(line) is not int or line < 1 for line in self.quarantined_source_lines):
            raise ValueError("Invalid quarantined source line")
        if any(record.source_line in self.quarantined_source_lines for record in self.records):
            raise ValueError("Measured request cannot also be quarantined")
        if any(record.kind != "request" for record in self.records):
            raise ValueError("Request repair cannot modify model usage or tool records")
        if len({record.id for record in self.records}) != len(self.records):
            raise ValueError("Repeated request record identity")
        return self
