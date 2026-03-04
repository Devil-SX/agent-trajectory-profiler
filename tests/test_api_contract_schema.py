"""Regression tests for backend OpenAPI contract fields used by frontend type generation."""

from agent_vis.api.app import app


def _schema() -> dict:
    return app.openapi()


def test_session_detail_schema_contains_subagent_and_statistics() -> None:
    schema = _schema()
    session_schema = schema["components"]["schemas"]["Session"]
    props = session_schema["properties"]
    assert "subagent_sessions" in props
    assert "statistics" in props


def test_tool_error_record_schema_contains_extended_fields() -> None:
    schema = _schema()
    tool_error_schema = schema["components"]["schemas"]["ToolErrorRecord"]
    props = tool_error_schema["properties"]
    assert "tool_call_id" in props
    assert "summary" in props
    assert "detail_snippet" in props


def test_subagent_type_schema_contains_aprompt_suggestion() -> None:
    schema = _schema()
    subagent_type_schema = schema["components"]["schemas"]["SubagentType"]
    assert "aprompt_suggestion" in subagent_type_schema["enum"]
