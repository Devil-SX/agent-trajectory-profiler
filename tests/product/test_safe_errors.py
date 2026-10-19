"""A swallowed HTTP failure remains diagnosable without logging private data."""

import json
import logging
from pathlib import Path

from fastapi.testclient import TestClient

from trajectory.product.error_logging import log_request_exception
from trajectory.product.server import Principal, create_app


def test_http_error_logs_locations_and_request_id_but_no_private_values(
    tmp_path: Path, monkeypatch, caplog
):
    def authorize(request, scope):
        return Principal("937c154a-010a-420a-af47-90b53d0cc28d", scopes=("read",))

    app = create_app(tmp_path / "isolated.sqlite", authorize)
    secret = "PRIVATE_TOKEN_AND_BUSINESS_CONTENT_MUST_NEVER_APPEAR"

    def failing_sessions(*args, **kwargs):
        local_sensitive_body = secret
        raise RuntimeError(local_sensitive_body)

    monkeypatch.setattr(app.state.semantic, "sessions", failing_sessions)
    with caplog.at_level(logging.ERROR, logger="trajectory.request_errors"):
        response = TestClient(app).get(
            "/trajectory/api/sessions?private_query=" + secret,
            headers={"Authorization": "Bearer " + secret},
        )
    assert response.status_code == 500
    assert secret not in response.text and secret not in caplog.text
    record = next(r for r in caplog.records if r.name == "trajectory.request_errors")
    assert record.exc_info is None
    logged = json.loads(record.getMessage().removeprefix("request_failure "))
    assert logged["request_id"] == response.json()["request_id"]
    assert len(logged["request_id"]) == 32
    assert any(
        error["type"] == "RuntimeError"
        and any(frame["function"] == "failing_sessions" for frame in error["frames"])
        for error in logged["exceptions"]
    )
    assert all(
        set(frame) == {"file", "function", "line"}
        for error in logged["exceptions"]
        for frame in error["frames"]
    )


def test_chained_exception_values_and_exception_groups_remain_private(caplog):
    secret = "NEVER_LOG_CAUSE_OR_GROUP_VALUES"
    try:
        try:
            raise ValueError(secret)
        except ValueError as cause:
            raise RuntimeError(secret) from cause
    except RuntimeError as error:
        with caplog.at_level(logging.ERROR, logger="trajectory.request_errors"):
            log_request_exception("0" * 32, ExceptionGroup(secret, [error]))
    assert secret not in caplog.text
    logged = json.loads(caplog.records[-1].getMessage().removeprefix("request_failure "))
    assert {item["type"] for item in logged["exceptions"]} == {
        "ExceptionGroup",
        "RuntimeError",
        "ValueError",
    }
    assert all(record.exc_info is None for record in caplog.records)


def test_real_sqlite_busy_snapshot_records_native_codes_not_sql(tmp_path, caplog):
    import sqlite3

    path = tmp_path / "fixture.sqlite"
    with sqlite3.connect(path) as initialize:
        initialize.execute("PRAGMA journal_mode=WAL")
        initialize.execute("CREATE TABLE fixture(value TEXT)")
    reader = sqlite3.connect(path)
    reader.execute("BEGIN")
    reader.execute("SELECT * FROM fixture").fetchall()
    with sqlite3.connect(path) as writer:
        writer.execute("INSERT INTO fixture VALUES('private fixture contents')")
    try:
        reader.execute("INSERT INTO fixture VALUES('private SQL must not be logged')")
    except sqlite3.OperationalError as error:
        with caplog.at_level(logging.ERROR, logger="trajectory.request_errors"):
            log_request_exception("1" * 32, error)
    else:
        raise AssertionError("Expected SQLite read-to-write snapshot conflict")
    finally:
        reader.close()
    logged = json.loads(caplog.records[-1].getMessage().removeprefix("request_failure "))
    entry = logged["exceptions"][0]
    assert entry["sqlite_errorcode"] == sqlite3.SQLITE_BUSY_SNAPSHOT
    assert entry["sqlite_errorname"] == "SQLITE_BUSY_SNAPSHOT"
    assert "private" not in caplog.text and "database is locked" not in caplog.text
