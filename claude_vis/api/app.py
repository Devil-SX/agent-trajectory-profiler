"""
FastAPI application for Agent Trajectory Visualizer.

Provides REST API endpoints to access session data, detailed information,
and computed statistics for local agent trajectories.
"""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from claude_vis.api.config import get_settings
from claude_vis.api.models import (
    AnalyticsDistributionResponse,
    AnalyticsOverviewResponse,
    AnalyticsTimeseriesResponse,
    ErrorResponse,
    ProjectComparisonResponse,
    ProjectSwimlaneResponse,
    SessionDetailResponse,
    SessionListResponse,
    SessionStatisticsResponse,
    SyncRunDetail,
    SyncStatusResponse,
    SyncTriggerRequest,
)
from claude_vis.api.service import SessionService

# Initialize session service
session_service: SessionService | None = None
_date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
AnalyticsDimension = Literal[
    "bottleneck",
    "project",
    "branch",
    "automation_band",
    "tool",
    "session_token_share",
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan context manager for FastAPI application."""
    global session_service
    settings = get_settings()
    session_service = SessionService(
        session_path=settings.session_path,
        codex_session_path=settings.codex_session_path,
        single_session=settings.single_session,
        db_path=settings.db_path,
        inactivity_threshold=settings.inactivity_threshold,
        model_timeout_threshold=settings.model_timeout_threshold,
    )
    await session_service.initialize()
    yield


# Application metadata
app = FastAPI(
    title="Agent Trajectory Visualizer API",
    description="REST API for visualizing and analyzing local agent trajectories",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configure CORS for local development
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _normalize_date_range(
    start_date: str | None,
    end_date: str | None,
    *,
    default_last_days: int | None = None,
) -> tuple[str | None, str | None]:
    """Validate and normalize date range query parameters."""
    if default_last_days is not None and not start_date and not end_date:
        end = date.today()
        start = end - timedelta(days=max(default_last_days - 1, 0))
        start_date = start.isoformat()
        end_date = end.isoformat()

    if start_date is not None and not _date_re.match(start_date):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid start_date format: '{start_date}'. Expected YYYY-MM-DD.",
        )
    if end_date is not None and not _date_re.match(end_date):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid end_date format: '{end_date}'. Expected YYYY-MM-DD.",
        )
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date must be on or before end_date.",
        )

    return start_date, end_date


@app.get("/api", tags=["Root"])
async def api_root() -> dict[str, str]:
    """API root endpoint with API information."""
    return {
        "name": "Agent Trajectory Visualizer API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }


# Check if frontend is built - used for root path routing
_frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"


@app.get("/", tags=["Root"], include_in_schema=False, response_model=None)
async def root() -> FileResponse | dict[str, str]:
    """
    Root endpoint - serves frontend if available, otherwise API info.

    When frontend is built, serves the index.html for web UI.
    When frontend is not built, returns API information.
    """
    index_path = _frontend_dist / "index.html"
    if index_path.exists():
        return FileResponse(index_path)

    # Fallback to API info if frontend not built
    return {
        "name": "Agent Trajectory Visualizer API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
        "hint": "Frontend not built. Run 'cd frontend && npm run build' to enable web UI.",
    }


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, Any]:
    """Health check endpoint."""
    if session_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    return {
        "status": "healthy",
        "session_path": str(session_service.session_path),
        "sessions_loaded": session_service.session_count,
    }


@app.get(
    "/api/sessions",
    response_model=SessionListResponse,
    tags=["Sessions"],
    summary="List all sessions",
    description="Get a list of all available agent sessions with basic metadata",
)
async def list_sessions(
    response: Response,
    page: int = 1,
    page_size: int = 50,
    start_date: str | None = Query(
        default=None, description="Filter sessions created on or after this date (YYYY-MM-DD)"
    ),
    end_date: str | None = Query(
        default=None, description="Filter sessions created on or before this date (YYYY-MM-DD)"
    ),
    ecosystem: str | None = Query(
        default=None,
        description="Filter sessions by ecosystem (e.g. claude_code, codex)",
    ),
) -> SessionListResponse:
    """
    List all available sessions with pagination and optional date filtering.

    Args:
        page: Page number (1-indexed, default: 1)
        page_size: Number of items per page (default: 50, max: 200)
        start_date: Include sessions on or after this date (YYYY-MM-DD)
        end_date: Include sessions on or before this date (YYYY-MM-DD)

    Returns:
        SessionListResponse: List of sessions with metadata and pagination info
    """
    if session_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Validate pagination parameters
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be >= 1")
    if page_size < 1 or page_size > 200:
        raise HTTPException(status_code=400, detail="Page size must be between 1 and 200")

    start_date, end_date = _normalize_date_range(start_date, end_date)

    try:
        sessions, total_count = await session_service.list_sessions(
            page,
            page_size,
            start_date=start_date,
            end_date=end_date,
            ecosystem=ecosystem,
        )
        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 0

        # Reduce cache duration when date filters are applied
        if start_date or end_date:
            response.headers["Cache-Control"] = "public, max-age=60"
        else:
            response.headers["Cache-Control"] = "public, max-age=300"

        return SessionListResponse(
            sessions=sessions,
            count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list sessions: {str(e)}") from e


@app.get(
    "/api/sessions/{session_id}",
    response_model=SessionDetailResponse,
    tags=["Sessions"],
    summary="Get session details",
    description=(
        "Get detailed information for a specific session including all " "messages and subagents"
    ),
)
async def get_session(session_id: str, response: Response) -> SessionDetailResponse:
    """
    Get detailed session data.

    Args:
        session_id: Session identifier

    Returns:
        SessionDetailResponse: Complete session data

    Raises:
        HTTPException: If session not found or error occurs
    """
    if session_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    try:
        session = await session_service.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        # Add caching headers - cache for 10 minutes (session data is immutable)
        response.headers["Cache-Control"] = "public, max-age=600"

        return SessionDetailResponse(session=session)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get session {session_id}: {str(e)}"
        ) from e


@app.get(
    "/api/sessions/{session_id}/statistics",
    response_model=SessionStatisticsResponse,
    tags=["Sessions"],
    summary="Get session statistics",
    description="Get computed analytics and statistics for a specific session",
)
async def get_session_statistics(session_id: str, response: Response) -> SessionStatisticsResponse:
    """
    Get session statistics.

    Args:
        session_id: Session identifier

    Returns:
        SessionStatisticsResponse: Computed statistics

    Raises:
        HTTPException: If session not found or error occurs
    """
    if session_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    try:
        statistics = await session_service.get_session_statistics(session_id)
        if statistics is None:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        # Add caching headers - cache for 10 minutes
        response.headers["Cache-Control"] = "public, max-age=600"

        return SessionStatisticsResponse(session_id=session_id, statistics=statistics)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get statistics for session {session_id}: {str(e)}",
        ) from e


@app.get(
    "/api/analytics/overview",
    response_model=AnalyticsOverviewResponse,
    tags=["Analytics"],
    summary="Get cross-session overview metrics",
    description="Aggregated analytics across sessions for a selected date range.",
)
async def get_analytics_overview(
    response: Response,
    start_date: str | None = Query(default=None, description="Range start date (YYYY-MM-DD)"),
    end_date: str | None = Query(default=None, description="Range end date (YYYY-MM-DD)"),
) -> AnalyticsOverviewResponse:
    if session_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    start_date, end_date = _normalize_date_range(start_date, end_date, default_last_days=7)
    assert start_date is not None and end_date is not None

    try:
        result = await session_service.get_analytics_overview(start_date, end_date)
        response.headers["Cache-Control"] = "public, max-age=60"
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to compute analytics overview: {str(e)}"
        ) from e


@app.get(
    "/api/analytics/distributions",
    response_model=AnalyticsDistributionResponse,
    tags=["Analytics"],
    summary="Get distribution metrics across sessions",
    description="Returns percentage breakdowns for bottlenecks, projects, tools, etc.",
)
async def get_analytics_distributions(
    response: Response,
    dimension: AnalyticsDimension = Query(  # noqa: B008
        default="bottleneck",
        description=(
            "Distribution dimension: bottleneck|project|branch|automation_band|tool|"
            "session_token_share"
        ),
    ),
    start_date: str | None = Query(default=None, description="Range start date (YYYY-MM-DD)"),
    end_date: str | None = Query(default=None, description="Range end date (YYYY-MM-DD)"),
) -> AnalyticsDistributionResponse:
    if session_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    start_date, end_date = _normalize_date_range(start_date, end_date, default_last_days=7)
    assert start_date is not None and end_date is not None

    try:
        result = await session_service.get_analytics_distribution(dimension, start_date, end_date)
        response.headers["Cache-Control"] = "public, max-age=60"
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to compute distribution: {str(e)}"
        ) from e


@app.get(
    "/api/analytics/timeseries",
    response_model=AnalyticsTimeseriesResponse,
    tags=["Analytics"],
    summary="Get time-series metrics across sessions",
    description="Returns day/week aggregated metrics for session activity trends.",
)
async def get_analytics_timeseries(
    response: Response,
    interval: Literal["day", "week"] = Query(default="day"),
    start_date: str | None = Query(default=None, description="Range start date (YYYY-MM-DD)"),
    end_date: str | None = Query(default=None, description="Range end date (YYYY-MM-DD)"),
) -> AnalyticsTimeseriesResponse:
    if session_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    start_date, end_date = _normalize_date_range(start_date, end_date, default_last_days=7)
    assert start_date is not None and end_date is not None

    try:
        result = await session_service.get_analytics_timeseries(start_date, end_date, interval)
        response.headers["Cache-Control"] = "public, max-age=60"
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to compute timeseries: {str(e)}"
        ) from e


@app.get(
    "/api/analytics/project-comparison",
    response_model=ProjectComparisonResponse,
    tags=["Analytics"],
    summary="Get cross-project comparison metrics",
    description="Returns project-level KPI comparison for selected date range.",
)
async def get_project_comparison(
    response: Response,
    start_date: str | None = Query(default=None, description="Range start date (YYYY-MM-DD)"),
    end_date: str | None = Query(default=None, description="Range end date (YYYY-MM-DD)"),
    limit: int = Query(default=10, ge=1, le=50, description="Maximum projects to return"),
) -> ProjectComparisonResponse:
    if session_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    start_date, end_date = _normalize_date_range(start_date, end_date, default_last_days=7)
    assert start_date is not None and end_date is not None

    try:
        result = await session_service.get_project_comparison(start_date, end_date, limit)
        response.headers["Cache-Control"] = "public, max-age=60"
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to compute project comparison: {str(e)}"
        ) from e


@app.get(
    "/api/analytics/project-swimlane",
    response_model=ProjectSwimlaneResponse,
    tags=["Analytics"],
    summary="Get project swimlane points",
    description="Returns project x time points for swimlane visualizations.",
)
async def get_project_swimlane(
    response: Response,
    interval: Literal["day", "week"] = Query(default="day"),
    start_date: str | None = Query(default=None, description="Range start date (YYYY-MM-DD)"),
    end_date: str | None = Query(default=None, description="Range end date (YYYY-MM-DD)"),
    project_limit: int = Query(default=12, ge=1, le=50),
) -> ProjectSwimlaneResponse:
    if session_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    start_date, end_date = _normalize_date_range(start_date, end_date, default_last_days=7)
    assert start_date is not None and end_date is not None

    try:
        result = await session_service.get_project_swimlane(
            start_date, end_date, interval, project_limit
        )
        response.headers["Cache-Control"] = "public, max-age=60"
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to compute project swimlane: {str(e)}"
        ) from e


@app.get(
    "/api/sync/status",
    response_model=SyncStatusResponse,
    tags=["Sync"],
    summary="Get sync status",
    description="Get the current synchronization status of the database",
)
async def sync_status() -> SyncStatusResponse:
    """Return information about the sync state (file count, last sync time)."""
    if session_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    info = session_service.get_sync_status()
    return SyncStatusResponse(**info)


@app.post(
    "/api/sync/run",
    response_model=SyncRunDetail,
    tags=["Sync"],
    summary="Trigger sync",
    description="Trigger a manual synchronization run and return execution details.",
)
async def run_sync(
    payload: SyncTriggerRequest | None = None,
) -> SyncRunDetail:
    """Trigger manual DB sync and return detailed results."""
    if session_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    if payload is None:
        payload = SyncTriggerRequest()

    detail = await session_service.trigger_sync(force=payload.force)
    return SyncRunDetail(**detail)


@app.exception_handler(Exception)
async def global_exception_handler(request: Any, exc: Exception) -> ErrorResponse:
    """Global exception handler for unhandled errors."""
    return ErrorResponse(error="Internal server error", detail=str(exc), status_code=500)


# Serve frontend static files in production mode
# This assumes the frontend has been built and the dist folder exists
# The frontend should be accessible at the root URL
if _frontend_dist.exists():
    # Mount static assets with caching
    assets_dir = _frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str) -> FileResponse:
        """
        Serve frontend static files.

        For any path that doesn't match an API route, serve the frontend.
        This enables client-side routing in the React app.
        """
        # If the path starts with /api/, it should have been handled by API routes
        # Let it fall through to 404
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")

        # Try to serve the requested file
        file_path = _frontend_dist / full_path
        if file_path.is_file():
            return FileResponse(file_path)

        # For all other routes, serve index.html (for client-side routing)
        index_path = _frontend_dist / "index.html"
        if index_path.exists():
            return FileResponse(index_path)

        raise HTTPException(status_code=404, detail="Frontend not found")
