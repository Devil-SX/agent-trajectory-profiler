"""Source attribution keeps global winners while isolating cached derived reads."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from test_memory_snapshot import event, ingest

from trajectory.product.contracts import Correction, Price
from trajectory.product.domain import Domain
from trajectory.product.ledger_scan import LedgerScan, UniqueUsages


def domain_fixture(tmp_path):
    domain = Domain(tmp_path / "ledger.sqlite")
    domain.register("owner", "machine", "fixture")
    return domain


def test_scoped_usage_projection_preserves_global_winner_before_session_filter(
    tmp_path, monkeypatch
):
    domain = domain_fixture(tmp_path)
    ingest(
        domain,
        "source-0000000001",
        [
            event("old-shared", "usage", 1, session="selected", consumption="shared", input=20),
            event("own", "usage", 2, session="selected", consumption="own", input=30),
            event("fallback", "usage", 3, session="selected", consumption="", input=40),
        ],
    )
    ingest(
        domain,
        "source-0000000002",
        [
            event("new-shared", "usage", 4, session="elsewhere", consumption="shared", input=200),
            event("unrelated", "usage", 5, session="elsewhere", consumption="other", input=300),
            event("fallback", "usage", 6, session="elsewhere", consumption="", input=400),
        ],
    )
    with domain.connect() as db:
        records = LedgerScan(db, "owner", {})
        baseline = UniqueUsages(records)
        expected = [item for item in baseline if item["session"] == "selected"]
        decoded = []
        original = records.decode

        def decode(row, **kwargs):
            decoded.append(row["source"])
            return original(row, **kwargs)

        monkeypatch.setattr(records, "decode", decode)
        scoped = UniqueUsages(records, sessions={"selected"})
        actual = list(scoped)
        assert actual == expected
        assert [item["input"] for item in actual] == [30]
        assert scoped.duplicates == baseline.duplicates == 2
        assert len(decoded) == 1
        assert list(UniqueUsages(LedgerScan(db, "stranger", {}), sessions={"selected"})) == []


def test_source_cache_copies_and_invalidates_for_global_winner_price_and_correction(
    tmp_path, monkeypatch
):
    domain = domain_fixture(tmp_path)
    first = "source-0000000001"
    ingest(domain, first, [event("own", "usage", 1, input=20, consumption="shared")])
    original = domain._calculate_overview
    calls = []

    def calculate(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(domain, "_calculate_overview", calculate)
    selected = domain.source_contributions("owner", "fixture", first)
    selected[0]["record"]["input"] = -100
    assert domain.source_contributions("owner", "fixture", first)[0]["record"]["input"] == 20
    assert len(calls) == 1
    domain.trace({"request_id": "trace-only", "created": "now"})
    domain.source_contributions("owner", "fixture", first)
    assert len(calls) == 1
    assert domain.source_contributions("stranger", "fixture", first) == []
    assert len(calls) == 2
    # A different writer/source can steal the global consumption winner.
    writer = Domain(domain.path)
    ingest(
        writer, "source-0000000002", [event("winner", "usage", 2, input=100, consumption="shared")]
    )
    assert (
        sum(item["calls"] for item in domain.source_contributions("owner", "fixture", first)) == 0
    )
    assert len(calls) == 3
    domain.price(
        "owner",
        Price.model_validate(
            {
                "mutation_id": uuid.uuid4().hex,
                "model": "model",
                "input": 1,
                "output": 1,
                "cached": 0,
                "cache_write": 0,
                "effective_from": "2026-01-01T00:00:00Z",
                "source_url": "https://example.org/price",
            }
        ),
    )
    domain.source_contributions("owner", "fixture", first)
    assert len(calls) == 4
    domain.correct(
        "owner",
        Correction(
            mutation_id=uuid.uuid4().hex,
            task="shared-task",
            project="changed",
            project_name="Changed",
        ),
    )
    updated = domain.source_contributions("owner", "fixture", "source-0000000002")
    assert updated[0]["record"]["project"] == "changed"
    assert len(calls) == 5


def test_identical_source_reads_coalesce_without_waiting_for_overview(tmp_path, monkeypatch):
    domain = domain_fixture(tmp_path)
    started, release = threading.Event(), threading.Event()
    calls = []

    def calculate(*args, **kwargs):
        calls.append(1)
        started.set()
        assert release.wait(5)
        return {"event_contributions": [{"record": {"id": "value"}}]}

    monkeypatch.setattr(domain, "_calculate_overview", calculate)
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [
            pool.submit(domain.source_contributions, "owner", "fixture", "source") for _ in range(5)
        ]
        try:
            assert started.wait(5), "Source reads must retain their independent coalesced flight"
        finally:
            release.set()
        results = [future.result(timeout=5) for future in futures]
    assert len(calls) == 1
    results[0][0]["record"]["id"] = "mutated"
    assert all(result[0]["record"]["id"] == "value" for result in results[1:])


def test_distinct_cold_sources_have_independent_flights_and_bounded_parallel_scans(
    tmp_path, monkeypatch
):
    domain = domain_fixture(tmp_path)
    entered = threading.Barrier(3)
    release = threading.Event()
    active = 0
    peak = 0
    lock = threading.Lock()

    def calculate(*args, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            if not release.is_set():
                entered.wait(timeout=5)
            assert release.wait(5)
            return {"event_contributions": []}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(domain, "_calculate_overview", calculate)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(domain.source_contributions, "owner", "fixture", str(i)) for i in range(3)
        ]
        try:
            entered.wait(timeout=5)
        finally:
            release.set()
        assert [f.result(timeout=5) for f in futures] == [[], [], []]
    assert peak == 2


def test_ledger_revision_uses_the_callers_read_snapshot(tmp_path):
    domain = domain_fixture(tmp_path)
    ingest(domain, "source-0000000001", [event("first", "usage", 1, input=10)])
    with domain.connect() as db:
        db.execute("BEGIN")
        original = domain.ledger_revision(db)
        ingest(Domain(domain.path), "source-0000000002", [event("second", "usage", 2, input=20)])
        assert domain.ledger_revision(db) == original
        assert domain.ledger_revision() > original
