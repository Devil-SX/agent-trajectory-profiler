"""The browser and Agent share authenticated snapshot reads and idempotent updates."""

import time
from threading import Event

from fastapi import HTTPException
from fastapi.testclient import TestClient

from trajectory.product.domain import Domain
from trajectory.product.semantic import SemanticStore
from trajectory.product.semantic_runtime import AnalysisRuntime
from trajectory.product.server import Principal, create_app


def test_http_isolation_revocation_scope_and_no_get_aggregation(tmp_path, monkeypatch):
    denied = set()

    def authorize(request, scope):
        who = request.headers.get("authorization", "").removeprefix("Bearer ")
        if who not in {"owner", "reader", "other"} or who in denied:
            raise HTTPException(403, "denied")
        if scope in {"configure", "read_all"} and who != "owner":
            raise HTTPException(403, "denied")
        return Principal(
            "owner" if who == "reader" else who,
            key_id=who,
            scopes=("read", "configure", "read_all") if who == "owner" else ("read",),
        )

    app = create_app(tmp_path / "domain.db", authorize)
    runtime = app.state.analysis_runtime
    client = TestClient(app)
    headers = {"Authorization": "Bearer owner"}
    response = client.get("/trajectory/api/overview", headers=headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Authorization"
    assert response.json()["statistics_snapshot"]["state"] == "building"
    assert "projects" not in response.json()
    tools = client.get("/trajectory/help", headers=headers).json()["tools"]
    assert {"overview", "statistics_refresh", "platform_statistics_refresh"} <= {
        v["name"] for v in tools
    }
    mutation = {"mutation_id": "statistics-http-manual-0001"}
    receipt = client.post("/trajectory/api/statistics/refresh", headers=headers, json=mutation)
    assert receipt.status_code == 200 and receipt.json()["coalesced"]
    assert (
        client.post("/trajectory/api/statistics/refresh", headers=headers, json=mutation).json()
        == receipt.json()
    )
    assert (
        client.post(
            "/trajectory/api/statistics/refresh",
            headers={"Authorization": "Bearer reader"},
            json=mutation,
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/trajectory/api/platform", headers={"Authorization": "Bearer reader"}
        ).status_code
        == 403
    )
    job = runtime.statistics.claim()
    assert runtime.statistics.build(job)
    monkeypatch.setattr(
        runtime.store.domain,
        "_calculate_snapshot",
        lambda *a: (_ for _ in ()).throw(AssertionError("GET computed")),
    )
    assert client.get("/trajectory/api/overview", headers=headers).json()["projects"] == []
    assert (
        "projects"
        not in client.get(
            "/trajectory/api/overview", headers={"Authorization": "Bearer other"}
        ).json()
    )
    assert client.get("/trajectory/api/overview?since=invalid", headers=headers).status_code == 409
    denied.add("owner")
    assert client.get("/trajectory/api/overview", headers=headers).status_code == 403
    assert (
        client.post(
            "/trajectory/api/statistics/refresh", headers=headers, json=mutation
        ).status_code
        == 403
    )
    runtime.close()


def test_runtime_uses_one_lease_and_parks_at_paid_window_boundary(tmp_path, monkeypatch):
    store = SemanticStore(Domain(tmp_path / "domain.db"))
    runtime = AnalysisRuntime(store)
    runtime.statistics.verify_actor = lambda actor: None
    competitor = AnalysisRuntime(store)
    started, finished = Event(), Event()
    job_available = [True]

    def claim_job():
        if job_available[0]:
            job_available[0] = False
            return {"kind": "analyze"}
        return None

    def paid_window(job):
        started.set()
        # Represents a received paid response being committed before the next window.
        assert finished.wait(5)
        assert runtime._pause_requested()
        return True

    monkeypatch.setattr(store, "claim_job", claim_job)
    monkeypatch.setattr(runtime, "_process_job", paid_window)
    assert runtime.tick() and started.wait(2)
    runtime.statistics.read("owner")
    assert not competitor.tick()
    assert not runtime.tick() and runtime.statistics_barrier.is_set()
    assert runtime.statistics_future is None
    finished.set()
    deadline = time.monotonic() + 5
    while runtime.futures and not all(f.done() for f in runtime.futures):
        assert time.monotonic() < deadline
        time.sleep(0.005)
    assert runtime.tick()
    assert runtime.statistics_future is not None
    runtime.statistics_future.result(timeout=5)
    runtime.tick()
    assert not runtime.statistics_barrier.is_set()
    assert runtime.statistics.read("owner")["statistics_snapshot"]["available"]
    runtime.close()
    competitor.close()


def test_pending_statistics_cooldown_does_not_starve_analysis(tmp_path, monkeypatch):
    store = SemanticStore(Domain(tmp_path / "domain.db"))
    runtime = AnalysisRuntime(store)
    runtime.statistics.verify_actor = lambda actor: None
    runtime.statistics.read("owner")
    first = runtime.statistics.claim()
    assert runtime.statistics.build(first)
    runtime.statistics.read("owner", since="2026-10-01")
    assert runtime.statistics.pending() and not runtime.statistics.can_start()
    claimed = []
    monkeypatch.setattr(store, "claim_job", lambda: claimed.append(True) or None)
    runtime.tick()
    assert claimed and not runtime.statistics_barrier.is_set()
    assert runtime.statistics_future is None
    runtime.close()


def test_paid_window_boundary_rechecks_authority_before_resuming(tmp_path, monkeypatch):
    runtime = AnalysisRuntime(SemanticStore(Domain(tmp_path / "domain.db")))
    called = []
    monkeypatch.setattr(
        runtime.schedules, "verify_job_authorization", lambda job: called.append(job)
    )
    job = {"id": "existing-job", "owner": "owner"}
    assert not runtime._pause_before_window(job)
    assert called == [job]
    runtime.statistics_barrier.set()
    assert runtime._pause_before_window(job)
    assert called == [job, job]

    def deny(job):
        raise PermissionError("Stored analysis authority revoked")

    monkeypatch.setattr(runtime.schedules, "verify_job_authorization", deny)
    import pytest

    with pytest.raises(PermissionError):
        runtime._pause_before_window(job)
    runtime.close()
