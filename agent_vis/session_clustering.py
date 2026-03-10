"""Deterministic clustering over persisted session-summary embeddings."""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from agent_vis.db.repository import SessionRepository
from agent_vis.session_embeddings import DEFAULT_OPENROUTER_EMBEDDING_MODEL

DEFAULT_CLUSTERING_MODEL_ID = DEFAULT_OPENROUTER_EMBEDDING_MODEL


@dataclass(frozen=True)
class SessionClusterConfig:
    """Repository-owned clustering configuration."""

    model_id: str = DEFAULT_CLUSTERING_MODEL_ID
    similarity_threshold: float = 0.92
    algorithm: str = "cosine_threshold_greedy"
    algorithm_version: str = "v1"


@dataclass(frozen=True)
class SessionClusterMembership:
    """Cluster membership for one session."""

    cluster_id: str
    session_id: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class SessionClusteringResult:
    """Persisted clustering snapshot summary."""

    run_id: str
    generated_at: str
    session_count: int
    cluster_count: int
    source_model_id: str
    algorithm: str
    algorithm_version: str
    similarity_threshold: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class _EmbeddingRecord:
    session_id: str
    vector: list[float]


@dataclass
class _WorkingCluster:
    member_ids: list[str]
    vectors: list[list[float]]

    @property
    def centroid(self) -> list[float]:
        dimension = len(self.vectors[0])
        totals = [0.0] * dimension
        for vector in self.vectors:
            for index, value in enumerate(vector):
                totals[index] += value
        return [value / len(self.vectors) for value in totals]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    return numerator / (left_norm * right_norm)


def _cluster_id_for_members(member_ids: list[str]) -> str:
    fingerprint = ",".join(sorted(member_ids))
    digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:12]
    return f"cluster-{digest}"


class SessionClusteringCoordinator:
    """Cluster persisted embeddings with a deterministic threshold heuristic."""

    def __init__(
        self,
        repo: SessionRepository,
        config: SessionClusterConfig,
    ) -> None:
        self._repo = repo
        self._config = config

    def _load_embeddings(self) -> list[_EmbeddingRecord]:
        rows = self._repo.list_completed_session_summary_embeddings(model_id=self._config.model_id)
        embeddings: list[_EmbeddingRecord] = []
        expected_dimension: int | None = None
        for row in rows:
            vector = self._repo.parse_embedding_vector(row["vector_json"])
            if not vector:
                continue
            if expected_dimension is None:
                expected_dimension = len(vector)
            if len(vector) != expected_dimension:
                raise ValueError(
                    "Persisted embeddings for clustering must all have the same dimension."
                )
            embeddings.append(_EmbeddingRecord(session_id=str(row["session_id"]), vector=vector))
        embeddings.sort(key=lambda item: item.session_id)
        return embeddings

    def _build_clusters(self, embeddings: list[_EmbeddingRecord]) -> list[SessionClusterMembership]:
        if not embeddings:
            return []

        clusters: list[_WorkingCluster] = []
        for embedding in embeddings:
            best_index: int | None = None
            best_similarity = -1.0
            for index, cluster in enumerate(clusters):
                similarity = _cosine_similarity(embedding.vector, cluster.centroid)
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_index = index
            if best_index is not None and best_similarity >= self._config.similarity_threshold:
                clusters[best_index].member_ids.append(embedding.session_id)
                clusters[best_index].vectors.append(embedding.vector)
            else:
                clusters.append(
                    _WorkingCluster(
                        member_ids=[embedding.session_id],
                        vectors=[embedding.vector],
                    )
                )

        memberships: list[SessionClusterMembership] = []
        for cluster in clusters:
            cluster_id = _cluster_id_for_members(cluster.member_ids)
            for session_id in sorted(cluster.member_ids):
                memberships.append(
                    SessionClusterMembership(
                        cluster_id=cluster_id,
                        session_id=session_id,
                    )
                )
        memberships.sort(key=lambda item: (item.cluster_id, item.session_id))
        return memberships

    def run(self) -> SessionClusteringResult:
        embeddings = self._load_embeddings()
        memberships = self._build_clusters(embeddings)
        generated_at = datetime.now(timezone.utc).isoformat()
        run_fingerprint = (
            f"{self._config.algorithm}|{self._config.algorithm_version}|"
            f"{self._config.model_id}|{generated_at}"
        )
        run_id = hashlib.sha1(run_fingerprint.encode("utf-8")).hexdigest()[:16]
        result = SessionClusteringResult(
            run_id=run_id,
            generated_at=generated_at,
            session_count=len(embeddings),
            cluster_count=len({item.cluster_id for item in memberships}),
            source_model_id=self._config.model_id,
            algorithm=self._config.algorithm,
            algorithm_version=self._config.algorithm_version,
            similarity_threshold=self._config.similarity_threshold,
        )
        self._repo.replace_session_clusters(
            run_id=result.run_id,
            generated_at=result.generated_at,
            algorithm=result.algorithm,
            algorithm_version=result.algorithm_version,
            source_model_id=result.source_model_id,
            similarity_threshold=result.similarity_threshold,
            session_count=result.session_count,
            cluster_count=result.cluster_count,
            memberships=memberships,
        )
        return result
