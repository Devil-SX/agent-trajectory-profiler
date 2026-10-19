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
    changes = model._canonical_task_titles(canonical["tasks"], known, packet)
    model._validate(canonical["tasks"], known, {"op"})
    assert canonical["tasks"][0]["title"] == known["stable"]["title"]
    assert received["tasks"][0]["title"] == "准备采样和检查"
    assert len(changes) == 1 and changes[0]["task_id"] == "stable"


@pytest.mark.parametrize("title", ["", "   ", None, 12, ["title"]])
def test_malformed_existing_titles_are_not_hidden_by_authority(title):
    known = {"stable": identity()}
    tasks = [identity(title)]
    assert not model._canonical_task_titles(tasks, known, {"existing_tasks": [identity()]})
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
    assert not model._canonical_task_titles(tasks, known, {"existing_tasks": visible})
    with pytest.raises(model.SemanticModelError, match="existing task identity"):
        model._validate(tasks, known, {"op"})


def test_new_task_title_is_not_normalized():
    task = identity("A valid new title")
    assert not model._canonical_task_titles([task], {}, {"existing_tasks": []})
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
        old.setattr(model, "_canonical_task_titles", lambda *args: [])
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
    assert reviews[0]["policy"] == model.TASK_TITLE_POLICY
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


@pytest.mark.parametrize(
    "title", ["界" * 236, "😀" * 201, "a\u0301" * 120, " \t" + "标题" * 103 + " \n"]
)
def test_new_titles_are_bounded_by_unicode_codepoints_with_explicit_audit(title):
    task = identity(title)
    original = copy.deepcopy(task)
    changes = model._canonical_task_titles([task], {}, {"existing_tasks": []})
    model._validate([task], {}, {"op"})
    assert task["title"] == title.strip()[: model.MAX_TASK_TITLE_CHARACTERS - 1] + "…"
    assert len(task["title"]) == model.MAX_TASK_TITLE_CHARACTERS
    assert {k: task[k] for k in ["id", "parent_id", "operation_ids"]} == {
        k: original[k] for k in ["id", "parent_id", "operation_ids"]
    }
    assert changes[0]["truncated"] is True
    assert changes[0]["received_characters"] == len(title)
    assert changes[0]["stripped_characters"] == len(title.strip())
    assert changes[0]["canonical_characters"] == model.MAX_TASK_TITLE_CHARACTERS
    assert changes[0]["received_title_sha256"] == hashlib.sha256(title.encode()).hexdigest()


def test_whitespace_is_stripped_before_applying_new_label_limit():
    title = " " * 300 + "短标题" + "\t" * 300
    task = identity(title)
    changes = model._canonical_task_titles([task], {}, {"existing_tasks": []})
    assert task["title"] == "短标题" and changes[0]["truncated"] is False
    assert changes[0]["stripped_characters"] == 3
    model._validate([task], {}, {"op"})


def test_visible_existing_title_authority_also_accepts_long_echo():
    known = {"stable": identity()}
    visible = [{k: v for k, v in identity().items() if k != "operation_ids"}]
    task = identity("x" * 300)
    changes = model._canonical_task_titles([task], known, {"existing_tasks": visible})
    assert task["title"] == known["stable"]["title"]
    assert changes[0]["reason"] == "stored_existing_title"
    assert changes[0]["received_characters"] == 300 and changes[0]["truncated"] is False
    model._validate([task], known, {"op"})


@pytest.mark.parametrize("mode", ["duplicate", "parent", "overlap", "missing"])
def test_title_bounding_never_repairs_identity_or_membership(mode):
    tasks = [
        identity("x" * 236),
        {"id": "other", "parent_id": "stable", "title": "x" * 203, "operation_ids": ["next"]},
    ]
    if mode == "duplicate":
        tasks[1]["id"] = "stable"
    elif mode == "parent":
        tasks[1]["parent_id"] = "missing-parent"
    elif mode == "overlap":
        tasks[1]["operation_ids"] = ["op"]
    else:
        tasks[1]["operation_ids"] = []
    model._canonical_task_titles(tasks, {}, {"existing_tasks": []})
    with pytest.raises(model.SemanticModelError):
        model._validate(tasks, {}, {"op", "next"})


def test_title_diagnostics_distinguish_type_blank_length_and_duplicate():
    for title, message in [
        (None, "must be a string"),
        (" ", "must be nonempty"),
        ("x" * 201, "maximum 200.*actual_characters=201"),
    ]:
        with pytest.raises(model.SemanticModelError, match=message):
            model._validate([identity(title)], {}, {"op"})
    with pytest.raises(model.SemanticModelError, match="Duplicate model task identity"):
        model._validate([identity(), identity()], {}, {"op"})


