"""Stored identity is authoritative; paid invalid echoes can be revalidated locally."""

import copy
import hashlib
import json

import pytest

from trajectory.product import semantic_model as model


def identity(title="准备采样与检查"):
    return {"id": "stable", "parent_id": "root", "title": title, "operation_ids": ["op"]}


def test_visible_title_echo_preserves_known_authority_without_changing_received_output():
    known = {"stable": identity()}
    packet = {"existing_tasks": [{k: v for k, v in identity().items() if k != "operation_ids"}]}
    received = {"tasks": [identity("准备采样和检查")]}
    canonical = copy.deepcopy(received)
    changes = model._canonical_existing_titles(canonical["tasks"], known, packet)
    model._validate(canonical["tasks"], known, {"op"})
    assert canonical["tasks"][0]["title"] == known["stable"]["title"]
    assert received["tasks"][0]["title"] == "准备采样和检查"
    assert len(changes) == 1 and changes[0]["task_id"] == "stable"


@pytest.mark.parametrize("title", ["", "   ", "x" * 201, None, 12, ["title"]])
def test_malformed_existing_titles_are_not_hidden_by_authority(title):
    known = {"stable": identity()}
    tasks = [identity(title)]
    assert not model._canonical_existing_titles(tasks, known, {"existing_tasks": [identity()]})
    with pytest.raises(model.SemanticModelError):
        model._validate(tasks, known, {"op"})


@pytest.mark.parametrize("change", ["parent", "invisible", "prompt_mismatch"])
def test_parent_changes_and_invisible_or_mismatched_existing_id_are_rejected(change):
    known = {"stable": identity()}
    tasks = [identity("准备采样和检查")]
    visible = [{k: v for k, v in identity().items() if k != "operation_ids"}]
    if change == "parent":
        tasks[0]["parent_id"] = "other"
    elif change == "invisible":
        visible = []
    else:
        visible[0]["title"] = "a different prompt identity"
    assert not model._canonical_existing_titles(tasks, known, {"existing_tasks": visible})
    with pytest.raises(model.SemanticModelError, match="existing task identity"):
        model._validate(tasks, known, {"op"})


def test_new_task_title_is_not_normalized():
    task = identity("A valid new title")
    assert not model._canonical_existing_titles([task], {}, {"existing_tasks": []})
    model._validate([task], {}, {"op"})
    assert task["title"] == "A valid new title"


def old_failure(tmp_path, monkeypatch):
    config = {
        "name": "glm-5.3",
        "route": "zai-glm-5-3",
        "reasoning_effort": "high",
        "input_chars": 24000,
        "operation_chars": 2000,
        "output_tokens": 8192,
    }
    monkeypatch.setattr(model, "_configuration", lambda: config)
    operations = [{"id": f"op-{i}", "evidence_truncated": False} for i in range(68)]
    monkeypatch.setattr(model, "_pack", lambda operations, config: [[o] for o in operations])
    requests = []

    def request(config, packet, call_id):
        requests.append(call_id)
        result = {
            "tasks": [
                {
                    "id": "stable",
                    "parent_id": "root",
                    "title": "准备采样和检查" if packet["chunk"] == 68 else "准备采样与检查",
                    "operation_indices": [0],
                }
            ]
        }
        usage = {"prompt_tokens": 100, "completion_tokens": 20}
        call = {"call_id": call_id, "receipt_id": "receipt-" + call_id[-8:], "elapsed_seconds": 1.0}
        raw = json.dumps(
            {
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}],
                "usage": usage,
            }
        )
        config["_response_recorder"](call_id, raw, call)
        return result, usage, call

    monkeypatch.setattr(model, "_request", request)
    checkpoint = tmp_path / "chunks.json"
    with monkeypatch.context() as old:
        old.setattr(model, "_canonical_existing_titles", lambda *args: [])
        with pytest.raises(model.SemanticModelError, match="existing task identity"):
            model.segment(operations, "fixture", analysis_id="same-job", checkpoint=checkpoint)
    before = json.loads(checkpoint.read_text())
    assert before["completed_chunks"] == 67 and len(requests) == 69
    journal_dir = checkpoint.with_name(checkpoint.name + ".calls")
    journals = {p.name: json.loads(p.read_text()) for p in journal_dir.glob("*.json")}
    assert sum(v["state"] == "invalid" for v in journals.values()) == 2
    monkeypatch.setattr(
        model, "_request", lambda *args: pytest.fail("No network during local replay")
    )
    return operations, checkpoint, before, journal_dir, journals


