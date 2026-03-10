"""Session-summary embedding generation via OpenRouter."""

from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agent_vis.db.repository import SessionRepository

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_EMBEDDING_MODEL = "openai/text-embedding-3-small"

_EMBEDDING_STATUS = Literal["completed", "failed"]


def compute_summary_text_hash(summary_text: str) -> str:
    """Compute a stable fingerprint for persisted summary text."""
    return hashlib.sha256(summary_text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EmbeddingGenerationConfig:
    """Repository-owned embedding settings."""

    enabled: bool = False
    model: str | None = None
    max_workers: int = 4
    timeout_seconds: float = 30.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.05
    provider_name: str = "openrouter"
    base_url: str = DEFAULT_OPENROUTER_BASE_URL
    api_key_env_var: str = "OPENROUTER_API_KEY"
    base_url_env_var: str = "OPENROUTER_BASE_URL"
    http_referer_env_var: str = "OPENROUTER_HTTP_REFERER"
    title_env_var: str = "OPENROUTER_X_TITLE"

    @property
    def model_id(self) -> str:
        return self.model or DEFAULT_OPENROUTER_EMBEDDING_MODEL

    @property
    def embeddings_url(self) -> str:
        base_url = os.getenv(self.base_url_env_var, self.base_url).rstrip("/")
        return f"{base_url}/embeddings"


@dataclass(frozen=True)
class SessionSummaryEmbedding:
    """One generated or failed session-summary embedding."""

    session_id: str
    summary_hash: str
    model_id: str
    provider_name: str
    status: _EMBEDDING_STATUS
    embedding_dimension: int | None
    vector: list[float] | None
    generated_at: str
    error_message: str | None = None


@dataclass(frozen=True)
class EmbeddingStageResult:
    """Aggregate embedding outcome for one sync or backfill run."""

    generated: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass(frozen=True)
class _EmbeddingWorkItem:
    session_id: str
    summary_text: str
    summary_hash: str


class SessionEmbeddingGenerationError(RuntimeError):
    """Raised when summary embedding generation fails."""


class SessionEmbeddingClient(Protocol):
    """Interface for repository-owned embedding clients."""

    def embed_summary(
        self,
        *,
        session_id: str,
        summary_text: str,
        summary_hash: str,
        config: EmbeddingGenerationConfig,
    ) -> SessionSummaryEmbedding:
        """Generate an embedding for the persisted summary text."""


def _is_retriable_http_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


def _read_http_error_body(exc: HTTPError) -> str:
    if exc.fp is None:
        return ""
    try:
        body = exc.fp.read()
    except Exception:
        return ""
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    return str(body)


class OpenRouterSessionEmbeddingClient:
    """Call OpenRouter's embeddings API using persisted plain-text summaries."""

    def embed_summary(
        self,
        *,
        session_id: str,
        summary_text: str,
        summary_hash: str,
        config: EmbeddingGenerationConfig,
    ) -> SessionSummaryEmbedding:
        api_key = os.getenv(config.api_key_env_var)
        if not api_key:
            raise SessionEmbeddingGenerationError(
                f"{config.api_key_env_var} is not set; cannot generate session embeddings."
            )

        payload = {
            "model": config.model_id,
            "input": summary_text,
            "encoding_format": "float",
        }
        request = Request(
            config.embeddings_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        http_referer = os.getenv(config.http_referer_env_var)
        if http_referer:
            request.add_header("HTTP-Referer", http_referer)
        title = os.getenv(config.title_env_var)
        if title:
            request.add_header("X-Title", title)

        attempts = config.max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                with urlopen(request, timeout=config.timeout_seconds) as response:
                    payload_data = json.loads(response.read().decode("utf-8"))
                vectors = payload_data.get("data")
                if not isinstance(vectors, list) or not vectors:
                    raise SessionEmbeddingGenerationError(
                        "OpenRouter embeddings response missing data[0].embedding."
                    )
                first_item = vectors[0]
                if not isinstance(first_item, dict) or not isinstance(
                    first_item.get("embedding"), list
                ):
                    raise SessionEmbeddingGenerationError(
                        "OpenRouter embeddings response missing data[0].embedding."
                    )
                raw_vector = first_item["embedding"]
                vector = [float(value) for value in raw_vector]
                if not vector:
                    raise SessionEmbeddingGenerationError(
                        "OpenRouter embeddings response returned an empty vector."
                    )
                return SessionSummaryEmbedding(
                    session_id=session_id,
                    summary_hash=summary_hash,
                    model_id=config.model_id,
                    provider_name=config.provider_name,
                    status="completed",
                    embedding_dimension=len(vector),
                    vector=vector,
                    generated_at=datetime.now(timezone.utc).isoformat(),
                    error_message=None,
                )
            except HTTPError as exc:
                error_body = _read_http_error_body(exc)
                message = f"OpenRouter embeddings request failed with status {exc.code}"
                if error_body:
                    message = f"{message}: {error_body.strip()}"
                if attempt < attempts and _is_retriable_http_status(exc.code):
                    time.sleep(config.retry_backoff_seconds * attempt)
                    continue
                raise SessionEmbeddingGenerationError(message) from exc
            except (TimeoutError, URLError) as exc:
                if attempt < attempts:
                    time.sleep(config.retry_backoff_seconds * attempt)
                    continue
                raise SessionEmbeddingGenerationError(
                    f"OpenRouter embeddings request failed after {attempts} attempts: {exc}"
                ) from exc
            except json.JSONDecodeError as exc:
                raise SessionEmbeddingGenerationError(
                    "OpenRouter embeddings response was not valid JSON."
                ) from exc

        raise SessionEmbeddingGenerationError("OpenRouter embeddings request failed unexpectedly.")


class SessionEmbeddingCoordinator:
    """Fan out embedding generation for persisted completed session summaries."""

    def __init__(
        self,
        repo: SessionRepository,
        client: SessionEmbeddingClient,
        config: EmbeddingGenerationConfig,
    ) -> None:
        self._repo = repo
        self._client = client
        self._config = config
        self._write_lock = Lock()

    def _should_skip(self, session_id: str, summary_hash: str) -> bool:
        existing = self._repo.get_session_summary_embedding(session_id)
        if existing is None:
            return False
        return (
            existing["summary_hash"] == summary_hash
            and existing["model_id"] == self._config.model_id
            and existing["provider_name"] == self._config.provider_name
            and existing["generation_status"] == "completed"
            and bool(existing["vector_json"])
        )

    def _persist_generation(self, generation: SessionSummaryEmbedding) -> None:
        with self._write_lock:
            vector_json = None
            if generation.vector is not None:
                vector_json = json.dumps(generation.vector)
            self._repo.upsert_session_summary_embedding(
                session_id=generation.session_id,
                summary_hash=generation.summary_hash,
                model_id=generation.model_id,
                provider_name=generation.provider_name,
                generation_status=generation.status,
                embedding_dimension=generation.embedding_dimension,
                vector_json=vector_json,
                generated_at=generation.generated_at,
                error_message=generation.error_message,
            )

    def generate_for_completed_summaries(
        self,
        *,
        session_ids: list[str] | None = None,
    ) -> EmbeddingStageResult:
        if not self._config.enabled:
            return EmbeddingStageResult()

        rows = self._repo.list_session_summaries_for_embedding(session_ids=session_ids)
        work_items: list[_EmbeddingWorkItem] = []
        skipped = 0
        for row in rows:
            summary_text = str(row["summary_text"])
            summary_hash = compute_summary_text_hash(summary_text)
            session_id = str(row["session_id"])
            if self._should_skip(session_id, summary_hash):
                skipped += 1
                continue
            work_items.append(
                _EmbeddingWorkItem(
                    session_id=session_id,
                    summary_text=summary_text,
                    summary_hash=summary_hash,
                )
            )

        if not work_items:
            return EmbeddingStageResult(generated=0, skipped=skipped, failed=0)

        generated = 0
        failed = 0
        max_workers = max(1, min(self._config.max_workers, len(work_items)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._client.embed_summary,
                    session_id=item.session_id,
                    summary_text=item.summary_text,
                    summary_hash=item.summary_hash,
                    config=self._config,
                ): item
                for item in work_items
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    generation = future.result()
                except Exception as exc:
                    generation = SessionSummaryEmbedding(
                        session_id=item.session_id,
                        summary_hash=item.summary_hash,
                        model_id=self._config.model_id,
                        provider_name=self._config.provider_name,
                        status="failed",
                        embedding_dimension=None,
                        vector=None,
                        generated_at=datetime.now(timezone.utc).isoformat(),
                        error_message=str(exc),
                    )
                    failed += 1
                else:
                    generated += 1
                self._persist_generation(generation)

        return EmbeddingStageResult(generated=generated, skipped=skipped, failed=failed)