def test_old_title_audit_metadata_moves_once_without_changing_old_event_or_policy():
    event = {
        "policy": "visible-existing-title-authority/1",
        "call_id": "old-call",
        "changes": [
            {"task_id": "old", "received_title_sha256": "a", "canonical_title_sha256": "b"}
        ],
    }
    provenance = {
        "title_echo_normalizations": [copy.deepcopy(event)],
        "task_title_normalizations": [copy.deepcopy(event)],
    }
    model._migrate_title_normalizations(provenance)
    assert "title_echo_normalizations" not in provenance
    assert provenance["task_title_normalizations"] == [event]
    model._migrate_title_normalizations(provenance)
    assert provenance["task_title_normalizations"] == [event]


def test_long_title_old_paid_failure_revalidates_and_completed_checkpoint_reenters(
    tmp_path, monkeypatch
):
    config = {
        "name": "glm-5.3",
        "route": "zai-glm-5-3",
        "reasoning_effort": "high",
        "input_chars": 24000,
        "operation_chars": 2000,
        "output_tokens": 8192,
    }
    monkeypatch.setattr(model, "_configuration", lambda: config)
    ops = [{"id": f"op-{i}", "evidence_truncated": False} for i in range(72)]
    monkeypatch.setattr(
        model,
        "_pack",
        lambda operations, config: [[o] for o in operations[:70]] + [operations[70:]],
    )
    requests = []

    def request(config, packet, call_id):
        requests.append(call_id)
        tasks = (
            [{"id": "stable", "parent_id": "root", "title": "原任务", "operation_indices": [0]}]
            if packet["chunk"] <= 70
            else [
                {
                    "id": "new-parent",
                    "parent_id": "stable",
                    "title": "甲" * 236,
                    "operation_indices": [0],
                },
                {
                    "id": "new-child",
                    "parent_id": "new-parent",
                    "title": "乙" * 203,
                    "operation_indices": [1],
                },
            ]
        )
        result = {"tasks": tasks}
        usage = {"prompt_tokens": 100, "completion_tokens": 20}
        call = {"call_id": call_id, "receipt_id": "receipt-" + call_id[-8:]}
        raw = json.dumps(
            {
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}],
                "usage": usage,
            }
        )
        config["_response_recorder"](call_id, raw, call)
        return result, usage, call

    checkpoint = tmp_path / "checkpoint.json"
    monkeypatch.setattr(model, "_request", request)
    strict = model._validate

    def legacy_validate(tasks, known, ids):
        if any(len(t["title"]) > 200 for t in tasks):
            raise model.SemanticModelError("Invalid model task title or duplicate identity")
        strict(tasks, known, ids)

    with monkeypatch.context() as old:
        old.setattr(model, "_canonical_task_titles", lambda *args: [])
        old.setattr(model, "_validate", legacy_validate)
        with pytest.raises(
            model.SemanticModelError, match="Invalid model task title or duplicate identity"
        ):
            model.segment(
                ops,
                "fixture",
                analysis_id="same-long-job",
                checkpoint=checkpoint,
                resume_generation=1,
            )
    before = json.loads(checkpoint.read_text())
    assert before["completed_chunks"] == 70 and len(requests) == 72
    old_event = {"policy": "visible-existing-title-authority/1", "call_id": "legacy", "changes": []}
    before["provenance"]["title_echo_normalizations"] = [old_event]
    checkpoint.write_text(json.dumps(before))
    original = copy.deepcopy(before)
    directory = checkpoint.with_name(checkpoint.name + ".calls")
    journals = {p.name: json.loads(p.read_text()) for p in directory.glob("*.json")}
    monkeypatch.setattr(
        model, "_request", lambda *args: pytest.fail("No network after durable title-only failure")
    )
    result = model.segment(
        ops, "fixture", analysis_id="same-long-job", checkpoint=checkpoint, resume_generation=2
    )
    after = json.loads(checkpoint.read_text())
    assert after["completed_chunks"] == 71
    assert after["provenance"]["analysis_usage"] == original["provenance"]["analysis_usage"]
    assert after["known"]["stable"] == original["known"]["stable"]
    assert after["known"]["new-parent"]["title"] == "甲" * 199 + "…"
    assert after["known"]["new-child"]["title"] == "乙" * 199 + "…"
    assert "title_echo_normalizations" not in after["provenance"]
    audits = after["provenance"]["task_title_normalizations"]
    assert audits[0] == old_event and len(audits) == 2
    assert all(change["truncated"] for change in audits[1]["changes"])
    assert after["provenance"]["local_revalidations"][0]["policy"] == model.TASK_TITLE_POLICY
    for name, old_entry in journals.items():
        entry = json.loads((directory / name).read_text())
        assert all(
            entry.get(k) == old_entry.get(k)
            for k in ["state", "validation_error", "raw_response", "usage", "call"]
        )
    again = model.segment(
        ops, "fixture", analysis_id="same-long-job", checkpoint=checkpoint, resume_generation=2
    )
    assert again == result
