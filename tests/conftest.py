"""
Pytest configuration and shared fixtures for integration tests.

This module provides reusable test fixtures for session data,
API testing, and integration testing scenarios.
"""

import json
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from claude_vis.api.app import app
from claude_vis.api.config import Settings, get_settings
from claude_vis.api.service import SessionService


@pytest.fixture
def temp_session_dir(tmp_path: Path) -> Path:
    """Create a temporary session directory for testing."""
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    return session_dir


@pytest.fixture
def sample_user_message() -> dict[str, object]:
    """Create a sample user message."""
    return {
        "type": "user",
        "sessionId": "test-session-001",
        "uuid": "msg-user-001",
        "timestamp": "2026-02-03T13:15:17.231Z",
        "userType": "external",
        "cwd": "/home/user/project",
        "version": "2.1.29",
        "gitBranch": "main",
        "isSidechain": False,
        "message": {
            "role": "user",
            "content": "Hello Claude, can you help me?",
        },
    }


@pytest.fixture
def sample_assistant_message() -> dict[str, object]:
    """Create a sample assistant message with tool usage."""
    return {
        "type": "assistant",
        "sessionId": "test-session-001",
        "uuid": "msg-assistant-001",
        "timestamp": "2026-02-03T13:15:20.531Z",
        "userType": "external",
        "cwd": "/home/user/project",
        "version": "2.1.29",
        "gitBranch": "main",
        "isSidechain": False,
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Of course! Let me read that file."},
                {
                    "type": "tool_use",
                    "id": "tool-read-001",
                    "name": "Read",
                    "input": {"file_path": "/test.py"},
                },
            ],
            "model": "claude-opus-4-5-20251101",
            "usage": {
                "input_tokens": 120,
                "output_tokens": 60,
            },
        },
    }


@pytest.fixture
def sample_tool_result_message() -> dict[str, object]:
    """Create a sample tool result message."""
    return {
        "type": "user",
        "sessionId": "test-session-001",
        "uuid": "msg-tool-result-001",
        "timestamp": "2026-02-03T13:15:21.231Z",
        "userType": "external",
        "cwd": "/home/user/project",
        "version": "2.1.29",
        "gitBranch": "main",
        "isSidechain": False,
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool-read-001",
                    "content": "print('Hello, World!')",
                    "is_error": False,
                }
            ],
        },
    }


@pytest.fixture
def sample_complete_session(
    sample_user_message: dict[str, object],
    sample_assistant_message: dict[str, object],
    sample_tool_result_message: dict[str, object],
) -> list[dict[str, object]]:
    """Create a complete sample session with multiple messages."""
    return [
        sample_user_message,
        sample_assistant_message,
        sample_tool_result_message,
        {
            "type": "assistant",
            "sessionId": "test-session-001",
            "uuid": "msg-assistant-002",
            "timestamp": "2026-02-03T13:15:25.231Z",
            "userType": "external",
            "cwd": "/home/user/project",
            "version": "2.1.29",
            "gitBranch": "main",
            "isSidechain": False,
            "message": {
                "role": "assistant",
                "content": "I can see the file contains a simple print statement.",
                "model": "claude-opus-4-5-20251101",
                "usage": {
                    "input_tokens": 150,
                    "output_tokens": 40,
                    "cache_read_input_tokens": 80,
                },
            },
        },
    ]


