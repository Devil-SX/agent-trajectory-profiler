"""A closed dispatch gate drains paid requests at saved window boundaries."""

from test_analysis_batches import request, seeded

from trajectory.product import semantic_model
from trajectory.product.semantic_runtime import AnalysisRuntime


def test_gate_parks_same_job_releases_lease_and_preserves_progress(tmp_path, monkeypatch):
    store, ids = seeded(tmp_path, 1)
    batch = store.request_batch("owner", request(ids, concurrency=1))
    job_id = batch["items"][0]["job_id"]
    gate = tmp_path / "enabled"
    gate.touch()
    monkeypatch.setenv("TRAJECTORY_WORKER_GATE", str(gate))
    seen = []

    def segment(*args, **kwargs):
        assert kwargs["analysis_id"] == job_id
        assert kwargs["resume_generation"] == 0
        assert not kwargs["should_pause"]()
        seen.append(kwargs["prior_progress"])
        kwargs["progress"]({"state": "paused", "completed_chunks": 1, "analysis_usage": []})
        gate.unlink()
        assert kwargs["should_pause"]()
        raise semantic_model.AnalysisPaused("saved boundary")

    monkeypatch.setattr(semantic_model, "segment", segment)
    runtime = AnalysisRuntime(store)
    try:
        assert runtime.process_next()
        detail = store.batch_detail("owner", batch["batch_id"])
        assert detail["counts"]["queued"] == 1 and detail["counts"]["failed"] == 0
        assert detail["items"][0]["job_id"] == job_id
        assert detail["items"][0]["progress"]["completed_chunks"] == 1
        assert not runtime.tick() and runtime.lease is None
        gate.touch()
        assert runtime.process_next()
        assert seen[0] == {}
        assert seen[1]["completed_chunks"] == 1
        with store.domain.connect() as db:
            assert db.execute("SELECT count(*) FROM semantic_jobs").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM semantic_job_resumes").fetchone()[0] == 0
            assert (
                db.execute(
                    "SELECT count(*) FROM audit WHERE operation='analysis.failed'"
                ).fetchone()[0]
                == 0
            )
    finally:
        runtime.close()
