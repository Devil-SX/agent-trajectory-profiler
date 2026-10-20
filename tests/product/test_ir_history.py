"""Retained inputs keep one canonical body and never borrow newer ledger metrics."""

import base64
import hashlib
import json
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_semantic_evidence_quality import append_source, contribution
from test_semantic_evidence_quality import seeded as seeded

from trajectory.product import semantic_model
from trajectory.product.contracts import AnalysisRequest
from trajectory.product.semantic import COUNTERS, digest
from trajectory.product.semantic_runtime import AnalysisRuntime
from trajectory.product.server import Principal, create_app


def save_result(store, sid, revision):
    result = {
        "tasks": [
            {"id": "saved", "parent_id": None, "title": "Saved snapshot", "operation_ids": ["op-0"]}
        ],
        "provenance": {
            "model": "glm-5.3",
            "analysis_usage": [{"usage": {"prompt_tokens": 30, "completion_tokens": 3}}],
        },
    }
    store.save_analysis("owner", sid, revision, result)
    return result


def append_and_parse(store, sid, value):
    old = json.loads(store.session_record("owner", sid)["body"])
    append_source(store, value)
    source, _ = store.archive("owner", sid)
    revision = digest(source["generation"] + ":" + str(source["received_bytes"]))
    old["operations"].append(
        {
            "id": "appended-op",
            "kind": "llm",
            "text": "new evidence",
            "location": {
                "source_line": 100,
                "byte_start": value.end,
                "byte_end": source["received_bytes"],
            },
        }
    )
    store.save_session("owner", sid, source, revision, old)
    return revision


def test_append_parse_retains_saved_tree_evidence_and_cost_with_unknown_execution(seeded):
    store, sid, old_revision, value = seeded
    saved = save_result(store, sid, old_revision)
    original = store.detail("owner", sid, contributions=[contribution()])
    new_revision = append_and_parse(store, sid, value)
    detail = store.detail("owner", sid, contributions=[contribution(line=999)])
    assert detail["source_revision"] == old_revision
    assert (
        detail["current_parsed_source_revision"]
        == detail["current_source_revision"]
        == new_revision
    )
    assert detail["analysis_matches_parsed"] is False
    assert detail["analysis_snapshot_available"] is True
    assert detail["historical_snapshot"] is True
    assert detail["analysis_current"] is False and detail["source_pending"] is False
    assert detail["tasks"][0]["title"] == "Saved snapshot"
    assert detail["analysis_cost"] == original["analysis_cost"]
    assert detail["provenance"] == saved["provenance"]
    assert detail["analysis_revision"] == original["analysis_revision"]
    assert all(detail["session"]["metrics"][key] is None for key in COUNTERS)
    assert all(op["metrics"]["recorded_tokens"] is None for op in detail["operations"])
    assert any("历史快照" in text for text in detail["coverage"]["warnings"])
    assert not any("等待重新解析" in text for text in detail["coverage"]["warnings"])
    assert (
        store.evidence("owner", sid, "op-0", source_revision=old_revision)["text"] == "original\n"
    )
    assert store.evidence("owner", sid, "op-0")["source_revision"] == old_revision
    current = store.detail(
        "owner", sid, source_revision=new_revision, contributions=[contribution()]
    )
    assert current["operations"][-1]["id"] == "appended-op"
    assert current["tasks"] == [] and current["analysis_snapshot_available"] is False
    with store.domain.connect() as db:
        assert db.execute("SELECT count(*) FROM semantic_ir_history").fetchone()[0] == 1
        assert (
            db.execute("SELECT source_revision FROM semantic_sessions").fetchone()[0]
            == new_revision
        )
        assert (
            db.execute("SELECT source_revision FROM semantic_analyses").fetchone()[0]
            == old_revision
        )
        assert (
            db.execute(
                "SELECT 1 FROM semantic_sessions c JOIN semantic_ir_history h "
                "ON c.owner=h.owner AND c.id=h.id AND c.source_revision=h.source_revision"
            ).fetchone()
            is None
        )
        assert (
            json.loads(db.execute("SELECT body FROM semantic_sessions").fetchone()[0])[
                "operations"
            ][-1]["id"]
            == "appended-op"
        )


