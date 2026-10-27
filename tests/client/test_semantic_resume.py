"""Durable model-call recovery uses local HTTP/fakes only; no supplier calls."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[2] / "trajectory/product/semantic_model.py"
spec = importlib.util.spec_from_file_location("semantic_resume_model", MODULE)
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


def setup(monkeypatch):
    config = {"name": "fixture", "route": "test", "operation_chars": 100, "input_chars": 10000}
    monkeypatch.setattr(model, "_configuration", lambda: dict(config))
    operations = [
        {"id": hashlib.sha256(str(i).encode()).hexdigest(), "evidence_truncated": False}
        for i in range(3)
    ]
    monkeypatch.setattr(model, "_pack", lambda ops, cfg: [[op] for op in ops])
    return config, operations


def response(indices):
    return {
        "tasks": [
            {"id": "task", "parent_id": "root", "title": "目标", "operation_indices": indices}
        ]
    }


def returned(call_id, indices):
    return (
        response(indices),
        {"prompt_tokens": 100, "completion_tokens": 20},
        {"call_id": call_id, "receipt_id": "fixture-" + call_id[-8:]},
    )


def call_id(job, chunk, attempt):
    return "trajectory:" + hashlib.sha256(f"{job}:{chunk}:{attempt}".encode()).hexdigest()


def test_short_window_indices_map_exactly_to_long_canonical_ids(monkeypatch):
    _, operations = setup(monkeypatch)
    packets = []

    def invoke(config, packet, identity):
        packets.append(packet)
        assert all("id" not in node for node in packet["operations"])
        assert packet["operations"][0]["index"] == 0
        return returned(identity, [0])

    monkeypatch.setattr(model, "_request", invoke)
    result = model.segment(operations, "目标", analysis_id="same-job")
    assert result["tasks"][1]["operation_ids"] == [op["id"] for op in operations]
    assert len(packets) == 3
    assert all(
        "operation_ids" not in task for packet in packets for task in packet["existing_tasks"]
    )


@pytest.mark.parametrize("indices", [[0, 0], [], [1], [-1], [True], ["0"]])
def test_membership_never_guesses_or_silently_repairs(indices):
    with pytest.raises(model.SemanticModelError):
        model._canonical_result(response(indices), [{"id": "long-original-id"}])


def test_received_http_body_survives_crash_without_another_request(tmp_path, monkeypatch):
    _, operations = setup(monkeypatch)
    path = tmp_path / "checkpoint.json"
    calls = []

    def crash(config, packet, identity):
        calls.append(identity)
        body = json.dumps(
            {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps(response([0]))}}
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            }
        )
        config["_response_recorder"](
            identity, body, {"call_id": identity, "receipt_id": "paid-receipt"}
        )
        raise SystemExit("crash after durable gateway response")

    monkeypatch.setattr(model, "_request", crash)
    with pytest.raises(SystemExit):
        model.segment(operations[:1], "目标", analysis_id="same-job", checkpoint=path)
    monkeypatch.setattr(
        model, "_request", lambda *args: pytest.fail("must replay durable response")
    )
    result = model.segment(operations[:1], "目标", analysis_id="same-job", checkpoint=path)
    assert len(calls) == 1
    assert result["tasks"][1]["operation_ids"] == [operations[0]["id"]]
    assert result["provenance"]["analysis_usage"][0]["receipt_id"] == "paid-receipt"
    journal = list(tmp_path.glob("*.calls/*.json"))[0]
    assert journal.stat().st_mode & 0o077 == 0
    assert json.loads(journal.read_text())["raw_response"]


def test_prepared_unknown_call_blocks_even_a_new_generation(tmp_path, monkeypatch):
    _, operations = setup(monkeypatch)
    path = tmp_path / "checkpoint.json"

    def crash(*args):
        raise SystemExit("unknown upstream outcome")

    monkeypatch.setattr(model, "_request", crash)
    with pytest.raises(SystemExit):
        model.segment(operations[:1], "目标", analysis_id="same-job", checkpoint=path)
    monkeypatch.setattr(
        model, "_request", lambda *args: pytest.fail("unknown call must not be resent")
    )
    for generation in (0, 1):
        with pytest.raises(model.SemanticModelError, match="reconcile"):
            model.segment(
                operations[:1],
                "目标",
                analysis_id="same-job",
                checkpoint=path,
                resume_generation=generation,
            )
    unknown = call_id("same-job", 0, 0)
    with pytest.raises(model.SemanticModelError, match="without body"):
        model.segment(
            operations[:1],
            "目标",
            analysis_id="same-job",
            checkpoint=path,
            resume_generation=1,
            reconciled_calls={unknown: {"state": "completed_no_body"}},
        )


def test_successful_prefix_and_paid_invalid_attempts_resume_once(tmp_path, monkeypatch):
    _, operations = setup(monkeypatch)
    path = tmp_path / "checkpoint.json"
    calls = []

    def fail_second(config, packet, identity):
        calls.append(identity)
        return returned(identity, [] if packet["chunk"] == 2 else [0])

    monkeypatch.setattr(model, "_request", fail_second)
    with pytest.raises(model.SemanticModelError, match="coverage") as failed:
        model.segment(operations, "目标", analysis_id="same-job", checkpoint=path)
    prior = {"completed_chunks": 1, "analysis_usage": failed.value.provenance["analysis_usage"]}
    assert len(calls) == 3
    with pytest.raises(model.SemanticModelError, match="coverage"):
        model.segment(
            operations, "目标", analysis_id="same-job", checkpoint=path, prior_progress=prior
        )
    assert (
        len(calls) == 3
    ), "same generation revalidates journal, never charges invalid attempts again"
    repaired_packets = []

    def repair(config, packet, identity):
        calls.append(identity)
        repaired_packets.append(dict(packet))
        return returned(identity, [0])

    monkeypatch.setattr(model, "_request", repair)
    result = model.segment(
        operations,
        "目标",
        analysis_id="same-job",
        checkpoint=path,
        prior_progress=prior,
        resume_generation=1,
    )
    assert len(calls) == 5
    assert "coverage is incomplete or duplicated" in repaired_packets[0]["validation_feedback"]
    assert "validation_feedback" not in repaired_packets[1]
    assert calls[3] == call_id("same-job", 1, 2)
    assert result["tasks"][1]["operation_ids"] == [op["id"] for op in operations]
    assert len(result["provenance"]["analysis_usage"]) == 5
    assert sum(c["usage"]["prompt_tokens"] for c in result["provenance"]["analysis_usage"]) == 500


def legacy_checkpoint(path, config, operations):
    chunks = [[op] for op in operations]
    identity = hashlib.sha256(
        json.dumps(
            {
                "analysis_id": "same-job",
                "prompt": model.LEGACY_PROMPT_VERSION,
                "title": "目标",
                "chunks": chunks,
                "model": config["name"],
                "route": config["route"],
                "reasoning_effort": "",
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    provenance = {
        "backend": "jindu",
        "model": config["name"],
        "route": config["route"],
        "reasoning_effort": "",
        "created_at": "2026-10-19T00:00:00Z",
        "prompt_version": model.LEGACY_PROMPT_VERSION,
        "cost": None,
        "analysis_usage": [
            {
                "call_id": call_id("same-job", 0, 0),
                "chunk": 1,
                "attempt": 1,
                "valid": True,
                "receipt_id": "old-success",
                "usage": {"prompt_tokens": 10},
            }
        ],
    }
    value = {
        "identity": identity,
        "completed_chunks": 1,
        "known": {
            "root": {"id": "root", "parent_id": None, "title": "目标", "operation_ids": []},
            "task": {
                "id": "task",
                "parent_id": "root",
                "title": "目标",
                "operation_ids": [operations[0]["id"]],
            },
        },
        "provenance": provenance,
    }
    path.write_text(json.dumps(value))
    return value


def test_v1_migration_preserves_file_prefix_and_failed_usage(tmp_path, monkeypatch):
    config, operations = setup(monkeypatch)
    operations = operations[:2]
    path = tmp_path / "old.json"
    old = legacy_checkpoint(path, config, operations)
    original = path.read_bytes()
    calls = []
    failed = [
        {
            "call_id": call_id("same-job", 1, a),
            "chunk": 2,
            "attempt": a + 1,
            "valid": False,
            "receipt_id": "old-invalid-" + str(a),
            "usage": {"prompt_tokens": 20},
        }
        for a in range(2)
    ]
    monkeypatch.setattr(
        model,
        "_request",
        lambda config, packet, identity: (calls.append(identity) or returned(identity, [0])),
    )
    result = model.segment(
        operations,
        "目标",
        analysis_id="same-job",
        checkpoint=path,
        prior_progress={
            "completed_chunks": 1,
            "analysis_usage": old["provenance"]["analysis_usage"] + failed,
        },
        resume_generation=1,
    )
    assert path.read_bytes() == original
    assert path.with_name(path.name + ".v2").is_file()
    assert calls == [call_id("same-job", 1, 2)]
    assert len(result["provenance"]["analysis_usage"]) == 4
    assert (
        result["provenance"]["checkpoint_migration"]["legacy_checkpoint_sha256"]
        == hashlib.sha256(original).hexdigest()
    )
    assert result["tasks"][1]["operation_ids"] == [op["id"] for op in operations]


def test_missing_prefix_checkpoint_never_restarts_paid_success(tmp_path, monkeypatch):
    _, operations = setup(monkeypatch)
    monkeypatch.setattr(
        model, "_request", lambda *args: pytest.fail("missing paid prefix must block")
    )
    with pytest.raises(model.SemanticModelError, match="checkpoint is missing"):
        model.segment(
            operations,
            "目标",
            analysis_id="same-job",
            checkpoint=tmp_path / "gone.json",
            prior_progress={"completed_chunks": 1},
            resume_generation=1,
        )


def test_completed_legacy_result_is_read_without_migration_or_model_call(tmp_path, monkeypatch):
    config, operations = setup(monkeypatch)
    operations = operations[:1]
    path = tmp_path / "completed-v1.json"
    saved = legacy_checkpoint(path, config, operations)
    original = path.read_bytes()
    monkeypatch.setattr(
        model, "_request", lambda *args: pytest.fail("completed legacy result is reusable")
    )
    result = model.segment(operations, "目标", analysis_id="same-job", checkpoint=path)
    assert result["provenance"] == saved["provenance"]
    assert path.read_bytes() == original
    assert not path.with_name(path.name + ".v2").exists()


def test_receipt_with_complete_body_replays_before_later_paid_generation(tmp_path, monkeypatch):
    _, operations = setup(monkeypatch)
    path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(model, "_request", lambda *args: (_ for _ in ()).throw(SystemExit("crash")))
    with pytest.raises(SystemExit):
        model.segment(operations[:1], "目标", analysis_id="same-job", checkpoint=path)
    identity = call_id("same-job", 0, 0)
    raw = json.dumps(
        {
            "choices": [
                {"finish_reason": "stop", "message": {"content": json.dumps(response([0]))}}
            ],
            "usage": {"prompt_tokens": 100},
        }
    )
    monkeypatch.setattr(
        model, "_request", lambda *args: pytest.fail("receipt already contains membership")
    )
    result = model.segment(
        operations[:1],
        "目标",
        analysis_id="same-job",
        checkpoint=path,
        resume_generation=1,
        reconciled_calls={
            identity: {
                "state": "completed",
                "raw_response": raw,
                "call": {"receipt_id": "recovered"},
            }
        },
    )
    assert result["tasks"][1]["operation_ids"] == [operations[0]["id"]]
    assert result["provenance"]["analysis_usage"][0]["call_id"] == identity


def test_rejected_without_dispatch_can_use_explicit_later_generation(tmp_path, monkeypatch):
    _, operations = setup(monkeypatch)
    path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(model, "_request", lambda *args: (_ for _ in ()).throw(SystemExit("crash")))
    with pytest.raises(SystemExit):
        model.segment(operations[:1], "目标", analysis_id="same-job", checkpoint=path)
    identities = []
    monkeypatch.setattr(
        model,
        "_request",
        lambda config, packet, identity: (identities.append(identity) or returned(identity, [0])),
    )
    model.segment(
        operations[:1],
        "目标",
        analysis_id="same-job",
        checkpoint=path,
        resume_generation=1,
        reconciled_calls={
            call_id("same-job", 0, 0): {"state": "rejected_no_dispatch", "receipt_id": "rejected"}
        },
    )
    assert identities == [call_id("same-job", 0, 2)]


def test_prior_uncertain_usage_cannot_be_hidden_by_resume_generation(tmp_path, monkeypatch):
    _, operations = setup(monkeypatch)
    monkeypatch.setattr(
        model, "_request", lambda *args: pytest.fail("uncertain prior attempt must block")
    )
    prior = {
        "completed_chunks": 0,
        "analysis_usage": [
            {
                "call_id": call_id("same-job", 0, 0),
                "failed": True,
                "usage": {},
                "receipt_id": "uncertain",
            }
        ],
    }
    with pytest.raises(model.SemanticModelError, match="Uncertain"):
        model.segment(
            operations[:1],
            "目标",
            analysis_id="same-job",
            checkpoint=tmp_path / "checkpoint.json",
            prior_progress=prior,
            resume_generation=1,
        )


def test_pause_after_successful_window_resumes_same_job_without_repaying(tmp_path, monkeypatch):
    _, operations = setup(monkeypatch)
    path = tmp_path / "checkpoint.json"
    calls = []
    monkeypatch.setattr(
        model,
        "_request",
        lambda config, packet, identity: (calls.append(identity) or returned(identity, [0])),
    )
    progress = []
    with pytest.raises(model.AnalysisPaused):
        model.segment(
            operations,
            "目标",
            analysis_id="same-job",
            checkpoint=path,
            progress=progress.append,
            should_pause=lambda: bool(calls),
        )
    assert len(calls) == 1
    assert json.loads(path.read_text())["completed_chunks"] == 1
    assert progress[-1]["state"] == "paused"
    result = model.segment(
        operations,
        "目标",
        analysis_id="same-job",
        checkpoint=path,
        progress=progress.append,
        should_pause=lambda: False,
    )
    assert len(calls) == 3
    assert len(set(calls)) == 3
    assert result["tasks"][1]["operation_ids"] == [op["id"] for op in operations]
    assert result["provenance"]["resume_generation"] == 0


def test_pause_before_request_prepares_no_uncertain_attempt(tmp_path, monkeypatch):
    _, operations = setup(monkeypatch)
    path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(model, "_request", lambda *args: pytest.fail("paused before paid request"))
    with pytest.raises(model.AnalysisPaused):
        model.segment(
            operations, "目标", analysis_id="same-job", checkpoint=path, should_pause=lambda: True
        )
    assert json.loads(path.read_text())["completed_chunks"] == 0
    assert not list(tmp_path.glob("*.calls/*.json"))


def lost_attempt():
    return {
        "call_id": call_id("same-job", 0, 0),
        "chunk": 1,
        "attempt": 1,
        "receipt_id": "terminal-lost-receipt",
        "failed": True,
        "uncertain": True,
        "usage": {},
    }


def recomputation_authorization():
    return {
        "job_id": "same-job",
        "call_id": call_id("same-job", 0, 0),
        "receipt_id": "terminal-lost-receipt",
        "chunk": 1,
        "attempt": 1,
        "resume_generation": 1,
        "receipt_state": "uncertain_terminal",
        "authorization_id": "domain-operator-authorization",
        "accept_possible_duplicate_charge": True,
    }


def test_explicit_terminal_lost_response_authorization_preserves_unknown_cost(
    tmp_path, monkeypatch
):
    _, operations = setup(monkeypatch)
    path = tmp_path / "checkpoint.json"
    original = lost_attempt()
    calls = []
    monkeypatch.setattr(
        model,
        "_request",
        lambda cfg, packet, identity: (calls.append(identity) or returned(identity, [0])),
    )
    result = model.segment(
        operations[:2],
        "目标",
        analysis_id="same-job",
        checkpoint=path,
        prior_progress={"completed_chunks": 0, "analysis_usage": [original]},
        resume_generation=1,
        authorized_recomputations=[recomputation_authorization()],
    )
    assert calls == [call_id("same-job", 0, 2), call_id("same-job", 1, 2)]
    assert result["provenance"]["analysis_usage"][0] == original
    assert result["provenance"]["analysis_usage"][0]["usage"] == {}
    assert result["provenance"]["authorized_recomputations"] == [recomputation_authorization()]
    monkeypatch.setattr(
        model, "_request", lambda *args: pytest.fail("completed recomputation is reusable")
    )
    replay = model.segment(
        operations[:2],
        "目标",
        analysis_id="same-job",
        checkpoint=path,
        resume_generation=1,
        authorized_recomputations=[recomputation_authorization()],
    )
    assert replay["tasks"] == result["tasks"]
    with pytest.raises(model.SemanticModelError, match="Uncertain"):
        model.segment(
            operations[:2], "目标", analysis_id="same-job", checkpoint=path, resume_generation=2
        )


@pytest.mark.parametrize(
    "override",
    [
        {"job_id": "another-job"},
        {"receipt_id": "wrong-receipt"},
        {"receipt_id": ""},
        {"call_id": call_id("another-job", 0, 0)},
        {"attempt": 2},
        {"chunk": 2},
        {"resume_generation": 0},
        {"resume_generation": 2},
        {"receipt_state": "sent"},
        {"receipt_state": "unknown"},
        {"receipt_state": "rejected"},
        {"authorization_id": ""},
        {"accept_possible_duplicate_charge": False},
    ],
)
def test_lost_authorization_requires_exact_domain_terminal_proof(override, tmp_path, monkeypatch):
    _, operations = setup(monkeypatch)
    monkeypatch.setattr(
        model, "_request", lambda *args: pytest.fail("invalid authorization must never dispatch")
    )
    with pytest.raises(model.SemanticModelError):
        model.segment(
            operations[:1],
            "目标",
            analysis_id="same-job",
            checkpoint=tmp_path / "checkpoint.json",
            prior_progress={"completed_chunks": 0, "analysis_usage": [lost_attempt()]},
            resume_generation=1,
            authorized_recomputations=[recomputation_authorization() | override],
        )


def test_prepared_journal_authorization_does_not_rewrite_original_state(tmp_path, monkeypatch):
    _, operations = setup(monkeypatch)
    path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(model, "_request", lambda *args: (_ for _ in ()).throw(SystemExit("lost")))
    with pytest.raises(SystemExit):
        model.segment(operations[:1], "目标", analysis_id="same-job", checkpoint=path)
    old_file = next(tmp_path.glob("*.calls/*.json"))
    old_bytes = old_file.read_bytes()
    calls = []
    monkeypatch.setattr(
        model,
        "_request",
        lambda cfg, packet, identity: (calls.append(identity) or returned(identity, [0])),
    )
    model.segment(
        operations[:1],
        "目标",
        analysis_id="same-job",
        checkpoint=path,
        resume_generation=1,
        authorized_recomputations=[recomputation_authorization()],
    )
    assert calls == [call_id("same-job", 0, 2)]
    assert old_file.read_bytes() == old_bytes
    assert json.loads(old_bytes)["state"] == "prepared"


def test_one_authorized_lost_call_never_authorizes_another_uncertain_call(tmp_path, monkeypatch):
    _, operations = setup(monkeypatch)
    path = tmp_path / "checkpoint.json"
    calls = []

    def uncertain(cfg, packet, identity):
        calls.append(identity)
        raise model.SemanticModelError(
            "new uncertain call",
            {"call": {"call_id": identity, "receipt_id": "new-uncertain"}},
            retryable=False,
        )

    monkeypatch.setattr(model, "_request", uncertain)
    with pytest.raises(model.SemanticModelError):
        model.segment(
            operations[:1],
            "目标",
            analysis_id="same-job",
            checkpoint=path,
            prior_progress={"completed_chunks": 0, "analysis_usage": [lost_attempt()]},
            resume_generation=1,
            authorized_recomputations=[recomputation_authorization()],
        )
    assert calls == [call_id("same-job", 0, 2)]
    monkeypatch.setattr(
        model, "_request", lambda *args: pytest.fail("different uncertain call remains blocked")
    )
    with pytest.raises(model.SemanticModelError, match="Uncertain"):
        model.segment(
            operations[:1],
            "目标",
            analysis_id="same-job",
            checkpoint=path,
            resume_generation=2,
            authorized_recomputations=[recomputation_authorization()],
        )


def test_identity_repair_feedback_carries_conflicting_task_identity(tmp_path, monkeypatch):
    _, operations = setup(monkeypatch)
    packets = []

    def invoke(config, packet, identity):
        packets.append(dict(packet))
        if packet["chunk"] == 2 and "validation_feedback" not in packet:
            return (
                {
                    "tasks": [
                        {
                            "id": "task",
                            "parent_id": "wrong-parent",
                            "title": "目标",
                            "operation_indices": [0],
                        }
                    ]
                },
                {"prompt_tokens": 100, "completion_tokens": 20},
                {"call_id": identity, "receipt_id": "paid-receipt"},
            )
        return returned(identity, [0])

    monkeypatch.setattr(model, "_request", invoke)
    result = model.segment(
        operations[:2], "目标", analysis_id="identity-repair", checkpoint=tmp_path / "checkpoint"
    )
    assert result["tasks"][1]["operation_ids"] == [op["id"] for op in operations[:2]]
    feedback = packets[2]["validation_feedback"]
    assert "Model changed an existing task identity" in feedback
    assert '"id": "task"' in feedback and '"parent_id": "root"' in feedback


def test_resume_feedback_uses_latest_failure_even_when_older_attempt_is_replayed(
    tmp_path, monkeypatch
):
    _, operations = setup(monkeypatch)
    packets = []

    def invoke(config, packet, identity):
        packets.append(dict(packet))
        if packet["chunk"] == 1:
            value = response([0])
        elif len([item for item in packets if item["chunk"] == 2]) == 1:
            value = {
                "tasks": [
                    {"id": "task", "parent_id": "wrong", "title": "目标", "operation_indices": [0]}
                ]
            }
        else:
            value = response([])
        body = json.dumps(
            {
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value)}}],
                "usage": {"prompt_tokens": 100},
            }
        )
        config["_response_recorder"](
            identity, body, {"call_id": identity, "receipt_id": "confirmed"}
        )
        return value, {"prompt_tokens": 100}, {"call_id": identity, "receipt_id": "confirmed"}

    monkeypatch.setattr(model, "_request", invoke)
    path = tmp_path / "checkpoint"
    with pytest.raises(model.SemanticModelError, match="coverage") as failed:
        model.segment(operations[:2], "目标", analysis_id="feedback-order", checkpoint=path)
    prior = {"completed_chunks": 1, "analysis_usage": failed.value.provenance["analysis_usage"]}
    repaired = []

    def recover(config, packet, identity):
        repaired.append(dict(packet))
        return returned(identity, [0])

    monkeypatch.setattr(model, "_request", recover)
    model.segment(
        operations[:2],
        "目标",
        analysis_id="feedback-order",
        checkpoint=path,
        prior_progress=prior,
        resume_generation=1,
    )
    assert "coverage is incomplete or duplicated" in repaired[0]["validation_feedback"]
