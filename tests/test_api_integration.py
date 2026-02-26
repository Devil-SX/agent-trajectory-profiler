"""
Integration tests for the FastAPI backend.

Tests cover API endpoints, service layer integration, and error handling
with test client for realistic request/response testing.
"""

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from claude_vis.api.service import SessionService


class TestAPIHealthEndpoints:
    """Tests for health check and root endpoints."""

    def test_root_endpoint(self, test_client: TestClient) -> None:
        """Test root endpoint returns API information."""
        response = test_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert data["docs"] == "/docs"

    def test_health_check_endpoint(self, test_client: TestClient) -> None:
        """Test health check endpoint returns service status."""
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "session_path" in data
        assert "sessions_loaded" in data
        assert data["sessions_loaded"] >= 0


class TestSessionListAPI:
    """Tests for session listing API endpoint."""

    def test_list_sessions_success(self, test_client: TestClient) -> None:
        """Test successful session listing."""
        response = test_client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert "count" in data
        assert isinstance(data["sessions"], list)
        assert data["count"] == len(data["sessions"])

    def test_list_sessions_contains_expected_fields(
        self, test_client: TestClient
    ) -> None:
        """Test that session summaries contain all required fields."""
        response = test_client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()

        if data["count"] > 0:
            session = data["sessions"][0]
            assert "session_id" in session
            assert "project_path" in session
            assert "created_at" in session
            assert "total_messages" in session
            assert "total_tokens" in session

    def test_list_sessions_sorted_by_created_at(
        self, test_client: TestClient
    ) -> None:
        """Test that sessions are sorted by creation time (newest first)."""
        response = test_client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()

        if data["count"] > 1:
            sessions = data["sessions"]
            # Verify sessions are sorted in descending order by created_at
            for i in range(len(sessions) - 1):
                assert sessions[i]["created_at"] >= sessions[i + 1]["created_at"]


class TestSessionDetailAPI:
    """Tests for session detail API endpoint."""

    def test_get_session_success(self, test_client: TestClient) -> None:
        """Test successful retrieval of session details."""
        # First, get list of sessions to find a valid session ID
        list_response = test_client.get("/api/sessions")
        assert list_response.status_code == 200
        sessions = list_response.json()["sessions"]

        if len(sessions) > 0:
            session_id = sessions[0]["session_id"]

            # Get session details
            response = test_client.get(f"/api/sessions/{session_id}")
            assert response.status_code == 200
            data = response.json()
            assert "session" in data
            assert data["session"]["metadata"]["session_id"] == session_id

    def test_get_session_contains_metadata(self, test_client: TestClient) -> None:
        """Test that session details contain metadata."""
        list_response = test_client.get("/api/sessions")
        sessions = list_response.json()["sessions"]

        if len(sessions) > 0:
            session_id = sessions[0]["session_id"]
            response = test_client.get(f"/api/sessions/{session_id}")
            assert response.status_code == 200
            data = response.json()

            session = data["session"]
            assert "metadata" in session
            assert "messages" in session
            assert "statistics" in session

    def test_get_session_contains_messages(self, test_client: TestClient) -> None:
        """Test that session details contain messages."""
        list_response = test_client.get("/api/sessions")
        sessions = list_response.json()["sessions"]

        if len(sessions) > 0:
            session_id = sessions[0]["session_id"]
            response = test_client.get(f"/api/sessions/{session_id}")
            assert response.status_code == 200
            data = response.json()

            session = data["session"]
            assert len(session["messages"]) > 0
            # Verify message structure
            message = session["messages"][0]
            assert "uuid" in message
            assert "timestamp" in message
            assert "type" in message

    def test_get_session_not_found(self, test_client: TestClient) -> None:
        """Test getting a non-existent session returns 404."""
        response = test_client.get("/api/sessions/non-existent-session-id")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data