@pytest.mark.parametrize("status", ["queued", "running", "failed"])
def test_unfinished_analysis_references_are_retained_and_resume_source_guard_stays(seeded, status):
    store, sid, old_revision, value = seeded
    receipt = store.request_analysis("owner", sid, AnalysisRequest(mutation_id=uuid.uuid4().hex))
    with store.domain.connect() as db:
        db.execute("UPDATE semantic_jobs SET status=? WHERE id=?", (status, receipt["job_id"]))
    new_revision = append_and_parse(store, sid, value)
    assert store.session_record("owner", sid, old_revision)["historical_snapshot"] is True
    detail = store.detail("owner", sid)
    assert (
        detail["source_revision"] == old_revision
        and detail["current_parsed_source_revision"] == new_revision
    )
    assert detail["status"] == status
    assert not detail["resume"]["eligible"]


def test_unreferenced_old_ir_is_not_copied(seeded):
    store, sid, _, value = seeded
    append_and_parse(store, sid, value)
    with store.domain.connect() as db:
        assert db.execute("SELECT count(*) FROM semantic_ir_history").fetchone()[0] == 0


def test_referenced_same_raw_revision_rejects_changed_operations_without_ledger_mutation(seeded):
    store, sid, revision, _ = seeded
    save_result(store, sid, revision)
    before = store.session_record("owner", sid)["body"]
    source, _ = store.archive("owner", sid)
    parsed = json.loads(before)
    parsed["operations"][0]["text"] = "different parser interpretation"
    with pytest.raises(ValueError, match="explicit parser migration"):
        store.save_session("owner", sid, source, revision, parsed)
    assert store.session_record("owner", sid)["body"] == before
    assert store.detail("owner", sid)["analysis_snapshot_available"] is True


def test_history_integrity_source_identity_owner_and_generation_fail_closed(seeded):
    store, sid, old_revision, value = seeded
    save_result(store, sid, old_revision)
    append_and_parse(store, sid, value)
    with pytest.raises(ValueError):
        store.detail("other-owner", sid, source_revision=old_revision)
    with pytest.raises(ValueError):
        store.evidence("other-owner", sid, "op-0", source_revision=old_revision)
    with store.domain.connect() as db:
        db.execute("UPDATE semantic_ir_history SET source='different-source'")
    with pytest.raises(ValueError, match="source identity"):
        store.detail("owner", sid)
    with store.domain.connect() as db:
        db.execute("UPDATE semantic_ir_history SET source=?,body='{}'", (value.source,))
    with pytest.raises(ValueError, match="integrity"):
        store.evidence("owner", sid, "op-0", source_revision=old_revision)


