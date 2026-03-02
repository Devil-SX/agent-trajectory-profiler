"""
Integration tests for the FastAPI backend.

Tests cover API endpoints, service layer integration, and error handling
with test client for realistic request/response testing.
"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_vis.api.app import app
from agent_vis.api.config import Settings, get_settings
from agent_vis.api.service import SessionService


class TestAPIHealthEndpoints:
    """Tests for health check and root endpoints."""

    def test_root_endpoint(self, test_client: TestClient) -> None:
        """Test root endpoint returns frontend HTML or API information."""
        response = test_client.get("/")
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")

        if "application/json" in content_type:
            data = response.json()
            assert "name" in data
            assert "version" in data
            assert data["name"] == "Agent Trajectory Visualizer API"
            assert data["docs"] == "/docs"
        else:
            assert "text/html" in content_type
            assert "<html" in response.text.lower()

    def test_api_root_endpoint_uses_agent_neutral_branding(self, test_client: TestClient) -> None:
        """API metadata endpoint should use ecosystem-neutral service naming."""
        response = test_client.get("/api")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Agent Trajectory Visualizer API"
        assert data["version"] == "0.1.0"

    def test_health_check_endpoint(self, test_client: TestClient) -> None:
        """Test health check endpoint returns service status."""
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "session_path" in data
        assert "sessions_loaded" in data
        assert data["sessions_loaded"] >= 0


class TestSyncAPI:
    """Tests for sync status and manual trigger endpoints."""

    def test_sync_status_exposes_detailed_fields(self, test_client: TestClient) -> None:
        response = test_client.get("/api/sync/status")
        assert response.status_code == 200
        data = response.json()

        assert "total_files" in data
        assert "total_sessions" in data
        assert "last_parsed_at" in data
        assert "sync_running" in data
        assert "last_sync" in data

        last_sync = data["last_sync"]
        assert "status" in last_sync
        assert "trigger" in last_sync
        assert "parsed" in last_sync
        assert "skipped" in last_sync
        assert "errors" in last_sync
        assert "total_files_scanned" in last_sync
        assert "total_file_size_bytes" in last_sync
        assert "ecosystems" in last_sync
        assert isinstance(last_sync["ecosystems"], list)

    def test_manual_sync_endpoint_returns_run_detail(self, test_client: TestClient) -> None:
        response = test_client.post("/api/sync/run", json={"force": False})
        assert response.status_code == 200
        data = response.json()

        assert data["status"] in {"completed", "failed", "already_running", "idle", "running"}
        assert data["trigger"] == "manual"
        assert "parsed" in data
        assert "skipped" in data
        assert "errors" in data
        assert "total_files_scanned" in data
        assert "total_file_size_bytes" in data
        assert "ecosystems" in data


class TestFrontendStateAPI:
    """Tests for frontend preference state endpoints."""

    def test_frontend_preferences_defaults_and_update(
        self,
        tmp_path: Path,
        multi_session_directory: Path,
    ) -> None:
        from importlib import import_module
        from unittest.mock import patch

        api_app_module = import_module("agent_vis.api.app")
        codex_empty = tmp_path / "codex_empty"
        codex_empty.mkdir(parents=True, exist_ok=True)

        settings = Settings(
            session_path=multi_session_directory,
            codex_session_path=codex_empty,
            db_path=tmp_path / "pref_state.db",
            api_host="127.0.0.1",
            api_port=8000,
            api_reload=False,
            log_level="INFO",
            cors_origins=["http://localhost:5173"],
        )

        get_settings.cache_clear()
        try:
            with patch.object(api_app_module, "get_settings", return_value=settings):
                with TestClient(app) as client:
                    default_response = client.get("/api/state/frontend-preferences")
                    assert default_response.status_code == 200
                    default_payload = default_response.json()
                    assert default_payload["locale"] == "en"
                    assert default_payload["theme_mode"] == "system"
                    assert default_payload["density_mode"] == "comfortable"
                    assert default_payload["session_view_mode"] == "table"
                    assert default_payload["session_aggregation_mode"] == "logical"
                    assert default_payload["updated_at"] is None

                    update_response = client.put(
                        "/api/state/frontend-preferences",
                        json={
                            "locale": "zh-CN",
                            "theme_mode": "dark",
                            "density_mode": "compact",
                            "session_view_mode": "cards",
                            "session_aggregation_mode": "physical",
                        },
                    )
                    assert update_response.status_code == 200
                    updated_payload = update_response.json()
                    assert updated_payload["locale"] == "zh-CN"
                    assert updated_payload["theme_mode"] == "dark"
                    assert updated_payload["density_mode"] == "compact"
                    assert updated_payload["session_view_mode"] == "cards"
                    assert updated_payload["session_aggregation_mode"] == "physical"
                    assert updated_payload["updated_at"] is not None

                    readback = client.get("/api/state/frontend-preferences")
                    assert readback.status_code == 200
                    assert readback.json()["locale"] == "zh-CN"

            state_dir = tmp_path / "state"
            state_file = state_dir / "frontend-preferences.json"
            assert state_dir.exists()
            assert state_file.exists()
            saved = json.loads(state_file.read_text(encoding="utf-8"))
            assert saved["session_view_mode"] == "cards"
            assert saved["session_aggregation_mode"] == "physical"
        finally:
            get_settings.cache_clear()


class TestSettingsCompatibility:
    """Backward-compatibility tests for AGENT_VIS_* environment settings."""

    def test_env_var_configuration_behavior_is_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENT_VIS_API_PORT", "9123")
        monkeypatch.setenv("AGENT_VIS_API_HOST", "127.0.0.1")
        monkeypatch.setenv("AGENT_VIS_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("AGENT_VIS_INACTIVITY_THRESHOLD", "1234")
        monkeypatch.setenv("AGENT_VIS_MODEL_TIMEOUT_THRESHOLD", "321")

        get_settings.cache_clear()
        try:
            settings = get_settings()
            assert settings.api_port == 9123
            assert settings.api_host == "127.0.0.1"
            assert settings.log_level == "DEBUG"
            assert settings.inactivity_threshold == 1234
            assert settings.model_timeout_threshold == 321
        finally:
            get_settings.cache_clear()


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

    def test_list_sessions_contains_expected_fields(self, test_client: TestClient) -> None:
        """Test that session summaries contain all required fields."""
        response = test_client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()

        if data["count"] > 0:
            session = data["sessions"][0]
            assert "session_id" in session
            assert "ecosystem" in session
            assert "project_path" in session
            assert "created_at" in session
            assert "total_messages" in session
            assert "total_tokens" in session

    def test_list_sessions_ecosystem_filter_with_mixed_sources(
        self,
        tmp_path: Path,
        multi_session_directory: Path,
        codex_session_root: Path,
        sample_codex_rollout_file: Path,
    ) -> None:
        """Sessions API should expose ecosystem field and support filtering."""
        from importlib import import_module
        from unittest.mock import patch

        api_app_module = import_module("agent_vis.api.app")
        _ = sample_codex_rollout_file  # Ensure Codex fixture file is created.
        settings = Settings(
            session_path=multi_session_directory,
            codex_session_path=codex_session_root,
            db_path=tmp_path / "mixed_ecosystem.db",
            api_host="127.0.0.1",
            api_port=8000,
            api_reload=False,
            log_level="INFO",
            cors_origins=["http://localhost:5173"],
        )

        get_settings.cache_clear()
        try:
            with patch.object(api_app_module, "get_settings", return_value=settings):
                with TestClient(app) as client:
                    response = client.get("/api/sessions")
                    assert response.status_code == 200
                    sessions = response.json()["sessions"]
                    ecosystems = {s["ecosystem"] for s in sessions}
                    assert "claude_code" in ecosystems
                    assert "codex" in ecosystems

                    codex_response = client.get("/api/sessions?ecosystem=codex")
                    assert codex_response.status_code == 200
                    codex_sessions = codex_response.json()["sessions"]
                    assert len(codex_sessions) >= 1
                    assert all(s["ecosystem"] == "codex" for s in codex_sessions)
        finally:
            get_settings.cache_clear()

    def test_list_sessions_sorted_by_created_at(self, test_client: TestClient) -> None:
        """Test that sessions are sorted by creation time (newest first)."""
        response = test_client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()

        if data["count"] > 1:
            sessions = data["sessions"]
            # Verify sessions are sorted in descending order by created_at
            for i in range(len(sessions) - 1):
                assert sessions[i]["created_at"] >= sessions[i + 1]["created_at"]

    def test_list_sessions_defaults_to_logical_view_for_codex_hierarchy(
        self,
        tmp_path: Path,
        codex_logical_hierarchy_root: Path,
    ) -> None:
        from importlib import import_module
        from unittest.mock import patch

        api_app_module = import_module("agent_vis.api.app")
        claude_empty = tmp_path / "claude_empty"
        claude_empty.mkdir(parents=True, exist_ok=True)
        settings = Settings(
            session_path=claude_empty,
            codex_session_path=codex_logical_hierarchy_root,
            db_path=tmp_path / "logical_view.db",
            api_host="127.0.0.1",
            api_port=8000,
            api_reload=False,
            log_level="INFO",
            cors_origins=["http://localhost:5173"],
        )

        get_settings.cache_clear()
        try:
            with patch.object(api_app_module, "get_settings", return_value=settings):
                with TestClient(app) as client:
                    logical_response = client.get("/api/sessions")
                    assert logical_response.status_code == 200
                    logical_payload = logical_response.json()
                    assert logical_payload["count"] == 1
                    assert len(logical_payload["sessions"]) == 1

                    logical_session = logical_payload["sessions"][0]
                    root_id = "11111111-1111-1111-1111-111111111111"
                    assert logical_session["logical_session_id"] == root_id
                    assert logical_session["physical_session_id"] == root_id

                    physical_response = client.get("/api/sessions?view=physical")
                    assert physical_response.status_code == 200
                    physical_payload = physical_response.json()
                    assert physical_payload["count"] == 3
                    assert len(physical_payload["sessions"]) == 3
                    assert all(
                        session["logical_session_id"] == root_id
                        for session in physical_payload["sessions"]
                    )
        finally:
            get_settings.cache_clear()


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

    def test_statistics_contains_required_fields(self, test_client: TestClient) -> None:
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
            assert "trajectory_file_size_bytes" in stats
            assert "character_breakdown" in stats
            assert "user_yield_ratio_tokens" in stats
            assert "user_yield_ratio_chars" in stats
            assert "leverage_ratio_tokens" in stats
            assert "leverage_ratio_chars" in stats
            assert "avg_tokens_per_second" in stats
            assert "read_tokens_per_second" in stats
            assert "output_tokens_per_second" in stats
            assert "cache_tokens_per_second" in stats

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
            assert "tool_error_records" in stats
            assert isinstance(stats["tool_error_records"], list)
            assert "tool_error_category_counts" in stats
            assert isinstance(stats["tool_error_category_counts"], dict)
            assert "error_taxonomy_version" in stats
            assert isinstance(stats["error_taxonomy_version"], str)

    def test_get_statistics_not_found(self, test_client: TestClient) -> None:
        """Test getting statistics for non-existent session returns 404."""
        response = test_client.get("/api/sessions/non-existent-session-id/statistics")
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
        assert "active_time_ratio" in payload
        assert "total_tool_output_tokens" in payload
        assert "total_trajectory_file_size_bytes" in payload
        assert "total_chars" in payload
        assert "yield_ratio_tokens_mean" in payload
        assert "yield_ratio_tokens_median" in payload
        assert "yield_ratio_tokens_p90" in payload
        assert "yield_ratio_chars_mean" in payload
        assert "yield_ratio_chars_median" in payload
        assert "yield_ratio_chars_p90" in payload
        assert "leverage_tokens_mean" in payload
        assert "leverage_tokens_median" in payload
        assert "leverage_tokens_p90" in payload
        assert "leverage_chars_mean" in payload
        assert "leverage_chars_median" in payload
        assert "leverage_chars_p90" in payload
        assert "avg_tokens_per_second_mean" in payload
        assert "avg_tokens_per_second_median" in payload
        assert "avg_tokens_per_second_p90" in payload
        assert "read_tokens_per_second_mean" in payload
        assert "output_tokens_per_second_mean" in payload
        assert "cache_tokens_per_second_mean" in payload
        assert "day_model_time_seconds" in payload
        assert "day_tool_time_seconds" in payload
        assert "day_user_time_seconds" in payload
        assert "day_inactive_time_seconds" in payload
        assert "night_model_time_seconds" in payload
        assert "night_tool_time_seconds" in payload
        assert "night_user_time_seconds" in payload
        assert "night_inactive_time_seconds" in payload
        assert "source_breakdown" in payload
        assert isinstance(payload["source_breakdown"], list)
        assert "control_plane" in payload
        assert "runtime_plane" in payload
        assert isinstance(payload["control_plane"], dict)
        assert isinstance(payload["runtime_plane"], dict)
        assert "last_sync" in payload["control_plane"]
        assert "files" in payload["control_plane"]
        assert "bottleneck_distribution" in payload["runtime_plane"]
        assert "top_tools" in payload["runtime_plane"]

        start = date.fromisoformat(payload["start_date"])
        end = date.fromisoformat(payload["end_date"])
        assert end - start == timedelta(days=6)

    def test_analytics_overview_with_explicit_range(self, test_client: TestClient) -> None:
        """Overview should include fixture data when range covers fixture timestamps."""
        response = test_client.get(
            "/api/analytics/overview?start_date=2026-02-01&end_date=2026-02-10"
        )
        assert response.status_code == 200

        payload = response.json()
        assert payload["total_sessions"] >= 1
        assert payload["total_messages"] >= 1
        assert payload["total_tokens"] >= 1
        assert 0.0 <= payload["active_time_ratio"] <= 1.0
        assert payload["yield_ratio_tokens_p90"] >= payload["yield_ratio_tokens_median"]
        assert payload["yield_ratio_chars_p90"] >= payload["yield_ratio_chars_median"]
        assert payload["leverage_tokens_p90"] >= payload["leverage_tokens_median"]
        assert payload["leverage_chars_p90"] >= payload["leverage_chars_median"]
        assert payload["avg_tokens_per_second_p90"] >= payload["avg_tokens_per_second_median"]

        active = (
            payload["model_time_seconds"]
            + payload["tool_time_seconds"]
            + payload["user_time_seconds"]
        )
        span = active + payload["inactive_time_seconds"]
        expected_ratio = active / span if span > 0 else 0.0
        assert payload["active_time_ratio"] == pytest.approx(expected_ratio, abs=1e-9)
        day_total = (
            payload["day_model_time_seconds"]
            + payload["day_tool_time_seconds"]
            + payload["day_user_time_seconds"]
            + payload["day_inactive_time_seconds"]
        )
        night_total = (
            payload["night_model_time_seconds"]
            + payload["night_tool_time_seconds"]
            + payload["night_user_time_seconds"]
            + payload["night_inactive_time_seconds"]
        )
        assert day_total + night_total == pytest.approx(span, abs=1e-3)

        control_keys = set(payload["control_plane"].keys())
        runtime_keys = set(payload["runtime_plane"].keys())
        assert control_keys.isdisjoint(runtime_keys)

    def test_analytics_overview_source_breakdown_with_mixed_sources(
        self,
        tmp_path: Path,
        multi_session_directory: Path,
        codex_session_root: Path,
        sample_codex_rollout_file: Path,
    ) -> None:
        """Overview API should include per-ecosystem aggregates for Codex and Claude Code."""
        from importlib import import_module
        from unittest.mock import patch

        api_app_module = import_module("agent_vis.api.app")
        _ = sample_codex_rollout_file
        settings = Settings(
            session_path=multi_session_directory,
            codex_session_path=codex_session_root,
            db_path=tmp_path / "mixed_overview_sources.db",
            api_host="127.0.0.1",
            api_port=8000,
            api_reload=False,
            log_level="INFO",
            cors_origins=["http://localhost:5173"],
        )

        get_settings.cache_clear()
        try:
            with patch.object(api_app_module, "get_settings", return_value=settings):
                with TestClient(app) as client:
                    response = client.get(
                        "/api/analytics/overview?start_date=2000-01-01&end_date=2100-12-31"
                    )
                    assert response.status_code == 200

                    payload = response.json()
                    source_breakdown = payload["source_breakdown"]
                    assert len(source_breakdown) >= 2
                    ecosystems = {row["ecosystem"] for row in source_breakdown}
                    assert "claude_code" in ecosystems
                    assert "codex" in ecosystems

                    for row in source_breakdown:
                        assert "label" in row
                        assert "sessions" in row
                        assert "total_tokens" in row
                        assert "total_tool_calls" in row
                        assert "active_time_seconds" in row
                        assert "percent_sessions" in row
                        assert "percent_tokens" in row
        finally:
            get_settings.cache_clear()

    def test_analytics_distribution_tool(self, test_client: TestClient) -> None:
        """Tool distribution endpoint should return bucketed results."""
        response = test_client.get(
            "/api/analytics/distributions?dimension=tool&start_date=2026-02-01&end_date=2026-02-10"
        )
        assert response.status_code == 200

        payload = response.json()
        assert payload["dimension"] == "tool"
        assert "buckets" in payload
        assert isinstance(payload["buckets"], list)

    def test_analytics_timeseries_weekly(self, test_client: TestClient) -> None:
        """Timeseries endpoint should support week aggregation."""
        response = test_client.get(
            "/api/analytics/timeseries?interval=week&start_date=2026-02-01&end_date=2026-02-10"
        )
        assert response.status_code == 200

        payload = response.json()
        assert payload["interval"] == "week"
        assert "points" in payload
        assert isinstance(payload["points"], list)

    def test_project_comparison_endpoint(self, test_client: TestClient) -> None:
        """Project comparison endpoint should return project KPI rows."""
        response = test_client.get(
            "/api/analytics/project-comparison?start_date=2026-02-01&end_date=2026-02-10&limit=5"
        )
        assert response.status_code == 200

        payload = response.json()
        assert "total_projects" in payload
        assert "projects" in payload
        assert isinstance(payload["projects"], list)
        if payload["projects"]:
            first = payload["projects"][0]
            assert "project_name" in first
            assert "sessions" in first
            assert "total_tokens" in first
            assert "active_ratio" in first
            assert "leverage_tokens_mean" in first
            assert "leverage_chars_mean" in first

    def test_project_swimlane_endpoint(self, test_client: TestClient) -> None:
        """Project swimlane endpoint should return period/project points."""
        response = test_client.get(
            "/api/analytics/project-swimlane?start_date=2026-02-01&end_date=2026-02-10"
            "&interval=day&project_limit=3"
        )
        assert response.status_code == 200

        payload = response.json()
        assert payload["interval"] == "day"
        assert "periods" in payload
        assert "projects" in payload
        assert "points" in payload
        assert "truncated_project_count" in payload
        assert isinstance(payload["points"], list)

    def test_analytics_invalid_date_range(self, test_client: TestClient) -> None:
        """Invalid date range should return HTTP 400."""
        response = test_client.get(
            "/api/analytics/overview?start_date=2026-02-10&end_date=2026-02-01"
        )
        assert response.status_code == 400

    def test_analytics_invalid_dimension(self, test_client: TestClient) -> None:
        """Invalid distribution dimension should return HTTP 422."""
        response = test_client.get("/api/analytics/distributions?dimension=invalid_dimension")
        assert response.status_code == 422


class TestSessionServiceIntegration:
    """Integration tests for SessionService."""

    @pytest.mark.asyncio
    async def test_service_initialization(
        self, multi_session_directory: Path, tmp_path: Path
    ) -> None:
        """Test that SessionService initializes correctly."""
        codex_session_dir = tmp_path / "codex_sessions_empty"
        codex_session_dir.mkdir(parents=True, exist_ok=True)
        service = SessionService(
            session_path=multi_session_directory,
            codex_session_path=codex_session_dir,
        )
        assert not service.is_initialized
        assert service.session_count == 0

        await service.initialize()
        assert service.is_initialized
        assert service.session_count > 0

    def test_service_list_sessions(self, initialized_session_service_sync: SessionService) -> None:
        """Test listing sessions through the service."""
        import asyncio

        sessions, total = asyncio.run(initialized_session_service_sync.list_sessions())
        assert len(sessions) > 0
        assert total > 0
        assert all(hasattr(s, "session_id") for s in sessions)
        assert all(hasattr(s, "total_messages") for s in sessions)

    def test_service_get_session(self, initialized_session_service_sync: SessionService) -> None:
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
        stats = asyncio.run(initialized_session_service_sync.get_session_statistics(session_id))
        assert stats is not None
        assert stats.message_count > 0
        assert stats.total_tokens >= 0

    def test_service_get_nonexistent_session(
        self, initialized_session_service_sync: SessionService
    ) -> None:
        """Test getting a non-existent session returns None."""
        import asyncio

        session = asyncio.run(initialized_session_service_sync.get_session("non-existent"))
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

    def test_day_night_window_boundaries(self) -> None:
        """Night window is [01:00, 09:00) in local clock time."""
        assert SessionService._is_night_local_clock(0, 59) is False
        assert SessionService._is_night_local_clock(1, 0) is True
        assert SessionService._is_night_local_clock(8, 59) is True
        assert SessionService._is_night_local_clock(9, 0) is False

    def test_split_day_night_span_boundaries(self) -> None:
        """Boundary split should classify pre-01:00 as day and 01:00+ as night."""
        local_tz = datetime.now().astimezone().tzinfo or timezone.utc
        start = datetime(2026, 2, 1, 0, 59, tzinfo=local_tz)
        day_seconds, night_seconds = SessionService._split_day_night_span(start, 120.0)

        assert day_seconds == pytest.approx(60.0)
        assert night_seconds == pytest.approx(60.0)

    @pytest.mark.asyncio
    async def test_analytics_overview_leverage_invalid_payload_fallback(
        self, tmp_path: Path
    ) -> None:
        """Malformed leverage source fields should not crash analytics aggregation."""
        service = SessionService(
            session_path=tmp_path / "claude",
            codex_session_path=tmp_path / "codex",
        )
        rows = [
            {
                "session_id": "bad-1",
                "project_path": "/tmp/project-a",
                "git_branch": "main",
                "created_at": "2026-02-03T10:00:00.000Z",
                "updated_at": "2026-02-03T10:10:00.000Z",
                "total_messages": 1,
                "total_tokens": 20,
                "total_tool_calls": 0,
                "duration_seconds": 600.0,
                "bottleneck": "Model",
                "automation_ratio": None,
                "statistics": {
                    "total_input_tokens": 0,
                    "total_output_tokens": 20,
                    "user_yield_ratio_tokens": "invalid",
                    "user_yield_ratio_chars": "invalid",
                    "character_breakdown": {
                        "total_chars": 30,
                        "user_chars": 0,
                        "model_chars": 30,
                        "tool_chars": 0,
                        "cjk_chars": 0,
                        "latin_chars": 30,
                        "other_chars": 0,
                    },
                    "tool_calls": [{"tool_name": "Read", "total_tokens": "invalid"}],
                    "time_breakdown": {
                        "total_model_time_seconds": 300.0,
                        "total_tool_time_seconds": 200.0,
                        "total_user_time_seconds": 100.0,
                        "total_inactive_time_seconds": 0.0,
                        "model_timeout_count": 0,
                    },
                },
            }
        ]
        service._get_analytics_rows = lambda *_: rows  # type: ignore[method-assign]

        payload = await service.get_analytics_overview("2026-02-01", "2026-02-10")
        assert payload.total_sessions == 1
        assert payload.total_tool_output_tokens == 0
        assert payload.leverage_tokens_mean == 0.0
        assert payload.leverage_chars_mean == 0.0
        assert payload.top_projects[0].leverage_tokens_mean is None
        assert payload.top_projects[0].leverage_chars_mean is None
        assert payload.control_plane.logical_sessions == 1
        assert payload.runtime_plane.total_tokens == 20


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
            # Path normalization may route malformed paths to list/static handlers.
            assert response.status_code in {200, 404}


class TestAPICORS:
    """Tests for CORS configuration."""

    def test_cors_headers_present(self, test_client: TestClient) -> None:
        """Test that CORS headers are present in responses."""
        response = test_client.get(
            "/api/sessions",
            headers={"Origin": "http://localhost:5173"},
        )
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
            stats_response = test_client.get(f"/api/sessions/{session_id}/statistics")
            assert stats_response.status_code == 200
            stats_data = stats_response.json()["statistics"]

            # Verify consistency
            assert session_data["metadata"]["total_messages"] == stats_data["message_count"]
            assert session_data["metadata"]["total_tokens"] == stats_data["total_tokens"]

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
            assert session_summary["total_messages"] == session_detail["metadata"]["total_messages"]
            assert session_summary["total_tokens"] == session_detail["metadata"]["total_tokens"]
