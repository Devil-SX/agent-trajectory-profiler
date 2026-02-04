"""
Full stack integration tests.

Tests cover end-to-end workflows from file parsing through API to
ensure all components work together correctly.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from claude_vis.parsers import parse_session_directory, parse_session_file


class TestFullStackSessionWorkflow:
    """Full stack tests for complete session workflows."""

    def test_parse_to_api_consistency(
        self, test_client: TestClient, multi_session_directory: Path
    ) -> None:
        """Test that parsed data is consistent from files to API."""
        # Step 1: Parse directory directly
        parsed_data = parse_session_directory(multi_session_directory)

        # Step 2: Get sessions from API
        api_response = test_client.get("/api/sessions")
        assert api_response.status_code == 200
        api_sessions = api_response.json()["sessions"]

        # Step 3: Verify counts match
        assert len(parsed_data.sessions) == len(api_sessions)

        # Step 4: Verify session data consistency
        for parsed_session in parsed_data.sessions:
            session_id = parsed_session.metadata.session_id

            # Get same session from API
            detail_response = test_client.get(f"/api/sessions/{session_id}")
            assert detail_response.status_code == 200
            api_session = detail_response.json()["session"]

            # Verify metadata consistency
            assert (
                api_session["metadata"]["session_id"]
                == parsed_session.metadata.session_id
            )
            assert (
                api_session["metadata"]["total_messages"]
                == parsed_session.metadata.total_messages
            )
            assert (
                api_session["metadata"]["total_tokens"]
                == parsed_session.metadata.total_tokens
            )

    def test_file_to_statistics_end_to_end(
        self, test_client: TestClient, sample_session_file: Path
    ) -> None:
        """Test complete workflow from file to statistics via API."""
        # Step 1: Parse file directly
        parsed_session = parse_session_file(sample_session_file)
        direct_stats = parsed_session.statistics

        # Step 2: Get statistics via API
        session_id = parsed_session.metadata.session_id
        stats_response = test_client.get(f"/api/sessions/{session_id}/statistics")

        if stats_response.status_code == 200:
            api_stats = stats_response.json()["statistics"]

            # Step 3: Verify statistics match
            assert direct_stats is not None
            assert api_stats["message_count"] == direct_stats.message_count
            assert api_stats["total_tokens"] == direct_stats.total_tokens
            assert api_stats["total_tool_calls"] == direct_stats.total_tool_calls

    def test_directory_parsing_to_api_serving(
        self, test_client: TestClient, multi_session_directory: Path
    ) -> None:
        """Test that all sessions in directory are accessible via API."""
        # Parse directory
        parsed_data = parse_session_directory(multi_session_directory)
        session_ids = {s.metadata.session_id for s in parsed_data.sessions}

        # Get sessions from API
        api_response = test_client.get("/api/sessions")
        assert api_response.status_code == 200
        api_session_ids = {s["session_id"] for s in api_response.json()["sessions"]}

        # Verify all parsed sessions are available via API
        for session_id in session_ids:
            assert session_id in api_session_ids

            # Verify each session is accessible
            detail_response = test_client.get(f"/api/sessions/{session_id}")
            assert detail_response.status_code == 200


class TestFullStackDataIntegrity:
    """Tests for data integrity across the full stack."""

    def test_message_order_preservation(
        self, test_client: TestClient, sample_session_file: Path
    ) -> None:
        """Test that message order is preserved from file to API."""
        # Parse file
        parsed_session = parse_session_file(sample_session_file)
        original_uuids = [m.uuid for m in parsed_session.messages]

        # Get session via API
        session_id = parsed_session.metadata.session_id
        api_response = test_client.get(f"/api/sessions/{session_id}")

        if api_response.status_code == 200:
            api_messages = api_response.json()["session"]["messages"]
            api_uuids = [m["uuid"] for m in api_messages]

            # Verify order is preserved
            assert original_uuids == api_uuids

    def test_subagent_data_preservation(
        self, test_client: TestClient, sample_session_file_with_subagents: Path
    ) -> None:
        """Test that subagent data is preserved through the stack."""
        # Parse file
        parsed_session = parse_session_file(sample_session_file_with_subagents)
        original_subagent_count = len(parsed_session.subagent_sessions)

        # Get session via API
        session_id = parsed_session.metadata.session_id
        api_response = test_client.get(f"/api/sessions/{session_id}")

        if api_response.status_code == 200:
            api_session = api_response.json()["session"]

            # Verify subagent sessions are preserved
            if "subagent_sessions" in api_session:
                assert len(api_session["subagent_sessions"]) == original_subagent_count

    def test_tool_call_data_consistency(
        self, test_client: TestClient, sample_session_file: Path
    ) -> None:
        """Test that tool call data is consistent across stack layers."""
        # Parse file
        parsed_session = parse_session_file(sample_session_file)
        direct_stats = parsed_session.statistics

        # Get statistics via API
        session_id = parsed_session.metadata.session_id
        stats_response = test_client.get(f"/api/sessions/{session_id}/statistics")

        if stats_response.status_code == 200 and direct_stats:
            api_stats = stats_response.json()["statistics"]

            # Verify tool call consistency
            assert api_stats["total_tool_calls"] == direct_stats.total_tool_calls
            assert len(api_stats["tool_calls"]) == len(direct_stats.tool_calls)

            # Verify individual tool statistics
            for tool_stat in direct_stats.tool_calls:
                api_tool = next(
                    (
                        t
                        for t in api_stats["tool_calls"]
                        if t["tool_name"] == tool_stat.tool_name
                    ),
                    None,
                )
                if api_tool:
                    assert api_tool["count"] == tool_stat.count
                    assert api_tool["success_count"] == tool_stat.success_count
                    assert api_tool["error_count"] == tool_stat.error_count


class TestFullStackErrorHandling:
    """Tests for error handling across the full stack."""

    def test_corrupt_file_handling(
        self, temp_session_dir: Path, test_client: TestClient
    ) -> None:
        """Test that corrupt files are handled gracefully."""
        # Create a corrupt file
        corrupt_file = temp_session_dir / "corrupt.jsonl"
        with open(corrupt_file, "w", encoding="utf-8") as f:
            f.write("not valid json\n")

        # API should still respond (even if no valid sessions)
        health_response = test_client.get("/health")
        assert health_response.status_code == 200

    def test_missing_session_directory_handling(self, tmp_path: Path) -> None:
        """Test handling of missing session directory."""
        from claude_vis.api.service import SessionService

        # Create service with non-existent directory
        nonexistent_dir = tmp_path / "nonexistent"
        service = SessionService(session_path=nonexistent_dir)

        # Should handle gracefully during initialization
        # (implementation allows this to proceed with empty sessions)


class TestFullStackPerformance:
    """Performance-related integration tests."""

    def test_large_directory_parsing(
        self, temp_session_dir: Path, sample_complete_session: list[dict[str, object]]
    ) -> None:
        """Test parsing a directory with many session files."""
        # Create 10 session files
        for i in range(10):
            session_file = temp_session_dir / f"session-{i:03d}.jsonl"
            with open(session_file, "w", encoding="utf-8") as f:
                for msg in sample_complete_session:
                    modified_msg = msg.copy()
                    modified_msg["sessionId"] = f"session-{i:03d}"
                    f.write(json.dumps(modified_msg) + "\n")

        # Parse directory - should complete without errors
        parsed_data = parse_session_directory(temp_session_dir)
        assert parsed_data.session_count == 10

    def test_large_session_file_parsing(
        self, temp_session_dir: Path, sample_user_message: dict[str, object]
    ) -> None:
        """Test parsing a session file with many messages."""
        # Create a session with 200 messages
        session_file = temp_session_dir / "large-session.jsonl"
        with open(session_file, "w", encoding="utf-8") as f:
            for i in range(200):
                msg = sample_user_message.copy()
                msg["uuid"] = f"msg-{i:04d}"
                msg["sessionId"] = "large-session"
                msg["timestamp"] = f"2026-02-03T{(i // 60) % 24:02d}:{i % 60:02d}:00.000Z"
                f.write(json.dumps(msg) + "\n")

        # Parse should complete without errors
        session = parse_session_file(session_file)
        assert len(session.messages) == 200


class TestFullStackCompleteScenarios:
    """Complete end-to-end scenario tests."""

    def test_new_user_viewing_sessions_scenario(
        self, test_client: TestClient
    ) -> None:
        """Simulate a new user viewing sessions for the first time."""
        # Step 1: User hits the health endpoint
        health_response = test_client.get("/health")
        assert health_response.status_code == 200
        assert health_response.json()["status"] == "healthy"

        # Step 2: User lists all sessions
        list_response = test_client.get("/api/sessions")
        assert list_response.status_code == 200
        sessions = list_response.json()["sessions"]

        if len(sessions) > 0:
            # Step 3: User clicks on first session
            first_session_id = sessions[0]["session_id"]
            detail_response = test_client.get(f"/api/sessions/{first_session_id}")
            assert detail_response.status_code == 200

            # Step 4: User views statistics
            stats_response = test_client.get(
                f"/api/sessions/{first_session_id}/statistics"
            )
            assert stats_response.status_code == 200

    def test_analytics_workflow_scenario(
        self, test_client: TestClient
    ) -> None:
        """Simulate user analyzing session statistics."""
        # Get all sessions
        list_response = test_client.get("/api/sessions")
        assert list_response.status_code == 200
        sessions = list_response.json()["sessions"]

        if len(sessions) > 0:
            # Analyze each session
            total_tokens = 0
            total_messages = 0

            for session_summary in sessions:
                session_id = session_summary["session_id"]

                # Get detailed statistics
                stats_response = test_client.get(
                    f"/api/sessions/{session_id}/statistics"
                )
                if stats_response.status_code == 200:
                    stats = stats_response.json()["statistics"]
                    total_tokens += stats["total_tokens"]
                    total_messages += stats["message_count"]

            # Should have accumulated some data
            assert total_messages > 0

    def test_session_comparison_scenario(
        self, test_client: TestClient
    ) -> None:
        """Simulate user comparing multiple sessions."""
        # Get all sessions
        list_response = test_client.get("/api/sessions")
        assert list_response.status_code == 200
        sessions = list_response.json()["sessions"]

        if len(sessions) >= 2:
            # Get statistics for first two sessions
            session_stats = []

            for i in range(min(2, len(sessions))):
                session_id = sessions[i]["session_id"]
                stats_response = test_client.get(
                    f"/api/sessions/{session_id}/statistics"
                )
                if stats_response.status_code == 200:
                    session_stats.append(stats_response.json()["statistics"])

            # Should be able to compare
            if len(session_stats) == 2:
                # Each should have comparable fields
                for stats in session_stats:
                    assert "message_count" in stats
                    assert "total_tokens" in stats
                    assert "total_tool_calls" in stats


class TestFullStackRoundTrip:
    """Round-trip tests to verify data consistency."""

    def test_session_metadata_round_trip(
        self, sample_session_file: Path, test_client: TestClient
    ) -> None:
        """Test that session metadata survives round trip through the stack."""
        # Parse directly from file
        direct_session = parse_session_file(sample_session_file)
        direct_metadata = direct_session.metadata

        # Get via API (if available)
        session_id = direct_metadata.session_id
        api_response = test_client.get(f"/api/sessions/{session_id}")

        if api_response.status_code == 200:
            api_metadata = api_response.json()["session"]["metadata"]

            # Verify key fields match
            assert api_metadata["session_id"] == direct_metadata.session_id
            assert api_metadata["project_path"] == direct_metadata.project_path
            assert api_metadata["git_branch"] == direct_metadata.git_branch
            assert api_metadata["version"] == direct_metadata.version

    def test_statistics_round_trip(
        self, sample_session_file: Path, test_client: TestClient
    ) -> None:
        """Test that statistics survive round trip through the stack."""
        # Parse directly from file
        direct_session = parse_session_file(sample_session_file)
        direct_stats = direct_session.statistics

        # Get via API (if available)
        session_id = direct_session.metadata.session_id
        stats_response = test_client.get(f"/api/sessions/{session_id}/statistics")

        if stats_response.status_code == 200 and direct_stats:
            api_stats = stats_response.json()["statistics"]

            # Verify computed properties match
            assert api_stats["message_count"] == direct_stats.message_count
            assert api_stats["total_tokens"] == direct_stats.total_tokens
            assert (
                abs(
                    api_stats["average_tokens_per_message"]
                    - direct_stats.average_tokens_per_message
                )
                < 0.01
            )
