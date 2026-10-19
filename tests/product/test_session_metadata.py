import base64
import hashlib
import uuid
from pathlib import Path

from trajectory.product.contracts import SourceChunk
from trajectory.product.domain import Domain
from trajectory.product.semantic import SemanticStore, digest
from trajectory.product.session_metadata import extract


def seeded(tmp_path: Path):
    domain = Domain(tmp_path / "metadata.db")
    domain.register("owner", "machine", "fixture")
    store = SemanticStore(domain)

    def add(index, cwd, first, day, parent=None):
        raw = b'{"type":"fixture"}\n'
        src = hashlib.sha256(str(index).encode()).hexdigest()
        req = SourceChunk(
            schema_id="trajectory-source-chunk/1",
            mutation_id=uuid.uuid4().hex,
            collector="fixture",
            source=src,
            ecosystem="codex",
            generation="v1",
            start=0,
            end=len(raw),
            source_bytes=len(raw),
            content=base64.b64encode(raw).decode(),
            sha256=hashlib.sha256(raw).hexdigest(),
            source_name="session.jsonl",
        )
        sid = store.ingest_source("machine", req)["session_id"]
        source, _ = store.archive("owner", sid)
        revision = digest("v1:" + str(len(raw)))
        parsed = {
            "metadata": {
                "cwd": cwd,
                "native_session_id": str(index),
                "parent_session_id": parent,
                "started_at": day + "T01:00:00Z",
                "last_activity_at": day + "T02:00:00Z",
                "first_user_message": first,
                "abstract": None,
            },
            "operations": [{"id": "op" + str(index), "kind": "prompt", "text": first}],
        }
        store.save_session("owner", sid, source, revision, parsed)
        return sid, revision

    return store, add


def test_filters_use_real_analysis_and_original_dates_before_pagination(tmp_path):
    store, add = seeded(tmp_path)
    a, revision = add(1, "/home/sdu/embodied", "检查 CPM 实验", "2026-10-05")
    b, _ = add(2, "/home/sdu/BatCave", "维护网站", "2026-10-18")
    c, _ = add(3, "/home/sdu/embodied", "查看论文", "2026-10-07", parent="1")
    store.save_analysis(
        "owner",
        a,
        revision,
        {"tasks": [{"id": "root", "parent_id": None, "title": "测试", "operation_ids": ["op1"]}]},
    )
    result = store.sessions("owner", analysis_status="analyzed", limit=1)
    assert [r["id"] for r in result["sessions"]] == [a]
    assert result["total"] == 1 and result["status_counts"]["all"] == 3
    assert result["sessions"][0]["display_title"] == "检查 CPM 实验"
    assert result["sessions"][0]["summary"] is None
    result = store.sessions("owner", cwd="/home/sdu/embodied", limit=1)
    assert result["total"] == 2 and result["next_cursor"] == "1"
    assert result["sessions"][0]["id"] == c and result["sessions"][0]["parent_session_id"] == a
    assert (
        store.sessions("owner", cwd="/home/sdu/embodied", limit=1, cursor="1")["sessions"][0]["id"]
        == a
    )
    assert len(store.sessions("owner", until="2026-10-06")["sessions"]) == 1
    assert store.sessions("owner", q="网站")["sessions"][0]["id"] == b
    assert store.sessions("other")["sessions"] == []


def test_metadata_migration_uses_ir_and_preserves_analysis_status(tmp_path):
    store, add = seeded(tmp_path)
    sid, _ = add(1, "/home/sdu/embodied", "原始提示，不生成摘要", "2026-10-02")
    with store.domain.connect() as db:
        db.execute("DELETE FROM semantic_session_metadata")
    result = store.sessions("owner")
    assert result["sessions"][0]["id"] == sid
    assert result["sessions"][0]["has_analysis"] is False
    assert result["sessions"][0]["first_user_message"] == "原始提示，不生成摘要"
    assert result["sessions"][0]["started_at"].startswith("2026-10-02")
    assert store.backfill_metadata("owner") == 0


def test_unified_ir_fallback_skips_injected_instructions_and_reads_lineage():
    value = extract(
        {
            "source_records": [
                {
                    "timestamp_ms": 1791158400000,
                    "lineage": {
                        "id": "native",
                        "source": {
                            "subagent": {
                                "thread_spawn": {
                                    "parent_thread_id": "parent",
                                    "agent_path": "/root/task",
                                }
                            }
                        },
                    },
                }
            ],
            "operations": [
                {"kind": "prompt", "text": "# AGENTS.md instructions for test"},
                {"kind": "prompt", "text": "检查真实任务"},
            ],
        },
        "session.jsonl",
    )
    assert value["display_title"] == "检查真实任务" and value["native_session_id"] == "native"
    assert value["parent_native_session_id"] == "parent" and value["agent_path"] == "/root/task"
    assert value["cwd"] is None and value["summary"] is None
