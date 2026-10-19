"""Source transport and semantic projections share one measured-usage ledger."""

import base64
import hashlib
import json
import os
import uuid
from pathlib import Path

import pytest

from trajectory.product.contracts import Batch, SourceChunk, TaskEdit
from trajectory.product.domain import Domain
from trajectory.product.semantic import SemanticStore, digest

SOURCE = "a" * 64


def chunk(
    data: bytes,
    *,
    start: int = 0,
    size: int | None = None,
    generation: str = "generation-1",
    **changes,
) -> SourceChunk:
    return SourceChunk.model_validate(
        {
            "schema_id": "trajectory-source-chunk/1",
            "mutation_id": uuid.uuid4().hex,
            "collector": "fixture",
            "source": SOURCE,
            "ecosystem": "codex",
            "generation": generation,
            "start": start,
            "end": start + len(data),
            "source_bytes": size if size is not None else start + len(data),
            "content": base64.b64encode(data).decode(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "source_name": "fixture.jsonl",
            **changes,
        }
    )


@pytest.fixture
def store(tmp_path: Path) -> SemanticStore:
    domain = Domain(tmp_path / "domain.db")
    domain.register("owner", "machine", "fixture")
    return SemanticStore(domain)


def seed_session(store: SemanticStore) -> tuple[str, str]:
    receipt = store.ingest_source("machine", chunk(b"x\n"))
    sid = receipt["session_id"]
    source, _ = store.archive("owner", sid)
    revision = digest(source["generation"] + ":" + str(source["received_bytes"]))
    operations = [
        {
            "id": f"op-{index}",
            "kind": "prompt" if index == 0 else "llm",
            "timestamp_ms": 1792368000000 + index * 1000,
            "text": f"evidence-{index}",
            "location": {"source_line": index + 1},
        }
        for index in range(4)
    ]
    store.save_session(
        "owner",
        sid,
        source,
        revision,
        {
            "parser": {"name": "agent-session", "version": "0.5.17"},
            "session": {"session_id": "fixture"},
            "operations": operations,
        },
    )
    return sid, revision


def advance_session(store: SemanticStore, sid: str) -> str:
    store.ingest_source("machine", chunk(b"y\n", start=2))
    source, _ = store.archive("owner", sid)
    revision = digest(source["generation"] + ":" + str(source["received_bytes"]))
    parsed = json.loads(store.session_record("owner", sid)["body"])
    store.save_session("owner", sid, source, revision, parsed)
    return revision


def analysis() -> dict:
    return {
        "tasks": [
            {"id": "parent", "parent_id": None, "title": "恢复同步", "operation_ids": []},
            {
                "id": "auth",
                "parent_id": "parent",
                "title": "恢复认证",
                "operation_ids": ["op-0", "op-2"],
            },
            {
                "id": "verify",
                "parent_id": "parent",
                "title": "验证入库",
                "operation_ids": ["op-1", "op-3"],
            },
        ],
        "provenance": {"model": "fixture"},
    }


def test_source_range_replay_has_one_archive_and_one_parse_job(store: SemanticStore) -> None:
    value = chunk(b"source\n")
    first = store.ingest_source("machine", value)
    assert store.ingest_source("machine", value) == first
    store.ingest_source("machine", value.model_copy(update={"mutation_id": uuid.uuid4().hex}))
    with store.domain.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM source_chunks").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM semantic_jobs").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert store.source_progress("machine", "fixture", SOURCE)["next_offset"] == 7


def test_missing_overlapping_and_digest_mismatched_ranges_are_atomic(store: SemanticStore) -> None:
    with pytest.raises(ValueError, match="preceding"):
        store.ingest_source("machine", chunk(b"def", start=3, size=6))
    store.ingest_source("machine", chunk(b"abc", size=6))
    with pytest.raises(ValueError, match="Overlapping"):
        store.ingest_source("machine", chunk(b"xyz", size=6))
    with pytest.raises(ValueError, match="digest"):
        store.ingest_source("machine", chunk(b"def", start=3, sha256="0" * 64))
    assert store.source_progress("machine", "fixture", SOURCE)["next_offset"] == 3
    store.ingest_source("machine", chunk(b"def", start=3))
    sid = store.session_id("fixture", SOURCE)
    assert b"".join(store.archive("owner", sid)[1]) == b"abcdef"


