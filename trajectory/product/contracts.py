"""The single wire contract; no prompts, credentials or source code are transported."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(min_length=16, max_length=128)
    session: str = Field(min_length=1, max_length=200)
    parent: str | None = Field(default=None, max_length=200)
    task: str = Field(min_length=1, max_length=128)
    ecosystem: Literal["codex", "claude_code"]
    timestamp: datetime | None
    kind: Literal["request", "usage", "tool_start", "tool_end", "notice"]
    model: str | None = Field(default=None, max_length=200)
    input: int | None = Field(default=None, ge=0, le=9_007_199_254_740_991)
    output: int | None = Field(default=None, ge=0, le=9_007_199_254_740_991)
    cached: int | None = Field(default=None, ge=0, le=9_007_199_254_740_991)
    cache_write: int | None = Field(default=None, ge=0, le=9_007_199_254_740_991)
    reasoning: int | None = Field(default=None, ge=0, le=9_007_199_254_740_991)
    input_includes_cache: bool = False
    output_includes_reasoning: bool = True
    consumption: str | None = Field(default=None, max_length=128)
    workspace: str | None = Field(default=None, max_length=200)
    references: list[str] = Field(default_factory=list, max_length=32)

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

    @field_validator("effective_from")
    @classmethod
    def price_zone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Timezone is required")
        return value