@pytest.fixture
def sample_session_with_subagents() -> list[dict[str, object]]:
    """Create a sample session with subagent messages."""
    return [
        {
            "type": "user",
            "sessionId": "test-session-002",
            "uuid": "msg-user-001",
            "timestamp": "2026-02-03T14:00:00.000Z",
            "userType": "external",
            "cwd": "/home/user/project",
            "version": "2.1.29",
            "gitBranch": "develop",
            "isSidechain": False,
            "message": {
                "role": "user",
                "content": "Explore the codebase structure",
            },
        },
        {
            "type": "assistant",
            "sessionId": "test-session-002",
            "uuid": "msg-subagent-001",
            "timestamp": "2026-02-03T14:00:01.000Z",
            "userType": "external",
            "cwd": "/home/user/project",
            "version": "2.1.29",
            "gitBranch": "develop",
            "isSidechain": True,
            "agentId": "aprompt_explore-agent-123",
            "parentUuid": "msg-user-001",
            "message": {
                "role": "assistant",
                "content": "Starting codebase exploration...",
                "usage": {"input_tokens": 50, "output_tokens": 25},
            },
        },
        {
            "type": "assistant",
            "sessionId": "test-session-002",
            "uuid": "msg-subagent-002",
            "timestamp": "2026-02-03T14:00:05.000Z",
            "userType": "external",
            "cwd": "/home/user/project",
            "version": "2.1.29",
            "gitBranch": "develop",
            "isSidechain": True,
            "agentId": "aprompt_explore-agent-123",
            "parentUuid": "msg-user-001",
            "message": {
                "role": "assistant",
                "content": "Found 15 Python files in the project.",
                "usage": {"input_tokens": 75, "output_tokens": 35},
            },
        },
        {
            "type": "assistant",
            "sessionId": "test-session-002",
            "uuid": "msg-assistant-001",
            "timestamp": "2026-02-03T14:00:10.000Z",
            "userType": "external",
            "cwd": "/home/user/project",
            "version": "2.1.29",
            "gitBranch": "develop",
            "isSidechain": False,
            "message": {
                "role": "assistant",
                "content": "I've explored the codebase. Here are the findings...",
                "usage": {"input_tokens": 200, "output_tokens": 100},
            },
        },
    ]


@pytest.fixture
def sample_session_file(
    temp_session_dir: Path, sample_complete_session: list[dict[str, object]]
) -> Path:
    """Create a sample JSONL session file."""
    session_file = temp_session_dir / "test-session-001.jsonl"
    with open(session_file, "w", encoding="utf-8") as f:
        for message in sample_complete_session:
            f.write(json.dumps(message) + "\n")
    return session_file


@pytest.fixture
def sample_session_file_with_subagents(
    temp_session_dir: Path, sample_session_with_subagents: list[dict[str, object]]
) -> Path:
    """Create a sample JSONL session file with subagents."""
    session_file = temp_session_dir / "test-session-002.jsonl"
    with open(session_file, "w", encoding="utf-8") as f:
        for message in sample_session_with_subagents:
            f.write(json.dumps(message) + "\n")
    return session_file


@pytest.fixture
def multi_session_directory(
    temp_session_dir: Path,
    sample_complete_session: list[dict[str, object]],
    sample_session_with_subagents: list[dict[str, object]],
) -> Path:
    """Create a directory with multiple session files."""
    # Create first session file
    session_file_1 = temp_session_dir / "test-session-001.jsonl"
    with open(session_file_1, "w", encoding="utf-8") as f:
        for message in sample_complete_session:
            f.write(json.dumps(message) + "\n")

    # Create second session file
    session_file_2 = temp_session_dir / "test-session-002.jsonl"
    with open(session_file_2, "w", encoding="utf-8") as f:
        for message in sample_session_with_subagents:
            f.write(json.dumps(message) + "\n")

    # Create third session file with different data
    session_file_3 = temp_session_dir / "test-session-003.jsonl"
    with open(session_file_3, "w", encoding="utf-8") as f:
        for message in sample_complete_session:
            # Modify session ID for uniqueness
            modified_message = message.copy()
            modified_message["sessionId"] = "test-session-003"
            f.write(json.dumps(modified_message) + "\n")

    return temp_session_dir


@pytest.fixture
def test_settings(temp_session_dir: Path) -> Settings:
    """Create test settings with temporary session directory."""
    return Settings(
        session_path=temp_session_dir,
        api_host="127.0.0.1",
        api_port=8000,
        api_reload=False,
        log_level="INFO",
        cors_origins=["http://localhost:5173"],
    )


@pytest.fixture
def session_service(multi_session_directory: Path) -> SessionService:
    """Create a SessionService instance with test data."""
    service = SessionService(session_path=multi_session_directory)
    return service


@pytest.fixture
def initialized_session_service_sync(
    multi_session_directory: Path,
) -> SessionService:
    """Create and initialize a SessionService instance with test data (sync version for testing)."""
    import asyncio

    service = SessionService(session_path=multi_session_directory)
    # Run initialization synchronously for testing
    asyncio.run(service.initialize())
    return service


@pytest.fixture
def test_client(
    test_settings: Settings, multi_session_directory: Path
) -> Generator[TestClient, None, None]:
    """Create a FastAPI test client with test settings."""

    # Override settings
    def override_get_settings() -> Settings:
        return test_settings

    app.dependency_overrides[get_settings] = override_get_settings

    # Use TestClient with lifespan context
    with TestClient(app) as client:
        yield client

    # Clean up
    app.dependency_overrides.clear()