def test_truncated_source_new_generation_replaces_current_content(store: SemanticStore) -> None:
    store.ingest_source("machine", chunk(b"long previous source\n"))
    store.ingest_source("machine", chunk(b"new\n", generation="generation-2"))
    sid = store.session_id("fixture", SOURCE)
    current, chunks = store.archive("owner", sid)
    assert current["generation"] == "generation-2"
    assert current["received_bytes"] == 4
    assert b"".join(chunks) == b"new\n"
    # Historical evidence may remain, but an old generation cannot become current again.
    with pytest.raises(ValueError, match="superseded|generation"):
        store.ingest_source("machine", chunk(b"long previous source\n"))
    assert store.source_progress("machine", "fixture", SOURCE)["generation"] == "generation-2"


def test_source_and_session_content_are_owner_scoped(store: SemanticStore) -> None:
    sid, _ = seed_session(store)
    with pytest.raises(PermissionError):
        store.source_progress("other-machine", "fixture", SOURCE)
    with pytest.raises(ValueError):
        store.archive("other-owner", sid)
    with pytest.raises(ValueError):
        store.detail("other-owner", sid)
    store.domain.register("other-owner", "other-machine", "fixture")
    store.ingest_source("other-machine", chunk(b"other\n"))
    assert b"".join(store.archive("other-owner", sid)[1]) == b"other\n"
    assert b"".join(store.archive("owner", sid)[1]) == b"x\n"


def test_semantic_metrics_conserve_deduplicated_usage_and_human_input(store: SemanticStore) -> None:
    records = [
        {
            "id": "human-request-00001",
            "session": "fixture",
            "task": "task",
            "ecosystem": "codex",
            "timestamp": "2026-10-19T00:00:00Z",
            "kind": "request",
            "source_line": 1,
            "input_origin": "human",
            "input_chars": 12,
        },
        {
            "id": "record-usage-000001",
            "session": "fixture",
            "task": "task",
            "ecosystem": "codex",
            "timestamp": "2026-10-19T00:00:01Z",
            "kind": "usage",
            "source_line": 2,
            "input": 100,
            "output": 20,
            "cached": 30,
            "input_includes_cache": True,
            "consumption": "one-source-call",
        },
    ]
    records.append({**records[1], "id": "record-usage-000002", "source_line": 3})
    store.domain.ingest(
        "machine",
        Batch.model_validate(
            {
                "mutation_id": uuid.uuid4().hex,
                "collector": "fixture",
                "source": SOURCE,
                "revision": 1,
                "source_bytes": 100,
                "read_bytes": 100,
                "parser_version": "fixture/1",
                "records": records,
            }
        ),
    )
    before = store.domain.overview("owner")
    sid, source_revision = seed_session(store)
    store.save_analysis("owner", sid, source_revision, analysis())
    detail = store.detail("owner", sid)
    after = store.domain.overview("owner")
    for overview in (before, after):
        overview.pop("generated_at", None)
    assert after == before
    metrics = detail["session"]["metrics"]
    assert metrics["calls"] == 1
    assert metrics["recorded_tokens"] == 120
    assert metrics["human_interactions"] == 1
    assert metrics["human_input_chars"] == 12
    tasks = {task["id"]: task for task in detail["tasks"]}
    assert len(tasks["auth"]["segments"]) == 2
    for key in ("calls", "recorded_tokens", "human_interactions", "human_input_chars"):
        assert tasks["parent"]["metrics"][key] == metrics[key]
        assert sum(tasks[tid]["metrics"][key] for tid in ("auth", "verify")) == metrics[key]


def test_task_edit_revision_is_compare_and_swap_with_idempotent_replay(
    store: SemanticStore,
) -> None:
    sid, source_revision = seed_session(store)
    revision = store.save_analysis("owner", sid, source_revision, analysis())
    edit = TaskEdit(
        mutation_id=uuid.uuid4().hex,
        analysis_revision=revision,
        action="rename",
        task_id="auth",
        title="认证修复",
    )
    first = store.edit_task("owner", sid, edit)
    assert first["analysis_revision"] != revision
    assert store.edit_task("owner", sid, edit) == first
    with pytest.raises(ValueError, match="changed|refresh"):
        store.edit_task("owner", sid, edit.model_copy(update={"mutation_id": uuid.uuid4().hex}))
    assert (
        next(t for t in store.detail("owner", sid)["tasks"] if t["id"] == "auth")["title"]
        == "认证修复"
    )


