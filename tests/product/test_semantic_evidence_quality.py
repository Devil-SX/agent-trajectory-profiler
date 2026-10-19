"""Task costs retain measured totals without pretending uncertain attribution is exact."""

import base64
import hashlib
import uuid
from pathlib import Path

import pytest

from trajectory.product.contracts import SourceChunk, TaskEdit
from trajectory.product.domain import Domain
from trajectory.product.semantic import SemanticStore, digest


@pytest.fixture
def seeded(tmp_path: Path):
    domain = Domain(tmp_path / "quality.db")
    domain.register("owner", "machine", "fixture")
    store = SemanticStore(domain)
    data = b"original\n"
    value = SourceChunk.model_validate(
        {
            "schema_id": "trajectory-source-chunk/1",
            "mutation_id": uuid.uuid4().hex,
            "collector": "fixture",
            "source": "a" * 64,
            "ecosystem": "codex",
            "generation": "first",
            "start": 0,
            "end": len(data),
            "source_bytes": len(data),
            "content": base64.b64encode(data).decode(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "source_name": "fixture.jsonl",
        }
    )
    sid = store.ingest_source("machine", value)["session_id"]
    source, _ = store.archive("owner", sid)
    revision = digest("first:" + str(len(data)))
    operations = [
        {
            "id": f"op-{index}",
            "kind": "llm",
            "call_id": f"call-{index}",
            "location": {"source_line": index * 10 + 1, "byte_start": 0, "byte_end": len(data)},
        }
        for index in range(4)
    ]
    store.save_session("owner", sid, source, revision, {"operations": operations})
    return store, sid, revision, value


def contribution(kind="usage", line=1, call=None):
    return {
        "record": {
            "collector": "fixture",
            "source": "a" * 64,
            "kind": kind,
            "source_line": line,
            "call": call,
        },
        "calls": 1 if kind == "usage" else 0,
        "recorded_tokens": 20 if kind == "usage" else 0,
        "input": 15 if kind == "usage" else 0,
        "output": 5 if kind == "usage" else 0,
        "known_subtotal_usd": 0,
        "priced_calls": 0,
        "unpriced_calls": 1 if kind == "usage" else 0,
        "human_interactions": 1 if kind == "request" else 0,
        "human_input_chars": 7 if kind == "request" else 0,
    }


def test_raw_only_cost_and_human_counts_remain_unknown(seeded):
    store, sid, _, _ = seeded
    detail = store.detail("owner", sid, contributions=[])
    assert detail["coverage"]["ledger_available"] is False
    assert detail["session"]["metrics"]["known_subtotal_usd"] is None
    assert detail["session"]["metrics"]["cost_status"] == "unknown"
    assert detail["session"]["metrics"]["human_interactions"] is None
    assert all(o["metrics"]["input"] is None for o in detail["operations"])


def test_request_only_keeps_human_counts_without_claiming_zero_model_usage(seeded):
    store, sid, _, _ = seeded
    detail = store.detail("owner", sid, contributions=[contribution("request")])
    assert detail["coverage"]["ledger_available"] is True
    assert detail["coverage"]["usage_available"] is False
    assert detail["session"]["metrics"]["human_interactions"] == 1
    assert detail["session"]["metrics"]["human_input_chars"] == 7
    assert detail["session"]["metrics"]["recorded_tokens"] is None
    assert detail["session"]["metrics"]["cost_status"] == "unknown"


def test_nearest_line_attribution_is_visible_and_conserves_actual_usage(seeded):
    store, sid, _, _ = seeded
    detail = store.detail("owner", sid, contributions=[contribution(line=8)])
    assert detail["session"]["metrics"]["recorded_tokens"] == 20
    assert sum(op["metrics"]["recorded_tokens"] for op in detail["operations"]) == 20
    assert detail["session"]["metrics"]["cost_status"] == "unknown"
    assert detail["coverage"]["attribution"]["estimated_records"] == 1
    assert detail["operations"][0]["attribution"]["methods"] == {"preceding_source_line": 1}
    assert detail["session"]["metrics"]["estimated_usage_records"] == 1
    exact = store.detail("owner", sid, contributions=[contribution(line=8, call="call-2")])
    assert exact["operations"][2]["metrics"]["recorded_tokens"] == 20
    assert exact["coverage"]["attribution"]["estimated_records"] == 0


def test_evidence_rejects_offsets_from_superseded_generation(seeded):
    store, sid, _, value = seeded
    assert store.evidence("owner", sid, "op-0")["text"] == "original\n"
    data = b"replaced\n"
    replacement = value.model_copy(
        update={
            "mutation_id": uuid.uuid4().hex,
            "generation": "second",
            "content": base64.b64encode(data).decode(),
            "end": len(data),
            "source_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    )
    store.ingest_source("machine", replacement)
    evidence = store.evidence("owner", sid, "op-0")
    assert evidence["available"] is False
    assert evidence["text"] == ""
    assert "更新" in evidence["message"]


def test_missing_archive_range_does_not_claim_available(seeded):
    store, sid, _, _ = seeded
    with store.domain.connect() as db:
        db.execute("DELETE FROM source_chunks")
    assert store.evidence("owner", sid, "op-0")["available"] is False


def test_merge_preserves_time_order_and_marks_profile_stale(seeded):
    store, sid, revision, _ = seeded
    analysis = {
        "tasks": [
            {"id": "a", "parent_id": None, "title": "A", "operation_ids": ["op-0", "op-2"]},
            {"id": "b", "parent_id": None, "title": "B", "operation_ids": ["op-1", "op-3"]},
        ],
        "provenance": {"profiler": {"profile_sha256": "original"}},
    }
    edit_revision = store.save_analysis("owner", sid, revision, analysis)
    receipt = store.edit_task(
        "owner",
        sid,
        TaskEdit(
            mutation_id=uuid.uuid4().hex,
            analysis_revision=edit_revision,
            action="merge",
            task_id="a",
            other_task_id="b",
        ),
    )
    merged = store.detail("owner", sid, contributions=[])
    assert merged["tasks"][0]["operation_ids"] == ["op-0", "op-1", "op-2", "op-3"]
    assert merged["provenance"]["profiler"]["stale"] is True
    assert merged["provenance"]["profiler"]["profile_sha256"] == "original"
    store.edit_task(
        "owner",
        sid,
        TaskEdit(
            mutation_id=uuid.uuid4().hex,
            analysis_revision=receipt["analysis_revision"],
            action="split",
            task_id="a",
            operation_id="op-1",
        ),
    )
    split = store.detail("owner", sid, contributions=[])
    assert split["tasks"][0]["operation_ids"] == ["op-0"]
    assert split["tasks"][1]["operation_ids"] == ["op-1", "op-2", "op-3"]


def test_background_result_cannot_overwrite_a_human_revision(seeded):
    store, sid, revision, _ = seeded
    initial = {
        "tasks": [
            {
                "id": "root",
                "parent_id": None,
                "title": "Original",
                "operation_ids": ["op-0", "op-1", "op-2", "op-3"],
            }
        ],
        "provenance": {},
    }
    before = store.save_analysis("owner", sid, revision, initial)
    store.edit_task(
        "owner",
        sid,
        TaskEdit(
            mutation_id=uuid.uuid4().hex,
            analysis_revision=before,
            action="rename",
            task_id="root",
            title="Human edit",
        ),
    )
    with pytest.raises(ValueError, match="human edits preserved"):
        store.save_analysis("owner", sid, revision, initial, expected_revision=before)
    assert store.detail("owner", sid, contributions=[])["tasks"][0]["title"] == "Human edit"


def test_overlapping_upload_callers_share_one_transactional_receipt(seeded):
    from concurrent.futures import ThreadPoolExecutor

    store, _, _, value = seeded
    value = value.model_copy(update={"source": "b" * 64, "mutation_id": uuid.uuid4().hex})
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda _: store.ingest_source("machine", value), range(8)))
    assert all(receipt == receipts[0] for receipt in receipts)
    with store.domain.connect() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM source_chunks WHERE source=?", ("b" * 64,)).fetchone()[
                0
            ]
            == 1
        )
        assert (
            db.execute("SELECT COUNT(*) FROM receipts WHERE id=?", (value.mutation_id,)).fetchone()[
                0
            ]
            == 1
        )
