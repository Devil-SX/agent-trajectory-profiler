"""Run the shared Sparkstead projector in the isolated remote environment."""

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location(
    "request_repair_client", TOOLS / "trajectory_request_repair.py"
)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


@pytest.mark.skipif(
    not os.environ.get("TRAJECTORY_REQUEST_PROJECTOR"),
    reason="Requires sealed Sparkstead projector",
)
def test_shared_projector_preserves_human_unicode_and_excludes_context_and_tools(tmp_path):
    records = [
        {"type": "session_meta", "payload": {"id": "fixture", "source": "vscode"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "中 A 😀\n"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "中 A 😀\n"}],
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "user_message",
                "message": "<environment_context>injected</environment_context>",
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {"last_token_usage": {"input_tokens": 99, "output_tokens": 5}},
            },
        },
    ]
    raw = ("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n").encode()
    path = tmp_path / "fixture.jsonl"
    path.write_bytes(raw)
    result = client.project(
        {"path": str(path), "ecosystem": "codex"},
        "a" * 64,
        len(raw),
        os.environ["TRAJECTORY_REQUEST_PROJECTOR"],
        os.environ.get("TRAJECTORY_NODE", "node"),
    )
    assert result["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["parse_errors"] == 0 and result["complete_bytes"] == len(raw)
    assert len(result["records"]) == 2
    human, system = result["records"]
    assert human["input_origin"] == "human" and human["input_chars"] == 3
    assert system["input_origin"] == "system"
    assert {record["kind"] for record in result["records"]} == {"request"}
    assert "injected" not in json.dumps(result)


def test_dry_run_uses_shared_collector_identity_and_never_writes_checkpoint_or_http(
    tmp_path, monkeypatch
):
    config = {
        "url": "https://fixture.test/trajectory/api/source-chunks",
        "state": str(tmp_path / "state.sqlite"),
        "credential": "fixture",
    }
    source = "a" * 64
    monkeypatch.setattr(
        client.sync,
        "validate_manifest",
        lambda config: (
            "existing-collector",
            [{"legacy_path": "fixture", "path": "fixture.jsonl", "ecosystem": "codex"}],
        ),
    )
    monkeypatch.setattr(client.sync, "source_id", lambda collector, path: source)
    monkeypatch.setattr(client.sync, "credentials", lambda *args: "fixture-token")
    monkeypatch.setattr(
        client.sync,
        "remote_progress",
        lambda *args: {"ledger_revision": 7, "generation": "first", "next_offset": 10},
    )
    monkeypatch.setattr(
        client,
        "project",
        lambda *args: {
            "parser_version": "sparkstead-trajectory/3",
            "complete_bytes": 10,
            "source_sha256": "b" * 64,
            "records": [{"input_origin": "human"}],
        },
    )
    monkeypatch.setattr(
        client.sync, "http_opener", lambda *args: pytest.fail("Dry run sent a mutation")
    )
    projector = tmp_path / "projector.mjs"
    projector.write_text("// sealed fixture")
    result = client.run(config, str(projector), apply=False)
    assert result["sources"][0]["status"] == "ready"
    assert result["sources"][0]["human_requests"] == 1
    assert result["collector"] == "existing-collector"
    assert result["collector_checkpoint_writes"] == result["usage_writes"] == 0
    assert not Path(config["state"]).exists()


@pytest.mark.skipif(
    not os.environ.get("TRAJECTORY_REQUEST_PROJECTOR"),
    reason="Requires sealed Sparkstead projector",
)
def test_shared_projector_quarantines_large_lines_without_losing_surrounding_requests(tmp_path):
    records = [
        {"type": "session_meta", "payload": {"id": "fixture", "source": "vscode"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "before"}},
        {"type": "notice", "padding": "x" * (600 * 1024)},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "after"}},
    ]
    raw = ("\n".join(json.dumps(record) for record in records) + "\n").encode()
    path = tmp_path / "large.jsonl"
    path.write_bytes(raw)
    result = client.project(
        {"path": str(path), "ecosystem": "codex"},
        "a" * 64,
        len(raw),
        os.environ["TRAJECTORY_REQUEST_PROJECTOR"],
        os.environ.get("TRAJECTORY_NODE", "node"),
    )
    assert result["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert len(result["records"]) == 2
    assert result["quarantined_source_lines"] == [3]


@pytest.mark.parametrize("interaction", [None, "provider-message-identity-0001"])
def test_duplicate_native_sessions_require_provider_identity_for_repair(
    tmp_path, monkeypatch, interaction
):
    native = "11111111-2222-3333-4444-555555555555"
    specs = [
        {
            "legacy_path": name,
            "path": str(tmp_path / f"{name}-{native}.jsonl"),
            "ecosystem": "codex",
        }
        for name in ("first", "copy")
    ]
    config = {
        "url": "https://fixture.test/trajectory/api/source-chunks",
        "state": str(tmp_path / "state.sqlite"),
        "credential": "fixture",
    }
    monkeypatch.setattr(
        client.sync, "validate_manifest", lambda config: ("existing-collector", specs)
    )
    monkeypatch.setattr(client.sync, "credentials", lambda *args: "fixture-token")
    monkeypatch.setattr(
        client.sync,
        "remote_progress",
        lambda *args: {"ledger_revision": 7, "generation": "first", "next_offset": 10},
    )
    monkeypatch.setattr(
        client,
        "project",
        lambda *args: {
            "parser_version": "sparkstead-trajectory/3",
            "complete_bytes": 10,
            "source_sha256": "b" * 64,
            "records": [
                {
                    "id": "request",
                    "session": native,
                    "source_line": 2,
                    "input_origin": "human",
                    "interaction_id": interaction,
                }
            ],
        },
    )
    projector = tmp_path / "projector.mjs"
    projector.write_text("// sealed fixture")
    result = client.run(config, str(projector), max_sources=1, apply=False)
    row = result["sources"][0]
    assert row["identity_unverified_requests"] == (0 if interaction else 1)
    assert row["human_requests"] == (1 if interaction else 0)


@pytest.mark.parametrize(
    "durable,queue_generation,remaining",
    [(True, "first", 0), (False, "first", 1), (True, "new-generation", 1)],
)
def test_repair_receipt_clears_only_durable_generation_fenced_queue(
    tmp_path, monkeypatch, durable, queue_generation, remaining
):
    import io
    from types import SimpleNamespace

    config = {
        "url": "https://fixture.test/trajectory/api/source-chunks",
        "state": str(tmp_path / "state.sqlite"),
        "credential": "fixture",
    }
    spec = {"legacy_path": "fixture", "path": "fixture.jsonl", "ecosystem": "codex"}
    source = client.sync.source_id("existing-collector", "fixture")
    state = client.sync.SyncState(Path(config["state"]))
    with state.db:
        state.db.execute(
            "INSERT INTO request_repairs(source,generation,end) VALUES(?,?,?)",
            (source, queue_generation, 10),
        )
    before = state.db.execute("SELECT * FROM sources").fetchall()
    state.close()
    monkeypatch.setattr(
        client.sync, "validate_manifest", lambda config: ("existing-collector", [spec])
    )
    monkeypatch.setattr(client.sync, "credentials", lambda *args: "fixture-token")
    monkeypatch.setattr(
        client.sync,
        "remote_progress",
        lambda *args: {"ledger_revision": 7, "generation": "first", "next_offset": 10},
    )
    monkeypatch.setattr(
        client,
        "project",
        lambda *args: {
            "parser_version": "sparkstead-trajectory/3",
            "complete_bytes": 10,
            "source_sha256": "b" * 64,
            "records": [],
        },
    )
    calls = []

    def send(request, timeout):
        body = json.loads(request.data)
        calls.append(body["mutation_id"])
        return io.BytesIO(
            json.dumps({"durable": durable, "mutation_id": body["mutation_id"]}).encode()
        )

    monkeypatch.setattr(client.sync, "http_opener", lambda *args: SimpleNamespace(open=send))
    projector = tmp_path / "projector.mjs"
    projector.write_text("// sealed fixture")
    first = client.run(config, str(projector), apply=True)
    client.run(config, str(projector), apply=True)
    assert calls[0] == calls[1]
    assert first["sources"][0]["status"] == ("repaired" if durable else "deferred")
    state = client.sync.SyncState(Path(config["state"]))
    assert len(state.pending_request_repairs()) == remaining
    assert before == state.db.execute("SELECT * FROM sources").fetchall()
    state.close()
