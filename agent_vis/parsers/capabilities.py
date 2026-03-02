"""Capability manifest loading and validation for parser ecosystems."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from pydantic import BaseModel, Field

SUPPORTED_SCHEMA_MAJOR = 1
_MANIFEST_DIR = Path(__file__).resolve().parent / "manifests"


class ManifestParserInfo(BaseModel):
    adapter: str
    session_id_strategy: str
    supports_logical_session: bool
    supports_physical_session: bool
    minimum_agent_version: str | None = None
    default_roots: list[str] = Field(default_factory=list)


class EventShapeSupport(BaseModel):
    message_events: bool
    tool_call_events: bool
    tool_result_events: bool
    session_boundary_events: bool
    timeline_timestamps: bool
    subagent_events: bool = False
    parent_child_session_links: bool = False
    streaming_partial_events: bool = False


class TokenFieldSupport(BaseModel):
    input_tokens: bool
    output_tokens: bool
    cache_read_tokens: bool
    cache_creation_tokens: bool
    reasoning_tokens: bool = False
    tool_output_tokens: bool = False
    token_units: str = "token"


class ToolErrorTaxonomySupport(BaseModel):
    categorization_available: bool
    rule_version: str
    error_preview_available: bool
    error_detail_available: bool
    supports_timestamped_error_timeline: bool = False
    supports_tool_name_mapping: bool = False


class FallbackBehavior(BaseModel):
    missing_token_fields: str
    missing_timestamps: str
    unknown_tool_errors: str


class CapabilityDimensions(BaseModel):
    event_shape_support: EventShapeSupport
    token_field_support: TokenFieldSupport
    tool_error_taxonomy_support: ToolErrorTaxonomySupport
    fallback_behavior: FallbackBehavior


class CapabilityManifest(BaseModel):
    schema_version: str
    ecosystem: str
    manifest_version: str
    display_name: str
    parser: ManifestParserInfo
    capabilities: CapabilityDimensions
    known_limitations: list[str] = Field(default_factory=list)

    def schema_major(self) -> int:
        prefix = self.schema_version.split(".")[0]
        return int(prefix)


def _manifest_path(ecosystem: str) -> Path:
    return _MANIFEST_DIR / f"{ecosystem}.json"


@cache
def load_capability_manifest(ecosystem: str) -> CapabilityManifest:
    """Load one ecosystem capability manifest and validate schema compatibility."""
    path = _manifest_path(ecosystem)
    if not path.exists():
        raise ValueError(f"Capability manifest not found for ecosystem '{ecosystem}': {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to read manifest for ecosystem '{ecosystem}': {exc}") from exc

    manifest = CapabilityManifest.model_validate(payload)
    if manifest.ecosystem != ecosystem:
        raise ValueError(
            f"Manifest ecosystem mismatch: expected '{ecosystem}', got '{manifest.ecosystem}'"
        )

    major = manifest.schema_major()
    if major > SUPPORTED_SCHEMA_MAJOR:
        raise ValueError(
            f"Unsupported manifest schema major version '{major}' for ecosystem '{ecosystem}'"
        )

    return manifest


def list_capability_manifests(ecosystems: list[str] | None = None) -> list[CapabilityManifest]:
    """Load manifests for given ecosystems (or all manifest files if omitted)."""
    if ecosystems is None:
        ecosystems = sorted(path.stem for path in _MANIFEST_DIR.glob("*.json"))
    return [load_capability_manifest(name) for name in ecosystems]


def validate_registered_capabilities(registered_ecosystems: list[str]) -> list[CapabilityManifest]:
    """Validate that all registered ecosystems have compatible manifests."""
    manifests = []
    for ecosystem in sorted(registered_ecosystems):
        manifests.append(load_capability_manifest(ecosystem))
    return manifests


def get_capability_warnings(
    ecosystem: str,
    *,
    total_tool_calls: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    has_tool_error_records: bool,
    has_subagent_sessions: bool,
) -> list[str]:
    """Return warnings when observed stats conflict with declared ecosystem capabilities."""
    manifest = load_capability_manifest(ecosystem)
    warnings: list[str] = []

    event_support = manifest.capabilities.event_shape_support
    token_support = manifest.capabilities.token_field_support
    error_support = manifest.capabilities.tool_error_taxonomy_support

    if not event_support.tool_call_events and total_tool_calls > 0:
        warnings.append(
            "tool_call_events=false but parsed stats include tool calls;"
            " check parser/manifest drift"
        )
    if not event_support.subagent_events and has_subagent_sessions:
        warnings.append(
            "subagent_events=false but parsed session includes subagent sessions;"
            " check manifest drift"
        )
    if not token_support.cache_read_tokens and cache_read_tokens > 0:
        warnings.append(
            "cache_read_tokens=false but parsed stats include cache_read_tokens;"
            " check manifest drift"
        )
    if not token_support.cache_creation_tokens and cache_creation_tokens > 0:
        warnings.append(
            "cache_creation_tokens=false but parsed stats include cache_creation_tokens;"
            " check manifest drift"
        )
    if not error_support.categorization_available and has_tool_error_records:
        warnings.append(
            "tool_error taxonomy disabled in manifest but parsed error records exist;"
            " check manifest drift"
        )

    return warnings