def test_history_evidence_never_reinterprets_changed_generation(seeded):
    store, sid, old_revision, value = seeded
    save_result(store, sid, old_revision)
    append_and_parse(store, sid, value)
    data = b"different generation\n"
    store.ingest_source(
        "machine",
        value.model_copy(
            update={
                "mutation_id": uuid.uuid4().hex,
                "generation": "replacement",
                "start": 0,
                "end": len(data),
                "source_bytes": len(data),
                "content": base64.b64encode(data).decode(),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        ),
    )
    detail = store.detail("owner", sid)
    assert detail["tasks"] and detail["source_pending"] is True
    assert store.evidence("owner", sid, "op-0", source_revision=old_revision)["available"] is False


def test_runtime_new_job_explicitly_pins_new_ir_instead_of_stored_analysis(seeded, monkeypatch):
    store, sid, old_revision, value = seeded
    save_result(store, sid, old_revision)
    new_revision = append_and_parse(store, sid, value)
    with store.domain.connect() as db:
        db.execute("UPDATE semantic_jobs SET status='complete' WHERE kind='parse'")
    queued = store.request_analysis("owner", sid, AnalysisRequest(mutation_id=uuid.uuid4().hex))
    observed = {}
    original = store.session_record

    def record(*args, **kwargs):
        observed["pin"] = kwargs["source_revision"]
        return original(*args, **kwargs)

    def segment(operations, title, **kwargs):
        observed["ids"] = [op["id"] for op in operations]
        observed["job"] = kwargs["analysis_id"]
        observed["source_context"] = kwargs["source_context"]
        raise semantic_model.SemanticModelError("fixture stops before any paid call")

    monkeypatch.setattr(store, "session_record", record)
    monkeypatch.setattr(semantic_model, "segment", segment)
    runtime = AnalysisRuntime(store)
    try:
        assert runtime.process_next()
    finally:
        runtime.close()
    assert observed["pin"] == new_revision
    assert observed["ids"][-1] == "appended-op"
    assert observed["job"] == queued["job_id"]
    assert observed["source_context"]["source_revision"] == new_revision
    assert (
        observed["source_context"]["ir_body_sha256"]
        == hashlib.sha256(original("owner", sid, new_revision)["body"].encode()).hexdigest()
    )


def test_http_revision_pin_and_331_unpinned_reader_keep_saved_snapshot(seeded):
    store, sid, old_revision, value = seeded
    save_result(store, sid, old_revision)
    new_revision = append_and_parse(store, sid, value)

    def auth(request, scope):
        actor = request.headers.get("authorization", "").removeprefix("Bearer ")
        if actor != "owner":
            raise HTTPException(403, "denied")
        return Principal(actor, scopes=("read",))

    client = TestClient(create_app(store.domain.path, auth))
    headers = {"Authorization": "Bearer owner"}
    base = f"/trajectory/api/sessions/{sid}"
    old = client.get(base + "/analysis", headers=headers).json()
    assert old["source_revision"] == old_revision and old["tasks"]
    assert (
        client.get(base + "/analysis?source_revision=" + new_revision, headers=headers).json()[
            "tasks"
        ]
        == []
    )
    # An old rendered button pins its revision while the current pointer can advance.
    evidence = client.get(
        base + "/operations/op-0/evidence?source_revision=" + old_revision, headers=headers
    )
    assert evidence.status_code == 200 and evidence.json()["text"] == "original\n"
    assert (
        client.get(base + "/operations/op-0/evidence", headers=headers).json()["text"]
        == "original\n"
    )
    assert (
        client.get(base + "/analysis?source_revision=missing", headers=headers).status_code == 409
    )
    assert client.get(base + "/analysis?source_revision=" + old_revision).status_code == 403


def test_only_original_referenced_ir_is_retained_across_continuous_appends(seeded):
    store, sid, old_revision, value = seeded
    save_result(store, sid, old_revision)
    intermediate = append_and_parse(store, sid, value)
    source, _ = store.archive("owner", sid)
    data = b"third snapshot\n"
    store.ingest_source(
        "machine",
        value.model_copy(
            update={
                "mutation_id": uuid.uuid4().hex,
                "start": source["received_bytes"],
                "end": source["received_bytes"] + len(data),
                "source_bytes": source["received_bytes"] + len(data),
                "content": base64.b64encode(data).decode(),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        ),
    )
    source, _ = store.archive("owner", sid)
    parsed = json.loads(store.session_record("owner", sid)["body"])
    last = digest(source["generation"] + ":" + str(source["received_bytes"]))
    store.save_session("owner", sid, source, last, parsed)
    assert store.detail("owner", sid)["source_revision"] == old_revision
    with store.domain.connect() as db:
        assert (
            db.execute("SELECT source_revision FROM semantic_ir_history").fetchall()[0][0]
            == old_revision
        )
        assert db.execute("SELECT count(*) FROM semantic_ir_history").fetchone()[0] == 1
        assert db.execute("SELECT source_revision FROM semantic_sessions").fetchone()[0] == last
    with pytest.raises(ValueError, match="unavailable"):
        store.session_record("owner", sid, intermediate)


def test_retain_and_current_move_roll_back_as_one_domain_transaction(seeded, monkeypatch):
    store, sid, revision, value = seeded
    save_result(store, sid, revision)
    before = store.session_record("owner", sid)["body"]

    def rejected(*args):
        raise ValueError("fixture importer failure after history retention")

    monkeypatch.setattr(store.domain, "import_native_measurements", rejected)
    with pytest.raises(ValueError, match="importer failure"):
        append_and_parse(store, sid, value)
    assert store.session_record("owner", sid)["body"] == before
    with store.domain.connect() as db:
        assert db.execute("SELECT count(*) FROM semantic_ir_history").fetchone()[0] == 0
        assert db.execute("SELECT source_revision FROM semantic_analyses").fetchone()[0] == revision


def test_readers_never_observe_uncommitted_dual_current_history(seeded, monkeypatch):
    store, sid, revision, value = seeded
    save_result(store, sid, revision)
    retain = store._retain_ir
    observed = []

    def checked(db, record):
        retain(db, record)
        with store.domain.connect() as reader:
            observed.append(
                (
                    reader.execute("SELECT source_revision FROM semantic_sessions").fetchone()[0],
                    reader.execute("SELECT count(*) FROM semantic_ir_history").fetchone()[0],
                )
            )

    monkeypatch.setattr(store, "_retain_ir", checked)
    new_revision = append_and_parse(store, sid, value)
    assert observed == [(revision, 0)]
    assert store.session_record("owner", sid)["source_revision"] == new_revision
    assert store.session_record("owner", sid, revision)["historical_snapshot"] is True


def test_parse_advance_during_ledger_scan_never_assigns_latest_measurements_to_old_ir(
    seeded, monkeypatch
):
    store, sid, revision, value = seeded
    save_result(store, sid, revision)

    def newer(*args):
        append_and_parse(store, sid, value)
        return [contribution(line=999), contribution("request", line=999)]

    monkeypatch.setattr(store.domain, "source_contributions", newer)
    detail = store.detail("owner", sid)
    assert detail["analysis_snapshot_available"] and detail["historical_snapshot"]
    assert detail["source_pending"] is False
    assert detail["source_revision"] == revision
    assert detail["session"]["metrics"]["human_interactions"] is None
    assert detail["session"]["metrics"]["recorded_tokens"] is None
    assert detail["tasks"][0]["metrics"]["recorded_tokens"] is None
    assert detail["analysis_cost"] is not None


def test_normal_coordinator_finishes_paid_snapshot_before_queued_parse(seeded):
    store, sid, revision, value = seeded
    with store.domain.connect() as db:
        db.execute("UPDATE semantic_jobs SET status='complete' WHERE kind='parse'")
    receipt = store.request_analysis("owner", sid, AnalysisRequest(mutation_id=uuid.uuid4().hex))
    running = store.claim_job()
    assert running["id"] == receipt["job_id"]
    append_source(store, value)
    assert store.claim_job() is None
    save_result(store, sid, revision)
    store.finish_job(running)
    queued_parse = store.claim_job()
    assert queued_parse["kind"] == "parse"
    source, _ = store.archive("owner", sid)
    parsed = json.loads(store.session_record("owner", sid)["body"])
    store.save_session("owner", sid, source, queued_parse["source_revision"], parsed)
    assert store.detail("owner", sid)["analysis_snapshot_available"] is True
    assert store.detail("owner", sid)["source_revision"] == revision


def test_metadata_only_refresh_of_referenced_raw_revision_is_allowed(seeded):
    store, sid, revision, _ = seeded
    save_result(store, sid, revision)
    source, _ = store.archive("owner", sid)
    parsed = json.loads(store.session_record("owner", sid)["body"])
    parsed["metadata"] = {"cwd": "/fixture/updated-metadata"}
    store.save_session("owner", sid, source, revision, parsed)
    assert store.detail("owner", sid)["tasks"]
    with store.domain.connect() as db:
        assert db.execute("SELECT count(*) FROM semantic_ir_history").fetchone()[0] == 0


def test_explicit_old_ir_pin_never_claims_newer_analysis_as_current(seeded):
    store, sid, old_revision, value = seeded
    save_result(store, sid, old_revision)
    new_revision = append_and_parse(store, sid, value)
    save_result(store, sid, new_revision)
    detail = store.detail("owner", sid, source_revision=old_revision)
    assert detail["analysis_matches_parsed"] is True
    assert detail["analysis_snapshot_available"] is False
    assert detail["analysis_current"] is False
    assert detail["tasks"] == []
    assert any("输入不同" in warning for warning in detail["coverage"]["warnings"])


def test_duplicate_current_history_authority_is_rejected_without_body_guessing(seeded):
    store, sid, revision, _ = seeded
    body = store.session_record("owner", sid)["body"]
    with store.domain.connect() as db:
        db.execute(
            "INSERT INTO semantic_ir_history SELECT owner,id,collector,source,title,agent,"
            "source_revision,body,updated,? FROM semantic_sessions WHERE owner=? AND id=?",
            (digest(body), "owner", sid),
        )
    with pytest.raises(ValueError, match="duplicate current and history"):
        store.session_record("owner", sid, revision)
    with pytest.raises(ValueError, match="duplicate current and history"):
        store.detail("owner", sid)
    with pytest.raises(ValueError, match="duplicate current and history"):
        store.evidence("owner", sid, "op-0", source_revision=revision)


def test_queued_reanalysis_of_newer_revision_keeps_saved_tree_on_screen(seeded):
    store, sid, old_revision, value = seeded
    save_result(store, sid, old_revision)
    new_revision = append_and_parse(store, sid, value)
    with store.domain.connect() as db:
        db.execute("UPDATE semantic_jobs SET status='complete' WHERE kind='parse'")
    store.request_analysis("owner", sid, AnalysisRequest(mutation_id=uuid.uuid4().hex))
    detail = store.detail("owner", sid)
    assert detail["source_revision"] == detail["analysis_source_revision"] == old_revision
    assert detail["current_parsed_source_revision"] == new_revision
    assert detail["analysis_snapshot_available"] is True
    assert detail["tasks"][0]["title"] == "Saved snapshot"
    assert detail["status"] == "stale"
    assert detail["reanalysis"] == {
        "status": "queued",
        "source_revision": new_revision,
        "progress": {},
    }
    assert any("历史快照" in text for text in detail["coverage"]["warnings"])


def test_saved_snapshot_keeps_measured_cost_inside_its_own_line_watermark(seeded):
    store, sid, old_revision, value = seeded
    save_result(store, sid, old_revision)
    append_and_parse(store, sid, value)
    detail = store.detail(
        "owner",
        sid,
        contributions=[contribution(line=1), contribution(line=999)],
    )
    assert detail["historical_snapshot"] is True
    assert detail["coverage"]["attribution"]["snapshot_scope"] == "bounded"
    assert detail["coverage"]["attribution"]["snapshot_line_watermark"] == 31
    assert detail["coverage"]["attribution"]["excluded_records"] == 1
    assert detail["coverage"]["attribution"]["usage_available"] is True
    assert detail["session"]["metrics"]["recorded_tokens"] == 20
    assert detail["tasks"][0]["title"] == "Saved snapshot"
    assert detail["tasks"][0]["metrics"]["input"] == 15
    assert any("水位" in text for text in detail["coverage"]["warnings"])


def test_pending_append_before_reparse_keeps_bounded_cost_and_excludes_new_records(seeded):
    store, sid, old_revision, value = seeded
    save_result(store, sid, old_revision)
    append_source(store, value)
    detail = store.detail(
        "owner",
        sid,
        contributions=[contribution(line=1), contribution(line=999)],
    )
    assert detail["source_pending"] is True
    assert detail["historical_snapshot"] is False
    assert detail["analysis_snapshot_available"] is True
    assert detail["reanalysis"] is None
    assert detail["coverage"]["attribution"]["snapshot_scope"] == "bounded"
    assert detail["coverage"]["attribution"]["excluded_records"] == 1
    assert detail["session"]["metrics"]["recorded_tokens"] == 20
    assert detail["tasks"][0]["metrics"]["input"] == 15
    assert any("追加" in text for text in detail["coverage"]["warnings"])


def test_changed_generation_never_attributes_retained_snapshot_cost(seeded):
    store, sid, old_revision, value = seeded
    save_result(store, sid, old_revision)
    append_and_parse(store, sid, value)
    data = b"different generation\n"
    store.ingest_source(
        "machine",
        value.model_copy(
            update={
                "mutation_id": uuid.uuid4().hex,
                "generation": "replacement",
                "start": 0,
                "end": len(data),
                "source_bytes": len(data),
                "content": base64.b64encode(data).decode(),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        ),
    )
    detail = store.detail("owner", sid, contributions=[contribution(line=1)])
    assert detail["coverage"]["attribution"]["snapshot_scope"] == "unavailable"
    assert detail["coverage"]["attribution"]["excluded_records"] == 1
    assert detail["coverage"]["attribution"]["ledger_available"] is True
    assert detail["coverage"]["attribution"]["usage_available"] is False
    assert detail["session"]["metrics"]["recorded_tokens"] is None
    assert any("更换版本" in text for text in detail["coverage"]["warnings"])


def test_snapshot_watermark_prefers_retained_source_records(seeded):
    store, sid, revision, value = seeded
    parsed = json.loads(store.session_record("owner", sid)["body"])
    # A trailing record without an operation still proves the snapshot covers its line.
    parsed["source_records"] = [{"source_line": 1}, {"source_line": 44}]
    source, _ = store.archive("owner", sid)
    store.save_session("owner", sid, source, revision, parsed)
    save_result(store, sid, revision)
    append_source(store, value)
    detail = store.detail(
        "owner",
        sid,
        contributions=[contribution(line=40), contribution(line=45)],
    )
    attribution = detail["coverage"]["attribution"]
    assert detail["source_pending"] is True
    assert attribution["snapshot_scope"] == "bounded"
    assert attribution["snapshot_line_watermark"] == 44
    assert attribution["excluded_records"] == 1
    assert detail["session"]["metrics"]["recorded_tokens"] == 20
