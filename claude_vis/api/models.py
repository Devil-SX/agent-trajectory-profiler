"""
API response models for FastAPI endpoints.

Defines the structure of API responses including session lists,
detailed session data, and statistics.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from claude_vis.models import Session, SessionStatistics


class SessionSummary(BaseModel):
    """
    Summary of a session for list endpoint.

    Contains minimal information for overview display.
    """

    session_id: str
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


class SyncStatusResponse(BaseModel):
    """Response model for GET /api/sync/status."""

    total_files: int
    total_sessions: int
    last_parsed_at: str | None = None


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


class ToolAggregate(BaseModel):
    """Aggregated metrics for a tool across sessions."""

    tool_name: str
    total_calls: int
    sessions_using_tool: int
    error_count: int
    avg_latency_seconds: float
    percent_of_tool_calls: float


class AnalyticsTimeseriesPoint(BaseModel):
    """Time-series point for aggregated analytics."""

    period: str
    sessions: int
    tokens: int
    tool_calls: int
    avg_automation_ratio: float
    avg_duration_seconds: float


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
    total_cache_read_tokens: int
    total_cache_creation_tokens: int
    avg_automation_ratio: float
    avg_session_duration_seconds: float
    model_time_seconds: float
    tool_time_seconds: float
    user_time_seconds: float
    inactive_time_seconds: float
    active_time_ratio: float
    model_timeout_count: int
    bottleneck_distribution: list[AnalyticsBucket]
    top_projects: list[ProjectAggregate]
    top_tools: list[ToolAggregate]


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
