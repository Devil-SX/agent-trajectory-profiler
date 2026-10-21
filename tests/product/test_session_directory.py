"""Navigation reads cannot trigger ledger replay or retrieve full IR bodies."""

import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_overview_snapshot import batch
from test_session_metadata import seeded

from trajectory.product.semantic import SessionCursorExpired
from trajectory.product.semantic_runtime import AnalysisRuntime
from trajectory.product.server import Principal, create_app


def test_directory_filters_and_pages_without_overview_ir_or_get_migrations(tmp_path, monkeypatch):
    store, add = seeded(tmp_path)
    first, _ = add(1, "/repo/one", "first task", "2026-10-01")
    second, _ = add(2, "/repo/two", "second task", "2026-10-03")
    third, _ = add(3, "/repo/one/sub", "child task", "2026-10-02", parent="1")
    original = store.domain.connect

    def connect():
        db = original()

        def authorize(action, table, column, database, trigger):
            if action == sqlite3.SQLITE_READ and table == "semantic_sessions" and column == "body":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        db.set_authorizer(authorize)
        return db

    def forbidden(*args, **kwargs):
        raise AssertionError("Directory read attempted aggregate replay or metadata migration")

    monkeypatch.setattr(store.domain, "connect", connect)
    monkeypatch.setattr(store.domain, "_calculate_snapshot", forbidden)
    monkeypatch.setattr(store, "backfill_metadata", forbidden)
    allrows = store.sessions("owner", limit=1)
    assert allrows["metrics_included"] is False
    assert allrows["total"] == 3 and allrows["sessions"][0]["id"] == second
    assert "metrics" not in allrows["sessions"][0]
    assert (
        store.sessions("owner", limit=1, cursor=allrows["next_cursor"])["sessions"][0]["id"]
        == third
    )
    selected = store.sessions("owner", cwd="/repo/one", limit=1)
    assert selected["total"] == 2 and selected["sessions"][0]["id"] == third
    assert store.sessions("owner", q=first)["total"] == 2
    assert store.sessions("owner", until="2026-10-01")["sessions"][0]["id"] == first
    assert store.sessions("stranger")["sessions"] == []


def test_checkpoint_coverage_never_replays_usage_and_is_account_scoped(tmp_path, monkeypatch):
    def authorize(request, scope):
        token = request.headers.get("authorization", "")
        if token == "Bearer owner" and scope in {None, "read"}:
            return Principal("owner", scopes=("read",))
        if token == "Bearer stranger" and scope in {None, "read"}:
            return Principal("stranger", scopes=("read",))
        raise HTTPException(403, "Denied")

    app = create_app(tmp_path / "checkpoint.sqlite", authorize)
    domain = app.state.domain
    domain.register("owner", "machine", "fixture")
    domain.ingest("machine", batch(1, 10))

    def forbidden(*args, **kwargs):
        raise AssertionError("Checkpoint read attempted usage replay")

    monkeypatch.setattr(domain, "_calculate_snapshot", forbidden)
    client = TestClient(app)
    assert client.get("/trajectory/api/coverage").status_code == 403
    invalid = client.get(
        "/trajectory/api/sessions?cursor=bad", headers={"Authorization": "Bearer owner"}
    )
    assert invalid.status_code == 409
    assert invalid.json()["detail"]["code"] == "session_cursor_expired"
    value = client.get("/trajectory/api/coverage", headers={"Authorization": "Bearer owner"}).json()
    assert value["sources"] == 1 and value["read_bytes"] == value["source_bytes"] == 100
    assert value["unknown_timestamps"] == 0 and value["scope"] == "source_checkpoints"
    assert "deduplicated_usage_records" not in value
    other = client.get(
        "/trajectory/api/coverage", headers={"Authorization": "Bearer stranger"}
    ).json()
    assert other["sources"] == other["read_bytes"] == 0
    help_value = client.get("/trajectory/help", headers={"Authorization": "Bearer owner"}).json()
    assert any(tool["name"] == "source_coverage" for tool in help_value["tools"])


