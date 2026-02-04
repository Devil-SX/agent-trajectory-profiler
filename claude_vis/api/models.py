"""
API response models for FastAPI endpoints.

Defines the structure of API responses including session lists,
detailed session data, and statistics.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from claude_vis.models import Session, SessionStatistics


class SessionSummary(BaseModel):
    """
    Summary of a session for list endpoint.

    Contains minimal information for overview display.
    """

    session_id: str
    project_path: str
    created_at: datetime
    updated_at: datetime | None = None
    total_messages: int
    total_tokens: int
    git_branch: str | None = None
    version: str


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


class ErrorResponse(BaseModel):
    """Standard error response model."""

    error: str
    detail: str | None = None
    status_code: int = 500
