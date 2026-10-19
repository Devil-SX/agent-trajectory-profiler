"""Explicit lost-response recomputation never invents a successful original receipt."""

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from pydantic import ValidationError
from test_analysis_resume import failed_job, mutation

from trajectory.product import receipt_verification
from trajectory.product.contracts import LostWindowRecomputeRequest
from trajectory.product.semantic import AnalysisResumeError


def lost(tmp_path, monkeypatch):
    store, job, batch, execution, progress = failed_job(tmp_path, monkeypatch)
    call_id = "trajectory:" + hashlib.sha256(f"{job['id']}:9:0".encode()).hexdigest()
    progress["analysis_usage"][-1] = {
        "chunk": 10,
        "attempt": 1,
        "call_id": call_id,
        "failed": True,
        "usage": {},
        "elapsed_seconds": 120.1,
    }
    store.job_progress(job, progress)
    store.finish_job(job, "Jindu call failed or result uncertain; reconcile call ID before retry")
    value = LostWindowRecomputeRequest(
        mutation_id="explicit-lost-window-decision-1",
        call_id=call_id,
        receipt_id="f59cdaf9-4eee-43df-88f1-e871d078d2f2",
        accept_possible_duplicate_charge=True,
        reason="Explicit operator accepts possible duplicate charge",
        receipt_checked_at=datetime.now(UTC),
    )
    proof = {
        "caller": {
            "account_id": "trajectory-machine",
            "key_id": "machine-key",
            "source_service": "trajectory",
            "machine_client_id": "trajectory-analysis",
            "scopes": ["jindu.invoke", "jindu.read"],
        },
        "receipt": {
            "id": value.receipt_id,
            "request_id": call_id,
            "account_id": "trajectory-machine",
            "source_service": "trajectory",
            "state": "uncertain",
            "finished": datetime.now(UTC).timestamp(),
            "model": execution["model"],
            "route": execution["route"],
            "input_tokens": None,
            "output_tokens": None,
            "http_status": None,
        },
        "verified_at": datetime.now(UTC).isoformat(),
    }
    return store, job, batch, progress, value, proof


def test_explicit_decision_keeps_unknown_usage_prefix_and_job_replay_skips_http(
    tmp_path, monkeypatch
):
    store, job, batch, progress, value, proof = lost(tmp_path, monkeypatch)
    saved = copy.deepcopy(progress)
    calls = []

    def verify(*args):
        calls.append(args)
        # A real competing writer succeeds: no long SQLite transaction spans the HTTP read.
        with store.domain.connect() as db:
            db.execute(
                "INSERT INTO audit VALUES(?,?,?,?,?)",
                ("fixture", "network-check", "fixture", "{}", "now"),
            )
        return proof

    with pytest.raises(AnalysisResumeError, match="prior_call_uncertain"):
        store.resume_analysis("owner", job["id"], mutation())
    receipt = store.recompute_lost_window(
        "owner", job["id"], value, {"account_id": "owner", "key_id": "operator"}, verifier=verify
    )
    assert receipt["job_id"] == job["id"] and receipt["completed_chunks"] == 9
    assert receipt["resume_generation"] == 1 and len(calls) == 1
    assert (
        store.recompute_lost_window(
            "owner", job["id"], value, {}, verifier=lambda *a: pytest.fail("replayed HTTP")
        )
        == receipt
    )
    ctx = store.resume_context(job)
    assert ctx["prior_progress"] == saved
    assert ctx["authorized_recomputations"] == [
        {
            "job_id": job["id"],
            "call_id": value.call_id,
            "receipt_id": value.receipt_id,
            "chunk": 10,
            "attempt": 1,
            "resume_generation": 1,
            "receipt_state": "uncertain_terminal",
            "authorization_id": value.mutation_id,
            "accept_possible_duplicate_charge": True,
        }
    ]
    assert ctx["authorization"]["receipt_verification"] == proof
    assert ctx["authorization"]["operator_decision"]["reason"] == value.reason
    assert ctx["authorization"]["actor"]["key_id"] == "operator"
    item = store.batch_detail("owner", batch["batch_id"])["items"][0]
    assert item["analysis_usage"] == saved["analysis_usage"]
    assert store.claim_job()["id"] == job["id"]


@pytest.mark.parametrize(
    "field,wrong",
    [
        ("state", "completed"),
        ("state", "sent"),
        ("state", "rejected"),
        ("state", "unknown"),
        ("account_id", "other-machine"),
        ("source_service", "external-agent"),
        ("request_id", "different-call"),
        ("route", "different-route"),
        ("model", "other-model"),
        ("id", "other-receipt"),
        ("finished", None),
    ],
)
def test_receipt_identity_and_terminal_state_fail_closed(tmp_path, monkeypatch, field, wrong):
    store, job, _, _, value, proof = lost(tmp_path, monkeypatch)
    proof["receipt"][field] = wrong
    with pytest.raises(AnalysisResumeError, match="receipt_verification_mismatch"):
        store.recompute_lost_window("owner", job["id"], value, {}, verifier=lambda *a: proof)
    assert store.resume_context(job)["generation"] == 0