class TestSessionStatisticsAPI:
    """Tests for session statistics API endpoint."""

    def test_get_statistics_success(self, test_client: TestClient) -> None:
        """Test successful retrieval of session statistics."""
        # Get a valid session ID
        list_response = test_client.get("/api/sessions")
        sessions = list_response.json()["sessions"]

        if len(sessions) > 0:
            session_id = sessions[0]["session_id"]
            response = test_client.get(f"/api/sessions/{session_id}/statistics")
            assert response.status_code == 200
            data = response.json()
            assert "session_id" in data
            assert "statistics" in data
            assert data["session_id"] == session_id

    def test_statistics_contains_required_fields(
        self, test_client: TestClient
    ) -> None:
        """Test that statistics contain all required fields."""
        list_response = test_client.get("/api/sessions")
        sessions = list_response.json()["sessions"]

        if len(sessions) > 0:
            session_id = sessions[0]["session_id"]
            response = test_client.get(f"/api/sessions/{session_id}/statistics")
            assert response.status_code == 200
            data = response.json()

            stats = data["statistics"]
            assert "message_count" in stats
            assert "user_message_count" in stats
            assert "assistant_message_count" in stats
            assert "total_tokens" in stats
            assert "total_input_tokens" in stats
            assert "total_output_tokens" in stats

    def test_statistics_tool_call_data(self, test_client: TestClient) -> None:
        """Test that statistics include tool call information."""
        list_response = test_client.get("/api/sessions")
        sessions = list_response.json()["sessions"]

        if len(sessions) > 0:
            session_id = sessions[0]["session_id"]
            response = test_client.get(f"/api/sessions/{session_id}/statistics")
            assert response.status_code == 200
            data = response.json()

            stats = data["statistics"]
            assert "total_tool_calls" in stats
            assert "tool_calls" in stats
            assert isinstance(stats["tool_calls"], list)

    def test_get_statistics_not_found(self, test_client: TestClient) -> None:
        """Test getting statistics for non-existent session returns 404."""
        response = test_client.get(
            "/api/sessions/non-existent-session-id/statistics"
        )
        assert response.status_code == 404


class TestAnalyticsAPI:
    """Tests for cross-session analytics endpoints."""

    def test_analytics_overview_default_range(self, test_client: TestClient) -> None:
        """Default overview request should apply a 7-day window."""
        response = test_client.get("/api/analytics/overview")
        assert response.status_code == 200

        payload = response.json()
        assert "start_date" in payload
        assert "end_date" in payload
        assert "total_sessions" in payload
        assert "total_tokens" in payload
        assert "bottleneck_distribution" in payload

        start = date.fromisoformat(payload["start_date"])
        end = date.fromisoformat(payload["end_date"])
        assert end - start == timedelta(days=6)

    def test_analytics_overview_with_explicit_range(
        self, test_client: TestClient
    ) -> None:
        """Overview should include fixture data when range covers fixture timestamps."""
        response = test_client.get(
            "/api/analytics/overview?start_date=2026-02-01&end_date=2026-02-10"
        )
        assert response.status_code == 200

        payload = response.json()
        assert payload["total_sessions"] >= 1
        assert payload["total_messages"] >= 1
        assert payload["total_tokens"] >= 1

    def test_analytics_distribution_tool(
        self, test_client: TestClient
    ) -> None:
        """Tool distribution endpoint should return bucketed results."""
        response = test_client.get(
            "/api/analytics/distributions?dimension=tool&start_date=2026-02-01&end_date=2026-02-10"
        )
        assert response.status_code == 200

        payload = response.json()
        assert payload["dimension"] == "tool"
        assert "buckets" in payload
        assert isinstance(payload["buckets"], list)

    def test_analytics_timeseries_weekly(
        self, test_client: TestClient
    ) -> None:
        """Timeseries endpoint should support week aggregation."""
        response = test_client.get(
            "/api/analytics/timeseries?interval=week&start_date=2026-02-01&end_date=2026-02-10"
        )
        assert response.status_code == 200

        payload = response.json()
        assert payload["interval"] == "week"
        assert "points" in payload
        assert isinstance(payload["points"], list)

    def test_analytics_invalid_date_range(
        self, test_client: TestClient
    ) -> None:
        """Invalid date range should return HTTP 400."""
        response = test_client.get(
            "/api/analytics/overview?start_date=2026-02-10&end_date=2026-02-01"
        )
        assert response.status_code == 400

    def test_analytics_invalid_dimension(
        self, test_client: TestClient
    ) -> None:
        """Invalid distribution dimension should return HTTP 422."""
        response = test_client.get(
            "/api/analytics/distributions?dimension=invalid_dimension"
        )
        assert response.status_code == 422


