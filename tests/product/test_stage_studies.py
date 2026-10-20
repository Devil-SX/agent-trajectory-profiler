"""Study imports preserve ownership, frozen identity, unknowns and unique metric attribution."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_analysis_batches import request, seeded

from trajectory.product.server import Principal, create_app
from trajectory.product.stage_studies import (
    METRICS,
    StageStudies,
    StageStudyImport,
    distribution,
    spearman,
)


def study_fixture(tmp_path, count=2):
    semantic, ids = seeded(tmp_path, count)
    batch = semantic.request_batch("owner", request(ids))
    references, labels = [], []
    for index, sid in enumerate(ids):
        tasks = [
            {"id": "root", "parent_id": None, "title": "root", "operation_ids": []},
            {"id": "p", "parent_id": "root", "title": "Plan and execute", "operation_ids": ["a"]},
            {"id": "c", "parent_id": "p", "title": "Test result", "operation_ids": ["b"]},
            {"id": "empty", "parent_id": "root", "title": "No own operations", "operation_ids": []},
            {"id": "d", "parent_id": "empty", "title": "Deliver", "operation_ids": ["c"]},
        ]
        revision = semantic.save_analysis("owner", sid, "revision", {"tasks": tasks})
        references.append(
            {
                "session_id": sid,
                "analysis_revision": revision,
                "source_revision": "revision",
                "measurement_sha256": "a" * 64,
                "segmentation": {"model": "fixture-segmenter"},
            }
        )
        for task, tag, confidence, mixed, tokens in [
            ("p", "understand_decide", 0.9, 0.8, 10),
            ("c", "validate_debug", 0.8, 0.2, 20),
            ("empty", "coordinate_maintain", 0.3, 0.6, None),
            ("d", "coordinate_maintain", 0.9, 0.1, 30),
        ]:
            t = next(t for t in tasks if t["id"] == task)
            metrics = {
                k: None if index else (tokens if k == "recorded_tokens" else 0) for k in METRICS
            }
            if task == "empty":
                metrics = dict.fromkeys(METRICS)
            labels.append(
                {
                    "session_id": sid,
                    "task_id": task,
                    "title": t["title"],
                    "operation_ids": t["operation_ids"],
                    "primary_tag": tag,
                    "confidence": confidence,
                    "mixed_probability": mixed,
                    "probabilities": {
                        k: float(k == tag)
                        for k in [
                            "understand_decide",
                            "build_execute",
                            "validate_debug",
                            "coordinate_maintain",
                            "uncertain",
                        ]
                    },
                    "secondary_tags": ["build_execute"] if task == "p" else [],
                    "call_id": "fixture-stable-call-id",
                    "receipt_id": "fixture-receipt-id-1",
                    "metrics": metrics,
                }
            )
    value = StageStudyImport.model_validate(
        {
            "mutation_id": "fixture-import-mutation",
            "study_id": "fixture-study",
            "title": "Fixture study",
            "batch_id": batch["batch_id"],
            "sessions": references,
            "stages": labels,
            "classification": {"model": "fixture-jev"},
            "measurement_policy": {"human": "unknown"},
        }
    )
    return semantic, StageStudies(semantic.domain), value


def test_import_replay_revision_conflict_owner_and_complete_memberships(tmp_path):
    semantic, studies, value = study_fixture(tmp_path)
    first = studies.import_study("owner", value)
    assert first["unique_operations"] == 6 and not first["replayed"]
    assert studies.import_study("owner", value)["replayed"]
    assert (
        StageStudies(semantic.domain).catalog("owner")["items"][0]["revision"] == first["revision"]
    )
    assert studies.catalog("stranger") == {"items": []}
    with pytest.raises(PermissionError):
        studies.import_study("stranger", value)
    for change in [
        {"title": "Changed body"},
        {"stages": value.model_dump()["stages"][:-1]},
    ]:
        with pytest.raises(ValueError):
            studies.import_study(
                "owner", StageStudyImport.model_validate({**value.model_dump(), **change})
            )
    altered = value.model_dump()
    altered.update(study_id="changed-revision", mutation_id="changed-revision-mutation")
    altered["sessions"][0]["analysis_revision"] = "wrong"
    with pytest.raises(ValueError, match="revision changed"):
        studies.import_study("owner", StageStudyImport.model_validate(altered))
    altered = value.model_dump()
    altered.update(study_id="changed-members", mutation_id="changed-members-mutation")
    altered["stages"][0]["operation_ids"] = ["different"]
    with pytest.raises(ValueError, match="membership changed"):
        studies.import_study("owner", StageStudyImport.model_validate(altered))


def test_direct_and_subtree_frontier_do_not_double_count_or_turn_unknown_into_zero(tmp_path):
    semantic, studies, value = study_fixture(tmp_path)
    studies.import_study("owner", value)
    direct = studies.summary("owner", "fixture-study", {})
    assert direct["summary"]["stages"] == 8 and direct["unique_resource_metric"]["sum"] == 60
    assert direct["summary"]["metric"]["missing"] == 5
    assert direct["unique_resource_metric"]["available"] == 3
    assert direct["unique_resource_metric"]["missing"] == 3
    assert direct["resource_frontier_stages"] == 6
    assert direct["summary"]["direct_nonempty_stages"] == 6
    assert direct["summary"]["multiple_label_rate"] == 0.25
    assert sum(direct["confidence_histogram"]) == 8
    assert (
        studies.summary("owner", "fixture-study", {"confidence_min": "0.85"})["summary"]["stages"]
        == 4
    )
    assert studies.summary("owner", "fixture-study", {"mixed": "single"})["summary"]["stages"] == 4
    subtree = studies.summary("owner", "fixture-study", {"membership": "subtree"})
    assert subtree["resource_frontier_stages"] == 4
    assert subtree["unique_resource_metric"]["sum"] == 60
    assert subtree["unique_resource_metric"]["missing"] == 2
    byid = {
        r["task_id"]: r
        for r in studies.stages("owner", "fixture-study", {"session_id": "session-0"})["items"]
    }
    assert (
        byid["p"]["subtree_operation_count"] == 2
        and byid["p"]["subtree_metrics"]["recorded_tokens"] == 30
    )
    assert byid["empty"]["metrics"]["recorded_tokens"] is None
    assert byid["empty"]["subtree_metrics"]["recorded_tokens"] == 30
    assert byid["p"]["subtree_tag_entropy"] > 0 and byid["p"]["mixed_probability"] == 0.8
    assert byid["p"]["depth"] == 1 and byid["c"]["depth"] == 2
    assert byid["c"]["is_leaf"] and not byid["p"]["is_leaf"]
    filtered = studies.summary(
        "owner", "fixture-study", {"tag": "build_execute", "node_kind": "parent"}
    )
    assert filtered["summary"]["stages"] == 2  # Secondary label matches; primary remains unchanged.
    assert filtered["categories"][0]["stage_share"] == 1
    assert direct["human_gold_accuracy"] is None and direct["segmentation_confidence"] is None
    assert direct["cluster_unit"] == "imported_session_record_id"
    assert direct["native_session_independence_corrected"] is False
    assert "fork dependencies uncorrected" in direct["uncertainty_method"]
    category = next(c for c in direct["categories"] if c["tag"] == "understand_decide")
    assert category["resource_share_sessions"] == 1 and category["resource_share_ci95"] is None
    assert category["stage_share_sessions"] == 2 and category["stage_share_ci95"] is not None
    assert (
        studies.summary("owner", "fixture-study", {"q": "no match"})["summary"]["confidence"][
            "mean"
        ]
        is None
    )
    assert (
        studies.stages("owner", "fixture-study", {"depth": "2", "limit": "1"})["next_offset"] == 1
    )
    assert "confidence,mixed_probability" in studies.csv("owner", "fixture-study", {})
    assert "resource_metric_eligible" in studies.csv("owner", "fixture-study", {})
    for filters in [
        {"metric": "fake"},
        {"depth": "-1"},
        {"membership": "bad"},
        {"node_kind": "bad"},
        {"secret": "x"},
        {"confidence_min": "nan"},
        {"mixed": "perhaps"},
    ]:
        with pytest.raises(ValueError):
            studies.summary("owner", "fixture-study", filters)
    semantic.save_analysis("owner", "session-0", "revision", {"tasks": []})
    assert studies.summary("owner", "fixture-study", {})["changed_analysis_sessions"] == [
        "session-0"
    ]


def test_authenticated_http_discovery_static_assets_and_export(tmp_path):
    semantic, studies, value = study_fixture(tmp_path, 1)

    def authorize(request, scope):
        token = request.headers.get("authorization")
        if token in {"owner", "reader", "stranger"} and (
            scope in {None, "read"} or token == "owner" and scope == "configure"
        ):
            return Principal(
                "owner" if token == "reader" else token,
                scopes=("read",) if token == "reader" else ("read", "configure"),
            )
        raise HTTPException(403, "Denied")

    app = create_app(semantic.domain.path, authorize)
    client = TestClient(app)
    path = "/trajectory/api/stage-studies"
    assert client.get(path).status_code == 403
    assert (
        client.post(path, json=value.model_dump(), headers={"Authorization": "reader"}).status_code
        == 403
    )
    assert (
        client.post(path, json=value.model_dump(), headers={"Authorization": "owner"}).status_code
        == 200
    )
    assert (
        client.get(path + "/fixture-study", headers={"Authorization": "stranger"}).status_code
        == 403
    )
    read = client.get(path + "/fixture-study", headers={"Authorization": "reader"})
    assert read.status_code == 200 and read.json()["summary"]["stages"] == 4
    active = client.get(
        path + "/fixture-study?metric=active_seconds_estimate&node_kind=leaf",
        headers={"Authorization": "reader"},
    )
    assert active.status_code == 200
    assert active.json()["metric"] == "active_seconds_estimate"
    assert active.json()["unique_resource_metric"]["sum"] == 0
    assert active.json()["categories"][0]["resource_share"] is None
    assert (
        client.get(
            path + "/fixture-study?metric=invalid", headers={"Authorization": "reader"}
        ).status_code
        == 409
    )
    assert (
        client.get(path + "/fixture-study/stages?format=csv", headers={"Authorization": "reader"})
        .headers["content-type"]
        .startswith("text/csv")
    )
    assert client.get("/trajectory/research.js").status_code == 403
    assert (
        "TrajectoryResearch"
        in client.get("/trajectory/research.js", headers={"Authorization": "reader"}).text
    )
    helpdoc = client.get("/trajectory/help", headers={"Authorization": "reader"}).json()
    assert {t["name"] for t in helpdoc["tools"]} >= {
        "stage_study_read",
        "stage_study_list",
        "stage_study_stages",
    }
    assert "stage_study_import" not in {t["name"] for t in helpdoc["tools"]}
    broken = value.model_dump()
    broken["stages"][0]["confidence"] = 2
    assert client.post(path, json=broken, headers={"Authorization": "owner"}).status_code == 422


def test_rank_relation_keeps_constant_and_empty_samples_unknown():
    assert spearman([1, 2, 3], [3, 2, 1]) == -1
    assert spearman([1, 1, 1], [1, 2, 3]) is None
    assert spearman([], []) is None


def test_variance_requires_multiple_observations_and_preserves_missing_values():
    assert distribution([None])["sample_variance"] is None
    assert distribution([0, None])["sample_sd"] is None
    values = distribution([1, 3, None])
    assert values["sample_variance"] == 2
    assert values["sample_sd"] == 2**0.5
    assert values["available"] == 2 and values["missing"] == 1


def test_active_time_is_filter_specific_and_retains_measured_zero(tmp_path):
    semantic, studies, value = study_fixture(tmp_path)
    payload = value.model_dump()
    for row in payload["stages"]:
        if row["task_id"] == "empty":
            continue
        row["metrics"]["active_seconds_estimate"] = (
            {"p": 10, "c": 20, "d": 30}[row["task_id"]] if row["session_id"] == "session-0" else 0
        )
    studies.import_study("owner", StageStudyImport.model_validate(payload))
    total = studies.summary("owner", "fixture-study", {"metric": "active_seconds_estimate"})
    assert total["unique_resource_metric"]["sum"] == 60
    assert total["unique_resource_metric"]["available"] == 6
    assert total["categories"][0]["resource_share"] == 1 / 6
    leaf = studies.summary(
        "owner", "fixture-study", {"metric": "active_seconds_estimate", "node_kind": "leaf"}
    )
    assert leaf["unique_resource_metric"]["sum"] == 50
    assert leaf["categories"][0]["resource_share"] == 0
    zero = studies.summary(
        "owner", "fixture-study", {"metric": "active_seconds_estimate", "session_id": "session-1"}
    )
    assert zero["unique_resource_metric"]["sum"] == 0
    assert zero["unique_resource_metric"]["available"] == 3
    assert all(
        c["resource_share"] is None and c["resource_share_ci95"] is None for c in zero["categories"]
    )
