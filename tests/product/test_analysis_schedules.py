"""Sampling snapshots and queue writes are atomic, reproducible and tenant-scoped."""

import json
import math
import random
import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_analysis_batches import seeded

from trajectory.product.contracts import AnalysisBatchRequest
from trajectory.product.schedules import AnalysisSchedules, ScheduleRun, ScheduleWrite
from trajectory.product.semantic import digest
from trajectory.product.server import Principal, create_app

NOW = datetime(2026, 10, 20, 2, tzinfo=UTC)


def fixture(tmp_path, count=8):
    store, ids = seeded(tmp_path, count)
    schedules = AnalysisSchedules(store)
    old = (NOW - timedelta(days=2)).isoformat()
    with store.domain.connect() as db:
        for n, sid in enumerate(ids):
            db.execute(
                "UPDATE semantic_sessions SET source_revision=?,body=? WHERE id=?",
                (digest("one:10"), json.dumps({"operations": [{}] * (n + 1)}), sid),
            )
            db.execute(
                "INSERT INTO semantic_session_metadata VALUES(?,?,?,?)",
                (
                    "owner",
                    sid,
                    json.dumps(
                        {
                            "cwd": "/home/sdu/BatCave",
                            "native_session_id": sid,
                            "last_activity_at": old,
                        }
                    ),
                    old,
                ),
            )
            db.execute(
                "INSERT INTO source_archives VALUES(?,?,?,?,?,?,?,?,?)",
                ("owner", "collector", sid, "one", "codex", "session.jsonl", 10, 10, old),
            )
    value = ScheduleWrite(
        mutation_id="create-fixture-plan",
        schedule_id="nightly",
        name="BatCave daily",
        directories=["/home/sdu/BatCave"],
        enabled=True,
    )
    result = schedules.write("owner", value, {"account_id": "owner", "machine_client": "native"})
    with store.domain.connect() as db:
        saved = json.loads(db.execute("SELECT body FROM analysis_schedules").fetchone()[0])
        saved["enabled_at"] = old
        db.execute("UPDATE analysis_schedules SET body=?", (json.dumps(saved),))
    return store, schedules, ids, result