class TestSessionServiceIntegration:
    """Integration tests for SessionService."""

    @pytest.mark.asyncio
    async def test_service_initialization(
        self, multi_session_directory: Path
    ) -> None:
        """Test that SessionService initializes correctly."""
        service = SessionService(session_path=multi_session_directory)
        assert not service.is_initialized
        assert service.session_count == 0

        await service.initialize()
        assert service.is_initialized
        assert service.session_count > 0

    def test_service_list_sessions(
        self, initialized_session_service_sync: SessionService
    ) -> None:
        """Test listing sessions through the service."""
        import asyncio

        sessions, total = asyncio.run(initialized_session_service_sync.list_sessions())
        assert len(sessions) > 0
        assert total > 0
        assert all(hasattr(s, "session_id") for s in sessions)
        assert all(hasattr(s, "total_messages") for s in sessions)

    def test_service_get_session(
        self, initialized_session_service_sync: SessionService
    ) -> None:
        """Test getting a session by ID."""
        import asyncio

        sessions, _ = asyncio.run(initialized_session_service_sync.list_sessions())
        assert len(sessions) > 0

        session_id = sessions[0].session_id
        session = asyncio.run(initialized_session_service_sync.get_session(session_id))
        assert session is not None
        assert session.metadata.session_id == session_id

    def test_service_get_session_statistics(
        self, initialized_session_service_sync: SessionService
    ) -> None:
        """Test getting session statistics."""
        import asyncio

        sessions, _ = asyncio.run(initialized_session_service_sync.list_sessions())
        assert len(sessions) > 0

        session_id = sessions[0].session_id
        stats = asyncio.run(
            initialized_session_service_sync.get_session_statistics(session_id)
        )
        assert stats is not None
        assert stats.message_count > 0
        assert stats.total_tokens >= 0

    def test_service_get_nonexistent_session(
        self, initialized_session_service_sync: SessionService
    ) -> None:
        """Test getting a non-existent session returns None."""
        import asyncio

        session = asyncio.run(
            initialized_session_service_sync.get_session("non-existent")
        )
        assert session is None

    def test_service_refresh_sessions(
        self, initialized_session_service_sync: SessionService
    ) -> None:
        """Test refreshing sessions reloads data."""
        import asyncio

        initial_count = initialized_session_service_sync.session_count
        asyncio.run(initialized_session_service_sync.refresh_sessions())
        # Count should remain the same after refresh
        assert initialized_session_service_sync.session_count == initial_count


class TestAPIErrorHandling:
    """Tests for API error handling."""

    def test_invalid_endpoint_returns_404(self, test_client: TestClient) -> None:
        """Test that invalid API endpoints return 404."""
        response = test_client.get("/api/invalid-endpoint")
        assert response.status_code == 404

    def test_malformed_session_id(self, test_client: TestClient) -> None:
        """Test handling of malformed session IDs."""
        # Use various malformed IDs
        malformed_ids = [
            "",
            "   ",
            "../../../etc/passwd",
            "null",
            "undefined",
        ]

        for session_id in malformed_ids:
            response = test_client.get(f"/api/sessions/{session_id}")
            # Should return 404 for non-existent sessions
            assert response.status_code == 404


class TestAPICORS:
    """Tests for CORS configuration."""

    def test_cors_headers_present(self, test_client: TestClient) -> None:
        """Test that CORS headers are present in responses."""
        response = test_client.get("/api/sessions")
        assert response.status_code == 200
        # CORS headers should be present
        assert "access-control-allow-origin" in response.headers


class TestAPIEndToEnd:
    """End-to-end API workflow tests."""

    def test_complete_session_workflow(self, test_client: TestClient) -> None:
        """Test complete workflow: list -> detail -> statistics."""
        # Step 1: List sessions
        list_response = test_client.get("/api/sessions")
        assert list_response.status_code == 200
        sessions = list_response.json()["sessions"]

        if len(sessions) > 0:
            session_id = sessions[0]["session_id"]

            # Step 2: Get session detail
            detail_response = test_client.get(f"/api/sessions/{session_id}")
            assert detail_response.status_code == 200
            session_data = detail_response.json()["session"]

            # Step 3: Get session statistics
            stats_response = test_client.get(
                f"/api/sessions/{session_id}/statistics"
            )
            assert stats_response.status_code == 200
            stats_data = stats_response.json()["statistics"]

            # Verify consistency
            assert (
                session_data["metadata"]["total_messages"]
                == stats_data["message_count"]
            )
            assert (
                session_data["metadata"]["total_tokens"] == stats_data["total_tokens"]
            )

    def test_session_data_consistency(self, test_client: TestClient) -> None:
        """Test that session data is consistent across endpoints."""
        list_response = test_client.get("/api/sessions")
        sessions = list_response.json()["sessions"]

        if len(sessions) > 0:
            session_summary = sessions[0]
            session_id = session_summary["session_id"]

            # Get full session
            detail_response = test_client.get(f"/api/sessions/{session_id}")
            session_detail = detail_response.json()["session"]

            # Verify consistency between summary and detail
            assert session_summary["session_id"] == session_id
            assert (
                session_summary["total_messages"]
                == session_detail["metadata"]["total_messages"]
            )
            assert (
                session_summary["total_tokens"]
                == session_detail["metadata"]["total_tokens"]
            )
