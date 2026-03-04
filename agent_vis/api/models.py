"""
API response models for FastAPI endpoints.

Defines the structure of API responses including session lists,
detailed session data, and statistics.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from agent_vis.models import Session, SessionStatistics


class SessionSummary(BaseModel):
    """
    Summary of a session for list endpoint.

    Contains minimal information for overview display.
    """

    session_id: str
    physical_session_id: str | None = None
    logical_session_id: str | None = None
    ecosystem: str = "claude_code"
    project_path: str
    created_at: datetime | str
    updated_at: datetime | str | None = None
    total_messages: int
    total_tokens: int
    git_branch: str | None = None
    version: str = ""
    parsed_at: str | None = None
    duration_seconds: float | None = None
    bottleneck: str | None = None
    automation_ratio: float | None = None


class SessionListResponse(BaseModel):
    """Response model for GET /api/sessions."""

    sessions: list[SessionSummary]
    count: int = Field(description="Total number of sessions")
    page: int = Field(default=1, description="Current page number")
    page_size: int = Field(default=50, description="Number of items per page")
    total_pages: int = Field(description="Total number of pages")


class SessionDetailResponse(BaseModel):
    """Response model for GET /api/sessions/{id}."""

    session: Session


class SessionStatisticsResponse(BaseModel):
    """Response model for GET /api/sessions/{id}/statistics."""

    session_id: str
    statistics: SessionStatistics


class SyncEcosystemDetail(BaseModel):
    """Per-ecosystem sync detail."""

    ecosystem: str
    files_scanned: int
    file_size_bytes: int
    parsed: int
    skipped: int
    errors: int


class SyncRunDetail(BaseModel):
    """Detail payload for sync execution status and results."""

    status: Literal["idle", "running", "completed", "failed", "already_running"]
    trigger: Literal["startup", "manual", "refresh"]
    started_at: str | None = None
    finished_at: str | None = None
    parsed: int = 0
    skipped: int = 0
    errors: int = 0
    total_files_scanned: int = 0
    total_file_size_bytes: int = 0
    ecosystems: list[SyncEcosystemDetail] = Field(default_factory=list)
    error_samples: list[str] = Field(default_factory=list)


class SyncTriggerRequest(BaseModel):
    """Request model for POST /api/sync/run."""

    force: bool = False


class SyncStatusResponse(BaseModel):
    """Response model for GET /api/sync/status."""

    total_files: int
    total_sessions: int
    last_parsed_at: str | None = None
    sync_running: bool = False
    last_sync: SyncRunDetail | None = None


class SessionBrowserFilterState(BaseModel):
    """Persisted filter state for Session Browser."""

    search_query: str = ""
    start_date: str | None = None
    end_date: str | None = None
    sort_by: Literal["updated", "created", "tokens", "duration", "automation", "messages"] = (
        "updated"
    )
    sort_direction: Literal["asc", "desc"] = "desc"
    bottleneck: Literal["all", "model", "tool", "user"] = "all"
    ecosystem: Literal["all", "codex", "claude_code"] = "all"
    token_min: int | None = None
    token_max: int | None = None
    message_min: int | None = None
    message_max: int | None = None
    automation_band: Literal["all", "low", "medium", "high"] = "all"
    automation_min: float | None = None
    automation_max: float | None = None


class FrontendPreferences(BaseModel):
    """Frontend preference state persisted under ~/.agent-vis/state."""

    locale: Literal["en", "zh-CN"] = "en"
    theme_mode: Literal["system", "light", "dark"] = "system"
    density_mode: Literal["comfortable", "compact"] = "comfortable"
    session_view_mode: Literal["cards", "table"] = "table"
    session_aggregation_mode: Literal["logical", "physical"] = "logical"
    session_browser_filters: SessionBrowserFilterState = Field(
        default_factory=SessionBrowserFilterState
    )
    updated_at: str | None = None


class FrontendPreferencesUpdate(BaseModel):
    """Partial update payload for frontend preference state."""

    locale: Literal["en", "zh-CN"] | None = None
    theme_mode: Literal["system", "light", "dark"] | None = None
    density_mode: Literal["comfortable", "compact"] | None = None
    session_view_mode: Literal["cards", "table"] | None = None
    session_aggregation_mode: Literal["logical", "physical"] | None = None
    session_browser_filters: SessionBrowserFilterState | None = None


class CapabilityParserInfo(BaseModel):
    adapter: str
    session_id_strategy: str
    supports_logical_session: bool
    supports_physical_session: bool
    minimum_agent_version: str | None = None
    default_roots: list[str] = Field(default_factory=list)


class CapabilityEventShape(BaseModel):
    message_events: bool
    tool_call_events: bool
    tool_result_events: bool
    session_boundary_events: bool
    timeline_timestamps: bool
    subagent_events: bool
    parent_child_session_links: bool
    streaming_partial_events: bool


class CapabilityTokenFieldSupport(BaseModel):
    input_tokens: bool
    output_tokens: bool
    cache_read_tokens: bool
    cache_creation_tokens: bool
    reasoning_tokens: bool
    tool_output_tokens: bool
    token_units: str


class CapabilityToolErrorSupport(BaseModel):
    categorization_available: bool
    rule_version: str
    error_preview_available: bool
    error_detail_available: bool
    supports_timestamped_error_timeline: bool
    supports_tool_name_mapping: bool


class CapabilityFallbackBehavior(BaseModel):
    missing_token_fields: str
    missing_timestamps: str
    unknown_tool_errors: str


class EcosystemCapabilityResponse(BaseModel):
    schema_version: str
    ecosystem: str
    manifest_version: str
    display_name: str
    parser: CapabilityParserInfo
    event_shape_support: CapabilityEventShape
    token_field_support: CapabilityTokenFieldSupport
    tool_error_taxonomy_support: CapabilityToolErrorSupport
    fallback_behavior: CapabilityFallbackBehavior
    known_limitations: list[str] = Field(default_factory=list)


class CapabilityListResponse(BaseModel):
    capabilities: list[EcosystemCapabilityResponse]


class ErrorResponse(BaseModel):
    """Standard error response model."""

    error: str
    detail: str | None = None
    status_code: int = 500


class AnalyticsBucket(BaseModel):
    """Generic distribution bucket."""

    key: str
    label: str
    count: int = 0
    value: float = 0.0
    percent: float = 0.0


class ProjectAggregate(BaseModel):
    """Aggregated metrics for a project path."""

    project_path: str
    project_name: str
    sessions: int
    total_tokens: int
    total_messages: int
    percent_sessions: float
    percent_tokens: float
    leverage_tokens_mean: float | None
    leverage_chars_mean: float | None


class ToolAggregate(BaseModel):
    """Aggregated metrics for a tool across sessions."""

    tool_name: str
    total_calls: int
    sessions_using_tool: int
    error_count: int
    avg_latency_seconds: float
    percent_of_tool_calls: float


class EcosystemAggregate(BaseModel):
    """Aggregated metrics grouped by source ecosystem."""

    ecosystem: str
    label: str
    sessions: int
    total_tokens: int
    total_tool_calls: int
    active_time_seconds: float
    percent_sessions: float
    percent_tokens: float


class RoleSourceAggregate(BaseModel):
    """Aggregated metrics grouped by role x source ecosystem."""

    ecosystem: str
    ecosystem_label: str
    role: Literal["user", "model", "tool"]
    role_label: str
    key: str
    label: str
    time_seconds: float
    time_percent: float
    token_count: int
    token_percent: float
    tool_calls: int
    tool_call_percent: float
    error_count: int
    error_percent: float


class ProjectComparisonItem(BaseModel):
    """Per-project KPI row for cross-session comparison."""

    project_path: str
    project_name: str
    sessions: int
    total_tokens: int
    active_ratio: float
    leverage_tokens_mean: float | None
    leverage_chars_mean: float | None


class ProjectSwimlanePoint(BaseModel):
    """One swimlane cell (project x period)."""

    period: str
    project_path: str
    project_name: str
    sessions: int
    tokens: int
    active_ratio: float
    leverage_tokens_mean: float | None


class AnalyticsTimeseriesPoint(BaseModel):
    """Time-series point for aggregated analytics."""

    period: str
    sessions: int
    tokens: int
    tool_calls: int
    avg_automation_ratio: float
    avg_duration_seconds: float


class ControlPlaneFileStats(BaseModel):
    """Tracked file status summary for ingestion/control plane."""

    total_files: int
    parsed_files: int
    error_files: int
    pending_files: int
    total_tracked_file_size_bytes: int
    total_trajectory_file_size_bytes: int
    last_parsed_at: str | None = None


class ControlPlaneOverview(BaseModel):
    """Control/Ingestion-plane metrics and sync state."""

    logical_sessions: int
    physical_sessions: int
    files: ControlPlaneFileStats
    sync_running: bool
    last_sync: SyncRunDetail


class RuntimePlaneOverview(BaseModel):
    """Runtime/Behavior-plane analytics summary."""

    total_messages: int
    total_tokens: int
    total_tool_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_tool_output_tokens: int
    total_cache_read_tokens: int
    total_cache_creation_tokens: int
    total_chars: int
    total_user_chars: int
    total_model_chars: int
    total_tool_chars: int
    total_cjk_chars: int
    total_latin_chars: int
    total_other_chars: int
    yield_ratio_tokens_mean: float
    yield_ratio_tokens_median: float
    yield_ratio_tokens_p90: float
    yield_ratio_chars_mean: float
    yield_ratio_chars_median: float
    yield_ratio_chars_p90: float
    leverage_tokens_mean: float
    leverage_tokens_median: float
    leverage_tokens_p90: float
    leverage_chars_mean: float
    leverage_chars_median: float
    leverage_chars_p90: float
    avg_tokens_per_second_mean: float
    avg_tokens_per_second_median: float
    avg_tokens_per_second_p90: float
    read_tokens_per_second_mean: float
    read_tokens_per_second_median: float
    read_tokens_per_second_p90: float
    output_tokens_per_second_mean: float
    output_tokens_per_second_median: float
    output_tokens_per_second_p90: float
    cache_tokens_per_second_mean: float
    cache_tokens_per_second_median: float
    cache_tokens_per_second_p90: float
    cache_read_tokens_per_second_mean: float
    cache_read_tokens_per_second_median: float
    cache_read_tokens_per_second_p90: float
    cache_creation_tokens_per_second_mean: float
    cache_creation_tokens_per_second_median: float
    cache_creation_tokens_per_second_p90: float
    avg_automation_ratio: float
    avg_session_duration_seconds: float
    model_time_seconds: float
    tool_time_seconds: float
    user_time_seconds: float
    inactive_time_seconds: float
    day_model_time_seconds: float
    day_tool_time_seconds: float
    day_user_time_seconds: float
    day_inactive_time_seconds: float
    night_model_time_seconds: float
    night_tool_time_seconds: float
    night_user_time_seconds: float
    night_inactive_time_seconds: float
    coverage_total_window_seconds: float = 0.0
    coverage_day_window_seconds: float = 0.0
    coverage_night_window_seconds: float = 0.0
    day_model_coverage_seconds: float = 0.0
    day_tool_coverage_seconds: float = 0.0
    day_user_coverage_seconds: float = 0.0
    night_model_coverage_seconds: float = 0.0
    night_tool_coverage_seconds: float = 0.0
    night_user_coverage_seconds: float = 0.0
    active_time_ratio: float
    model_timeout_count: int
    source_breakdown: list[EcosystemAggregate]
    role_source_breakdown: list[RoleSourceAggregate]
    primary_bottleneck_key: str | None
    primary_bottleneck_label: str | None
    primary_bottleneck_source: str | None
    primary_bottleneck_role: Literal["user", "model", "tool"] | None
    bottleneck_distribution: list[AnalyticsBucket]
    top_projects: list[ProjectAggregate]
    top_tools: list[ToolAggregate]


class AnalyticsOverviewResponse(BaseModel):
    """Response model for GET /api/analytics/overview."""

    start_date: str
    end_date: str
    total_sessions: int
    total_messages: int
    total_tokens: int
    total_tool_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_tool_output_tokens: int
    total_cache_read_tokens: int
    total_cache_creation_tokens: int
    total_trajectory_file_size_bytes: int
    total_chars: int
    total_user_chars: int
    total_model_chars: int
    total_tool_chars: int
    total_cjk_chars: int
    total_latin_chars: int
    total_other_chars: int
    yield_ratio_tokens_mean: float
    yield_ratio_tokens_median: float
    yield_ratio_tokens_p90: float
    yield_ratio_chars_mean: float
    yield_ratio_chars_median: float
    yield_ratio_chars_p90: float
    leverage_tokens_mean: float
    leverage_tokens_median: float
    leverage_tokens_p90: float
    leverage_chars_mean: float
    leverage_chars_median: float
    leverage_chars_p90: float
    avg_tokens_per_second_mean: float
    avg_tokens_per_second_median: float
    avg_tokens_per_second_p90: float
    read_tokens_per_second_mean: float
    read_tokens_per_second_median: float
    read_tokens_per_second_p90: float
    output_tokens_per_second_mean: float
    output_tokens_per_second_median: float
    output_tokens_per_second_p90: float
    cache_tokens_per_second_mean: float
    cache_tokens_per_second_median: float
    cache_tokens_per_second_p90: float
    cache_read_tokens_per_second_mean: float
    cache_read_tokens_per_second_median: float
    cache_read_tokens_per_second_p90: float
    cache_creation_tokens_per_second_mean: float
    cache_creation_tokens_per_second_median: float
    cache_creation_tokens_per_second_p90: float
    avg_automation_ratio: float
    avg_session_duration_seconds: float
    model_time_seconds: float
    tool_time_seconds: float
    user_time_seconds: float
    inactive_time_seconds: float
    day_model_time_seconds: float
    day_tool_time_seconds: float
    day_user_time_seconds: float
    day_inactive_time_seconds: float
    night_model_time_seconds: float
    night_tool_time_seconds: float
    night_user_time_seconds: float
    night_inactive_time_seconds: float
    coverage_total_window_seconds: float = 0.0
    coverage_day_window_seconds: float = 0.0
    coverage_night_window_seconds: float = 0.0
    day_model_coverage_seconds: float = 0.0
    day_tool_coverage_seconds: float = 0.0
    day_user_coverage_seconds: float = 0.0
    night_model_coverage_seconds: float = 0.0
    night_tool_coverage_seconds: float = 0.0
    night_user_coverage_seconds: float = 0.0
    active_time_ratio: float
    model_timeout_count: int
    source_breakdown: list[EcosystemAggregate]
    role_source_breakdown: list[RoleSourceAggregate]
    primary_bottleneck_key: str | None
    primary_bottleneck_label: str | None
    primary_bottleneck_source: str | None
    primary_bottleneck_role: Literal["user", "model", "tool"] | None
    bottleneck_distribution: list[AnalyticsBucket]
    top_projects: list[ProjectAggregate]
    top_tools: list[ToolAggregate]
    control_plane: ControlPlaneOverview
    runtime_plane: RuntimePlaneOverview


class ProjectComparisonResponse(BaseModel):
    """Response model for GET /api/analytics/project-comparison."""

    start_date: str
    end_date: str
    total_projects: int
    projects: list[ProjectComparisonItem]


class ProjectSwimlaneResponse(BaseModel):
    """Response model for GET /api/analytics/project-swimlane."""

    interval: Literal["day", "week"]
    start_date: str
    end_date: str
    project_limit: int
    truncated_project_count: int
    periods: list[str]
    projects: list[ProjectComparisonItem]
    points: list[ProjectSwimlanePoint]


class AnalyticsDistributionResponse(BaseModel):
    """Response model for GET /api/analytics/distributions."""

    dimension: Literal[
        "bottleneck",
        "project",
        "branch",
        "automation_band",
        "tool",
        "session_token_share",
    ]
    start_date: str
    end_date: str
    total: float
    buckets: list[AnalyticsBucket]


class AnalyticsTimeseriesResponse(BaseModel):
    """Response model for GET /api/analytics/timeseries."""

    interval: Literal["day", "week"]
    start_date: str
    end_date: str
    points: list[AnalyticsTimeseriesPoint]
