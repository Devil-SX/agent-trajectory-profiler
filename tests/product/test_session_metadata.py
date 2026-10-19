import base64
import hashlib
import json
import uuid
from pathlib import Path

import pytest

from trajectory.product.contracts import AnalysisRequest, SourceChunk
from trajectory.product.domain import Domain
from trajectory.product.semantic import SemanticStore, digest
from trajectory.product.session_metadata import extract


def seeded(tmp_path: Path):
    domain = Domain(tmp_path / "metadata.db")
    domain.register("owner", "machine", "fixture")
    store = SemanticStore(domain)

    def add(index, cwd, first, day, parent=None):
        raw = b'{"type":"fixture"}\n'
        src = hashlib.sha256(str(index).encode()).hexdigest()
        req = SourceChunk(
            schema_id="trajectory-source-chunk/1",
            mutation_id=uuid.uuid4().hex,
            collector="fixture",
            source=src,
            ecosystem="codex",
            generation="v1",
            start=0,
            end=len(raw),
            source_bytes=len(raw),
            content=base64.b64encode(raw).decode(),
            sha256=hashlib.sha256(raw).hexdigest(),
            source_name="session.jsonl",
        )
        sid = store.ingest_source("machine", req)["session_id"]
        source, _ = store.archive("owner", sid)
        revision = digest("v1:" + str(len(raw)))
        parsed = {
            "metadata": {
                "cwd": cwd,
                "native_session_id": str(index),
                "parent_session_id": parent,
                "started_at": day + "T01:00:00Z",
                "last_activity_at": day + "T02:00:00Z",
                "first_user_message": first,
                "abstract": None,
            },
            "operations": [{"id": "op" + str(index), "kind": "prompt", "text": first}],
        }
        store.save_session("owner", sid, source, revision, parsed)
        return sid, revision

    return store, add


def test_filters_use_real_analysis_and_original_dates_before_pagination(tmp_path):
    store, add = seeded(tmp_path)
    a, revision = add(1, "/home/sdu/embodied", "检查 CPM 实验", "2026-10-05")
    b, _ = add(2, "/home/sdu/BatCave", "维护网站", "2026-10-18")
    c, _ = add(3, "/home/sdu/embodied", "查看论文", "2026-10-07", parent="1")
    store.save_analysis(
        "owner",
        a,
        revision,
        {"tasks": [{"id": "root", "parent_id": None, "title": "测试", "operation_ids": ["op1"]}]},
    )
    result = store.sessions("owner", analysis_status="analyzed", limit=1)
    assert [r["id"] for r in result["sessions"]] == [a]
    assert result["total"] == 1 and result["status_counts"]["all"] == 3
    assert result["sessions"][0]["display_title"] == "检查 CPM 实验"
    assert result["sessions"][0]["summary"] is None
    result = store.sessions("owner", cwd="/home/sdu/embodied", limit=1)
    assert result["total"] == 2 and result["next_cursor"] == "1"
    assert result["sessions"][0]["id"] == c and result["sessions"][0]["parent_session_id"] == a
    assert (
        store.sessions("owner", cwd="/home/sdu/embodied", limit=1, cursor="1")["sessions"][0]["id"]
        == a
    )
    assert len(store.sessions("owner", until="2026-10-06")["sessions"]) == 1
    assert store.sessions("owner", q="网站")["sessions"][0]["id"] == b
    assert store.sessions("other")["sessions"] == []


def test_metadata_migration_uses_ir_and_preserves_analysis_status(tmp_path):
    store, add = seeded(tmp_path)
    sid, _ = add(1, "/home/sdu/embodied", "原始提示，不生成摘要", "2026-10-02")
    with store.domain.connect() as db:
        db.execute("DELETE FROM semantic_session_metadata")
    result = store.sessions("owner")
    assert result["sessions"][0]["id"] == sid
    assert result["sessions"][0]["has_analysis"] is False
    assert result["sessions"][0]["first_user_message"] == "原始提示，不生成摘要"
    assert result["sessions"][0]["started_at"].startswith("2026-10-02")
    assert store.backfill_metadata("owner") == 0


def test_unified_ir_fallback_skips_injected_instructions_and_reads_lineage():
    value = extract(
        {
            "source_records": [
                {
                    "timestamp_ms": 1791158400000,
                    "lineage": {
                        "id": "native",
                        "source": {
                            "subagent": {
                                "thread_spawn": {
                                    "parent_thread_id": "parent",
                                    "agent_path": "/root/task",
                                }
                            }
                        },
                    },
                }
            ],
            "operations": [
                {"kind": "prompt", "text": "# AGENTS.md instructions for test"},
                {"kind": "prompt", "text": "检查真实任务"},
            ],
        },
        "session.jsonl",
    )
    assert value["display_title"] == "检查真实任务" and value["native_session_id"] == "native"
    assert value["parent_native_session_id"] == "parent" and value["agent_path"] == "/root/task"
    assert value["cwd"] is None and value["summary"] is None


