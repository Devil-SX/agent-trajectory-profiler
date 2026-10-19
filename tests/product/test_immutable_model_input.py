"""Paid request inputs survive mutable UI attribution and fail closed on drift."""

import copy
import json
import os

import pytest

from trajectory.product import semantic_model as model


@pytest.fixture
def setup(tmp_path, monkeypatch):
    config = {
        "name": "glm-5.3",
        "route": "zai-glm-5-3",
        "reasoning_effort": "high",
        "input_chars": 4000,
        "operation_chars": 2000,
        "output_tokens": 8192,
    }
    monkeypatch.setattr(model, "_configuration", lambda: config)
    monkeypatch.setattr(
        model, "_request", lambda *a, **k: pytest.fail("Network dispatch forbidden")
    )
    return (
        tmp_path / "chunks-job.json",
        config,
        [{"id": "op", "type": "message", "text": "原始正文"}],
    )


def prepare(cp, operations, **kwargs):
    return model.prepare_model_input(
        operations,
        "标题",
        checkpoint=cp,
        analysis_id="job",
        source_context={"source_revision": "rev", "ir_body_sha256": "body"},
        **kwargs,
    )


def legacy(cp, config, operations, version=None):
    cp.write_text(
        json.dumps(
            {
                "identity": model._input_identity(
                    "job",
                    "标题",
                    model._pack(operations, config),
                    config,
                    version or model.LEGACY_PROMPT_VERSION,
                )
            }
        )
    )


def test_new_input_uses_raw_ir_and_frozen_resume_ignores_display_changes(setup):
    cp, _, raw = setup
    display = copy.deepcopy(raw)
    display[0]["attribution"] = {"ledger": 268}
    original = prepare(cp, display, fresh_input={"operations": raw, "title": "原始标题"})
    assert original[1] == "原始标题" and "attribution" not in original[0][0][0]["evidence"]
    display[0].update(attribution={"ledger": 304}, task_id="another", timestamp="changed")
    resumed = prepare(
        cp, display, fresh_input={"operations": raw, "title": "different display title"}
    )
    assert original == resumed
    assert cp.with_name(cp.name + ".input.json").stat().st_mode & 0o777 == 0o600


def test_legacy_requires_exact_full_identity_and_keeps_original_evidence(setup):
    cp, config, raw = setup
    paid = copy.deepcopy(raw)
    paid[0]["attribution"] = {"ledger": 268}
    legacy(cp, config, paid)
    changed = copy.deepcopy(paid)
    changed[0]["attribution"]["ledger"] = 304
    with pytest.raises(model.SemanticModelError, match="configuration changed"):
        prepare(cp, changed, fresh_input={"operations": raw, "title": "标题"})
    assert not cp.with_name(cp.name + ".input.json").exists()
    frozen = prepare(cp, paid, fresh_input={"operations": raw, "title": "标题"})
    assert "268" in frozen[0][0][0]["evidence"]
    assert prepare(cp, changed) == frozen


@pytest.mark.parametrize("mutation", ["source", "config", "body", "order", "digest", "system"])
def test_frozen_source_config_integrity_and_ir_membership_cannot_drift(setup, mutation):
    cp, config, raw = setup
    prepare(cp, raw)
    path = cp.with_name(cp.name + ".input.json")
    if mutation == "source":
        with pytest.raises(model.SemanticModelError):
            model.prepare_model_input(
                raw, "标题", analysis_id="job", checkpoint=cp, source_context={}
            )
        return
    if mutation == "config":
        config["output_tokens"] += 1
    elif mutation == "order":
        with pytest.raises(model.SemanticModelError, match="pinned IR"):
            prepare(cp, raw, fresh_input={"operations": [{"id": "different"}], "title": "标题"})
        return
    else:
        value = json.loads(path.read_text())
        value[
            {"body": "title", "digest": "payload_sha256", "system": "system_sha256"}[mutation]
        ] = "tampered"
        path.write_text(json.dumps(value))
    with pytest.raises(model.SemanticModelError):
        prepare(cp, raw)