def test_owner_call_freshness_and_concurrent_change_block(tmp_path, monkeypatch):
    store, job, _, progress, value, proof = lost(tmp_path, monkeypatch)
    with pytest.raises(PermissionError):
        store.recompute_lost_window(
            "other", job["id"], value, {}, verifier=lambda *a: pytest.fail("HTTP before ownership")
        )
    stale = value.model_copy(update={"receipt_checked_at": datetime.now(UTC) - timedelta(hours=1)})
    with pytest.raises(AnalysisResumeError, match="receipt_check_not_fresh"):
        store.recompute_lost_window("owner", job["id"], stale, {}, verifier=lambda *a: proof)
    wrong = value.model_copy(update={"call_id": "trajectory:" + "0" * 64})
    with pytest.raises(AnalysisResumeError, match="last_lost_call_mismatch"):
        store.recompute_lost_window("owner", job["id"], wrong, {}, verifier=lambda *a: proof)

    def verify(*args):
        progress["completed_chunks"] = 8
        store.job_progress(job, progress)
        return proof

    with pytest.raises(AnalysisResumeError):
        store.recompute_lost_window("owner", job["id"], value, {}, verifier=verify)
    assert store.resume_context(job)["generation"] == 0


def test_recompute_requires_strict_explicit_acceptance(tmp_path, monkeypatch):
    *_, value, _ = lost(tmp_path, monkeypatch)
    for acceptance in (False, 1, "true", None):
        with pytest.raises(ValidationError):
            LostWindowRecomputeRequest.model_validate(
                {**value.model_dump(), "accept_possible_duplicate_charge": acceptance}
            )


def test_verifier_uses_only_authenticated_help_and_calls_http(tmp_path, monkeypatch):
    _, _, _, _, value, proof = lost(tmp_path, monkeypatch)
    observed = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            assert self.headers["Authorization"] == "Bearer fixture-key"
            observed.append(self.path)
            payload = (
                {"caller": proof["caller"]}
                if self.path.endswith("/help")
                else {"items": [proof["receipt"]]}
            )
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        receipt_verification,
        "_configuration",
        lambda: {
            "base_url": f"http://127.0.0.1:{server.server_port}/jindu/api/v1",
            "api_key": "fixture-key",
        },
    )
    try:
        result = receipt_verification.verify_lost_receipt(
            value.call_id, value.receipt_id, "zai-glm-5-3", "glm-5.3"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert result["receipt"] == proof["receipt"]
    assert observed == ["/jindu/api/v1/help", "/jindu/api/v1/calls"]


def test_recompute_http_schema_authority_and_no_automatic_control(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    from trajectory.product.server import Principal, create_app

    store, job, _, _, value, proof = lost(tmp_path, monkeypatch)
    checks = []

    def verify(*args):
        checks.append(args)
        return proof

    monkeypatch.setattr(receipt_verification, "verify_lost_receipt", verify)

    def auth(req, scope):
        actor = req.headers.get("Authorization", "").removeprefix("Bearer ")
        if actor not in {"owner", "other"}:
            raise HTTPException(403, "denied")
        return Principal(actor, key_id="operator-key", scopes=("read", "configure"))

    client = TestClient(create_app(store.domain.path, auth))
    url = f"/trajectory/api/analysis-jobs/{job['id']}/recompute-lost-window"
    payload = value.model_dump(mode="json")
    assert client.post(url, json=payload).status_code == 403
    assert (
        client.post(url, json=payload, headers={"Authorization": "Bearer other"}).status_code == 403
    )
    assert not checks
    assert (
        client.post(
            url,
            json={**payload, "accept_possible_duplicate_charge": False},
            headers={"Authorization": "Bearer owner"},
        ).status_code
        == 422
    )
    response = client.post(url, json=payload, headers={"Authorization": "Bearer owner"})
    assert response.status_code == 200 and response.json()["job_id"] == job["id"]
    assert (
        client.post(url, json=payload, headers={"Authorization": "Bearer owner"}).json()
        == response.json()
    )
    assert len(checks) == 1
    help_value = client.get("/trajectory/help", headers={"Authorization": "Bearer owner"}).json()
    op = next(x for x in help_value["tools"] if x["name"] == "analysis_recompute_lost_window")
    assert "accept_possible_duplicate_charge" in op["input_schema"]["required"]
    assert store.resume_context(job)["authorization"]["actor"]["key_id"] == "operator-key"


@pytest.mark.parametrize(
    "field,wrong",
    [
        ("machine_client_id", None),
        ("source_service", "external-agent"),
        ("scopes", ["jindu.invoke"]),
    ],
)
def test_receipt_reader_must_be_native_trajectory_machine(tmp_path, monkeypatch, field, wrong):
    store, job, _, _, value, proof = lost(tmp_path, monkeypatch)
    proof["caller"][field] = wrong
    with pytest.raises(AnalysisResumeError, match="receipt_verification_mismatch"):
        store.recompute_lost_window("owner", job["id"], value, {}, verifier=lambda *a: proof)
    assert store.resume_context(job)["generation"] == 0


@pytest.mark.parametrize("known_tokens", [0, 17])
def test_known_gateway_usage_requires_separate_reconciliation(tmp_path, monkeypatch, known_tokens):
    store, job, _, _, value, proof = lost(tmp_path, monkeypatch)
    proof["receipt"]["input_tokens"] = known_tokens
    with pytest.raises(AnalysisResumeError, match="receipt_usage_reconciliation_required"):
        store.recompute_lost_window("owner", job["id"], value, {}, verifier=lambda *a: proof)
    assert store.resume_context(job)["generation"] == 0
