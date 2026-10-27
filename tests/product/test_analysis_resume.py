"""Resume authorization preserves paid prefixes and never masks uncertain calls."""

import json
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_analysis_batches import request, seeded

from trajectory.product import semantic_model
from trajectory.product.contracts import AnalysisRequest
from trajectory.product.semantic import AnalysisResumeError
from trajectory.product.semantic_runtime import AnalysisRuntime
from trajectory.product.server import Principal, create_app


def failed_job(tmp_path, monkeypatch):
    monkeypatch.setattr(semantic_model, "PROMPT_VERSION", "trajectory-task-hierarchy/2")
    store, ids = seeded(tmp_path, 1)
    batch = store.request_batch("owner", request(ids, concurrency=1))
    job = store.claim_job()
    identity = {
        "model": "glm-5.3",
        "route": "zai-glm-5-3",
        "reasoning_effort": "high",
        "prompt_version": "trajectory-task-hierarchy/1",
        "source_revision": "revision",
        "input_chars": "24000",
        "operation_chars": "2000",
        "output_tokens": "8192",
    }
    store.pin_execution(job, identity)
    progress = {
        "completed_chunks": 9,
        "total_chunks": 374,
        "state": "failed",
        "analysis_usage": [
            {
                "chunk": 9,
                "attempt": 1,
                "call_id": "valid-original",
                "receipt_id": "receipt-good",
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                "valid": True,
            },
            {
                "chunk": 10,
                "attempt": 1,
                "call_id": "invalid-original",
                "receipt_id": "receipt-bad",
                "usage": {"prompt_tokens": 11, "completion_tokens": 3},
                "valid": False,
            },
        ],
    }
    store.job_progress(job, progress)
    store.finish_job(job, "Model operation coverage is incomplete or duplicated")
    return store, job, batch, identity, progress


def mutation():
    return AnalysisRequest(mutation_id=uuid.uuid4().hex)


def test_resume_same_job_atomic_replay_pin_migration_and_complete_usage(tmp_path, monkeypatch):
    store, job, batch, identity, progress = failed_job(tmp_path, monkeypatch)
    before = store.detail("owner", job["session"])["resume"]
    assert before == store.batch_detail("owner", batch["batch_id"])["items"][0]["resume"]
    assert before == {
        "eligible": True,
        "reason": "eligible",
        "job_id": job["id"],
        "generation": 0,
        "completed_chunks": 9,
        "max_generations": 12,
        "window_resumes": 0,
        "max_window_resumes": 3,
    }
    value = mutation()
    receipt = store.resume_analysis("owner", job["id"], value)
    assert store.resume_analysis("owner", job["id"], value) == receipt
    assert receipt["job_id"] == job["id"] and receipt["resume_generation"] == 1
    assert receipt["completed_chunks"] == 9
    assert store.detail("owner", job["session"])["resume"]["eligible"] is False
    context = store.resume_context(job)
    assert context["prior_progress"] == progress
    assert context["authorization"]["previous_call_ids"] == ["valid-original", "invalid-original"]
    next_job = store.claim_job()
    assert next_job["id"] == job["id"]
    target = {**identity, "prompt_version": "trajectory-task-hierarchy/2"}
    store.pin_execution(next_job, target)
    for key in (
        "model",
        "route",
        "reasoning_effort",
        "source_revision",
        "input_chars",
        "output_tokens",
        "operation_chars",
    ):
        with pytest.raises(ValueError, match="configuration changed"):
            store.pin_execution(next_job, {**target, key: "changed"})
    item = store.batch_detail("owner", batch["batch_id"])["items"][0]
    assert item["job_id"] == job["id"] and item["analysis_usage"] == progress["analysis_usage"]
    with store.domain.connect() as db:
        assert db.execute("SELECT count(*) FROM semantic_jobs").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM semantic_job_resumes").fetchone()[0] == 1
        assert (
            db.execute("SELECT count(*) FROM audit WHERE operation='analysis.resume'").fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"failed": True, "valid": False}, "prior_call_uncertain"),
        ({"state": "uncertain"}, "prior_call_uncertain"),
        ({"receipt_id": ""}, "received_invalid_result_required"),
        ({"usage": {}}, "received_invalid_result_required"),
        ({"valid": True}, "received_invalid_result_required"),
    ],
)
def test_resume_requires_explicit_received_invalid_evidence(tmp_path, monkeypatch, change, reason):
    store, job, _, _, progress = failed_job(tmp_path, monkeypatch)
    progress["analysis_usage"][-1].update(change)
    store.job_progress(job, progress)
    with pytest.raises(AnalysisResumeError, match=reason):
        store.resume_analysis("owner", job["id"], mutation())
    with store.domain.connect() as db:
        assert db.execute("SELECT count(*) FROM semantic_job_resumes").fetchone()[0] == 0