def test_journal_without_checkpoint_cannot_select_new_raw_input(setup):
    cp, _, raw = setup
    cp.with_name(cp.name + ".calls").mkdir()
    with pytest.raises(model.SemanticModelError, match="no input checkpoint"):
        prepare(cp, raw)


def test_ambiguous_v2_successor_is_rejected_and_paid_v1_v2_is_supported(setup):
    cp, config, raw = setup
    successor = cp.with_name(cp.name + ".v2")
    legacy(cp, config, raw, model.PROMPT_VERSION)
    legacy(successor, config, raw, model.PROMPT_VERSION)
    with pytest.raises(model.SemanticModelError, match="Ambiguous"):
        prepare(cp, raw)
    legacy(cp, config, raw)
    assert prepare(cp, raw)[2]["origin"] == "verified_legacy_checkpoint"


@pytest.mark.parametrize("target", ["checkpoint", "frozen"])
def test_symlinks_are_rejected(setup, target):
    cp, config, raw = setup
    destination = cp.parent / "outside.json"
    destination.write_text("{}")
    path = cp if target == "checkpoint" else cp.with_name(cp.name + ".input.json")
    path.symlink_to(destination)
    with pytest.raises((model.SemanticModelError, OSError)):
        prepare(cp, raw)


def test_missing_paid_prefix_fails_before_creating_freeze(setup):
    cp, _, raw = setup
    with pytest.raises(model.SemanticModelError, match="Successful prefix checkpoint"):
        model.segment(
            raw, "标题", analysis_id="job", checkpoint=cp, prior_progress={"completed_chunks": 5}
        )
    assert not cp.with_name(cp.name + ".input.json").exists()


def test_failed_durability_barrier_cannot_dispatch_or_report_success(setup, monkeypatch):
    cp, _, raw = setup

    def fail(fd):
        raise OSError("injected fsync failure")

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError, match="fsync failure"):
        model.segment(raw, "标题", analysis_id="job", checkpoint=cp)
    assert not cp.with_name(cp.name + ".input.json").exists()


def test_competing_install_cannot_overwrite_the_first_input(setup, monkeypatch):
    cp, _, raw = setup
    original_link = os.link
    calls = []

    def compete(source, target):
        original_link(source, target)
        calls.append(target)
        raise FileExistsError("installed concurrently")

    monkeypatch.setattr(os, "link", compete)
    first = prepare(cp, raw)
    assert len(calls) == 1 and first == prepare(cp, [{"id": "op", "text": "changed"}])


def test_frozen_file_read_runs_its_own_durability_barrier(setup, monkeypatch):
    cp, _, raw = setup
    prepare(cp, raw)

    def fail(fd):
        raise OSError("read barrier failed")

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError, match="read barrier failed"):
        prepare(cp, raw)


def test_resume_never_repacks_mutable_display_data(setup, monkeypatch):
    cp, _, raw = setup
    original = prepare(cp, raw)
    monkeypatch.setattr(
        model, "_pack", lambda *args: pytest.fail("Frozen input must not be repacked")
    )
    assert prepare(cp, [{"id": "op", "attribution": {"records": 304}}]) == original


def test_concurrent_different_initializations_have_one_winner(setup, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    cp, _, raw = setup
    link = os.link
    barrier = threading.Barrier(2)

    def simultaneous_link(source, target):
        barrier.wait(timeout=5)
        link(source, target)

    monkeypatch.setattr(os, "link", simultaneous_link)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(prepare, cp, [{"id": "op", "text": text}]) for text in ("first", "second")
        ]
        results = []
        for future in futures:
            try:
                results.append(future.result())
            except model.SemanticModelError as error:
                assert "Concurrent" in str(error)
    assert len(results) == 1
    assert prepare(cp, raw) == results[0]
