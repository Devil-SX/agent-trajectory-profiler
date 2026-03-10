from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from agent_vis.db.connection import get_connection
from agent_vis.db.repository import SessionRepository
from agent_vis.db.sync import SyncEngine
from agent_vis.models import Session
from agent_vis.parsers.claude_code import ClaudeCodeParser
from agent_vis.session_embeddings import (
    EmbeddingGenerationConfig,
    OpenRouterSessionEmbeddingClient,
    SessionEmbeddingCoordinator,
    SessionEmbeddingGenerationError,
    SessionSummaryEmbedding,
    compute_summary_text_hash,
)
from agent_vis.session_summaries import (
    SessionSummaryCoordinator,
    SummaryGeneration,
    SummaryGenerationConfig,
)


@pytest.fixture
def embedding_db(tmp_path: Path):
    conn = get_connection(tmp_path / "embedding.db")
    yield conn
    conn.close()


@pytest.fixture
def embedding_repo(embedding_db) -> SessionRepository:
    return SessionRepository(embedding_db)


@pytest.fixture
def parser() -> ClaudeCodeParser:
    return ClaudeCodeParser()


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    root = tmp_path / "sessions"
    root.mkdir()

    def _write_session(path: Path, session_id: str, user_text: str, assistant_text: str) -> None:
        rows = [
            {
                "type": "user",
                "sessionId": session_id,
                "uuid": f"{session_id}-u1",
                "timestamp": "2026-03-01T10:00:00.000Z",
                "cwd": "/tmp/project",
                "version": "1.0.0",
                "message": {"role": "user", "content": user_text},
            },
            {
                "type": "assistant",
                "sessionId": session_id,
                "uuid": f"{session_id}-a1",
                "timestamp": "2026-03-01T10:00:05.000Z",
                "cwd": "/tmp/project",
                "version": "1.0.0",
                "message": {
                    "role": "assistant",
                    "content": assistant_text,
                    "usage": {"input_tokens": 20, "output_tokens": 10},
                },
            },
        ]
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    _write_session(
        root / "sess-a.jsonl",
        "sess-a",
        "Investigate failing CI job and collect the likely root cause.",
        "Found a flaky path assertion in the smoke suite and suggested tightening the selector.",
    )
    _write_session(
        root / "sess-b.jsonl",
        "sess-b",
        "Profile sync performance and identify the slowest parser stage.",
        "Measured parser hotspots and narrowed the main cost to JSON parsing on large files.",
    )
    return root


def _persist_session(repo: SessionRepository, session: Session, file_path: Path) -> None:
    file_id = repo.upsert_tracked_file(
        str(file_path.resolve()),
        file_path.stat().st_size,
        file_path.stat().st_mtime,
        ecosystem="claude_code",
        parse_status="parsed",
    )
    stats = session.statistics
    automation_ratio = None
    if stats and stats.time_breakdown and stats.time_breakdown.user_interaction_count > 0:
        automation_ratio = round(
            stats.total_tool_calls / stats.time_breakdown.user_interaction_count, 2
        )
    repo.upsert_session(
        session_id=session.metadata.session_id,
        file_id=file_id,
        ecosystem="claude_code",
        physical_session_id=session.metadata.physical_session_id,
        logical_session_id=session.metadata.logical_session_id,
        parent_session_id=session.metadata.parent_session_id,
        root_session_id=session.metadata.root_session_id,
        project_path=session.metadata.project_path,
        git_branch=session.metadata.git_branch,
        created_at=session.metadata.created_at.isoformat() if session.metadata.created_at else None,
        updated_at=session.metadata.updated_at.isoformat() if session.metadata.updated_at else None,
        total_messages=session.metadata.total_messages,
        total_tokens=session.metadata.total_tokens,
        duration_seconds=stats.session_duration_seconds if stats else None,
        total_tool_calls=stats.total_tool_calls if stats else 0,
        bottleneck=None,
        automation_ratio=automation_ratio,
        version=session.metadata.version,
    )
    if stats is not None:
        repo.upsert_statistics(session.metadata.session_id, stats)


def _persist_summary(repo: SessionRepository, session_id: str, summary_text: str) -> None:
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
    repo.upsert_session_summary(
        session_id=session_id,
        synopsis_hash=f"synopsis-{session_id}",
        prompt_version="v1",
        model_id="gpt-5-codex",
        generation_status="completed",
        summary_text=summary_text,
        summary_chars=len(summary_text),
        generated_at="2026-03-01T00:00:00+00:00",
        error_message=None,
    )


