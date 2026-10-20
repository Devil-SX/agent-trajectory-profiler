"""Request migrations leave usage/checkpoints/paid snapshots unchanged."""

import base64
import hashlib
import json

import pytest

from trajectory.product.contracts import Batch, RequestMeasurementRepair, SourceChunk
from trajectory.product.domain import Domain
from trajectory.product.semantic import SemanticStore, digest


def fixture(tmp_path):
    domain = Domain(tmp_path / "fixture.db")
    domain.register("owner", "machine", "fixture")
    store = SemanticStore(domain)
    source = "a" * 64
    raw = b'{"type":"session_meta"}\n{"type":"event_msg"}\n{"type":"event_msg"}\n'
    store.ingest_source(
        "machine",
        SourceChunk.model_validate(
            {
                "schema_id": "trajectory-source-chunk/1",
                "mutation_id": "source-upload-fixture-001",
                "collector": "fixture",
                "source": source,
                "ecosystem": "codex",
                "generation": "first",
                "start": 0,
                "end": len(raw),
                "source_bytes": len(raw),
                "content": base64.b64encode(raw).decode(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "source_name": "fixture.jsonl",
            }
        ),
    )
    request = {
        "id": digest(source + ":2"),
        "session": "fixture-session",
        "task": "original-task",
        "ecosystem": "codex",
        "kind": "request",
        "timestamp": "2026-10-20T00:00:00Z",
        "source_line": 2,
    }
    usage = {
        **request,
        "id": digest(source + ":3"),
        "kind": "usage",
        "source_line": 3,
        "input": 100,
        "output": 10,
    }
    domain.ingest(
        "machine",
        Batch.model_validate(
            {
                "mutation_id": "original-batch-fixture-001",
                "collector": "fixture",
                "source": source,
                "revision": 1,
                "source_bytes": len(raw),
                "read_bytes": len(raw),
                "parser_version": "sparkstead-trajectory/1",
                "records": [request, usage],
            }
        ),
    )
    value = {
        "mutation_id": "request-repair-fixture-001",
        "collector": "fixture",
        "source": source,
        "expected_ledger_revision": 1,
        "source_revision": digest("first:" + str(len(raw))),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "complete_bytes": len(raw),
        "parser_version": "sparkstead-trajectory/3",
        "projector_sha256": "d" * 64,
        "records": [
            {**request, "task": "new-task-not-used", "input_origin": "human", "input_chars": 3}
        ],
    }
    return domain, store, value


def test_repair_preserves_checkpoint_usage_identity_and_is_idempotent(tmp_path):
    domain, store, value = fixture(tmp_path)
    with domain.connect() as db:
        before_source = tuple(db.execute("SELECT * FROM sources").fetchone())
        before_usage = db.execute(
            "SELECT body FROM events WHERE json_extract(body,'$.kind')='usage'"
        ).fetchone()[0]
    model = RequestMeasurementRepair.model_validate(value)
    receipt = domain.repair_requests("machine", model)
    assert receipt["checkpoint_unchanged"] and receipt["usage_unchanged"]
    assert domain.repair_requests("machine", model) == receipt
    with domain.connect() as db:
        assert before_source == tuple(db.execute("SELECT * FROM sources").fetchone())
        assert (
            before_usage
            == db.execute(
                "SELECT body FROM events WHERE json_extract(body,'$.kind')='usage'"
            ).fetchone()[0]
        )
        request = json.loads(
            db.execute(
                "SELECT body FROM events WHERE json_extract(body,'$.kind')='request'"
            ).fetchone()[0]
        )
        assert request["task"] == "original-task"
    metrics = domain.overview("owner")["projects"][0]
    assert metrics["human_interactions"] == 1 and metrics["human_input_chars"] == 3
    progress = store.source_progress("machine", value["collector"], value["source"])
    assert progress["ledger_revision"] == 1
    assert progress["ledger_parser"] == "sparkstead-trajectory/1"


@pytest.mark.parametrize(
    "changes",
    [
        {"source_sha256": "b" * 64},
        {"source_revision": "b" * 64},
        {"expected_ledger_revision": 2},
        {"complete_bytes": 1},
    ],
)
def test_repair_rejects_stale_or_mismatched_evidence_atomically(tmp_path, changes):
    domain, _, value = fixture(tmp_path)
    with domain.connect() as db:
        before = [tuple(row) for row in db.execute("SELECT * FROM events")]
    with pytest.raises(ValueError):
        domain.repair_requests(
            "machine", RequestMeasurementRepair.model_validate({**value, **changes})
        )
    with domain.connect() as db:
        assert before == [tuple(row) for row in db.execute("SELECT * FROM events")]


def test_repair_rejects_unbound_actor_and_nonrequest_records(tmp_path):
    domain, _, value = fixture(tmp_path)
    with pytest.raises(PermissionError):
        domain.repair_requests("other-machine", RequestMeasurementRepair.model_validate(value))
    value["records"][0]["kind"] = "usage"
    value["records"][0].pop("input_origin")
    value["records"][0].pop("input_chars")
    with pytest.raises(ValueError):
        RequestMeasurementRepair.model_validate(value)


def test_repair_is_discoverable_and_requires_native_machine(tmp_path):
    from fastapi.testclient import TestClient

    from trajectory.product.server import Principal, create_app

    app = create_app(
        tmp_path / "http.db", lambda request, scope: Principal("owner", scopes=("upload",))
    )
    client = TestClient(app)
    help_value = client.get("/trajectory/help", headers={"Authorization": "Bearer fixture"}).json()
    assert any(tool["name"] == "request_measurements_repair" for tool in help_value["tools"])
    _, _, value = fixture(tmp_path / "client")
    response = client.post("/trajectory/api/request-measurements/repair", json=value)
    assert response.status_code == 403


def test_legacy_append_cannot_downgrade_repaired_measurements(tmp_path):
    domain, _, value = fixture(tmp_path)
    domain.repair_requests("machine", RequestMeasurementRepair.model_validate(value))
    request = {**value["records"][0]}
    for field in ("input_origin", "input_chars"):
        request.pop(field)
    request["task"] = "original-task"
    payload = {
        "mutation_id": "legacy-append-fixture-002",
        "collector": "fixture",
        "source": value["source"],
        "revision": 2,
        "source_bytes": value["complete_bytes"],
        "read_bytes": value["complete_bytes"],
        "parser_version": "sparkstead-trajectory/1",
        "records": [request],
    }
    domain.ingest("machine", Batch.model_validate(payload))
    metrics = domain.overview("owner")["projects"][0]
    assert metrics["human_input_chars"] == 3
    assert metrics["human_interactions"] == 1
    with pytest.raises(ValueError, match="downgrade"):
        domain.ingest(
            "machine",
            Batch.model_validate(
                {
                    **payload,
                    "mutation_id": "legacy-reset-fixture-003",
                    "revision": 3,
                    "replace": True,
                }
            ),
        )
    request.update(input_origin="human", input_chars=5)
    domain.ingest(
        "machine",
        Batch.model_validate(
            {
                **payload,
                "mutation_id": "modern-reset-fixture-003",
                "revision": 3,
                "replace": True,
                "parser_version": "sparkstead-trajectory/3",
                "records": [request],
            }
        ),
    )
    metrics = domain.overview("owner")["projects"][0]
    assert metrics["human_input_chars"] == 5
    assert metrics["human_interactions"] == 1


def test_native_http_request_repair_uses_bound_account_and_key(tmp_path):
    from fastapi.testclient import TestClient

    from trajectory.product.server import Principal, create_app

    domain, _, value = fixture(tmp_path)
    app = create_app(
        domain.path,
        lambda request, scope: Principal(
            "machine", machine_client="fixture-client", key_id="fixture-key", scopes=("upload",)
        ),
    )
    client = TestClient(app)
    first = client.post("/trajectory/api/request-measurements/repair", json=value)
    assert first.status_code == 200
    receipt = first.json()
    assert receipt["durable"] is True
    assert receipt["machine_account"] == "machine"
    assert receipt["key_id"] == "fixture-key"
    assert client.post("/trajectory/api/request-measurements/repair", json=value).json() == receipt


def test_quarantined_request_evidence_is_preserved(tmp_path):
    domain, _, value = fixture(tmp_path)
    value["records"] = []
    value["quarantined_source_lines"] = [2]
    domain.repair_requests("machine", RequestMeasurementRepair.model_validate(value))
    with domain.connect() as db:
        request = json.loads(
            db.execute(
                "SELECT body FROM events WHERE json_extract(body,'$.kind')='request'"
            ).fetchone()[0]
        )
    assert request["source_line"] == 2
    assert request.get("input_origin") is None
    assert domain.overview("owner")["projects"][0]["human_input_chars"] is None


@pytest.mark.parametrize("race", [False, True])
def test_archive_hash_does_not_hold_writer_lock_and_heads_are_refenced(tmp_path, monkeypatch, race):
    domain, _, value = fixture(tmp_path)
    original_connect = domain.connect
    connections = []

    def connect():
        db = original_connect()
        connections.append(db)
        return db

    original_hash = hashlib.sha256
    updates = []

    class ProbeHash:
        def __init__(self, *args, **kwargs):
            self.inner = original_hash(*args, **kwargs)

        def update(self, data):
            assert not connections[-1].in_transaction
            # A concurrent metadata writer succeeds while the archive is read.
            with original_connect() as db:
                db.execute(
                    "INSERT INTO audit VALUES(?,?,?,?,?)", ("probe", "probe", "probe", "{}", "now")
                )
                if race:
                    db.execute("UPDATE sources SET revision=revision+1")
            updates.append(len(data))
            self.inner.update(data)

        def hexdigest(self):
            return self.inner.hexdigest()

    monkeypatch.setattr(domain, "connect", connect)
    monkeypatch.setattr(hashlib, "sha256", ProbeHash)
    if race:
        with pytest.raises(ValueError, match="changed before"):
            domain.repair_requests("machine", RequestMeasurementRepair.model_validate(value))
        with original_connect() as db:
            request = json.loads(
                db.execute(
                    "SELECT body FROM events WHERE json_extract(body,'$.kind')='request'"
                ).fetchone()[0]
            )
            assert request.get("input_origin") is None
    else:
        receipt = domain.repair_requests("machine", RequestMeasurementRepair.model_validate(value))
        assert receipt["durable"]
    assert updates


def test_repair_invalidates_warm_overview_source_and_detail_once(tmp_path):
    domain, store, value = fixture(tmp_path)
    sid = store.session_id(value["collector"], value["source"])
    source, _ = store.archive("owner", sid)
    store.save_session(
        "owner",
        sid,
        source,
        value["source_revision"],
        {
            "metadata": {"native_session_id": "fixture-session", "cwd": "/fixture"},
            "operations": [
                {
                    "id": "prompt",
                    "kind": "prompt",
                    "text": "fixture",
                    "location": {"source_line": 2},
                },
                {"id": "usage", "kind": "llm", "location": {"source_line": 3}},
            ],
        },
    )
    before = domain.ledger_revision()
    assert domain.overview("owner")["projects"][0]["human_input_chars"] is None
    assert store.detail("owner", sid)["session"]["metrics"]["human_input_chars"] is None
    # Source contributions and the compact listing are warm as well.
    store.sessions("owner")
    domain.source_contributions("owner", value["collector"], value["source"])
    repair = RequestMeasurementRepair.model_validate(value)
    receipt = domain.repair_requests("machine", repair)
    after = domain.ledger_revision()
    assert after > before
    assert domain.overview("owner")["projects"][0]["human_input_chars"] == 3
    detail = store.detail("owner", sid)
    assert detail["session"]["metrics"]["human_input_chars"] == 3
    assert (
        next(op for op in detail["operations"] if op["id"] == "prompt")["metrics"][
            "human_input_chars"
        ]
        == 3
    )
    assert store.sessions("owner")["metrics_included"] is False
    assert "metrics" not in store.sessions("owner")["sessions"][0]
    assert domain.repair_requests("machine", repair) == receipt
    assert domain.ledger_revision() == after
    assert store.detail("owner", sid) == detail