def test_sibling_merge_and_split_preserve_single_operation_ownership(store: SemanticStore) -> None:
    sid, source_revision = seed_session(store)
    revision = store.save_analysis("owner", sid, source_revision, analysis())
    merged = store.edit_task(
        "owner",
        sid,
        TaskEdit(
            mutation_id=uuid.uuid4().hex,
            analysis_revision=revision,
            action="merge",
            task_id="auth",
            other_task_id="verify",
        ),
    )
    detail = store.detail("owner", sid)
    assert len(detail["tasks"]) == 2
    assert {operation["task_id"] for operation in detail["operations"]} == {"auth"}
    store.edit_task(
        "owner",
        sid,
        TaskEdit(
            mutation_id=uuid.uuid4().hex,
            analysis_revision=merged["analysis_revision"],
            action="split",
            task_id="auth",
            operation_id="op-1",
        ),
    )
    detail = store.detail("owner", sid)
    leaf_ids = [
        oid
        for task in detail["tasks"]
        if task["parent_id"] == "parent"
        for oid in task["operation_ids"]
    ]
    assert sorted(leaf_ids) == ["op-0", "op-1", "op-2", "op-3"]
    assert len(leaf_ids) == len(set(leaf_ids))


def test_parser_result_cannot_overwrite_newer_source_archive(store: SemanticStore) -> None:
    sid, source_revision = seed_session(store)
    source, _ = store.archive("owner", sid)
    old_body = json.loads(store.session_record("owner", sid)["body"])
    store.ingest_source("machine", chunk(b"new\n", start=2))
    with pytest.raises(ValueError, match="changed|revision|stale"):
        store.save_session("owner", sid, source, source_revision, old_body)


def test_source_revision_history_preserves_old_tasks_and_rejects_stale_writers(
    store: SemanticStore,
) -> None:
    sid, old_source = seed_session(store)
    revision = store.save_analysis("owner", sid, old_source, analysis())
    advance_session(store, sid)
    detail = store.detail("owner", sid)
    assert detail["status"] != "complete"
    assert detail["tasks"]
    assert detail["analysis_snapshot_available"] is True
    assert detail["source_revision"] == old_source
    with pytest.raises(ValueError, match="changed|revision|refresh|stale"):
        store.save_analysis("owner", sid, old_source, analysis())
    with pytest.raises(ValueError, match="changed|revision|refresh|stale"):
        store.edit_task(
            "owner",
            sid,
            TaskEdit(
                mutation_id=uuid.uuid4().hex,
                analysis_revision=revision,
                action="rename",
                task_id="auth",
                title="stale",
            ),
        )


@pytest.mark.skipif(
    not os.environ.get("TRAJECTORY_AGENTPPROF"),
    reason="native CLI is installed in remote integration jobs",
)
def test_real_profiler_handles_noncontiguous_tasks_and_nested_paths(
    store: SemanticStore, tmp_path: Path
) -> None:
    from trajectory.product.semantic_runtime import AnalysisRuntime

    sid, _ = seed_session(store)
    detail = store.detail("owner", sid)
    for operation in detail["operations"]:
        operation["metrics"]["recorded_tokens"] = 10
    runtime = AnalysisRuntime(store)
    result = runtime.profile(tmp_path, detail, analysis())
    assert result["operation_count"] == 4
    trace = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
    operations = {row["id"]: row for row in trace if row["id"].startswith("op-")}
    assert operations["op-0"]["path"] == operations["op-2"]["path"]
    assert operations["op-1"]["path"] == operations["op-3"]["path"]
    assert operations["op-0"]["path"][-2:] == ["恢复同步", "恢复认证"]
    assert operations["op-1"]["path"][-2:] == ["恢复同步", "验证入库"]
    folded = (tmp_path / "stacks.folded").read_text().splitlines()
    assert sum(int(line.rsplit(" ", 1)[1]) for line in folded) == 40