def test_openrouter_embedding_client_builds_payload_from_persisted_summary_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OpenRouterSessionEmbeddingClient()
    config = EmbeddingGenerationConfig(enabled=True, model="openai/text-embedding-3-small")
    summary_text = "Bounded summary text from persistence."

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    seen_request: dict[str, object] = {}

    class _Response:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    def _fake_urlopen(request, timeout: float):
        del timeout
        seen_request["url"] = request.full_url
        seen_request["headers"] = dict(request.header_items())
        seen_request["body"] = json.loads(request.data.decode("utf-8"))
        payload = {
            "data": [{"embedding": [0.25, 0.5, 0.75]}],
            "model": "openai/text-embedding-3-small",
        }
        return _Response(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr("agent_vis.session_embeddings.urlopen", _fake_urlopen)

    embedding = client.embed_summary(
        session_id="sess-a",
        summary_text=summary_text,
        summary_hash=compute_summary_text_hash(summary_text),
        config=config,
    )

    assert seen_request["url"] == "https://openrouter.ai/api/v1/embeddings"
    assert seen_request["body"] == {
        "model": "openai/text-embedding-3-small",
        "input": summary_text,
        "encoding_format": "float",
    }
    headers = {str(k).lower(): str(v) for k, v in seen_request["headers"].items()}
    assert headers["authorization"] == "Bearer test-key"
    assert embedding.embedding_dimension == 3
    assert embedding.vector == [0.25, 0.5, 0.75]


def test_embedding_coordinator_skips_unchanged_completed_embedding(
    embedding_repo: SessionRepository,
) -> None:
    summary_text = "A concise summary for reuse."
    summary_hash = compute_summary_text_hash(summary_text)
    _persist_summary(embedding_repo, "sess-a", summary_text)
    embedding_repo.upsert_session_summary_embedding(
        session_id="sess-a",
        summary_hash=summary_hash,
        model_id="openai/text-embedding-3-small",
        provider_name="openrouter",
        generation_status="completed",
        embedding_dimension=3,
        vector_json="[0.1, 0.2, 0.3]",
        generated_at="2026-03-01T00:00:00+00:00",
        error_message=None,
    )

    class _FailIfCalledClient:
        def embed_summary(self, **kwargs):
            raise AssertionError("embedding client should not be called for unchanged summary")

    coordinator = SessionEmbeddingCoordinator(
        embedding_repo,
        _FailIfCalledClient(),
        EmbeddingGenerationConfig(enabled=True, model="openai/text-embedding-3-small"),
    )

    result = coordinator.generate_for_completed_summaries(session_ids=["sess-a"])

    assert result.generated == 0
    assert result.skipped == 1
    assert result.failed == 0


def test_embedding_coordinator_persists_vector_metadata(
    embedding_repo: SessionRepository,
) -> None:
    summary_text = "Investigated sync hot path and isolated JSON decoding cost."
    summary_hash = compute_summary_text_hash(summary_text)
    _persist_summary(embedding_repo, "sess-a", summary_text)

    class _Client:
        def embed_summary(
            self,
            *,
            session_id: str,
            summary_text: str,
            summary_hash: str,
            config: EmbeddingGenerationConfig,
        ) -> SessionSummaryEmbedding:
            del config
            assert session_id == "sess-a"
            assert summary_text == "Investigated sync hot path and isolated JSON decoding cost."
            assert summary_hash == compute_summary_text_hash(summary_text)
            return SessionSummaryEmbedding(
                session_id=session_id,
                summary_hash=summary_hash,
                model_id="openai/text-embedding-3-small",
                provider_name="openrouter",
                status="completed",
                embedding_dimension=4,
                vector=[0.1, 0.2, 0.3, 0.4],
                generated_at="2026-03-01T00:00:00+00:00",
            )

    coordinator = SessionEmbeddingCoordinator(
        embedding_repo,
        _Client(),
        EmbeddingGenerationConfig(enabled=True, model="openai/text-embedding-3-small"),
    )

    result = coordinator.generate_for_completed_summaries(session_ids=["sess-a"])
    persisted = embedding_repo.get_session_summary_embedding("sess-a")

    assert result.generated == 1
    assert result.skipped == 0
    assert result.failed == 0
    assert persisted is not None
    assert persisted["summary_hash"] == summary_hash
    assert persisted["embedding_dimension"] == 4
    assert json.loads(persisted["vector_json"]) == [0.1, 0.2, 0.3, 0.4]


def test_sync_engine_embedding_stage_is_failure_isolated(
    tmp_path: Path,
    parser: ClaudeCodeParser,
    session_dir: Path,
) -> None:
    conn = get_connection(tmp_path / "sync-embedding.db")
    repo = SessionRepository(conn)

    class _SummaryRunner:
        def generate(self, synopsis, *, config):
            del config
            return SummaryGeneration(
                session_id=synopsis.session_id,
                synopsis_hash=f"synopsis-{synopsis.session_id}",
                prompt_version="v1",
                model_id="gpt-5-codex",
                status="completed",
                summary_text=f"Persisted summary for {synopsis.session_id}.",
                summary_chars=len(f"Persisted summary for {synopsis.session_id}."),
                generated_at="2026-03-01T00:00:00+00:00",
            )

    class _EmbeddingClient:
        def embed_summary(self, **kwargs):
            raise SessionEmbeddingGenerationError("provider error")

    summary_coordinator = SessionSummaryCoordinator(
        repo,
        _SummaryRunner(),
        SummaryGenerationConfig(enabled=True),
    )
    embedding_coordinator = SessionEmbeddingCoordinator(
        repo,
        _EmbeddingClient(),
        EmbeddingGenerationConfig(enabled=True, model="openai/text-embedding-3-small"),
    )
    engine = SyncEngine(
        repo,
        parser,
        summary_coordinator=summary_coordinator,
        embedding_coordinator=embedding_coordinator,
    )

    result = engine.sync(session_dir)

    assert result.parsed == 2
    assert result.summaries_generated == 2
    assert result.embeddings_failed == 2
    assert repo.get_session("sess-a") is not None
    assert repo.get_session_summary("sess-a") is not None
    assert repo.get_session_summary_embedding("sess-a")["generation_status"] == "failed"
    conn.close()


def test_openrouter_embedding_client_raises_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OpenRouterSessionEmbeddingClient()
    config = EmbeddingGenerationConfig(enabled=True, model="openai/text-embedding-3-small")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def _fake_urlopen(request, timeout: float):
        del request, timeout
        raise HTTPError(
            url="https://openrouter.ai/api/v1/embeddings",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("agent_vis.session_embeddings.urlopen", _fake_urlopen)

    with pytest.raises(SessionEmbeddingGenerationError, match="429"):
        client.embed_summary(
            session_id="sess-a",
            summary_text="summary",
            summary_hash=compute_summary_text_hash("summary"),
            config=config,
        )
