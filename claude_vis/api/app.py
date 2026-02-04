"""
FastAPI application for Claude Code Session Visualizer.

Provides REST API endpoints to access session data, detailed information,
and computed statistics for Claude Code sessions.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from claude_vis.api.config import get_settings
from claude_vis.api.models import (
    ErrorResponse,
    SessionDetailResponse,
    SessionListResponse,
    SessionStatisticsResponse,
)
from claude_vis.api.service import SessionService

# Initialize session service
session_service: SessionService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan context manager for FastAPI application."""
    global session_service
    settings = get_settings()
    session_service = SessionService(
        session_path=settings.session_path, single_session=settings.single_session
    )
    await session_service.initialize()
    yield


# Application metadata
app = FastAPI(
    title="Claude Code Session Visualizer API",
    description="REST API for visualizing and analyzing Claude Code sessions",
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


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    """Root endpoint with API information."""
    return {
        "name": "Claude Code Session Visualizer API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
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
    description="Get a list of all available Claude Code sessions with basic metadata",
)
async def list_sessions() -> SessionListResponse:
    """
    List all available sessions.

    Returns:
        SessionListResponse: List of sessions with metadata
    """
    if session_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    try:
        sessions = await session_service.list_sessions()
        return SessionListResponse(sessions=sessions, count=len(sessions))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to list sessions: {str(e)}"
        ) from e


@app.get(
    "/api/sessions/{session_id}",
    response_model=SessionDetailResponse,
    tags=["Sessions"],
    summary="Get session details",
    description=(
        "Get detailed information for a specific session including all "
        "messages and subagents"
    ),
)
async def get_session(session_id: str) -> SessionDetailResponse:
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
async def get_session_statistics(session_id: str) -> SessionStatisticsResponse:
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

        return SessionStatisticsResponse(session_id=session_id, statistics=statistics)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get statistics for session {session_id}: {str(e)}",
        ) from e


@app.exception_handler(Exception)
async def global_exception_handler(request: Any, exc: Exception) -> ErrorResponse:
    """Global exception handler for unhandled errors."""
    return ErrorResponse(error="Internal server error", detail=str(exc), status_code=500)


# Serve frontend static files in production mode
# This assumes the frontend has been built and the dist folder exists
# The frontend should be accessible at the root URL
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    # Mount static assets with caching
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

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
        file_path = frontend_dist / full_path
        if file_path.is_file():
            return FileResponse(file_path)

        # For all other routes, serve index.html (for client-side routing)
        index_path = frontend_dist / "index.html"
        if index_path.exists():
            return FileResponse(index_path)

        raise HTTPException(status_code=404, detail="Frontend not found")
