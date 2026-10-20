"""Cross-session saved structure queries remain lightweight, scoped and revision-pinned."""

import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_analysis_batches import request, seeded
from test_semantic import analysis

from trajectory.product.semantic import SemanticStore
from trajectory.product.server import Principal, create_app


def test_task_query_filters_pages_and_revision_conflicts(tmp_path, monkeypatch):
    store, ids = seeded(tmp_path, 2)
    batch = store.request_batch("owner", request(ids))
    for index, sid in enumerate(ids):
        store.save_analysis("owner", sid, "revision", analysis())
        with store.domain.connect() as db:
            db.execute(
                "INSERT INTO semantic_session_metadata VALUES(?,?,?,?)",
                (
                    "owner",
                    sid,
                    json.dumps({"metadata_version": 2, "cwd": f"/research/{index}"}),
                    "now",
                ),
            )
    monkeypatch.setattr(store, "detail", lambda *a, **k: pytest.fail("Heavy detail read"))
    monkeypatch.setattr(
        store.domain, "source_contributions", lambda *a, **k: pytest.fail("Ledger recomputed")
    )
    first = store.task_query("owner", batch_id=batch["batch_id"], limit=2)
    assert first["total"] == 6 and first["metrics_included"] is False
    assert [item["depth"] for item in first["items"]] == [0, 1]
    second = store.task_query(
        "owner", batch_id=batch["batch_id"], limit=2, cursor=first["next_cursor"]
    )
    assert len({(item["session_id"], item["id"]) for item in first["items"] + second["items"]}) == 4
    assert store.task_query("owner", depth=1)["total"] == 4
    selected = store.task_query("owner", cwd="/research/0", q="恢复同步")
    assert selected["total"] == 3  # Ancestor titles remain searchable.
    assert store.task_query("owner", session_id=ids[0], q="AUTH")["total"] == 1
    assert store.task_query("stranger")["total"] == 0
    with pytest.raises(PermissionError):
        store.task_query("stranger", batch_id=batch["batch_id"])
    changed = analysis()
    changed["tasks"][0]["title"] = "changed"
    store.save_analysis("owner", ids[0], "revision", changed)
    with pytest.raises(ValueError, match="restart pagination"):
        store.task_query("owner", batch_id=batch["batch_id"], cursor=first["next_cursor"])
    for options in ({"limit": 0}, {"limit": 501}, {"depth": -1}, {"cursor": "bad"}):
        with pytest.raises(ValueError):
            store.task_query("owner", **options)


def test_task_query_does_not_substitute_reanalyzed_batch_source(tmp_path):
    store, ids = seeded(tmp_path, 1)
    batch = store.request_batch("owner", request(ids))
    store.save_analysis("owner", ids[0], "revision", analysis())
    assert store.task_query("owner", batch_id=batch["batch_id"])["total"] == 3
    with store.domain.connect() as db:
        db.execute("UPDATE semantic_analyses SET source_revision='new' WHERE session=?", (ids[0],))
    result = store.task_query("owner", batch_id=batch["batch_id"])
    assert result["total"] == 0
    assert result["skipped_sessions"] == [
        {"session_id": ids[0], "reason": "batch_snapshot_replaced"}
    ]


def test_task_query_http_help_and_account_isolation(tmp_path):
    store, ids = seeded(tmp_path, 1)
    store.save_analysis("owner", ids[0], "revision", analysis())

    def authorize(request, scope):
        token = request.headers.get("authorization", "")
        if token in ("owner", "stranger") and scope in (None, "read"):
            return Principal(token, scopes=("read",))
        raise HTTPException(403, "Denied")

    app = create_app(store.domain.path, authorize)
    client = TestClient(app)
    assert isinstance(app.state.semantic, SemanticStore)
    path = "/trajectory/api/tasks"
    assert client.get(path).status_code == 403
    assert client.get(path, headers={"Authorization": "stranger"}).json()["total"] == 0
    result = client.get(path, params={"depth": 1}, headers={"Authorization": "owner"})
    assert result.status_code == 200 and result.json()["total"] == 2
    assert (
        client.get(path, params={"limit": "bad"}, headers={"Authorization": "owner"}).status_code
        == 409
    )
    help_value = client.get("/trajectory/help", headers={"Authorization": "owner"}).json()
    assert (
        next(tool for tool in help_value["tools"] if tool["name"] == "task_query")["method"]
        == "GET"
    )