def test_parser_refresh_reuses_archive_and_invalidates_changed_membership(tmp_path):
    store, add = seeded(tmp_path)
    sid, revision = add(1, "/home/sdu/embodied", "任务", "2026-10-02")
    original_job = store.claim_job()
    assert original_job and original_job["kind"] == "parse"
    store.finish_job(original_job)
    store.save_analysis(
        "owner",
        sid,
        revision,
        {"tasks": [{"id": "root", "parent_id": None, "title": "任务", "operation_ids": ["op1"]}]},
    )
    request = AnalysisRequest(mutation_id=uuid.uuid4().hex)
    with pytest.raises(ValueError):
        store.request_parse("stranger", sid, request)
    receipt = store.request_parse("owner", sid, request)
    assert store.request_parse("owner", sid, request) == receipt
    assert receipt["job_id"] != original_job["id"]
    record = store.session_record("owner", sid)
    parsed = json.loads(record["body"])
    parsed["operations"][0]["id"] = "new-parser-op"
    source, _ = store.archive("owner", sid)
    store.save_session("owner", sid, source, revision, parsed)
    detail = store.detail("owner", sid)
    assert detail["status"] == "stale"
    assert detail["has_analysis"] and not detail["tasks"]
    analyze = store.request_analysis("owner", sid, AnalysisRequest(mutation_id=uuid.uuid4().hex))
    assert analyze["status"] == "queued"
    with pytest.raises(ValueError, match="active analysis"):
        store.request_parse("owner", sid, AnalysisRequest(mutation_id=uuid.uuid4().hex))


def test_four_http_metadata_backfills_with_wal_writer(tmp_path, monkeypatch):
    """Concurrent first reads migrate once without read-to-write WAL upgrades."""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient

    import trajectory.product.semantic as semantic
    from trajectory.product.server import Principal, create_app

    store, add = seeded(tmp_path)
    sessions = [add(i, "/research/embodied", f"原始任务 {i}", "2026-10-02")[0] for i in range(40)]
    with store.domain.connect() as db:
        db.execute("DELETE FROM semantic_session_metadata")
        db.execute("CREATE TABLE fixture_writer (value INTEGER)")
        db.execute("INSERT INTO fixture_writer VALUES(0)")
    original_extract = semantic.extract_metadata
    extracting = threading.Event()
    stop = threading.Event()
    writes = []

    def slow_extract(parsed, title):
        extracting.set()
        time.sleep(0.004)
        return original_extract(parsed, title)

    monkeypatch.setattr(semantic, "extract_metadata", slow_extract)
    app = create_app(store.domain.path, lambda request, scope: Principal("owner", scopes=("read",)))

    def writer():
        assert extracting.wait(5)
        while not stop.is_set():
            with store.domain.connect() as db:
                db.execute("UPDATE fixture_writer SET value=value+1")
            writes.append(True)
            time.sleep(0.001)

    barrier = threading.Barrier(4)

    def read_wave():
        barrier.wait(timeout=10)
        # Do not start four independent application lifespans (and worker runtimes).
        client = TestClient(app)
        try:
            response = client.get("/trajectory/api/sessions?analysis_status=analyzed&limit=100")
            assert response.status_code == 200, response.text
            assert response.json()["sessions"] == []
        finally:
            client.close()

    with ThreadPoolExecutor(max_workers=5) as pool:
        worker = pool.submit(writer)
        try:
            for _ in range(3):
                readers = [pool.submit(read_wave) for _ in range(4)]
                for reader in readers:
                    reader.result(timeout=30)
        finally:
            stop.set()
            worker.result(timeout=20)
    assert writes
    with store.domain.connect() as db:
        assert db.execute("SELECT value FROM fixture_writer").fetchone()[0] == len(writes)
        rows = db.execute("SELECT session,body FROM semantic_session_metadata").fetchall()
    assert {row["session"] for row in rows} == set(sessions)
    assert len(rows) == 40
    assert {json.loads(row["body"])["first_user_message"] for row in rows} == {
        f"原始任务 {i}" for i in range(40)
    }


def test_backfill_rechecks_parser_metadata_after_waiting_for_writer(tmp_path, monkeypatch):
    """A parser committed after candidate selection wins over legacy backfill."""
    store, add = seeded(tmp_path)
    sid, revision = add(1, "/old", "old", "2026-10-02")
    with store.domain.connect() as db:
        db.execute("DELETE FROM semantic_session_metadata")
    source, _ = store.archive("owner", sid)
    original_connect = store.domain.connect
    calls = 0

    def connect():
        nonlocal calls
        calls += 1
        # First connection finalizes IDs; second acquires the per-record write lock.
        if calls == 2:
            monkeypatch.setattr(store.domain, "connect", original_connect)
            store.save_session(
                "owner",
                sid,
                source,
                revision,
                {
                    "metadata": {"cwd": "/new", "first_user_message": "new parser metadata"},
                    "operations": [],
                },
            )
        return original_connect()

    monkeypatch.setattr(store.domain, "connect", connect)
    assert store.backfill_metadata("owner") == 0
    assert store.sessions("owner")["sessions"][0]["first_user_message"] == "new parser metadata"