def test_atomic_daily_restart_concurrent_no_repeat_and_reproducible_weights(tmp_path):
    store, plans, ids, receipt = fixture(tmp_path)
    threads = [threading.Thread(target=plans.tick, args=(NOW,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    plans.tick(NOW + timedelta(hours=1))
    catalog = plans.catalog("owner")["schedules"][0]
    assert len(catalog["runs"]) == 1
    run = plans.run_detail("owner", "nightly", catalog["runs"][0]["run_id"])
    assert len(run["selected"]) == len({r["session_id"] for r in run["selected"]}) == 3
    assert run["requested_count"] == 3 and run["slot"] == "daily:2026-10-20"
    rng = random.Random(run["seed"])
    expected = sorted(
        run["snapshot"]["eligible"],
        key=lambda x: (-math.log(1 - rng.random()) / x["weight"], x["session_id"]),
    )[:3]
    assert expected == run["selected"]
    assert len(store.batches("owner")["batches"]) == 1
    AnalysisSchedules(store).tick(NOW + timedelta(days=1))
    runs = plans.catalog("owner")["schedules"][0]["runs"]
    assert len(runs) == 2
    assert {r["session_id"] for r in runs[0]["selected"]}.isdisjoint(
        {r["session_id"] for r in runs[1]["selected"]}
    )
    assert plans.catalog("stranger")["schedules"] == []
    with pytest.raises(PermissionError):
        plans.preview("stranger", "nightly")
    with store.domain.connect() as db:
        assert db.execute("SELECT count(*) FROM semantic_jobs").fetchone()[0] == 6


def test_revision_pin_conflict_and_manual_durable_receipt(tmp_path, monkeypatch):
    store, plans, ids, result = fixture(tmp_path, 2)
    monkeypatch.setattr("trajectory.product.schedules.datetime", Clock)
    value = ScheduleRun(
        mutation_id="manual-ten-request", expected_revision=result["revision"], count=10
    )
    first = plans.run("owner", "nightly", value)
    assert plans.run("owner", "nightly", value) == first
    assert len(first["selected"]) == 2 and first["requested_count"] == 10
    bad = AnalysisBatchRequest(
        mutation_id="expected-rev-conflict",
        session_ids=ids,
        expected_source_revisions=dict.fromkeys(ids, "wrong"),
    )
    with pytest.raises(ValueError, match="revision changed"):
        store.request_batch("owner", bad)
    assert len(store.batches("owner")["batches"]) == 1
    with store.domain.connect() as db:
        db.execute("UPDATE source_archives SET received_bytes=11,source_bytes=11")
    bad.expected_source_revisions = dict.fromkeys(ids, digest("one:10"))
    with pytest.raises(ValueError, match="upload changed"):
        store.request_batch("owner", bad)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def test_scope_quiet_unknown_fork_duplicate_budget_and_no_candidates(tmp_path):
    store, plans, ids, receipt = fixture(tmp_path, 8)
    with store.domain.connect() as db:
        for n, changes in enumerate(
            [
                {"cwd": "/home/sdu/embodied"},
                {"last_activity_at": NOW.isoformat()},
                {"parent_native_session_id": "parent"},
                {"native_session_id": ids[4]},
                {},
                {"last_activity_at": None},
                {},
                {},
            ]
        ):
            row = db.execute(
                "SELECT body FROM semantic_session_metadata WHERE session=?", (ids[n],)
            ).fetchone()
            meta = {**json.loads(row[0]), **changes}
            db.execute(
                "UPDATE semantic_session_metadata SET body=? WHERE session=?",
                (json.dumps(meta), ids[n]),
            )
        db.execute("UPDATE source_archives SET updated=NULL WHERE source=?", (ids[5],))
        db.execute("UPDATE source_archives SET received_bytes=9 WHERE source=?", (ids[6],))
    with store.domain.connect() as db:
        config = plans._read(db, "owner", "nightly")
        config["max_operations"] = 7
        snapshot = plans.candidates(db, "owner", config, NOW)
    reasons = {r for item in snapshot["excluded"] for r in item["reasons"]}
    assert {
        "directory_outside_scope",
        "recently_active",
        "known_fork_shared_context",
        "duplicate_native_session",
        "activity_unknown",
        "source_revision_pending",
        "exceeds_operation_budget_guard",
    } <= reasons
    assert len(snapshot["eligible"]) == 1
    plans.tick(NOW)
    plans.tick(NOW + timedelta(days=1))
    plans.tick(NOW + timedelta(days=2))
    assert plans.catalog("owner")["schedules"][0]["runs"][0]["status"] == "no_candidates"


def test_plan_revision_disabled_timezone_and_dst(tmp_path):
    store, plans, ids, receipt = fixture(tmp_path)
    config = plans.catalog("owner")["schedules"][0]
    value = ScheduleWrite(
        mutation_id="disable-fixture-plan",
        schedule_id="nightly",
        name="Disabled",
        directories=config["directories"],
        expected_revision=receipt["revision"],
    )
    assert plans.write("owner", value, {}) == plans.write("owner", value, {})
    plans.tick(NOW)
    assert plans.catalog("owner")["schedules"][0]["runs"] == []
    assert plans.catalog("owner")["schedules"][0]["next_run_at"] is None
    with pytest.raises(ValueError, match="revision changed"):
        plans.write("owner", value.model_copy(update={"mutation_id": "different-mutation"}), {})
    with pytest.raises(ValidationError):
        value.model_validate({**value.model_dump(), "timezone": "Bad/Zone"})
    # The first fold is the one daily local slot; fall-back cannot create a second.
    tz = {"timezone": "America/New_York", "local_time": "01:30"}
    assert plans.due(tz, datetime(2026, 11, 1).date()).fold == 0
    # Nonexistent 02:30 resolves to 03:30 in UTC, documenting gap catch-up.
    tz["local_time"] = "02:30"
    due = plans.due(tz, datetime(2026, 3, 8).date())
    assert due.astimezone(UTC).hour == 7


def test_http_help_scope_isolation_and_invalid_inputs(tmp_path):
    def auth(request, scope):
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        scopes = (
            ("read", "configure") if token == "owner" else ("read",) if token == "stranger" else ()
        )
        if scope is not None and scope not in scopes:
            raise HTTPException(403, "Denied")
        return Principal(token, scopes=scopes)

    app = create_app(tmp_path / "db", auth)
    client = TestClient(app)
    headers = {"Authorization": "Bearer owner"}
    route = "/trajectory/api/analysis-schedules"
    value = ScheduleWrite(
        mutation_id="create-fixture-schedule",
        schedule_id="one",
        name="One",
        directories=["/home/sdu/BatCave"],
    )
    response = client.post(route, json=value.model_dump(), headers=headers)
    assert response.status_code == 200, response.text
    assert client.post(route, json=value.model_dump(), headers=headers).json() == response.json()
    other = {"Authorization": "Bearer stranger"}
    assert client.post(route, json=value.model_dump(), headers=other).status_code == 403
    assert client.get(route, headers=other).json()["schedules"] == []
    assert client.get(route + "/one/candidates", headers=other).status_code == 403
    assert client.get(route + "/one/candidates", headers=headers).json()["eligible"] == []
    tools = client.get("/trajectory/help", headers=headers).json()["tools"]
    assert len([t for t in tools if t["name"].startswith("analysis_schedule_")]) == 6
    assert (
        client.post(
            route, json={**value.model_dump(), "daily_count": 0}, headers=headers
        ).status_code
        == 422
    )


def test_replayed_source_does_not_reset_inactivity_clock(tmp_path):
    from test_semantic import chunk

    from trajectory.product.domain import Domain
    from trajectory.product.semantic import SemanticStore

    store = SemanticStore(Domain(tmp_path / "clock.db"))
    store.domain.register("owner", "machine", "fixture")
    store.ingest_source("machine", chunk(b"x\n"))
    old = "2026-10-01T00:00:00+00:00"
    with store.domain.connect() as db:
        db.execute("UPDATE source_content_activity SET changed=?", (old,))
    store.ingest_source("machine", chunk(b"x\n"))
    with store.domain.connect() as db:
        assert db.execute("SELECT changed FROM source_content_activity").fetchone()[0] == old
    store.ingest_source("machine", chunk(b"y\n", start=2))
    with store.domain.connect() as db:
        row = db.execute("SELECT * FROM source_content_activity").fetchone()
        assert row["changed"] != old and row["revision"] == "generation-1:4"


def test_active_copy_excludes_quiet_same_native_and_self_parent_is_not_fork(tmp_path):
    store, plans, ids, _ = fixture(tmp_path, 3)
    with store.domain.connect() as db:
        for sid, meta in [
            (ids[0], {"native_session_id": "shared"}),
            (ids[1], {"native_session_id": "shared", "last_activity_at": NOW.isoformat()}),
            (ids[2], {"parent_native_session_id": ids[2]}),
        ]:
            prior = json.loads(
                db.execute(
                    "SELECT body FROM semantic_session_metadata WHERE session=?", (sid,)
                ).fetchone()[0]
            )
            db.execute(
                "UPDATE semantic_session_metadata SET body=? WHERE session=?",
                (json.dumps({**prior, **meta}), sid),
            )
        snap = plans.candidates(db, "owner", plans._read(db, "owner", "nightly"), NOW)
    assert [r["session_id"] for r in snap["eligible"]] == [ids[2]]
    assert all("recently_active" in r["reasons"] for r in snap["excluded"])


def test_archive_preserves_receipts_and_cannot_launch_paid_work(tmp_path):
    from trajectory.product.schedules import ScheduleDelete

    _, plans, _, receipt = fixture(tmp_path)
    value = ScheduleDelete(
        mutation_id="archive-fixture-plan", expected_revision=receipt["revision"]
    )
    result = plans.remove("owner", "nightly", value, {})
    assert plans.remove("owner", "nightly", value, {}) == result
    plan = plans.catalog("owner")["schedules"][0]
    assert plan["archived"] and not plan["enabled"]
    with pytest.raises(ValueError, match="Archived"):
        plans.run(
            "owner",
            "nightly",
            ScheduleRun(mutation_id="archived-paid-block", expected_revision=result["revision"]),
        )


def test_enabling_after_slot_starts_next_day_not_surprise_immediate_charge(tmp_path, monkeypatch):
    _, plans, _, _ = fixture(tmp_path)
    monkeypatch.setattr("trajectory.product.schedules.datetime", Clock)
    config = plans.catalog("owner")["schedules"][0]
    disable = ScheduleWrite(
        schedule_id="nightly",
        name="One",
        directories=config["directories"],
        mutation_id="disable-for-enable-check",
        expected_revision=config["revision"],
    )
    result = plans.write("owner", disable, {})
    plans.write(
        "owner",
        disable.model_copy(
            update={
                "enabled": True,
                "mutation_id": "enable-after-daily-time",
                "expected_revision": result["revision"],
            }
        ),
        {},
    )
    plans.tick(NOW)
    assert plans.catalog("owner")["schedules"][0]["runs"] == []
    assert plans.catalog("owner")["schedules"][0]["next_run_at"].startswith("2026-10-21T01:00")
    plans.tick(NOW + timedelta(days=1))
    assert len(plans.catalog("owner")["schedules"][0]["runs"]) == 1


def test_invalid_plan_runtime_budget_is_receipted_once_without_poisoning_queue(
    tmp_path, monkeypatch
):
    store, plans, ids, _ = fixture(tmp_path)
    monkeypatch.setenv("TRAJECTORY_ANALYSIS_CONCURRENCY", "1")
    plans.tick(NOW)
    plans.tick(NOW)
    plan = plans.catalog("owner")["schedules"][0]
    assert len(plan["runs"]) == 1 and plan["runs"][0]["status"] == "blocked"
    assert "Concurrency" in plan["runs"][0]["error"]
    assert store.batches("owner")["batches"] == []
    store.request_batch(
        "owner",
        AnalysisBatchRequest(
            mutation_id="independent-normal-work", session_ids=ids[:1], concurrency=1
        ),
    )
    assert store.claim_job()


def test_explicit_native_delegation_revocation_and_caller_identity(tmp_path):
    import uuid

    machine = str(uuid.uuid4())
    checks = {"machine": True, "owner": True}

    def auth(request, scope):
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if token == "machine" and checks["machine"]:
            return Principal(machine, "automation", "key-1", ("read", "configure"))
        if token == "operator":
            return Principal("owner", scopes=("read", "configure", "read_all"))
        raise HTTPException(403, "Denied")

    app = create_app(
        tmp_path / "delegation.db",
        auth,
        machine_verifier=lambda account, client: account == machine and client == "automation",
        resource_owner_verifier=lambda owner: checks["owner"] and owner == "owner",
    )
    client = TestClient(app)
    op = {"Authorization": "Bearer operator"}
    robot = {"Authorization": "Bearer machine"}
    base = "/trajectory/api/analysis-schedules"
    payload = ScheduleWrite(
        schedule_id="test",
        mutation_id="owner-plan-delegation",
        name="Owner",
        directories=["/home/sdu/BatCave"],
    ).model_dump()
    assert client.post(base, json=payload, headers=op).status_code == 200
    assert client.get(base, headers=robot).json()["schedules"] == []
    assert client.get(base + "?resource_owner=owner", headers=robot).status_code == 403
    grant = {
        "mutation_id": "grant-native-analysis",
        "machine": machine,
        "machine_client": "automation",
    }
    route = "/trajectory/api/analysis-automation-grants"
    result = client.post(route, json=grant, headers=op)
    assert result.status_code == 200, result.text
    assert client.post(route, json=grant, headers=op).json() == result.json()
    assert len(client.get(base + "?resource_owner=owner", headers=robot).json()["schedules"]) == 1
    help = client.get("/trajectory/help", headers=robot).json()
    assert help["caller"] == {"account_id": machine, "machine_client": "automation"}
    assert (
        client.get("/trajectory/api/overview?resource_owner=owner", headers=robot).status_code
        == 403
    )
    assert client.post(route, json=grant, headers=robot).status_code == 403
    checks["owner"] = False
    assert client.get(base + "?resource_owner=owner", headers=robot).status_code == 403
    checks["owner"] = True
    revoke = {
        **grant,
        "mutation_id": "revoke-native-analysis",
        "enabled": False,
        "expected_revision": result.json()["revision"],
    }
    assert client.post(route, json=revoke, headers=op).status_code == 200
    assert client.get(base + "?resource_owner=owner", headers=robot).status_code == 403
    checks["machine"] = False
    assert client.get(base, headers=robot).status_code == 403
