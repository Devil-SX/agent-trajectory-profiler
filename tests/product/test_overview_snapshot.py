"""Persistent statistics retain successful results until one atomic refresh publishes."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from trajectory.product.contracts import Batch
from trajectory.product.domain import Domain
from trajectory.product.statistics_snapshots import (
    MAX_SCOPES,
    StatisticsRefresh,
    StatisticsSnapshots,
    schedule,
    scope_dates,
)


def batch(revision, tokens):
    return Batch.model_validate(
        {
            "mutation_id": uuid.uuid4().hex,
            "collector": "fixture",
            "source": "source-000000001",
            "revision": revision,
            "source_bytes": 100,
            "read_bytes": 100,
            "parser_version": "fixture/1",
            "replace": True,
            "records": [
                {
                    "id": "usage-00000000001",
                    "session": "session",
                    "task": "task",
                    "ecosystem": "codex",
                    "timestamp": "2026-10-01T00:00:00Z",
                    "kind": "usage",
                    "model": "model",
                    "source_line": 1,
                    "input": tokens,
                    "output": 0,
                    "cached": 0,
                    "cache_write": 0,
                }
            ],
        }
    )


def seeded(tmp_path):
    domain = Domain(tmp_path / "domain.db")
    domain.register("owner", "machine", "fixture")
    domain.ingest("machine", batch(1, 10))
    store = StatisticsSnapshots(domain)
    store.verify_actor = lambda actor: None  # Isolated fixture has no native account store.
    return domain, store


def publish(store):
    job = store.claim()
    assert job is not None
    assert store.build(job)
    return job


def test_initial_get_is_fast_metadata_only_and_published_values_survive_restart(
    tmp_path, monkeypatch
):
    domain, store = seeded(tmp_path)
    original = domain._calculate_snapshot
    monkeypatch.setattr(
        domain, "_calculate_snapshot", lambda *a: pytest.fail("GET computed statistics")
    )
    initial = store.read("owner")
    assert initial["statistics_snapshot"]["state"] == "building"
    assert initial["statistics_snapshot"]["available"] is False
    assert "projects" not in initial and "generated_at" not in initial
    assert (
        store.read("owner")["statistics_snapshot"]["update"]["id"]
        == initial["statistics_snapshot"]["update"]["id"]
    )
    monkeypatch.setattr(domain, "_calculate_snapshot", original)
    publish(store)
    ready = store.read("owner")
    assert ready["projects"][0]["input"] == 10
    assert ready["statistics_snapshot"]["available"]
    assert ready["statistics_snapshot"]["source_watermark"]
    assert ready["statistics_snapshot"]["source_observed_at"] <= ready["generated_at"]
    domain.ingest("machine", batch(2, 20))
    stale = store.read("owner")
    assert stale["projects"] == ready["projects"]
    assert stale["statistics_snapshot"]["stale"]
    restarted = StatisticsSnapshots(Domain(domain.path))
    monkeypatch.setattr(
        restarted.domain, "_calculate_snapshot", lambda *a: pytest.fail("Restart GET recomputed")
    )
    assert restarted.read("owner")["projects"] == ready["projects"]
    assert not hasattr(domain, "_overview_cache")


def test_manual_concurrent_and_daily_coalesce_failure_retains_success(tmp_path, monkeypatch):
    domain, store = seeded(tmp_path)
    store.read("owner")
    publish(store)
    old = store.read("owner")
    actor = {"account_id": "owner", "required_scopes": ["configure"]}
    requests = [StatisticsRefresh(mutation_id=uuid.uuid4().hex) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(lambda v: store.request("owner", actor, v), requests))
    assert len({r["job_id"] for r in receipts}) == 1
    assert all(r["durable"] for r in receipts)
    assert store.request("owner", actor, requests[0]) == receipts[0]
    assert store.tick(datetime(2026, 10, 20, 16, 59, 59, tzinfo=UTC)) == 0
    assert store.tick(datetime(2026, 10, 20, 17, tzinfo=UTC)) == 1
    assert store.tick(datetime(2026, 10, 20, 17, 1, tzinfo=UTC)) == 0
    assert store.read("owner")["statistics_snapshot"]["state"] == "updating"
    job = store.claim()
    monkeypatch.setattr(
        domain,
        "_calculate_snapshot",
        lambda *a: (_ for _ in ()).throw(ValueError("private source text")),
    )
    assert not store.build(job)
    failed = store.read("owner")
    assert failed["projects"] == old["projects"]
    assert failed["generated_at"] == old["generated_at"]
    assert failed["statistics_snapshot"]["state"] == "failed"
    assert "private source text" not in str(failed)
    assert store.tick(datetime(2026, 10, 21, 17, tzinfo=UTC)) == 1
    assert store.pending()


def test_scope_isolation_limits_and_atomic_read_watermark(tmp_path, monkeypatch):
    domain, store = seeded(tmp_path)
    old = domain.overview("owner")
    store.read("owner")
    original = domain._calculate_snapshot

    def with_concurrent_write(db, *args):
        domain.ingest("machine", batch(2, 99))
        return original(db, *args)

    monkeypatch.setattr(domain, "_calculate_snapshot", with_concurrent_write)
    publish(store)
    result = store.read("owner")
    assert result["projects"] == old["projects"]
    assert result["daily"] == old["daily"]
    assert result["statistics_snapshot"]["stale"]
    assert (
        result["statistics_snapshot"]["source_watermark"]
        != result["statistics_snapshot"]["current_watermark"]
    )
    assert "projects" not in store.read("stranger")
    assert "projects" not in store.read(None)
    assert "projects" not in store.read("owner", since="2026-10-02")
    for day in range(3, MAX_SCOPES + 1):
        store.read("owner", since=f"2026-10-{day:02}")
    with pytest.raises(ValueError, match="上限"):
        store.read("owner", since="2026-11-01")
    with pytest.raises(ValueError):
        scope_dates("2026-11-02", "2026-10-01")
    with pytest.raises(ValueError):
        scope_dates("invalid")
    assert schedule(datetime(2026, 10, 20, 16, 59, tzinfo=UTC))["next_run_at"].startswith(
        "2026-10-21T01:00"
    )
    assert schedule(datetime(2026, 10, 20, 17, tzinfo=UTC))["next_run_at"].startswith(
        "2026-10-22T01:00"
    )


def test_scope_algorithm_and_actor_revalidation_fail_closed(tmp_path):
    domain, store = seeded(tmp_path)
    store.read("owner")
    job = store.claim()
    store.recover()
    recovered = store.claim()
    assert recovered["id"] == job["id"] and recovered["attempt"] == job["attempt"] + 1
    assert not store.build(job)  # An old attempt cannot publish or mark the new one failed.
    store.verify_actor = lambda actor: (_ for _ in ()).throw(PermissionError("revoked"))
    assert not store.build(recovered)
    assert not store.read("owner")["statistics_snapshot"]["available"]
    actor = {"account_id": "owner"}
    store.request("owner", actor, StatisticsRefresh(mutation_id="retry-statistics-0001"))
    store.verify_actor = lambda actor: None
    publish(store)
    with domain.connect() as db:
        db.execute("UPDATE statistics_snapshots SET algorithm='retired/0'")
    assert "projects" not in store.read("owner")


def test_build_cooldown_survives_restart_and_allows_other_work(tmp_path):
    domain, store = seeded(tmp_path)
    assert store.can_start()
    store.read("owner")
    publish(store)
    with domain.connect() as db:
        completed = datetime.fromisoformat(
            db.execute("SELECT finished FROM statistics_jobs WHERE status='complete'").fetchone()[0]
        )
    restarted = StatisticsSnapshots(domain)
    assert not restarted.can_start(completed + timedelta(seconds=29))
    assert restarted.can_start(completed + timedelta(seconds=30))


def test_reads_keep_published_result_while_building_and_revoked_publish_is_rejected(
    tmp_path, monkeypatch
):
    domain, store = seeded(tmp_path)
    store.read("owner")
    publish(store)
    old = store.read("owner")
    domain.ingest("machine", batch(2, 99))
    store.request(
        "owner",
        {"account_id": "owner"},
        StatisticsRefresh(mutation_id="refresh-revoked-before-publish"),
    )
    job = store.claim()
    original = domain._calculate_snapshot
    started, resume = Event(), Event()
    checks = []

    def calculate(*args):
        started.set()
        assert resume.wait(5)
        return original(*args)

    def verify(actor):
        checks.append(actor)
        if len(checks) > 1:
            raise PermissionError("revoked while computing")

    monkeypatch.setattr(domain, "_calculate_snapshot", calculate)
    store.verify_actor = verify
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(store.build, job)
        assert started.wait(2)
        during = store.read("owner")
        assert during["projects"] == old["projects"]
        assert during["statistics_snapshot"]["state"] == "updating"
        resume.set()
        assert not future.result(timeout=5)
    failed = store.read("owner")
    assert failed["projects"] == old["projects"]
    assert failed["statistics_snapshot"]["state"] == "failed"
    assert len(checks) == 2


def test_builder_without_an_explicit_identity_verifier_fails_closed(tmp_path):
    domain, _ = seeded(tmp_path)
    store = StatisticsSnapshots(domain)
    store.read("owner")
    assert not store.build(store.claim())
    value = store.read("owner")
    assert value["statistics_snapshot"]["state"] == "failed"
    assert not value["statistics_snapshot"]["available"]
