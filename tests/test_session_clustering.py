from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import agent_vis.cli.main as cli_main
from agent_vis.db.connection import get_connection
from agent_vis.db.repository import SessionRepository
from agent_vis.session_clustering import (
    DEFAULT_CLUSTERING_MODEL_ID,
    SessionClusterConfig,
    SessionClusteringCoordinator,
)


@pytest.fixture
def cluster_db_path(tmp_path: Path) -> Path:
    return tmp_path / "clusters.db"


@pytest.fixture
def cluster_repo(cluster_db_path: Path) -> SessionRepository:
    conn = get_connection(cluster_db_path)
    repo = SessionRepository(conn)
    yield repo
    conn.close()


def _persist_embedding(
    repo: SessionRepository,
    *,
    session_id: str,
    vector: list[float],
    model_id: str = DEFAULT_CLUSTERING_MODEL_ID,
) -> None:
    file_id = repo.upsert_tracked_file(
        f"/tmp/{session_id}.jsonl",
        1,
        1.0,
        ecosystem="claude_code",
        parse_status="parsed",
    )
    repo.upsert_session(
        session_id=session_id,
        file_id=file_id,
        ecosystem="claude_code",
        physical_session_id=session_id,
        logical_session_id=session_id,
        parent_session_id=None,
        root_session_id=session_id,
        project_path="/tmp/project",
        git_branch="main",
        created_at="2026-03-01T00:00:00+00:00",
        updated_at="2026-03-01T00:05:00+00:00",
        total_messages=2,
        total_tokens=32,
        duration_seconds=5.0,
        total_tool_calls=0,
        bottleneck=None,
        automation_ratio=None,
        version="1.0.0",
    )
    repo.upsert_session_summary_embedding(
        session_id=session_id,
        summary_hash=f"summary-{session_id}",
        model_id=model_id,
        provider_name="openrouter",
        generation_status="completed",
        embedding_dimension=len(vector),
        vector_json=json.dumps(vector),
        generated_at="2026-03-01T00:00:00+00:00",
        error_message=None,
    )


def test_clustering_groups_nearest_neighbors_deterministically(
    cluster_repo: SessionRepository,
) -> None:
    _persist_embedding(cluster_repo, session_id="sess-a", vector=[1.0, 0.0])
    _persist_embedding(cluster_repo, session_id="sess-b", vector=[0.99, 0.01])
    _persist_embedding(cluster_repo, session_id="sess-c", vector=[0.0, 1.0])

    coordinator = SessionClusteringCoordinator(
        cluster_repo,
        SessionClusterConfig(similarity_threshold=0.95),
    )

    result = coordinator.run()
    memberships = cluster_repo.list_latest_session_cluster_memberships()
    by_session = {row["session_id"]: row["cluster_id"] for row in memberships}

    assert result.cluster_count == 2
    assert result.session_count == 3
    assert by_session["sess-a"] == by_session["sess-b"]
    assert by_session["sess-a"] != by_session["sess-c"]


def test_clustering_persists_run_metadata_and_reloadable_memberships(
    cluster_repo: SessionRepository,
) -> None:
    _persist_embedding(cluster_repo, session_id="sess-a", vector=[1.0, 0.0])
    _persist_embedding(cluster_repo, session_id="sess-b", vector=[0.99, 0.01])

    coordinator = SessionClusteringCoordinator(
        cluster_repo,
        SessionClusterConfig(similarity_threshold=0.95),
    )

    result = coordinator.run()
    run_row = cluster_repo.get_latest_session_cluster_run()
    memberships = cluster_repo.list_latest_session_cluster_memberships()

    assert run_row is not None
    assert run_row["run_id"] == result.run_id
    assert run_row["algorithm"] == "cosine_threshold_greedy"
    assert run_row["algorithm_version"] == "v1"
    assert run_row["source_model_id"] == DEFAULT_CLUSTERING_MODEL_ID
    assert len(memberships) == 2


def test_clustering_rerun_replaces_latest_snapshot_when_embeddings_change(
    cluster_repo: SessionRepository,
) -> None:
    _persist_embedding(cluster_repo, session_id="sess-a", vector=[1.0, 0.0])
    _persist_embedding(cluster_repo, session_id="sess-b", vector=[0.99, 0.01])
    _persist_embedding(cluster_repo, session_id="sess-c", vector=[0.0, 1.0])

    coordinator = SessionClusteringCoordinator(
        cluster_repo,
        SessionClusterConfig(similarity_threshold=0.95),
    )
    first = coordinator.run()

    cluster_repo.upsert_session_summary_embedding(
        session_id="sess-c",
        summary_hash="summary-sess-c-v2",
        model_id=DEFAULT_CLUSTERING_MODEL_ID,
        provider_name="openrouter",
        generation_status="completed",
        embedding_dimension=2,
        vector_json=json.dumps([0.98, 0.02]),
        generated_at="2026-03-02T00:00:00+00:00",
        error_message=None,
    )

    second = coordinator.run()
    memberships = cluster_repo.list_latest_session_cluster_memberships()

    assert second.run_id != first.run_id
    assert second.cluster_count == 1
    assert len({row["cluster_id"] for row in memberships}) == 1
    assert len(memberships) == 3


def test_clustering_handles_empty_and_singleton_datasets(
    cluster_repo: SessionRepository,
) -> None:
    coordinator = SessionClusteringCoordinator(
        cluster_repo,
        SessionClusterConfig(similarity_threshold=0.95),
    )

    empty = coordinator.run()
    _persist_embedding(cluster_repo, session_id="sess-a", vector=[1.0, 0.0])
    singleton = coordinator.run()

    assert empty.cluster_count == 0
    assert empty.session_count == 0
    assert singleton.cluster_count == 1
    assert singleton.session_count == 1


def test_clusters_cli_run_and_list_expose_latest_snapshot(cluster_db_path: Path) -> None:
    conn = get_connection(cluster_db_path)
    repo = SessionRepository(conn)
    _persist_embedding(repo, session_id="sess-a", vector=[1.0, 0.0])
    _persist_embedding(repo, session_id="sess-b", vector=[0.99, 0.01])
    _persist_embedding(repo, session_id="sess-c", vector=[0.0, 1.0])
    conn.close()

    runner = CliRunner()
    run_result = runner.invoke(
        cli_main.main,
        ["clusters", "run", "--db-path", str(cluster_db_path)],
    )
    list_result = runner.invoke(
        cli_main.main,
        ["clusters", "list", "--db-path", str(cluster_db_path)],
    )

    assert run_result.exit_code == 0
    assert list_result.exit_code == 0

    run_payload = json.loads(run_result.output)
    list_payload = json.loads(list_result.output)

    assert run_payload["cluster_count"] == 2
    assert list_payload["run"]["cluster_count"] == 2
    assert len(list_payload["memberships"]) == 3