def test_resume_owner_limit_source_and_old_queue_cannot_bypass(tmp_path, monkeypatch):
    store, job, _, _, _ = failed_job(tmp_path, monkeypatch)
    with pytest.raises(PermissionError):
        store.resume_analysis("stranger", job["id"], mutation())
    with pytest.raises(ValueError, match="original failed"):
        store.request_analysis("owner", job["session"], mutation())
    with store.domain.connect() as db:
        db.execute("UPDATE semantic_sessions SET source_revision='changed'")
    with pytest.raises(AnalysisResumeError, match="analysis_source_changed"):
        store.resume_analysis("owner", job["id"], mutation())
    with store.domain.connect() as db:
        db.execute("UPDATE semantic_sessions SET source_revision='revision'")
    for generation in range(1, 4):
        receipt = store.resume_analysis("owner", job["id"], mutation())
        assert receipt["resume_generation"] == generation
        store.finish_job(job, "Model operation coverage is incomplete or duplicated")
    with pytest.raises(AnalysisResumeError, match="resume_limit_reached"):
        store.resume_analysis("owner", job["id"], mutation())


def test_resume_http_uses_shared_schema_scopes_and_structured_reason(tmp_path, monkeypatch):
    store, job, _, _, _ = failed_job(tmp_path, monkeypatch)

    def auth(req, scope):
        token = req.headers.get("authorization", "").removeprefix("Bearer ")
        if token not in {"owner", "other"}:
            raise HTTPException(403, "denied")
        return Principal(token, scopes=("read", "configure"))

    client = TestClient(create_app(store.domain.path, auth))
    path = f"/trajectory/api/analysis-jobs/{job['id']}/resume"
    payload = mutation().model_dump()
    assert client.post(path, json=payload).status_code == 403
    assert (
        client.post(path, json=payload, headers={"Authorization": "Bearer other"}).status_code
        == 403
    )
    result = client.post(path, json=payload, headers={"Authorization": "Bearer owner"})
    assert result.status_code == 200
    assert (
        client.post(path, json=payload, headers={"Authorization": "Bearer owner"}).json()
        == result.json()
    )
    blocked = client.post(
        path, json=mutation().model_dump(), headers={"Authorization": "Bearer owner"}
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "analysis_not_failed"
    help_doc = client.get("/trajectory/help", headers={"Authorization": "Bearer owner"}).json()
    operation = next(x for x in help_doc["tools"] if x["name"] == "analysis_resume")
    assert "mutation_id" in operation["input_schema"]["properties"]


def test_runtime_passes_prior_failed_attempts_and_resume_generation(tmp_path, monkeypatch):
    store, job, _, identity, progress = failed_job(tmp_path, monkeypatch)
    store.resume_analysis("owner", job["id"], mutation())
    for key, value in {"NAME": identity["model"], "REASONING_EFFORT": "high"}.items():
        monkeypatch.setenv("TRAJECTORY_MODEL_" + key, value)
    monkeypatch.setenv("TRAJECTORY_JINDU_ROUTE", identity["route"])
    seen = {}

    def segment(*args, **kwargs):
        seen.update(kwargs)
        raise semantic_model.SemanticModelError("fixture stop before any model invocation")

    monkeypatch.setattr(semantic_model, "segment", segment)
    runtime = AnalysisRuntime(store)
    try:
        assert runtime.process_next()
    finally:
        runtime.close()
    assert seen["analysis_id"] == job["id"]
    assert seen["resume_generation"] == 1
    assert seen["prior_progress"] == progress
    assert seen["checkpoint"].name == "chunks-" + job["id"] + ".json"


def test_latest_failed_attempt_usage_remains_visible(tmp_path, monkeypatch):
    store, job, batch, _, progress = failed_job(tmp_path, monkeypatch)
    with store.domain.connect() as db:
        for index in range(2):
            db.execute(
                "INSERT INTO audit VALUES(?,?,?,?,?)",
                (
                    "owner",
                    job["id"],
                    "analysis.failed",
                    json.dumps(
                        {"provenance": {"analysis_usage": progress["analysis_usage"][: index + 1]}}
                    ),
                    f"2026-10-19T00:0{index}:00+00:00",
                ),
            )
    item = store.batch_detail("owner", batch["batch_id"])["items"][0]
    assert item["analysis_usage"] == progress["analysis_usage"]


def test_automatic_repair_requeues_same_job_once_with_audited_failure(tmp_path, monkeypatch):
    store, job, batch, _, progress = failed_job(tmp_path, monkeypatch)
    with store.domain.connect() as db:
        db.execute("UPDATE semantic_jobs SET status='running' WHERE id=?", (job["id"],))
    assert store.fail_and_auto_resume(job, "Model operation coverage is incomplete or duplicated")
    context = store.resume_context(job)
    assert context["generation"] == 1
    assert context["authorization"]["resume_mode"] == "automatic"
    assert context["authorization"]["validation_error"] == (
        "Model operation coverage is incomplete or duplicated"
    )
    assert context["prior_progress"] == progress
    detail = store.batch_detail("owner", batch["batch_id"])["items"][0]
    assert detail["job_id"] == job["id"] and detail["status"] == "queued"
    assert not store.fail_and_auto_resume(
        job, "Model operation coverage is incomplete or duplicated"
    )
    with store.domain.connect() as db:
        assert db.execute("SELECT count(*) FROM semantic_job_resumes").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM semantic_jobs").fetchone()[0] == 1
        assert (
            db.execute(
                "SELECT count(*) FROM audit WHERE operation='analysis.auto_resume'"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize("problem", ["uncertain", "missing_receipt", "source_changed"])
def test_automatic_repair_never_bypasses_receipt_or_source_pinning(tmp_path, monkeypatch, problem):
    store, job, _, _, progress = failed_job(tmp_path, monkeypatch)
    if problem == "uncertain":
        progress["analysis_usage"][-1]["uncertain"] = True
    if problem == "missing_receipt":
        progress["analysis_usage"][-1]["receipt_id"] = ""
    store.job_progress(job, progress)
    with store.domain.connect() as db:
        db.execute("UPDATE semantic_jobs SET status='running' WHERE id=?", (job["id"],))
        if problem == "source_changed":
            db.execute("UPDATE semantic_sessions SET source_revision='new-source'")
    assert not store.fail_and_auto_resume(job, "Model changed an existing task identity")
    with store.domain.connect() as db:
        assert (
            db.execute("SELECT status FROM semantic_jobs WHERE id=?", (job["id"],)).fetchone()[0]
            == "failed"
        )
        assert db.execute("SELECT count(*) FROM semantic_job_resumes").fetchone()[0] == 0


def test_runtime_continues_confirmed_validation_failure_automatically(tmp_path, monkeypatch):
    store, job, batch, identity, progress = failed_job(tmp_path, monkeypatch)
    store.resume_analysis("owner", job["id"], mutation())
    next_job = store.claim_job()
    monkeypatch.setenv("TRAJECTORY_MODEL_NAME", identity["model"])
    monkeypatch.setenv("TRAJECTORY_MODEL_REASONING_EFFORT", identity["reasoning_effort"])
    monkeypatch.setenv("TRAJECTORY_JINDU_ROUTE", identity["route"])

    def fail_segment(*args, **kwargs):
        kwargs["progress"](progress)
        raise semantic_model.SemanticModelError("Model changed an existing task identity")

    monkeypatch.setattr(semantic_model, "segment", fail_segment)
    runtime = AnalysisRuntime(store)
    monkeypatch.setattr(runtime.schedules, "verify_job_authorization", lambda job: None)
    try:
        assert runtime._process_job(next_job)
    finally:
        runtime.close()
    context = store.resume_context(job)
    assert context["generation"] == 2
    assert context["authorization"]["resume_mode"] == "automatic"
    assert store.batch_detail("owner", batch["batch_id"])["items"][0]["status"] == "queued"


def test_automatic_repair_stops_after_three_generations(tmp_path, monkeypatch):
    store, job, _, _, _ = failed_job(tmp_path, monkeypatch)
    for generation in range(1, 4):
        with store.domain.connect() as db:
            db.execute("UPDATE semantic_jobs SET status='running' WHERE id=?", (job["id"],))
        assert store.fail_and_auto_resume(job, "Model changed an existing task identity")
        assert store.resume_context(job)["generation"] == generation
    with store.domain.connect() as db:
        db.execute("UPDATE semantic_jobs SET status='running' WHERE id=?", (job["id"],))
    assert not store.fail_and_auto_resume(job, "Model changed an existing task identity")
    with store.domain.connect() as db:
        assert (
            db.execute("SELECT status FROM semantic_jobs WHERE id=?", (job["id"],)).fetchone()[0]
            == "failed"
        )
        assert db.execute("SELECT count(*) FROM semantic_job_resumes").fetchone()[0] == 3


def test_automatic_repair_budget_resets_after_new_window_checkpoint(tmp_path, monkeypatch):
    store, job, _, _, progress = failed_job(tmp_path, monkeypatch)
    for _ in range(3):
        with store.domain.connect() as db:
            db.execute("UPDATE semantic_jobs SET status='running' WHERE id=?", (job["id"],))
        assert store.fail_and_auto_resume(job, "Model changed an existing task identity")
    progress["completed_chunks"] += 1
    progress["analysis_usage"][-1]["chunk"] += 1
    store.job_progress(job, progress)
    with store.domain.connect() as db:
        db.execute("UPDATE semantic_jobs SET status='running' WHERE id=?", (job["id"],))
    assert store.fail_and_auto_resume(job, "Model changed an existing task identity")
    context = store.resume_context(job)
    assert context["generation"] == 4
    assert context["authorization"]["completed_chunks"] == 10


def test_automatic_repair_respects_total_job_limit_across_windows(tmp_path, monkeypatch):
    store, job, _, _, progress = failed_job(tmp_path, monkeypatch)
    for generation in range(1, 13):
        progress["completed_chunks"] = generation
        store.job_progress(job, progress)
        with store.domain.connect() as db:
            db.execute("UPDATE semantic_jobs SET status='running' WHERE id=?", (job["id"],))
        assert store.fail_and_auto_resume(job, "Model changed an existing task identity")
        assert store.resume_context(job)["generation"] == generation
    progress["completed_chunks"] = 13
    store.job_progress(job, progress)
    with store.domain.connect() as db:
        db.execute("UPDATE semantic_jobs SET status='running' WHERE id=?", (job["id"],))
    assert not store.fail_and_auto_resume(job, "Model changed an existing task identity")
    with store.domain.connect() as db:
        assert (
            db.execute("SELECT status FROM semantic_jobs WHERE id=?", (job["id"],)).fetchone()[0]
            == "failed"
        )
