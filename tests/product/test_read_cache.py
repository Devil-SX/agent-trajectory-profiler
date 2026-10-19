"""Derived reads coalesce work, retain isolation, and follow authoritative revisions."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_semantic import advance_session, analysis, seed_session
from test_semantic import store as store

from trajectory.product.read_cache import RevisionCache


def test_same_revision_coalesces_and_never_shares_mutable_results():
    cache = RevisionCache(max_bytes=1024, max_entries=2)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def load():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return {"tasks": [{"title": "original"}]}

    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(cache.get, ("owner", 1), load)
        assert entered.wait(5)
        others = [pool.submit(cache.get, ("owner", 1), load) for _ in range(3)]
        release.set()
        results = [first.result(), *(future.result() for future in others)]
    assert len(calls) == 1
    results[0]["tasks"][0]["title"] = "edited by caller"
    assert all(value["tasks"][0]["title"] == "original" for value in results[1:])
    assert cache.get(("other-owner", 1), lambda: {"tasks": []}) == {"tasks": []}


def test_failed_load_does_not_poison_or_deadlock_and_capacity_is_bounded():
    cache = RevisionCache(max_bytes=64, max_entries=2)
    with pytest.raises(ValueError):
        cache.get("failed", lambda: (_ for _ in ()).throw(ValueError("failed")))
    assert cache.get("failed", lambda: [1]) == [1]
    for key in range(20):
        assert cache.get(key, lambda: "x" * 40) == "x" * 40
    assert cache._bytes <= 64
    assert len(cache._values) <= 2
    assert cache.get("oversize", lambda: "x" * 100) == "x" * 100
    assert "oversize" not in cache._values


def test_detail_changes_with_saved_analysis_and_new_source_and_pins_old_body(store):
    sid, revision = seed_session(store)
    store.save_analysis("owner", sid, revision, analysis())
    first = store.detail("owner", sid)
    first["tasks"][0]["title"] = "caller mutation"
    assert store.detail("owner", sid)["tasks"][0]["title"] != "caller mutation"
    changed = analysis()
    changed["tasks"][0]["title"] = "new authoritative title"
    store.save_analysis("owner", sid, revision, changed)
    assert store.detail("owner", sid)["tasks"][0]["title"] == "new authoritative title"
    new_revision = advance_session(store, sid)
    current = store.detail("owner", sid)
    assert current["current_parsed_source_revision"] == new_revision
    assert current["historical_snapshot"] is True
    assert store.operation("owner", sid, "op-0", source_revision=revision)["text"] == "evidence-0"
    with pytest.raises(ValueError):
        store.operation("stranger", sid, "op-0", source_revision=revision)
    with pytest.raises(ValueError, match="Unknown operation"):
        store.operation("owner", sid, "missing", source_revision=revision)
