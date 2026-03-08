"""Session synopsis construction and headless Codex summary generation."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Literal

from pydantic import BaseModel, Field

from agent_vis.db.repository import SessionRepository
from agent_vis.models import MessageRecord, Session
from agent_vis.prompts.session_summary import (
    DEFAULT_SESSION_SUMMARY_TIMEOUT_SECONDS,
    DEFAULT_SESSION_SUMMARY_WORKERS,
    SESSION_SUMMARY_MAX_CHARS,
    SESSION_SUMMARY_PROMPT_VERSION,
    build_session_summary_prompt,
)

_SUMMARY_STATUS = Literal["completed", "failed"]
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _truncate_text(text: str, limit: int) -> str:
    normalized = _normalize_whitespace(text)
    if len(normalized) <= limit:
        return normalized
    clipped = normalized[:limit].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0].rstrip()
    return clipped.rstrip(" ,;:") + "..."


def _extract_message_text(message: MessageRecord, *, limit: int = 200) -> str:
    parts: list[str] = []
    if message.summary:
        parts.append(message.summary)
    if message.message is None:
        return _truncate_text(" ".join(parts), limit)

    content = message.message.content
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text" and isinstance(block.get("text"), str):
                parts.append(str(block["text"]))
            elif block_type == "tool_use" and isinstance(block.get("name"), str):
                parts.append(f"tool:{block['name']}")
            elif block_type == "tool_result":
                block_content = block.get("content")
                if isinstance(block_content, str):
                    parts.append(block_content)
    return _truncate_text(" ".join(parts), limit)


class SessionSynopsis(BaseModel):
    """Provider-agnostic summary input derived from normalized session data."""

    session_id: str
    ecosystem: str
    project_path: str
    git_branch: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    total_messages: int
    total_tokens: int
    total_tool_calls: int
    duration_seconds: float | None = None
    bottleneck: str | None = None
    automation_ratio: float | None = None
    tool_error_count: int = 0
    compact_count: int = 0
    subagent_count: int = 0
    top_tools: list[str] = Field(default_factory=list)
    tool_error_categories: list[str] = Field(default_factory=list)
    user_goal: str | None = None
    final_outcome: str | None = None

    def to_prompt_context(self) -> str:
        """Render synopsis into a dense deterministic text block for prompting."""
        lines = [
            f"session_id: {self.session_id}",
            f"ecosystem: {self.ecosystem}",
            f"project_path: {self.project_path}",
            f"git_branch: {self.git_branch or '(unknown)'}",
            f"created_at: {self.created_at or '(unknown)'}",
            f"updated_at: {self.updated_at or '(unknown)'}",
            f"total_messages: {self.total_messages}",
            f"total_tokens: {self.total_tokens}",
            f"total_tool_calls: {self.total_tool_calls}",
            f"duration_seconds: {self.duration_seconds or 0.0}",
            f"bottleneck: {self.bottleneck or '(unknown)'}",
            "automation_ratio: "
            + (str(self.automation_ratio) if self.automation_ratio is not None else "(unknown)"),
            f"tool_error_count: {self.tool_error_count}",
            f"compact_count: {self.compact_count}",
            f"subagent_count: {self.subagent_count}",
            f"top_tools: {', '.join(self.top_tools) if self.top_tools else '(none)'}",
            (
                "tool_error_categories: "
                + (
                    ", ".join(self.tool_error_categories)
                    if self.tool_error_categories
                    else "(none)"
                )
            ),
            f"user_goal: {self.user_goal or '(unknown)'}",
            f"final_outcome: {self.final_outcome or '(unknown)'}",
        ]
        return "\n".join(lines)


@dataclass(frozen=True)
class SummaryGenerationConfig:
    """Repository-owned settings for plain-text session summaries."""

    enabled: bool = False
    model: str | None = None
    max_chars: int = SESSION_SUMMARY_MAX_CHARS
    max_workers: int = DEFAULT_SESSION_SUMMARY_WORKERS
    timeout_seconds: int = DEFAULT_SESSION_SUMMARY_TIMEOUT_SECONDS
    prompt_version: str = SESSION_SUMMARY_PROMPT_VERSION
    codex_bin: str = "codex"

    @property
    def model_id(self) -> str:
        return self.model or "default"


@dataclass(frozen=True)
class SummaryGeneration:
    """One generated or failed session summary."""

    session_id: str
    synopsis_hash: str
    prompt_version: str
    model_id: str
    status: _SUMMARY_STATUS
    summary_text: str | None
    summary_chars: int | None
    generated_at: str
    error_message: str | None = None


@dataclass(frozen=True)
class SummaryStageResult:
    """Aggregate summary-generation outcome for one sync run."""

    generated: int = 0
    skipped: int = 0
    failed: int = 0


class SessionSummaryGenerationError(RuntimeError):
    """Raised when headless summary generation fails."""


def derive_bottleneck_label(session: Session) -> str | None:
    stats = session.statistics
    if stats is None or stats.time_breakdown is None:
        return None
    breakdown = stats.time_breakdown
    categories = [
        ("Model", breakdown.model_time_percent),
        ("Tool", breakdown.tool_time_percent),
        ("User", breakdown.user_time_percent),
    ]
    return max(categories, key=lambda item: item[1])[0]


def build_session_synopsis(session: Session, *, ecosystem: str) -> SessionSynopsis:
    """Construct a provider-agnostic synopsis from normalized session objects."""
    stats = session.statistics
    main_messages = session.main_messages
    first_user = next((msg for msg in main_messages if msg.is_user_message), None)
    last_assistant = next(
        (msg for msg in reversed(main_messages) if msg.is_assistant_message), None
    )
    top_tools = [tool.tool_name for tool in stats.get_top_tools(5)] if stats else []
    error_categories = []
    if stats is not None:
        error_categories = sorted(
            stats.tool_error_category_counts,
            key=lambda category: stats.tool_error_category_counts[category],
            reverse=True,
        )[:5]

    automation_ratio = None
    if stats and stats.time_breakdown and stats.time_breakdown.user_interaction_count > 0:
        automation_ratio = round(
            stats.total_tool_calls / stats.time_breakdown.user_interaction_count, 2
        )

    return SessionSynopsis(
        session_id=session.metadata.session_id,
        ecosystem=ecosystem,
        project_path=session.metadata.project_path,
        git_branch=session.metadata.git_branch,
        created_at=session.metadata.created_at.isoformat() if session.metadata.created_at else None,
        updated_at=session.metadata.updated_at.isoformat() if session.metadata.updated_at else None,
        total_messages=session.metadata.total_messages,
        total_tokens=session.metadata.total_tokens,
        total_tool_calls=stats.total_tool_calls if stats else 0,
        duration_seconds=stats.session_duration_seconds if stats else None,
        bottleneck=derive_bottleneck_label(session),
        automation_ratio=automation_ratio,
        tool_error_count=stats.total_tool_errors if stats else 0,
        compact_count=stats.compact_count if stats else 0,
        subagent_count=stats.subagent_count if stats else len(session.subagent_sessions),
        top_tools=top_tools,
        tool_error_categories=error_categories,
        user_goal=_extract_message_text(first_user) if first_user else None,
        final_outcome=_extract_message_text(last_assistant) if last_assistant else None,
    )


def compute_synopsis_hash(synopsis: SessionSynopsis) -> str:
    """Compute a stable hash over the synopsis payload."""
    payload = json.dumps(synopsis.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_summary_text(text: str, *, max_chars: int) -> str:
    """Collapse whitespace and enforce the configured summary-length budget."""
    return _truncate_text(text, max_chars)


class CodexSessionSummaryRunner:
    """Invoke Codex headlessly to generate bounded plain-text summaries."""

    def __init__(self, *, repo_root: Path | None = None) -> None:
        self._repo_root = repo_root or Path(__file__).resolve().parent.parent

    def build_command(
        self,
        *,
        config: SummaryGenerationConfig,
        output_path: Path,
    ) -> list[str]:
        command = [
            config.codex_bin,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--dangerously-bypass-approvals-and-sandbox",
            "-C",
            str(self._repo_root),
            "--output-last-message",
            str(output_path),
            "-",
        ]
        if config.model:
            command[2:2] = ["--model", config.model]
        return command

    def generate(
        self, synopsis: SessionSynopsis, *, config: SummaryGenerationConfig
    ) -> SummaryGeneration:
        if shutil.which(config.codex_bin) is None:
            raise SessionSummaryGenerationError(
                f"{config.codex_bin} CLI not found in PATH; cannot generate session summaries."
            )

        prompt = build_session_summary_prompt(
            synopsis.to_prompt_context(),
            max_chars=config.max_chars,
        )
        synopsis_hash = compute_synopsis_hash(synopsis)

        with tempfile.TemporaryDirectory(prefix="agent-vis-summary-") as tmp_dir:
            output_path = Path(tmp_dir) / "summary.txt"
            command = self.build_command(config=config, output_path=output_path)
            try:
                result = subprocess.run(
                    command,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=config.timeout_seconds,
                )
            except subprocess.CalledProcessError as exc:
                stderr = _normalize_whitespace(exc.stderr or "")
                raise SessionSummaryGenerationError(
                    f"codex exec failed with exit code {exc.returncode}: {stderr or 'no stderr'}"
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise SessionSummaryGenerationError(
                    f"codex exec timed out after {config.timeout_seconds} seconds"
                ) from exc

            raw_text = ""
            if output_path.exists():
                raw_text = output_path.read_text(encoding="utf-8")
            if not raw_text.strip():
                raw_text = result.stdout
            normalized = normalize_summary_text(raw_text, max_chars=config.max_chars)
            if not normalized:
                raise SessionSummaryGenerationError("codex exec returned an empty summary")

        generated_at = datetime.now(timezone.utc).isoformat()
        return SummaryGeneration(
            session_id=synopsis.session_id,
            synopsis_hash=synopsis_hash,
            prompt_version=config.prompt_version,
            model_id=config.model_id,
            status="completed",
            summary_text=normalized,
            summary_chars=len(normalized),
            generated_at=generated_at,
            error_message=None,
        )


@dataclass(frozen=True)
class _SummaryWorkItem:
    session_id: str
    synopsis: SessionSynopsis
    synopsis_hash: str


class SessionSummaryCoordinator:
    """Fan out summary generation for parsed sessions after sync persistence."""

    def __init__(
        self,
        repo: SessionRepository,
        runner: CodexSessionSummaryRunner,
        config: SummaryGenerationConfig,
    ) -> None:
        self._repo = repo
        self._runner = runner
        self._config = config
        self._write_lock = Lock()

    def _should_skip(self, session_id: str, synopsis_hash: str) -> bool:
        existing = self._repo.get_session_summary(session_id)
        if existing is None:
            return False
        return (
            existing["synopsis_hash"] == synopsis_hash
            and existing["prompt_version"] == self._config.prompt_version
            and existing["model_id"] == self._config.model_id
            and existing["generation_status"] == "completed"
            and bool(existing["summary_text"])
        )

    def _persist_generation(self, generation: SummaryGeneration) -> None:
        with self._write_lock:
            self._repo.upsert_session_summary(
                session_id=generation.session_id,
                synopsis_hash=generation.synopsis_hash,
                prompt_version=generation.prompt_version,
                model_id=generation.model_id,
                generation_status=generation.status,
                summary_text=generation.summary_text,
                summary_chars=generation.summary_chars,
                generated_at=generation.generated_at,
                error_message=generation.error_message,
            )

    def generate_for_sessions(
        self,
        sessions: list[Session],
        *,
        ecosystem: str,
    ) -> SummaryStageResult:
        if not self._config.enabled:
            return SummaryStageResult()

        work_items: list[_SummaryWorkItem] = []
        skipped = 0
        for session in sessions:
            synopsis = build_session_synopsis(session, ecosystem=ecosystem)
            synopsis_hash = compute_synopsis_hash(synopsis)
            if self._should_skip(session.metadata.session_id, synopsis_hash):
                skipped += 1
                continue
            work_items.append(
                _SummaryWorkItem(
                    session_id=session.metadata.session_id,
                    synopsis=synopsis,
                    synopsis_hash=synopsis_hash,
                )
            )

        if not work_items:
            return SummaryStageResult(generated=0, skipped=skipped, failed=0)

        generated = 0
        failed = 0
        max_workers = max(1, min(self._config.max_workers, len(work_items)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._runner.generate, item.synopsis, config=self._config): item
                for item in work_items
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    generation = future.result()
                except Exception as exc:
                    generation = SummaryGeneration(
                        session_id=item.session_id,
                        synopsis_hash=item.synopsis_hash,
                        prompt_version=self._config.prompt_version,
                        model_id=self._config.model_id,
                        status="failed",
                        summary_text=None,
                        summary_chars=None,
                        generated_at=datetime.now(timezone.utc).isoformat(),
                        error_message=str(exc),
                    )
                    failed += 1
                else:
                    generated += 1
                self._persist_generation(generation)

        return SummaryStageResult(generated=generated, skipped=skipped, failed=failed)
