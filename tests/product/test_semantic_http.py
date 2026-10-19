"""New analysis operations preserve native authorization and canonical accounting."""

import base64
import hashlib
import uuid
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient

from trajectory.product.server import Principal, create_app


def test_source_http_account_isolation_and_dynamic_help(tmp_path: Path) -> None:
    def authorize(request, scope):
        token = request.headers.get("authorization")
        if token == "Bearer machine" and scope in {None, "upload"}:
            return Principal("machine", "native", scopes=("upload",))
        if token == "Bearer owner" and scope in {None, "read", "configure"}:
            return Principal("owner", scopes=("read", "configure"))
        if token == "Bearer stranger" and scope in {None, "read"}:
            return Principal("stranger", scopes=("read",))
        raise HTTPException(403, "Denied")

    app = create_app(tmp_path / "db.sqlite", authorize)
    app.state.domain.register("owner", "machine", "fixture")
    client = TestClient(app)
    source = "a" * 64
    content = b'{"type":"event"}\n'
    payload = {
        "schema_id": "trajectory-source-chunk/1",
        "mutation_id": uuid.uuid4().hex,
        "collector": "fixture",
        "source": source,
        "ecosystem": "codex",
        "generation": "one",
        "start": 0,
        "end": len(content),
        "source_bytes": len(content),
        "content": base64.b64encode(content).decode(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "source_name": "session.jsonl",
    }
    route = "/trajectory/api/source-chunks"
    first = client.post(route, json=payload, headers={"Authorization": "Bearer machine"})
    assert first.status_code == 200, first.text
    assert first.json()["durable"] is True
    assert (
        client.post(route, json=payload, headers={"Authorization": "Bearer machine"}).json()
        == first.json()
    )
    assert (
        client.post(route, json=payload, headers={"Authorization": "Bearer owner"}).status_code
        == 403
    )
    assert client.get(
        "/trajectory/api/source-progress",
        params={"collector": "fixture", "source": source},
        headers={"Authorization": "Bearer machine"},
    ).json()["next_offset"] == len(content)
    sid = first.json()["session_id"]
    assert (
        client.get(
            f"/trajectory/api/sessions/{sid}/analysis", headers={"Authorization": "Bearer stranger"}
        ).status_code
        != 200
    )
    assert (
        client.get(
            "/trajectory/api/sessions", headers={"Authorization": "Bearer machine"}
        ).status_code
        == 403
    )
    tools = client.get("/trajectory/help", headers={"Authorization": "Bearer owner"}).json()[
        "tools"
    ]
    assert {"sessions", "analysis_read", "analysis_run", "task_edit", "source_evidence"} <= {
        t["name"] for t in tools
    }
    overview = client.get(
        "/trajectory/api/overview", headers={"Authorization": "Bearer owner"}
    ).json()
    assert overview["projects"] == []  # Content cannot generate another usage bill.


def test_standby_gate_prevents_claiming_work(tmp_path: Path, monkeypatch) -> None:
    from trajectory.product.domain import Domain
    from trajectory.product.semantic import SemanticStore
    from trajectory.product.semantic_runtime import AnalysisRuntime

    store = SemanticStore(Domain(tmp_path / "domain.db"))
    with store.domain.connect() as db:
        store._queue(db, "owner", "session", "parse", "revision")
    monkeypatch.setenv("TRAJECTORY_WORKER_GATE", str(tmp_path / "enable-worker"))
    assert AnalysisRuntime(store).process_next() is False
    with store.domain.connect() as db:
        assert db.execute("SELECT status FROM semantic_jobs").fetchone()[0] == "queued"


def test_online_backup_is_scoped_durable_and_replayable(tmp_path: Path) -> None:
    import sqlite3

    def authorize(request, scope):
        if request.headers.get("authorization") == "Bearer backup" and scope == "backup":
            return Principal("backup-machine", "native-backup", scopes=("backup",))
        raise HTTPException(403, "Denied")

    app = create_app(tmp_path / "domain.db", authorize)
    client = TestClient(app)
    body = {"mutation_id": uuid.uuid4().hex}
    url = "/trajectory/api/backups"
    assert client.post(url, json=body).status_code == 403
    headers = {"Authorization": "Bearer backup"}
    response = client.post(url, json=body, headers=headers)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["fsynced"] and receipt["integrity_verified"] and receipt["durable"]
    assert not receipt["full_system_restore_verified"]
    snapshot = Path(receipt["path"])
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == receipt["sha256"]
    assert snapshot.stat().st_mode & 0o777 == 0o600
    assert client.post(url, json=body, headers=headers).json() == receipt
    with sqlite3.connect(snapshot) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_analysis_metadata_and_lazy_operation_reader_share_authorized_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    from trajectory.product.semantic import SemanticStore

    def authorize(request, scope):
        if request.headers.get("authorization") == "Bearer owner" and scope in {None, "read"}:
            return Principal("owner", scopes=("read",))
        raise HTTPException(403, "Denied")

    operation = {
        "id": "op",
        "kind": "tool",
        "text": "long command\n" * 50000,
        "title": "inspect",
        "metrics": {"input": 120},
        "location": {"source_line": 5},
        "call_id": "call",
    }
    original = {"source_revision": "snapshot-one", "operations": [operation]}
    calls = []

    def detail(self, owner, sid, *, source_revision=None):
        assert owner == "owner" and sid == "session"
        return original

    def read_operation(self, owner, sid, oid, *, source_revision=None):
        calls.append((owner, sid, oid, source_revision))
        if source_revision != "snapshot-one":
            raise ValueError("Unknown retained source revision")
        return operation

    monkeypatch.setattr(SemanticStore, "detail", detail)
    monkeypatch.setattr(SemanticStore, "operation", read_operation, raising=False)
    client = TestClient(create_app(tmp_path / "lazy.db", authorize))
    headers = {"Authorization": "Bearer owner"}
    response = client.get("/trajectory/api/sessions/session/analysis", headers=headers)
    assert response.status_code == 200
    metadata = response.json()["operations"][0]
    assert "text" not in metadata and metadata["body_available"] is True
    assert metadata["metrics"] == operation["metrics"]
    assert metadata["location"] == operation["location"]
    assert metadata["call_id"] == "call"
    assert len(response.content) < 1000
    assert "text" in original["operations"][0]  # Do not mutate shared semantic results.
    route = "/trajectory/api/sessions/session/operations/op"
    assert client.get(route, params={"source_revision": "snapshot-one"}).status_code == 403
    assert calls == []
    complete = client.get(route, params={"source_revision": "snapshot-one"}, headers=headers)
    assert complete.status_code == 200 and complete.json() == operation
    assert calls == [("owner", "session", "op", "snapshot-one")]
    assert (
        client.get(route, params={"source_revision": "unknown"}, headers=headers).status_code == 409
    )
    tools = client.get("/trajectory/help", headers=headers).json()["tools"]
    assert "operation_read" in {tool["name"] for tool in tools}