def test_local_revalidation_preserves_67_window_prefix_raw_invalid_reviews_and_all_usage(
    tmp_path, monkeypatch
):
    ops, checkpoint, before, directory, original = old_failure(tmp_path, monkeypatch)
    result = model.segment(
        ops, "fixture", analysis_id="same-job", checkpoint=checkpoint, resume_generation=1
    )
    after = json.loads(checkpoint.read_text())
    assert after["completed_chunks"] == 68
    assert result["provenance"]["analysis_usage"] == before["provenance"]["analysis_usage"]
    assert result["tasks"][1]["title"] == "准备采样与检查"
    assert result["tasks"][1]["operation_ids"][:67] == before["known"]["stable"]["operation_ids"]
    assert len(result["tasks"][1]["operation_ids"]) == 68
    reviews = result["provenance"]["local_revalidations"]
    assert len(reviews) == 1 and reviews[0]["network_requests"] == 0
    assert reviews[0]["policy"] == model.TITLE_ECHO_POLICY
    assert len(list(directory.glob("*.json"))) == len(original)
    for name, old in original.items():
        new = json.loads((directory / name).read_text())
        if new.get("local_revalidations"):
            assert new["raw_response"] == old["raw_response"]
            assert new["state"] == old["state"] == "invalid"
            assert new["validation_error"] == old["validation_error"]
            assert new["usage"] == old["usage"] and new["call"] == old["call"]
            assert (
                reviews[0]["raw_response_sha256"]
                == hashlib.sha256(old["raw_response"].encode()).hexdigest()
            )
        else:
            assert new == old
    # Completed checkpoints replay without a second review, new call or usage duplication.
    again = model.segment(
        ops, "fixture", analysis_id="same-job", checkpoint=checkpoint, resume_generation=1
    )
    assert again["provenance"]["local_revalidations"] == reviews
    assert again["provenance"]["analysis_usage"] == before["provenance"]["analysis_usage"]


@pytest.mark.parametrize("state", ["prepared", "uncertain"])
def test_title_policy_never_replays_prepared_or_uncertain_as_completed(
    tmp_path, monkeypatch, state
):
    ops, checkpoint, _, directory, original = old_failure(tmp_path, monkeypatch)
    name, entry = next((n, e) for n, e in original.items() if e["state"] == "invalid")
    entry["state"] = state
    (directory / name).write_text(json.dumps(entry))
    with pytest.raises(model.SemanticModelError, match="reconcile before retry"):
        model.segment(
            ops, "fixture", analysis_id="same-job", checkpoint=checkpoint, resume_generation=1
        )


def test_revalidation_keeps_canonical_packet_and_request_digest_fence(tmp_path, monkeypatch):
    ops, checkpoint, _, directory, original = old_failure(tmp_path, monkeypatch)
    for name, entry in original.items():
        if entry["state"] == "invalid":
            entry["request_digest"] = "changed-digest"
            (directory / name).write_text(json.dumps(entry))
    with pytest.raises(model.SemanticModelError, match="different request digest"):
        model.segment(
            ops, "fixture", analysis_id="same-job", checkpoint=checkpoint, resume_generation=1
        )


def test_local_revalidation_rejects_receipt_mismatch_without_changing_old_usage(
    tmp_path, monkeypatch
):
    ops, checkpoint, before, directory, original = old_failure(tmp_path, monkeypatch)
    for name, entry in original.items():
        if entry["state"] == "invalid":
            entry["call"]["receipt_id"] = "different-receipt"
            (directory / name).write_text(json.dumps(entry))
    with pytest.raises(model.SemanticModelError, match="matching paid usage"):
        model.segment(
            ops, "fixture", analysis_id="same-job", checkpoint=checkpoint, resume_generation=1
        )
    after = json.loads(checkpoint.read_text())
    assert after["provenance"]["analysis_usage"] == before["provenance"]["analysis_usage"]
    assert after["completed_chunks"] == 67
    assert not after["provenance"].get("local_revalidations")


@pytest.mark.parametrize("damage", ["raw_decode", "paid_usage"])
def test_invalid_revalidation_evidence_never_mutates_usage_or_journal(
    tmp_path, monkeypatch, damage
):
    ops, checkpoint, before, directory, original = old_failure(tmp_path, monkeypatch)
    for name, entry in original.items():
        if entry["state"] != "invalid":
            continue
        if damage == "raw_decode":
            entry["raw_response"] = "{incomplete"
        else:
            raw = json.loads(entry["raw_response"])
            raw["usage"]["prompt_tokens"] += 1
            entry["raw_response"] = json.dumps(raw)
        (directory / name).write_text(json.dumps(entry))
    journal_bytes = {p.name: p.read_bytes() for p in directory.glob("*.json")}
    with pytest.raises(model.SemanticModelError) as raised:
        model.segment(
            ops, "fixture", analysis_id="same-job", checkpoint=checkpoint, resume_generation=1
        )
    assert not raised.value.retryable
    after = json.loads(checkpoint.read_text())
    assert after["provenance"]["analysis_usage"] == before["provenance"]["analysis_usage"]
    assert after["completed_chunks"] == 67
    assert not after["provenance"].get("local_revalidations")
    assert {p.name: p.read_bytes() for p in directory.glob("*.json")} == journal_bytes