def test_old_metadata_is_migrated_by_idle_coordinator_and_not_directory_get(tmp_path, monkeypatch):
    store, add = seeded(tmp_path)
    sid, _ = add(1, "/repo/one", "original prompt", "2026-10-02")
    with store.domain.connect() as db:
        db.execute("DELETE FROM semantic_session_metadata")
    assert store.sessions("owner")["sessions"][0]["first_user_message"] is None
    monkeypatch.delenv("TRAJECTORY_WORKER_GATE", raising=False)
    monkeypatch.setattr(store, "claim_job", lambda: None)
    runtime = AnalysisRuntime(store)
    try:
        assert runtime.tick()
        row = store.sessions("owner")["sessions"][0]
        assert row["id"] == sid and row["first_user_message"] == "original prompt"
        assert not runtime.tick()
    finally:
        runtime.close()


def test_cursor_pins_metadata_snapshot_and_never_leaks_other_owner_or_scope(tmp_path):
    import pytest

    from trajectory.product.read_cache import RevisionCache
    from trajectory.product.semantic import SessionCursorExpired

    store, add = seeded(tmp_path)
    first, _ = add(1, "/repo/one", "first task", "2026-10-01")
    second, _ = add(2, "/repo/two", "second task", "2026-10-03")
    page = store.sessions("owner", limit=1)
    assert page["sessions"][0]["id"] == second
    add(3, "/repo/new", "new task", "2026-10-04")
    next_page = store.sessions("owner", limit=1, cursor=page["next_cursor"])
    assert next_page["sessions"][0]["id"] == first
    assert next_page["total"] == 2 and next_page["next_cursor"] is None
    assert next_page["listing_snapshot_id"] == page["listing_snapshot_id"]
    assert store.sessions("owner", limit=1)["total"] == 3
    with pytest.raises(SessionCursorExpired):
        store.sessions("other", limit=1, cursor=page["next_cursor"])
    with pytest.raises(SessionCursorExpired):
        store.sessions("owner", q="different", limit=1, cursor=page["next_cursor"])
    store._directory_cache = RevisionCache(max_bytes=16 * 1024**2, max_entries=1)
    with pytest.raises(SessionCursorExpired):
        store.sessions("owner", limit=1, cursor=page["next_cursor"])


def test_full_directory_facets_precede_pagination_cwd_and_follow_status(tmp_path):
    store, add = seeded(tmp_path)
    first, revision = add(1, "/repo/one", "task first", "2026-10-01")
    add(2, "/repo/one", "task second", "2026-10-03")
    add(3, "/repo/one/sub", "task child", "2026-10-02")
    missing, _ = add(4, None, "task unknown", "2026-10-04")
    page = store.sessions("owner", limit=1)
    assert page["directory_facets"] == [
        {"cwd": "/repo/one", "count": 2},
        {"cwd": "/repo/one/sub", "count": 1},
        {"cwd": None, "count": 1},
    ]
    following = store.sessions("owner", limit=1, cursor=page["next_cursor"])
    assert following["directory_facets"] == page["directory_facets"]
    scoped = store.sessions("owner", cwd="/repo/one", limit=1)
    assert scoped["total"] == 3 and scoped["directory_facets"] == page["directory_facets"]
    unknown = store.sessions("owner", cwd_presence="unknown", limit=1)
    assert unknown["total"] == 1 and unknown["sessions"][0]["id"] == missing
    assert unknown["directory_facets"] == page["directory_facets"]
    assert store.sessions("other")["directory_facets"] == []
    assert store.sessions("owner", q="second")["directory_facets"] == [
        {"cwd": "/repo/one", "count": 1}
    ]
    store.save_analysis("owner", first, revision, {"tasks": []})
    assert store.sessions("owner", analysis_status="analyzed")["directory_facets"] == [
        {"cwd": "/repo/one", "count": 1}
    ]
    with pytest.raises(ValueError):
        store.sessions("owner", cwd="/repo", cwd_presence="unknown")
    with pytest.raises(SessionCursorExpired):
        store.sessions("owner", limit=1, cursor=page["next_cursor"], cwd_presence="unknown")
