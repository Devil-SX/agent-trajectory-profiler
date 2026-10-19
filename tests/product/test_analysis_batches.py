"""Durable, account-owned batch scheduling and actual bounded concurrency."""

import json
import threading
import time
import uuid
from pathlib import Path

import pytest

from trajectory.product.contracts import AnalysisBatchRequest, AnalysisRequest
from trajectory.product.domain import Domain
from trajectory.product.semantic import SemanticStore
from trajectory.product.semantic_runtime import AnalysisRuntime


def seeded(tmp_path: Path, count=5):
    store = SemanticStore(Domain(tmp_path / "db.sqlite"))
    ids = [f"session-{i}" for i in range(count)]
    with store.domain.connect() as db:
        for sid in ids:
            db.execute(
                "INSERT INTO semantic_sessions VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    "owner",
                    sid,
                    "collector",
                    sid,
                    sid,
                    "codex",
                    "revision",
                    json.dumps({"session": {}, "operations": []}),
                    "2026-10-19T00:00:00+00:00",
                ),
            )
    return store, ids


def request(ids, concurrency=2, mutation_id=None):
    return AnalysisBatchRequest(
        session_ids=ids, concurrency=concurrency, mutation_id=mutation_id or uuid.uuid4().hex
    )


def test_batch_replay_atomic_isolation_and_shared_queue(tmp_path):
    store, ids = seeded(tmp_path)
    value = request(ids + [ids[0]])
    receipt = store.request_batch("owner", value)
    assert store.request_batch("owner", value) == receipt
    batch_id = receipt["batch_id"]
    detail = store.batch_detail("owner", batch_id)
    assert detail["counts"] == {"queued": 5, "running": 0, "complete": 0, "failed": 0}
    assert detail["total"] == 5
    assert detail["items"][0]["analysis_cost"] is None
    with pytest.raises(PermissionError):
        store.batch_detail("stranger", batch_id)
    assert store.batches("stranger") == {"batches": []}
    with pytest.raises(ValueError):
        store.request_batch("stranger", request(ids))
    with pytest.raises(ValueError):
        store.request_batch("owner", request(ids + ["missing"]))
    assert len(store.batches("owner")["batches"]) == 1
    with pytest.raises(ValueError):
        store.request_batch("owner", request(ids[:1], mutation_id=value.mutation_id))
    single = store.request_analysis("owner", ids[0], AnalysisRequest(mutation_id=uuid.uuid4().hex))
    assert (
        single["job_id"] == next(i for i in detail["items"] if i["session_id"] == ids[0])["job_id"]
    )
    first = store.claim_job()
    second = store.claim_job()
    assert first and second and store.claim_job() is None
    duplicate = store.request_batch("owner", request(ids))
    assert {x["job_id"] for x in duplicate["items"]} == {x["job_id"] for x in receipt["items"]}
    store.job_progress(
        first,
        {"completed_chunks": 1, "total_chunks": 3, "analysis_usage": [{"usage": {"input": 5}}]},
    )
    store.finish_job(first, "explicit failure")
    detail = store.batch_detail("owner", batch_id)
    item = next(i for i in detail["items"] if i["job_id"] == first["id"])
    assert item["last_error"] == "explicit failure"
    assert item["elapsed_seconds"] >= 0
    assert item["progress"]["completed_chunks"] == 1
    assert item["analysis_usage"] == [{"usage": {"input": 5}}]
    assert store.claim_job()


def test_real_bounded_pool_exclusive_lease_and_natural_drain(tmp_path, monkeypatch):
    store, ids = seeded(tmp_path, 6)
    gate = tmp_path / "gate"
    gate.touch()
    monkeypatch.setenv("TRAJECTORY_WORKER_GATE", str(gate))
    monkeypatch.setenv("TRAJECTORY_ANALYSIS_CONCURRENCY", "4")
    store.request_batch("owner", request(ids, concurrency=2))
    runtime = AnalysisRuntime(store)
    competitor = AnalysisRuntime(store)
    release = threading.Event()
    lock = threading.Lock()
    counts = {"active": 0, "maximum": 0}

    def work(job):
        with lock:
            counts["active"] += 1
            counts["maximum"] = max(counts["maximum"], counts["active"])
        release.wait(5)
        store.finish_job(job)
        with lock:
            counts["active"] -= 1
        return True

    monkeypatch.setattr(runtime, "_process_job", work)
    assert runtime.tick()
    deadline = time.monotonic() + 3
    while counts["active"] < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert counts["active"] == 2
    assert not competitor.tick()
    assert counts["maximum"] == 2
    gate.unlink()
    assert not runtime.tick()
    assert not competitor.tick()
    release.set()
    deadline = time.monotonic() + 3
    while counts["active"] and time.monotonic() < deadline:
        time.sleep(0.01)
    runtime.tick()
    assert runtime.lease is None
    gate.touch()
    monkeypatch.setattr(competitor, "_process_job", work)
    assert competitor.tick()
    runtime.close()
    competitor.close()
    assert counts["maximum"] <= 2


def test_interrupted_job_recovers_same_stable_identity_only_after_lease(tmp_path, monkeypatch):
    store, ids = seeded(tmp_path, 1)
    result = store.request_batch("owner", request(ids))
    job = store.claim_job()
    assert job
    worker = AnalysisRuntime(store)
    other = AnalysisRuntime(store)
    assert worker._coordinate()
    with store.domain.connect() as db:
        recovered = db.execute(
            "SELECT status FROM semantic_jobs WHERE id=?", (job["id"],)
        ).fetchone()[0]
    assert recovered == "queued"
    active = store.claim_job()
    assert active["id"] == result["items"][0]["job_id"]
    assert not other._coordinate()
    with store.domain.connect() as db:
        assert (
            db.execute("SELECT status FROM semantic_jobs WHERE id=?", (job["id"],)).fetchone()[0]
            == "running"
        )
    worker.close()
    assert other._coordinate()
    assert store.claim_job()["id"] == active["id"]
    other.close()


def test_uncertain_call_cannot_be_resubmitted_with_a_new_paid_identity(tmp_path):
    store, ids = seeded(tmp_path, 1)
    store.request_batch("owner", request(ids))
    job = store.claim_job()
    store.finish_job(job, "Jindu call failed or result uncertain; reconcile call ID before retry")
    with pytest.raises(ValueError, match="reconcile"):
        store.request_batch("owner", request(ids))
    with pytest.raises(ValueError, match="reconcile"):
        store.request_analysis("owner", ids[0], AnalysisRequest(mutation_id=uuid.uuid4().hex))


def test_execution_model_route_effort_and_source_are_pinned(tmp_path):
    store, ids = seeded(tmp_path, 1)
    store.request_batch("owner", request(ids))
    job = store.claim_job()
    identity = {
        "model": "glm-5.3",
        "route": "zai-glm-5-3",
        "reasoning_effort": "high",
        "source_revision": "revision",
        "prompt_version": "v1",
    }
    store.pin_execution(job, identity)
    store.pin_execution(job, identity)
    for key in identity:
        with pytest.raises(ValueError, match="configuration changed"):
            store.pin_execution(job, {**identity, key: "changed"})


def test_batch_http_help_schema_permissions_and_account_isolation(tmp_path):
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    from trajectory.product.server import Principal, create_app

    store, ids = seeded(tmp_path, 2)

    def authorize(request, scope):
        actor = request.headers.get("authorization", "").removeprefix("Bearer ")
        if actor == "owner" or actor == "other" and scope in {None, "read", "configure"}:
            return Principal(actor, scopes=("read", "configure"))
        raise HTTPException(403, "Denied")

    app = create_app(store.domain.path, authorize)
    client = TestClient(app)
    base = "/trajectory/api/analysis-batches"
    body = request(ids).model_dump()
    assert client.post(base, json=body).status_code == 403
    response = client.post(base, json=body, headers={"Authorization": "Bearer owner"})
    assert response.status_code == 200, response.text
    assert (
        client.post(base, json=body, headers={"Authorization": "Bearer owner"}).json()
        == response.json()
    )
    batch_id = response.json()["batch_id"]
    assert (
        client.get(base + "/" + batch_id, headers={"Authorization": "Bearer owner"}).json()["total"]
        == 2
    )
    assert (
        client.get(base + "/" + batch_id, headers={"Authorization": "Bearer other"}).status_code
        == 403
    )
    assert client.get(base, headers={"Authorization": "Bearer other"}).json() == {"batches": []}
    assert (
        client.post(
            base, json={**body, "concurrency": 0}, headers={"Authorization": "Bearer owner"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            base, json={**body, "concurrency": 8}, headers={"Authorization": "Bearer owner"}
        ).status_code
        == 409
    )
    help_doc = client.get("/trajectory/help", headers={"Authorization": "Bearer owner"})
    assert help_doc.status_code == 200
    operation = next(op for op in help_doc.json()["tools"] if op["name"] == "analysis_batch_run")
    assert "session_ids" in operation["input_schema"]["properties"]
