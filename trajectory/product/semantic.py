"""Source evidence, derived sessions and jobs owned by the existing domain database.

Raw content never generates another usage ledger. All displayed measures come
from Domain.overview's deduplicated event contributions.
"""

from __future__ import annotations

import base64
import bisect
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from trajectory.product.contracts import (
    AnalysisBatchRequest,
    AnalysisRequest,
    LostWindowRecomputeRequest,
    SourceChunk,
    TaskEdit,
)
from trajectory.product.domain import Domain
from trajectory.product.read_cache import RevisionCache
from trajectory.product.session_metadata import VERSION as METADATA_VERSION
from trajectory.product.session_metadata import extract as extract_metadata
from trajectory.product.session_metadata import read as read_metadata

MAX_RESUME_GENERATIONS = 12
MAX_WINDOW_RESUMES = 3


def stamp() -> str:
    return datetime.now(UTC).isoformat()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def archive_revision(source: Any) -> str | None:
    """The archive cursor is the single authority for received source identity."""
    return digest(source["generation"] + ":" + str(source["received_bytes"])) if source else None


def snapshot_line_watermark(parsed: dict[str, Any], generation: str | None) -> int | None:
    """Highest source line the displayed parsed snapshot can prove it contains.

    Ledger records and parsed operations use the same line numbering only inside
    one source generation. A changed generation, or a body without any recorded
    line, has no comparable bound and must not attribute anything.
    """
    snapshot = parsed.get("source_snapshot") or {}
    if not generation or snapshot.get("generation") != generation:
        return None
    lines: list[int] = []
    records = parsed.get("source_records") or parsed.get("records") or []
    for item in records:
        line = item.get("source_line") if isinstance(item, dict) else None
        if isinstance(line, int) and not isinstance(line, bool):
            lines.append(line)
    for item in parsed.get("operations") or []:
        location = item.get("location") or {}
        line = location.get("source_line") if isinstance(location, dict) else None
        if isinstance(line, int) and not isinstance(line, bool):
            lines.append(line)
    return max(lines) if lines else None


COUNTERS = (
    "input",
    "output",
    "cached",
    "cache_write",
    "reasoning",
    "calls",
    "recorded_tokens",
    "human_interactions",
    "human_input_chars",
    "missing_human_input_chars",
    "unknown_origin_interactions",
    "agent_interactions",
    "system_interactions",
    "active_seconds_estimate",
    "tool_seconds",
    "known_subtotal_usd",
    "priced_calls",
    "unpriced_calls",
    "unknown_usage",
    "estimated_usage_records",
)


def total_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in COUNTERS:
        values = []
        for item in items:
            coverage = item.get("human_input_coverage", {})
            if key == "human_interactions" and "confirmed_human_requests" in coverage:
                value = coverage["confirmed_human_requests"]
            elif key == "human_input_chars" and "known_human_input_chars" in coverage:
                value = coverage["known_human_input_chars"]
            else:
                value = item.get(key)
            if isinstance(value, (int, float)):
                values.append(value)
        result[key] = sum(values) if values else None
    result["missing_counters"] = {
        key: sum(item.get("missing_counters", {}).get(key, 0) for item in items)
        for key in ("input", "output", "cached", "cache_write", "reasoning")
    }
    result["cost_status"] = (
        "complete"
        if result["unpriced_calls"] == 0 and result["priced_calls"] is not None
        else "partial" if result["priced_calls"] or result["known_subtotal_usd"] else "unknown"
    )
    result["estimated_usd"] = (
        result["known_subtotal_usd"] if result["cost_status"] == "complete" else None
    )
    missing_items = sum(
        (
            item.get("human_input_coverage", {}).get("missing_measurement_items", 0)
            if item.get("human_input_coverage")
            else int(
                item.get("human_interactions") is None
                and item.get("unknown_origin_interactions") is None
            )
        )
        for item in items
    )
    Domain.apply_human_input_coverage(result, missing_items)
    return result


def collection_progress(row: Any) -> dict[str, Any]:
    """Only the collector-reported ledger snapshot, not raw-generation alignment."""
    if row is None:
        return {
            "status": "unknown",
            "read_bytes": None,
            "source_bytes": None,
            "parse_errors": None,
            "unknown_events": None,
        }
    read, size, errors = int(row["read_bytes"]), int(row["source_bytes"]), int(row["errors"])
    return {
        "status": "partial" if read < size or errors else "complete",
        "read_bytes": read,
        "source_bytes": size,
        "parse_errors": errors,
        "unknown_events": int(row["unknown"]),
    }


class AnalysisResumeError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class SessionCursorExpired(ValueError):
    """A bounded read snapshot is unavailable or belongs to another filter scope."""


class IRSnapshotUnavailable(ValueError):
    """The requested immutable parsed revision was never retained."""


class SemanticStore:
    def __init__(self, domain: Domain):
        self.domain = domain
        self._detail_cache = RevisionCache(max_bytes=32 * 1024**2, max_entries=8)
        self._directory_cache = RevisionCache(max_bytes=16 * 1024**2, max_entries=8)
        with domain.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS source_archives(
                    owner TEXT,collector TEXT,source TEXT,generation TEXT,ecosystem TEXT,
                    source_name TEXT,received_bytes INTEGER,source_bytes INTEGER,updated TEXT,
                    PRIMARY KEY(owner,collector,source));
                CREATE TABLE IF NOT EXISTS source_content_activity(
                    owner TEXT,collector TEXT,source TEXT,revision TEXT,changed TEXT,
                    PRIMARY KEY(owner,collector,source));
                INSERT OR IGNORE INTO source_content_activity
                    SELECT owner,collector,source,generation||':'||received_bytes,updated
                    FROM source_archives;
                CREATE TABLE IF NOT EXISTS source_chunks(
                    owner TEXT,collector TEXT,source TEXT,generation TEXT,start INTEGER,
                    end INTEGER,sha256 TEXT,content BLOB,
                    PRIMARY KEY(owner,collector,source,generation,start));
                CREATE TABLE IF NOT EXISTS semantic_sessions(
                    owner TEXT,id TEXT,collector TEXT,source TEXT,title TEXT,agent TEXT,
                    source_revision TEXT,body TEXT,updated TEXT,
                    PRIMARY KEY(owner,id),UNIQUE(owner,collector,source));
                CREATE TABLE IF NOT EXISTS semantic_ir_history(
                    owner TEXT,id TEXT,collector TEXT,source TEXT,title TEXT,agent TEXT,
                    source_revision TEXT,body TEXT,updated TEXT,body_sha256 TEXT,
                    PRIMARY KEY(owner,id,source_revision));
                CREATE TABLE IF NOT EXISTS semantic_analyses(
                    owner TEXT,session TEXT,revision TEXT,source_revision TEXT,
                    status TEXT,body TEXT,updated TEXT,PRIMARY KEY(owner,session));
                CREATE TABLE IF NOT EXISTS semantic_jobs(
                    id TEXT PRIMARY KEY,owner TEXT,session TEXT,kind TEXT,status TEXT,
                    source_revision TEXT,message TEXT,created TEXT,updated TEXT);
                CREATE TABLE IF NOT EXISTS semantic_batches(
                    id TEXT PRIMARY KEY,owner TEXT,concurrency INTEGER,created TEXT);
                CREATE TABLE IF NOT EXISTS semantic_batch_items(
                    batch TEXT,session TEXT,job TEXT,PRIMARY KEY(batch,session));
                CREATE TABLE IF NOT EXISTS semantic_job_execution(job TEXT PRIMARY KEY,body TEXT);
                CREATE TABLE IF NOT EXISTS semantic_job_resumes(
                    job TEXT,generation INTEGER,body TEXT,created TEXT,
                    PRIMARY KEY(job,generation));
                CREATE TABLE IF NOT EXISTS semantic_job_progress(job TEXT PRIMARY KEY,body TEXT);
                CREATE TABLE IF NOT EXISTS semantic_job_times(
                    job TEXT PRIMARY KEY,started TEXT,finished TEXT);
                CREATE INDEX IF NOT EXISTS semantic_jobs_pending ON semantic_jobs(status,created);
                CREATE TABLE IF NOT EXISTS semantic_session_metadata(
                    owner TEXT,session TEXT,body TEXT,updated TEXT,
                    PRIMARY KEY(owner,session));
                CREATE INDEX IF NOT EXISTS semantic_sessions_directory ON semantic_sessions(
                    owner,id,title,agent,collector,source,source_revision,updated);
            """)

    @staticmethod
    def session_id(collector: str, source: str) -> str:
        return digest(collector + ":" + source)[:40]

    def _owner(self, db: Any, actor: str, collector: str) -> str:
        row = db.execute(
            "SELECT owner FROM collectors WHERE machine=? AND collector=?", (actor, collector)
        ).fetchone()
        if not row:
            raise PermissionError("Collector is not bound to an owner")
        return str(row[0])

    def source_progress(self, actor: str, collector: str, source: str) -> dict[str, Any]:
        with self.domain.connect() as db:
            owner = self._owner(db, actor, collector)
            row = db.execute(
                "SELECT generation,received_bytes AS next_offset,source_bytes FROM source_archives "
                "WHERE owner=? AND collector=? AND source=?",
                (owner, collector, source),
            ).fetchone()
            ledger = db.execute(
                "SELECT revision,parser FROM sources WHERE owner=? AND collector=? AND source=?",
                (owner, collector, source),
            ).fetchone()
        return {
            **(dict(row) if row else {"generation": None, "next_offset": 0, "source_bytes": 0}),
            "ledger_revision": ledger["revision"] if ledger else None,
            "ledger_parser": ledger["parser"] if ledger else None,
        }

    def ingest_source(self, actor: str, value: SourceChunk) -> dict[str, Any]:
        try:
            content = base64.b64decode(value.content, validate=True)
        except ValueError as error:
            raise ValueError("Invalid source encoding") from error
        if not content or len(content) > 512 * 1024:
            raise ValueError("Source range must contain 1 to 524288 bytes")
        if value.end != value.start + len(content) or value.end > value.source_bytes:
            raise ValueError("Invalid source range")
        if hashlib.sha256(content).hexdigest() != value.sha256:
            raise ValueError("Source range digest mismatch")
        if any(char in value.source_name for char in ("/", "\\", "\0")):
            raise ValueError("Source name must be a basename")
        body = value.model_dump_json()
        sid = self.session_id(value.collector, value.source)
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            owner = self._owner(db, actor, value.collector)
            prior = self.domain._prior(db, actor, value.mutation_id, body)
            if prior:
                return prior
            key = (owner, value.collector, value.source)
            old = db.execute(
                "SELECT * FROM source_archives WHERE owner=? AND collector=? AND source=?", key
            ).fetchone()
            if old and old["ecosystem"] != value.ecosystem:
                raise ValueError("Source ecosystem cannot change")
            same = old and old["generation"] == value.generation
            if (
                old
                and not same
                and db.execute(
                    "SELECT 1 FROM source_chunks WHERE owner=? AND collector=? AND source=? "
                    "AND generation=? LIMIT 1",
                    (*key, value.generation),
                ).fetchone()
            ):
                raise ValueError("Cannot reactivate a superseded source generation")
            cursor = int(old["received_bytes"]) if same else 0
            if value.start < cursor:
                previous = db.execute(
                    "SELECT end,sha256 FROM source_chunks WHERE owner=? AND collector=? "
                    "AND source=? AND generation=? AND start=?",
                    (*key, value.generation, value.start),
                ).fetchone()
                if (
                    not previous
                    or previous["end"] != value.end
                    or previous["sha256"] != value.sha256
                ):
                    raise ValueError("Overlapping source range differs from durable content")
            elif value.start == cursor:
                db.execute(
                    "INSERT INTO source_chunks VALUES(?,?,?,?,?,?,?,?)",
                    (*key, value.generation, value.start, value.end, value.sha256, content),
                )
                cursor = value.end
            else:
                raise ValueError("Missing preceding source range")
            db.execute(
                "INSERT OR REPLACE INTO source_archives VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    *key,
                    value.generation,
                    value.ecosystem,
                    value.source_name,
                    cursor,
                    max(value.source_bytes, int(old["source_bytes"]) if same else 0),
                    stamp(),
                ),
            )

            # Replay deliveries must not reset the source inactivity clock.
            content_cursor = value.generation + ":" + str(cursor)
            activity = db.execute(
                "SELECT revision FROM source_content_activity "
                "WHERE owner=? AND collector=? AND source=?",
                key,
            ).fetchone()
            if not activity or activity[0] != content_cursor:
                db.execute(
                    "INSERT OR REPLACE INTO source_content_activity VALUES(?,?,?,?,?)",
                    (*key, content_cursor, stamp()),
                )
            if cursor == value.source_bytes:
                revision = digest(value.generation + ":" + str(cursor))
                self._queue(db, owner, sid, "parse", revision)
            result = self.domain._receipt(
                db,
                actor,
                value.mutation_id,
                body,
                "source.append",
                {
                    "source": value.source,
                    "session_id": sid,
                    "generation": value.generation,
                    "accepted_bytes": len(content),
                    "next_offset": value.end,
                },
            )
            db.execute(
                "UPDATE audit SET body=? WHERE actor=? AND id=?",
                (
                    json.dumps(
                        {
                            "source": value.source,
                            "generation": value.generation,
                            "start": value.start,
                            "end": value.end,
                            "sha256": value.sha256,
                        }
                    ),
                    actor,
                    value.mutation_id,
                ),
            )
        return result

    @staticmethod
    def _queue(
        db: Any, owner: str, sid: str, kind: str, revision: str, *, refresh: bool = False
    ) -> str:
        row = db.execute(
            "SELECT id FROM semantic_jobs WHERE owner=? AND session=? AND kind=? "
            "AND source_revision=? AND (status IN ('queued','running') OR "
            "(status='complete' AND ?=0 AND (kind='parse' OR EXISTS ("
            "SELECT 1 FROM semantic_analyses a WHERE a.owner=semantic_jobs.owner "
            "AND a.session=semantic_jobs.session "
            "AND a.source_revision=semantic_jobs.source_revision))))",
            (owner, sid, kind, revision, int(refresh)),
        ).fetchone()
        if row:
            return str(row[0])
        uncertain = db.execute(
            "SELECT id FROM semantic_jobs WHERE owner=? AND session=? AND kind=? "
            "AND source_revision=? AND status='failed' AND message LIKE '%result uncertain%'",
            (owner, sid, kind, revision),
        ).fetchone()
        if uncertain:
            raise ValueError("Prior Jindu result uncertain; reconcile original job before retry")
        if (
            kind == "analyze"
            and db.execute(
                "SELECT 1 FROM semantic_jobs WHERE owner=? AND session=? AND kind='analyze' "
                "AND source_revision=? AND status='failed'",
                (owner, sid, revision),
            ).fetchone()
        ):
            raise ValueError(
                "Resume the original failed analysis job; a new paid identity is prohibited"
            )
        identifier = uuid.uuid4().hex
        db.execute(
            "INSERT INTO semantic_jobs VALUES(?,?,?,?,?,?,?,?,?)",
            (
                identifier,
                owner,
                sid,
                kind,
                "queued",
                revision,
                "",
                stamp(),
                stamp(),
            ),
        )
        return identifier

    def request_parse(self, owner: str, sid: str, value: AnalysisRequest) -> dict[str, Any]:
        """Refresh normalized IR from the durable archive without uploading or model calls."""
        body = value.model_dump_json() + ":parse:" + sid
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = self.domain._prior(db, owner, value.mutation_id, body)
            if prior:
                return prior
            source = None
            for candidate in db.execute("SELECT * FROM source_archives WHERE owner=?", (owner,)):
                if self.session_id(candidate["collector"], candidate["source"]) == sid:
                    source = candidate
                    break
            if source is None or source["received_bytes"] != source["source_bytes"]:
                raise ValueError("A complete account-owned source archive is required")
            if db.execute(
                "SELECT 1 FROM semantic_jobs WHERE owner=? AND session=? AND kind='analyze' "
                "AND status IN ('queued','running')",
                (owner, sid),
            ).fetchone():
                raise ValueError("Wait for active analysis before refreshing parser output")
            revision = digest(source["generation"] + ":" + str(source["received_bytes"]))
            job = self._queue(db, owner, sid, "parse", revision, refresh=True)
            return self.domain._receipt(
                db,
                owner,
                value.mutation_id,
                body,
                "session.parse",
                {
                    "job_id": job,
                    "session_id": sid,
                    "status": db.execute(
                        "SELECT status FROM semantic_jobs WHERE id=?", (job,)
                    ).fetchone()[0],
                },
            )

    def request_analysis(self, owner: str, sid: str, value: AnalysisRequest) -> dict[str, Any]:
        body = value.model_dump_json() + ":" + sid
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = self.domain._prior(db, owner, value.mutation_id, body)
            if prior:
                return prior
            row = db.execute(
                "SELECT source_revision FROM semantic_sessions WHERE owner=? AND id=?", (owner, sid)
            ).fetchone()
            if not row:
                raise ValueError("Session content has not finished parsing")
            job = self._queue(db, owner, sid, "analyze", row[0])
            return self.domain._receipt(
                db,
                owner,
                value.mutation_id,
                body,
                "analysis.request",
                {
                    "job_id": job,
                    "status": db.execute(
                        "SELECT status FROM semantic_jobs WHERE id=?", (job,)
                    ).fetchone()[0],
                    "session_id": sid,
                },
            )

    @staticmethod
    def resume_eligibility(
        job: dict[str, Any],
        progress: dict[str, Any],
        generation: int,
        authorized_recomputations: list[dict[str, Any]] | None = None,
        window_resumes: int = 0,
    ) -> str:
        if job["kind"] != "analyze" or job["status"] != "failed":
            return "analysis_not_failed"
        if generation >= MAX_RESUME_GENERATIONS or window_resumes >= MAX_WINDOW_RESUMES:
            return "resume_limit_reached"
        calls = progress.get("analysis_usage", [])

        def acknowledged(call: dict[str, Any]) -> bool:
            return any(
                ack.get("job_id") == job["id"]
                and ack.get("accept_possible_duplicate_charge") is True
                and ack.get("receipt_state") in {"uncertain_terminal", "receipt_not_found"}
                and ack.get("call_id") == call.get("call_id")
                and ack.get("chunk") == call.get("chunk")
                and ack.get("attempt") == call.get("attempt")
                and (not call.get("receipt_id") or ack.get("receipt_id") == call["receipt_id"])
                for ack in authorized_recomputations or []
            )

        def received_invalid(call: dict[str, Any]) -> bool:
            return bool(
                (
                    call.get("valid") is False
                    or (
                        call.get("failed") is True
                        and call.get("uncertain") is False
                        and call.get("retryable") is True
                    )
                )
                and call.get("receipt_id")
                and isinstance(call.get("usage"), dict)
                and call["usage"]
            )

        unknown = [
            call
            for call in calls
            if call.get("state") in {"prepared", "uncertain"}
            or call.get("uncertain") is True
            or call.get("failed")
            and not (
                call.get("uncertain") is False
                and call.get("retryable") is True
                and received_invalid(call)
            )
        ]
        if any(not acknowledged(call) for call in unknown) or (
            "result uncertain" in job.get("message", "") and not unknown
        ):
            return "prior_call_uncertain"
        if not calls or not received_invalid(calls[-1]):
            return "received_invalid_result_required"
        if progress.get("state") != "failed":
            return "failed_progress_required"
        return "eligible"

    def resume_state(
        self,
        db: Any,
        job: dict[str, Any] | None,
        progress: dict[str, Any],
        current_source_revision: str,
    ) -> dict[str, Any]:
        generation = (
            db.execute(
                "SELECT COALESCE(max(generation),0) FROM semantic_job_resumes WHERE job=?",
                (job["id"],),
            ).fetchone()[0]
            if job
            else 0
        )
        acknowledgments = self._audited_recomputations(db, job) if job else []
        window_resumes = (
            db.execute(
                "SELECT count(*) FROM semantic_job_resumes WHERE job=? "
                "AND json_extract(body,'$.completed_chunks')=?",
                (job["id"], progress.get("completed_chunks", 0)),
            ).fetchone()[0]
            if job
            else 0
        )
        reason = (
            self.resume_eligibility(job, progress, generation, acknowledgments, window_resumes)
            if job
            else "analysis_not_failed"
        )
        if reason == "eligible" and job:
            if job["source_revision"] != current_source_revision:
                reason = "analysis_source_changed"
            elif not db.execute(
                "SELECT 1 FROM semantic_job_execution WHERE job=?", (job["id"],)
            ).fetchone():
                reason = "execution_identity_missing"
        return {
            "eligible": reason == "eligible",
            "reason": reason,
            "job_id": job["id"] if job else None,
            "generation": generation,
            "completed_chunks": progress.get("completed_chunks", 0),
            "max_generations": MAX_RESUME_GENERATIONS,
            "window_resumes": window_resumes,
            "max_window_resumes": MAX_WINDOW_RESUMES,
        }

    @staticmethod
    def _audited_recomputations(db: Any, job: dict[str, Any]) -> list[dict[str, Any]]:
        """Only the canonical persisted operator decisions can exempt old uncertainty."""
        result = []
        for row in db.execute(
            "SELECT generation,body FROM semantic_job_resumes WHERE job=? ORDER BY generation",
            (job["id"],),
        ):
            body = json.loads(row["body"])
            ack = body.get("authorized_recomputation", {})
            proof = body.get("receipt_verification", {})
            receipt = proof.get("receipt") or {}
            decision = body.get("operator_decision", {})
            chunk, attempt = ack.get("chunk"), ack.get("attempt")
            if not (
                body.get("policy") == "explicit_operator_recompute_missing_response"
                and ack.get("job_id") == job["id"]
                and ack.get("resume_generation") == row["generation"]
                and ack.get("accept_possible_duplicate_charge") is True
                and decision.get("accept_possible_duplicate_charge") is True
                and ack.get("authorization_id") == decision.get("mutation_id")
                and (
                    (
                        ack.get("receipt_state") == "uncertain_terminal"
                        and receipt.get("state") == "uncertain"
                        and receipt.get("id") == decision.get("receipt_id") == ack.get("receipt_id")
                        and receipt.get("request_id")
                        == decision.get("call_id")
                        == ack.get("call_id")
                    )
                    or (
                        ack.get("receipt_state") == "receipt_not_found"
                        and decision.get("receipt_id") is None
                        and ack.get("receipt_id") is None
                        and proof.get("receipt") is None
                        and proof.get("lookup", {}).get("state") == "receipt_not_found"
                        and proof.get("lookup", {}).get("request_id")
                        == decision.get("call_id")
                        == ack.get("call_id")
                    )
                )
                and isinstance(chunk, int)
                and chunk > 0
                and isinstance(attempt, int)
                and attempt > 0
                and ack.get("call_id")
                == "trajectory:"
                + hashlib.sha256(f"{job['id']}:{chunk-1}:{attempt-1}".encode()).hexdigest()
            ):
                continue
            result.append(ack)
        return result

    def resume_context(self, job: dict[str, Any]) -> dict[str, Any]:
        with self.domain.connect() as db:
            row = db.execute(
                "SELECT generation,body FROM semantic_job_resumes WHERE job=? "
                "ORDER BY generation DESC LIMIT 1",
                (job["id"],),
            ).fetchone()
            progress = db.execute(
                "SELECT body FROM semantic_job_progress WHERE job=?", (job["id"],)
            ).fetchone()
            recomputations = self._audited_recomputations(db, job)
        return {
            "authorized_recomputations": recomputations,
            "generation": row["generation"] if row else 0,
            "authorization": json.loads(row["body"]) if row else None,
            "prior_progress": json.loads(progress[0]) if progress else {},
        }

    def resume_analysis(self, owner: str, job_id: str, value: AnalysisRequest) -> dict[str, Any]:
        """Authorize bounded continuation of the same failed job, never a fresh analysis."""
        body = "analysis.resume:" + job_id + ":" + value.model_dump_json()
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = self.domain._prior(db, owner, value.mutation_id, body)
            if prior:
                return prior
            row = db.execute(
                "SELECT * FROM semantic_jobs WHERE owner=? AND id=?", (owner, job_id)
            ).fetchone()
            if row is None:
                raise PermissionError("Analysis job unavailable")
            progress_row = db.execute(
                "SELECT body FROM semantic_job_progress WHERE job=?", (job_id,)
            ).fetchone()
            progress = json.loads(progress_row[0]) if progress_row else {}
            current = db.execute(
                "SELECT source_revision FROM semantic_sessions WHERE owner=? AND id=?",
                (owner, row["session"]),
            ).fetchone()
            state = self.resume_state(db, dict(row), progress, current[0] if current else "")
            if not state["eligible"]:
                raise AnalysisResumeError(state["reason"])
            generation = state["generation"]
            return self._continue_analysis(db, owner, row, progress, generation, value, body)

    def recompute_lost_window(
        self,
        owner: str,
        job_id: str,
        value: LostWindowRecomputeRequest,
        actor: dict[str, Any],
        *,
        verifier: Any = None,
    ) -> dict[str, Any]:
        """One explicit paid decision after read-only receipt verification, outside SQLite locks."""
        from trajectory.product.receipt_verification import verify_lost_receipt

        body = "analysis.recompute_lost_window:" + job_id + ":" + value.model_dump_json()
        with self.domain.connect() as db:
            prior = self.domain._prior(db, owner, value.mutation_id, body)
            if prior:
                return prior
            if abs((datetime.now(UTC) - value.receipt_checked_at).total_seconds()) > 900:
                raise AnalysisResumeError("receipt_check_not_fresh")
            row, progress, generation, execution = self._lost_window_snapshot(
                db, owner, job_id, value
            )
            snapshot = json.dumps([dict(row), progress, generation, execution], sort_keys=True)
        # No SQL transaction spans this authenticated network read.
        try:
            proof = (verifier or verify_lost_receipt)(
                value.call_id, value.receipt_id, execution["route"], execution["model"]
            )
        except Exception as error:
            raise AnalysisResumeError("receipt_verification_unavailable") from error
        receipt = proof.get("receipt")
        caller = proof["caller"]
        if not (
            caller.get("source_service") == "trajectory"
            and caller.get("machine_client_id")
            and caller.get("key_id")
            and caller.get("account_id")
            and "jindu.read" in caller.get("scopes", [])
            and (receipt is None or receipt.get("account_id") == caller["account_id"])
        ):
            raise AnalysisResumeError("receipt_verification_mismatch")
        if value.receipt_id is None:
            if not (
                receipt is None
                and proof.get("lookup", {}).get("request_id") == value.call_id
                and proof.get("lookup", {}).get("state") == "receipt_not_found"
            ):
                raise AnalysisResumeError("receipt_verification_mismatch")
        elif not (
            receipt is not None
            and receipt.get("source_service") == "trajectory"
            and receipt.get("id") == value.receipt_id
            and receipt.get("request_id") == value.call_id
            and receipt.get("route") == execution["route"]
            and receipt.get("model") == execution["model"]
            and receipt.get("state") == "uncertain"
            and receipt.get("finished") is not None
        ):
            raise AnalysisResumeError("receipt_verification_mismatch")
        if receipt is not None and any(
            receipt.get(key) is not None
            for key in ("input_tokens", "output_tokens", "cached_tokens")
        ):
            raise AnalysisResumeError("receipt_usage_reconciliation_required")
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = self.domain._prior(db, owner, value.mutation_id, body)
            if prior:
                return prior
            row, progress, generation, execution = self._lost_window_snapshot(
                db, owner, job_id, value
            )
            if snapshot != json.dumps([dict(row), progress, generation, execution], sort_keys=True):
                raise AnalysisResumeError("analysis_changed_during_receipt_check")
            last = progress["analysis_usage"][-1]
            authorization = {
                "job_id": job_id,
                "call_id": value.call_id,
                "receipt_id": value.receipt_id,
                "chunk": last["chunk"],
                "attempt": last["attempt"],
                "resume_generation": generation + 1,
                "receipt_state": (
                    "uncertain_terminal" if receipt is not None else "receipt_not_found"
                ),
                "authorization_id": value.mutation_id,
                "accept_possible_duplicate_charge": True,
            }
            return self._continue_analysis(
                db,
                owner,
                row,
                progress,
                generation,
                value,
                body,
                operation="analysis.recompute_lost_window",
                extra={
                    "policy": "explicit_operator_recompute_missing_response",
                    "authorized_recomputation": authorization,
                    "receipt_verification": proof,
                    "operator_decision": value.model_dump(mode="json"),
                    "actor": actor,
                    "authorized_at": stamp(),
                },
            )

    def _lost_window_snapshot(
        self,
        db: Any,
        owner: str,
        job_id: str,
        value: LostWindowRecomputeRequest,
    ) -> tuple[Any, dict[str, Any], int, dict[str, Any]]:
        row = db.execute(
            "SELECT * FROM semantic_jobs WHERE owner=? AND id=?", (owner, job_id)
        ).fetchone()
        if row is None:
            raise PermissionError("Analysis job unavailable")
        if row["kind"] != "analyze" or row["status"] != "failed":
            raise AnalysisResumeError("analysis_not_failed")
        progress_row = db.execute(
            "SELECT body FROM semantic_job_progress WHERE job=?", (job_id,)
        ).fetchone()
        progress = json.loads(progress_row[0]) if progress_row else {}
        calls = progress.get("analysis_usage", [])
        last = calls[-1] if calls else {}
        if not (
            progress.get("state") == "failed"
            and last.get("failed") is True
            and last.get("call_id") == value.call_id
            and (not last.get("receipt_id") or last["receipt_id"] == value.receipt_id)
            and isinstance(last.get("chunk"), int)
            and isinstance(last.get("attempt"), int)
            and last["chunk"] == progress.get("completed_chunks", 0) + 1
            and last["attempt"] > 0
            and value.call_id
            == "trajectory:"
            + hashlib.sha256(f"{job_id}:{last['chunk']-1}:{last['attempt']-1}".encode()).hexdigest()
        ):
            raise AnalysisResumeError("last_lost_call_mismatch")
        generation = db.execute(
            "SELECT COALESCE(max(generation),0) FROM semantic_job_resumes WHERE job=?", (job_id,)
        ).fetchone()[0]
        window_resumes = db.execute(
            "SELECT count(*) FROM semantic_job_resumes WHERE job=? "
            "AND json_extract(body,'$.completed_chunks')=?",
            (job_id, progress.get("completed_chunks", 0)),
        ).fetchone()[0]
        if (
            generation >= MAX_RESUME_GENERATIONS
            or window_resumes >= MAX_WINDOW_RESUMES
            or (generation + 1) * 2 <= last["attempt"] - 1
        ):
            raise AnalysisResumeError("resume_limit_reached")
        execution = db.execute(
            "SELECT body FROM semantic_job_execution WHERE job=?", (job_id,)
        ).fetchone()
        if not execution:
            raise AnalysisResumeError("execution_identity_missing")
        return row, progress, generation, json.loads(execution[0])

    def _continue_analysis(
        self,
        db: Any,
        owner: str,
        row: Any,
        progress: dict[str, Any],
        generation: int,
        value: AnalysisRequest,
        body: str,
        *,
        operation: str = "analysis.resume",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from trajectory.product.semantic_model import PROMPT_VERSION

        job_id = row["id"]
        current = db.execute(
            "SELECT source_revision FROM semantic_sessions WHERE owner=? AND id=?",
            (owner, row["session"]),
        ).fetchone()
        if current is None or current[0] != row["source_revision"]:
            raise AnalysisResumeError("analysis_source_changed")
        if db.execute(
            "SELECT 1 FROM semantic_jobs WHERE owner=? AND session=? AND id<>? "
            "AND status IN ('queued','running')",
            (owner, row["session"], job_id),
        ).fetchone():
            raise AnalysisResumeError("another_analysis_active")
        execution = db.execute(
            "SELECT body FROM semantic_job_execution WHERE job=?", (job_id,)
        ).fetchone()
        if not execution:
            raise AnalysisResumeError("execution_identity_missing")
        old_execution = json.loads(execution[0])
        if old_execution.get("prompt_version") not in {
            "trajectory-task-hierarchy/1",
            PROMPT_VERSION,
        }:
            raise AnalysisResumeError("unsupported_prompt_migration")
        target = {**old_execution, "prompt_version": PROMPT_VERSION}
        authorization = {
            "generation": generation + 1,
            "from_execution": old_execution,
            "to_execution": target,
            "completed_chunks": progress.get("completed_chunks", 0),
            "previous_call_ids": [call.get("call_id") for call in progress["analysis_usage"]],
            "policy": "received_invalid_only_preserve_completed_chunks",
            **(extra or {}),
        }
        queued_at = stamp()
        db.execute(
            "INSERT INTO semantic_job_resumes VALUES(?,?,?,?)",
            (job_id, generation + 1, json.dumps(authorization, sort_keys=True), queued_at),
        )
        db.execute(
            "UPDATE semantic_jobs SET status='queued',message='',updated=? WHERE id=?",
            (queued_at, job_id),
        )
        return self.domain._receipt(
            db,
            owner,
            value.mutation_id,
            body,
            operation,
            {
                "job_id": job_id,
                "session_id": row["session"],
                "status": "queued",
                "resume_generation": generation + 1,
                "queued_at": queued_at,
                "completed_chunks": progress.get("completed_chunks", 0),
                "source_revision": row["source_revision"],
            },
        )

    def claim_job(self) -> dict[str, Any] | None:
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT j.* FROM semantic_jobs j WHERE j.status='queued' AND NOT EXISTS ("
                "SELECT 1 FROM semantic_jobs active WHERE active.owner=j.owner "
                "AND active.session=j.session AND active.status='running') AND NOT EXISTS ("
                "SELECT 1 FROM semantic_batch_items i JOIN semantic_batches b ON b.id=i.batch "
                "WHERE i.job=j.id AND (SELECT count(*) FROM semantic_batch_items x "
                "JOIN semantic_jobs r ON r.id=x.job WHERE x.batch=b.id AND r.status='running') "
                ">=b.concurrency) ORDER BY j.created LIMIT 1"
            ).fetchone()
            if not row:
                return None
            db.execute(
                "UPDATE semantic_jobs SET status='running',updated=? WHERE id=?",
                (stamp(), row["id"]),
            )
            db.execute(
                "INSERT INTO semantic_job_times VALUES(?,?,NULL) "
                "ON CONFLICT(job) DO UPDATE SET finished=NULL",
                (row["id"], stamp()),
            )
            return {**dict(row), "status": "running"}

    def recover_jobs(self) -> None:
        """Only the exclusive coordinator may recover interrupted jobs."""
        with self.domain.connect() as db:
            db.execute("UPDATE semantic_jobs SET status='queued' WHERE status='running'")

    def finish_job(self, job: dict[str, Any], error: str = "") -> None:
        with self.domain.connect() as db:
            db.execute(
                "UPDATE semantic_jobs SET status=?,message=?,updated=? WHERE id=?",
                ("failed" if error else "complete", error[:500], stamp(), job["id"]),
            )

            db.execute("UPDATE semantic_job_times SET finished=? WHERE job=?", (stamp(), job["id"]))

    def fail_and_auto_resume(self, job: dict[str, Any], error: str) -> bool:
        """Atomically queue bounded repair only for confirmed invalid responses."""
        from trajectory.product.semantic_model import repairable_validation_error

        if not repairable_validation_error(error):
            self.finish_job(job, error)
            return False
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute(
                "UPDATE semantic_jobs SET status='failed',message=?,updated=? "
                "WHERE id=? AND owner=? AND source_revision=? AND status='running'",
                (error[:500], stamp(), job["id"], job["owner"], job["source_revision"]),
            )
            if updated.rowcount != 1:
                return False
            db.execute("UPDATE semantic_job_times SET finished=? WHERE job=?", (stamp(), job["id"]))
            row = db.execute("SELECT * FROM semantic_jobs WHERE id=?", (job["id"],)).fetchone()
            progress_row = db.execute(
                "SELECT body FROM semantic_job_progress WHERE job=?", (job["id"],)
            ).fetchone()
            progress = json.loads(progress_row[0]) if progress_row else {}
            current = db.execute(
                "SELECT source_revision FROM semantic_sessions WHERE owner=? AND id=?",
                (job["owner"], job["session"]),
            ).fetchone()
            state = self.resume_state(db, dict(row), progress, current[0] if current else "")
            if not state["eligible"]:
                return False
            generation = state["generation"]
            value = AnalysisRequest(mutation_id="auto-" + digest(f"{job['id']}:{generation + 1}"))
            body = "analysis.auto_resume:" + job["id"] + ":" + value.model_dump_json()
            try:
                self._continue_analysis(
                    db,
                    job["owner"],
                    row,
                    progress,
                    generation,
                    value,
                    body,
                    operation="analysis.auto_resume",
                    extra={"resume_mode": "automatic", "validation_error": error[:600]},
                )
            except AnalysisResumeError:
                return False
            return True

    def park_job(self, job: dict[str, Any]) -> None:
        """Return a checkpointed job to the same queue without authorizing new attempts."""
        with self.domain.connect() as db:
            db.execute(
                "UPDATE semantic_jobs SET status='queued',message=?,updated=? "
                "WHERE id=? AND owner=? AND source_revision=? AND status='running'",
                (
                    "Analysis saved at a window boundary, awaiting worker availability",
                    stamp(),
                    job["id"],
                    job["owner"],
                    job["source_revision"],
                ),
            )

    def pin_execution(self, job: dict[str, Any], configuration: dict[str, Any]) -> None:
        body = json.dumps(configuration, sort_keys=True)
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT body FROM semantic_job_execution WHERE job=?", (job["id"],)
            ).fetchone()
            if prior and prior[0] != body:
                resume = db.execute(
                    "SELECT body FROM semantic_job_resumes WHERE job=? "
                    "ORDER BY generation DESC LIMIT 1",
                    (job["id"],),
                ).fetchone()
                authorization = json.loads(resume[0]) if resume else {}
                if (
                    authorization.get("from_execution") != json.loads(prior[0])
                    or authorization.get("to_execution") != configuration
                ):
                    raise ValueError(
                        "Analysis execution configuration changed; review original job before retry"
                    )
                db.execute(
                    "UPDATE semantic_job_execution SET body=? WHERE job=?", (body, job["id"])
                )
            db.execute(
                "INSERT OR IGNORE INTO semantic_job_execution VALUES(?,?)", (job["id"], body)
            )

    def job_progress(self, job: dict[str, Any], progress: dict[str, Any]) -> None:
        with self.domain.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO semantic_job_progress VALUES(?,?)",
                (job["id"], json.dumps(progress)),
            )
            db.execute("UPDATE semantic_jobs SET updated=? WHERE id=?", (stamp(), job["id"]))

    def request_batch(self, owner: str, value: AnalysisBatchRequest) -> dict[str, Any]:
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self.queue_batch(db, owner, value)

    def queue_batch(self, db: Any, owner: str, value: AnalysisBatchRequest) -> dict[str, Any]:
        """Queue inside the caller transaction, including revision checks and durable receipt."""
        body = "analysis.batch:" + value.model_dump_json(exclude_none=True)
        maximum = max(1, min(8, int(os.environ.get("TRAJECTORY_ANALYSIS_CONCURRENCY", "4"))))
        if value.concurrency > maximum:
            raise ValueError(f"Concurrency exceeds configured maximum {maximum}")
        prior = self.domain._prior(db, owner, value.mutation_id, body)
        if prior:
            return prior
        sessions = list(dict.fromkeys(value.session_ids))
        revisions = []
        for sid in sessions:
            row = db.execute(
                "SELECT source_revision FROM semantic_sessions WHERE owner=? AND id=?",
                (owner, sid),
            ).fetchone()
            if row is None:
                raise ValueError("Session unavailable or content has not finished parsing")
            if value.expected_source_revisions is not None:
                if value.expected_source_revisions.get(sid) != row[0]:
                    raise ValueError("Source revision changed since selection")
                archive = db.execute(
                    "SELECT a.generation,a.received_bytes,a.source_bytes FROM source_archives a "
                    "JOIN semantic_sessions s ON s.owner=a.owner AND s.collector=a.collector "
                    "AND s.source=a.source WHERE s.owner=? AND s.id=?",
                    (owner, sid),
                ).fetchone()
                if (
                    not archive
                    or archive_revision(archive) != row[0]
                    or archive["received_bytes"] != archive["source_bytes"]
                ):
                    raise ValueError("Source upload changed since selection")
            revisions.append(row[0])
        batch_id = uuid.uuid4().hex
        db.execute(
            "INSERT INTO semantic_batches VALUES(?,?,?,?)",
            (batch_id, owner, value.concurrency, stamp()),
        )
        items = []
        for sid, revision in zip(sessions, revisions, strict=True):
            job_id = self._queue(db, owner, sid, "analyze", revision)
            db.execute("INSERT INTO semantic_batch_items VALUES(?,?,?)", (batch_id, sid, job_id))
            status = db.execute(
                "SELECT status FROM semantic_jobs WHERE id=?", (job_id,)
            ).fetchone()[0]
            items.append({"session_id": sid, "job_id": job_id, "status": status})
        return self.domain._receipt(
            db,
            owner,
            value.mutation_id,
            body,
            "analysis.batch",
            {"batch_id": batch_id, "items": items, "concurrency": value.concurrency},
        )

    def batches(self, owner: str) -> dict[str, Any]:
        with self.domain.connect() as db:
            ids = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM semantic_batches WHERE owner=? ORDER BY created DESC LIMIT 50",
                    (owner,),
                )
            ]
        return {"batches": [self.batch_detail(owner, identifier) for identifier in ids]}

    def batch_detail(self, owner: str, batch_id: str) -> dict[str, Any]:
        with self.domain.connect() as db:
            batch = db.execute(
                "SELECT * FROM semantic_batches WHERE owner=? AND id=?", (owner, batch_id)
            ).fetchone()
            if batch is None:
                raise PermissionError("Batch unavailable")
            rows = db.execute(
                "SELECT j.*,t.started,t.finished,s.title AS session_title,s.agent AS session_agent,"
                "m.body AS session_metadata,s.source_revision AS current_source_revision,"
                "e.job AS execution_job,COALESCE((SELECT max(generation) FROM semantic_job_resumes "
                "r WHERE r.job=j.id),0) AS resume_generation FROM semantic_batch_items i "
                "JOIN semantic_jobs j ON j.id=i.job LEFT JOIN semantic_job_times t ON t.job=j.id "
                "LEFT JOIN semantic_sessions s ON s.owner=j.owner AND s.id=j.session "
                "LEFT JOIN semantic_session_metadata m ON m.owner=j.owner AND m.session=j.session "
                "LEFT JOIN semantic_job_execution e ON e.job=j.id "
                "WHERE i.batch=? ORDER BY j.created,j.id",
                (batch_id,),
            ).fetchall()
            items = []
            for row in rows:
                analysis = db.execute(
                    "SELECT body FROM semantic_analyses WHERE owner=? AND session=? "
                    "AND source_revision=?",
                    (owner, row["session"], row["source_revision"]),
                ).fetchone()
                provenance = json.loads(analysis[0]).get("provenance", {}) if analysis else {}
                if row["status"] == "failed":
                    failed = db.execute(
                        "SELECT body FROM audit WHERE actor=? AND id=? "
                        "AND operation='analysis.failed' ORDER BY created DESC,rowid DESC LIMIT 1",
                        (owner, row["id"]),
                    ).fetchone()
                    if failed:
                        provenance = json.loads(failed[0]).get("provenance", {})
                progress_row = db.execute(
                    "SELECT body FROM semantic_job_progress WHERE job=?", (row["id"],)
                ).fetchone()
                progress = json.loads(progress_row[0]) if progress_row else {}
                elapsed = (
                    (
                        (
                            datetime.fromisoformat(row["finished"])
                            if row["finished"]
                            else datetime.now(UTC)
                        )
                        - datetime.fromisoformat(row["started"])
                    ).total_seconds()
                    if row["started"]
                    else None
                )
                items.append(
                    {
                        "session_id": row["session"],
                        "session": {
                            **(
                                read_metadata(json.loads(row["session_metadata"]))
                                if row["session_metadata"]
                                else read_metadata({})
                            ),
                            "id": row["session"],
                            "title": row["session_title"],
                            "agent": row["session_agent"],
                        },
                        "job_id": row["id"],
                        "status": row["status"],
                        "last_error": row["message"],
                        "created_at": row["created"],
                        "updated_at": row["updated"],
                        "started_at": row["started"],
                        "finished_at": row["finished"],
                        "elapsed_seconds": elapsed,
                        "progress": progress,
                        "resume": self.resume_state(
                            db, dict(row), progress, row["current_source_revision"]
                        ),
                        "analysis_usage": provenance.get(
                            "analysis_usage", progress.get("analysis_usage", [])
                        ),
                        "analysis_cost": (
                            self.domain.analysis_cost(owner, provenance or progress)
                            if provenance.get("analysis_usage") or progress.get("analysis_usage")
                            else None
                        ),
                    }
                )
        counts = {
            state: sum(item["status"] == state for item in items)
            for state in ("queued", "running", "complete", "failed")
        }
        status = (
            "running"
            if counts["running"]
            else "queued" if counts["queued"] else "failed" if counts["failed"] else "complete"
        )
        return {
            "batch_id": batch_id,
            "status": status,
            "counts": counts,
            "total": len(items),
            "concurrency": batch["concurrency"],
            "created_at": batch["created"],
            "items": items,
        }

    def archive(self, owner: str, sid: str) -> tuple[dict[str, Any], list[bytes]]:
        with self.domain.connect() as db:
            rows = db.execute("SELECT * FROM source_archives WHERE owner=?", (owner,)).fetchall()
            source = next(
                (
                    dict(row)
                    for row in rows
                    if self.session_id(row["collector"], row["source"]) == sid
                ),
                None,
            )
            if source is None:
                raise ValueError("Unknown source")
            chunks = db.execute(
                "SELECT content FROM source_chunks WHERE owner=? AND collector=? AND source=? "
                "AND generation=? ORDER BY start",
                (owner, source["collector"], source["source"], source["generation"]),
            ).fetchall()
        return source, [bytes(row[0]) for row in chunks]

    def save_session(
        self, owner: str, sid: str, source: dict[str, Any], revision: str, parsed: dict[str, Any]
    ) -> None:
        session = parsed.get("session", {})
        title = str(session.get("title") or source["source_name"])[:200]
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT generation,received_bytes FROM source_archives "
                "WHERE owner=? AND collector=? AND source=?",
                (owner, source["collector"], source["source"]),
            ).fetchone()
            if (
                not current
                or digest(current["generation"] + ":" + str(current["received_bytes"])) != revision
            ):
                raise ValueError(
                    "Source changed during parsing; current revision remains authoritative"
                )
            parsed = {
                **parsed,
                "source_snapshot": {
                    "generation": current["generation"],
                    "received_bytes": current["received_bytes"],
                },
            }
            previous = db.execute(
                "SELECT * FROM semantic_sessions WHERE owner=? AND id=?", (owner, sid)
            ).fetchone()
            if previous:
                referenced = db.execute(
                    "SELECT 1 FROM semantic_analyses WHERE owner=? AND session=? "
                    "AND source_revision=? "
                    "UNION ALL SELECT 1 FROM semantic_jobs WHERE owner=? AND session=? "
                    "AND source_revision=? AND kind='analyze' "
                    "AND status IN ('queued','running','failed') LIMIT 1",
                    (
                        owner,
                        sid,
                        previous["source_revision"],
                        owner,
                        sid,
                        previous["source_revision"],
                    ),
                ).fetchone()
                if referenced and previous["source_revision"] == revision:
                    if json.loads(previous["body"]).get("operations") != parsed.get("operations"):
                        raise ValueError(
                            "Referenced IR changed at the same source revision; "
                            "explicit parser migration required"
                        )
                elif referenced:
                    self._retain_ir(db, dict(previous))
            if db.execute(
                "SELECT 1 FROM semantic_ir_history WHERE owner=? AND id=? AND source_revision=?",
                (owner, sid, revision),
            ).fetchone():
                raise ValueError("A historical IR revision cannot become mutable current input")
            self.domain.import_native_measurements(db, owner, source, revision, parsed)
            db.execute(
                "INSERT OR REPLACE INTO semantic_sessions VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    owner,
                    sid,
                    source["collector"],
                    source["source"],
                    title,
                    source["ecosystem"],
                    revision,
                    json.dumps(parsed, ensure_ascii=False),
                    stamp(),
                ),
            )

            db.execute(
                "INSERT OR REPLACE INTO semantic_session_metadata VALUES(?,?,?,?)",
                (owner, sid, json.dumps(extract_metadata(parsed, source["source_name"])), stamp()),
            )

    def maintain_metadata(self, limit: int = 32) -> int:
        """Bounded migration called only by the existing coordinator, never by GET."""
        with self.domain.connect() as db:
            pending = db.execute(
                "SELECT s.owner FROM semantic_sessions s "
                "LEFT JOIN semantic_session_metadata m ON m.owner=s.owner AND m.session=s.id "
                "WHERE m.session IS NULL OR "
                "COALESCE(json_extract(m.body,'$.metadata_version'),0)<? LIMIT 1",
                (METADATA_VERSION,),
            ).fetchone()
        return self.backfill_metadata(pending["owner"], limit) if pending else 0

    def backfill_metadata(self, owner: str, limit: int = 32) -> int:
        """Migrate old IR one snapshot at a time, bounded by count and text budget."""
        migrated = 0
        read_chars = 0
        with self.domain.connect() as db:
            # Finalize the bounded ID cursor before entering any write transaction.
            # A live WAL read snapshot cannot safely upgrade after another writer commits.
            rows = db.execute(
                "SELECT s.id FROM semantic_sessions s "
                "LEFT JOIN semantic_session_metadata m ON m.owner=s.owner AND m.session=s.id "
                "WHERE s.owner=? AND (m.session IS NULL OR "
                "COALESCE(json_extract(m.body,'$.metadata_version'),0)<?) "
                "ORDER BY s.updated DESC LIMIT ?",
                (owner, METADATA_VERSION, limit),
            ).fetchall()
        for row in rows:
            # One record per transaction bounds writer ownership. Recheck under the
            # write lock so a concurrent parser or backfill remains authoritative.
            with self.domain.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                current = db.execute(
                    "SELECT s.body,s.title FROM semantic_sessions s "
                    "LEFT JOIN semantic_session_metadata m ON m.owner=s.owner AND m.session=s.id "
                    "WHERE s.owner=? AND s.id=? AND (m.session IS NULL OR "
                    "COALESCE(json_extract(m.body,'$.metadata_version'),0)<?)",
                    (owner, row["id"], METADATA_VERSION),
                ).fetchone()
                if current is None:
                    continue
                snapshot = current["body"]
                metadata = extract_metadata(json.loads(snapshot), current["title"])
                db.execute(
                    "INSERT OR REPLACE INTO semantic_session_metadata VALUES(?,?,?,?)",
                    (owner, row["id"], json.dumps(metadata), stamp()),
                )
                migrated += 1
                read_chars += len(snapshot)
            if read_chars >= 16 * 1024 * 1024:
                break
        return migrated

    @staticmethod
    def _retain_ir(db: Any, record: dict[str, Any]) -> None:
        old = db.execute(
            "SELECT * FROM semantic_ir_history WHERE owner=? AND id=? AND source_revision=?",
            (record["owner"], record["id"], record["source_revision"]),
        ).fetchone()
        if old:
            if old["body"] != record["body"] or old["body_sha256"] != digest(record["body"]):
                raise ValueError("Immutable IR history differs from referenced input")
            return
        fields = (
            "owner",
            "id",
            "collector",
            "source",
            "title",
            "agent",
            "source_revision",
            "body",
            "updated",
        )
        db.execute(
            "INSERT INTO semantic_ir_history VALUES(?,?,?,?,?,?,?,?,?,?)",
            (*[record[key] for key in fields], digest(record["body"])),
        )

    @staticmethod
    def _resolve_ir(db: Any, owner: str, sid: str, revision: str | None = None) -> dict[str, Any]:
        # Select only identity first: a historical read must not load both large IR bodies.
        current = db.execute(
            "SELECT s.collector,s.source,s.source_revision,EXISTS(SELECT 1 "
            "FROM semantic_ir_history h WHERE h.owner=s.owner AND h.id=s.id "
            "AND h.source_revision=s.source_revision) AS dual_authority "
            "FROM semantic_sessions s WHERE s.owner=? AND s.id=?",
            (owner, sid),
        ).fetchone()
        if current is None:
            raise IRSnapshotUnavailable("Unknown session")
        if current["dual_authority"]:
            raise ValueError("IR revision has duplicate current and history authority")
        if revision is None or current["source_revision"] == revision:
            row = db.execute(
                "SELECT * FROM semantic_sessions WHERE owner=? AND id=?", (owner, sid)
            ).fetchone()
            return {**dict(row), "historical_snapshot": False}
        history = db.execute(
            "SELECT * FROM semantic_ir_history WHERE owner=? AND id=? AND source_revision=?",
            (owner, sid, revision),
        ).fetchone()
        if history is None:
            raise IRSnapshotUnavailable("Requested parsed snapshot is unavailable")
        if digest(history["body"]) != history["body_sha256"]:
            raise ValueError("Immutable IR history integrity check failed")
        if (history["collector"], history["source"]) != (current["collector"], current["source"]):
            raise ValueError("Immutable IR history source identity changed")
        return {**dict(history), "historical_snapshot": True}

    def _display_ir(
        self, db: Any, owner: str, sid: str, revision: str | None = None
    ) -> dict[str, Any]:
        if revision:
            return self._resolve_ir(db, owner, sid, revision)
        active = db.execute(
            "SELECT source_revision FROM semantic_jobs WHERE owner=? AND session=? "
            "AND kind='analyze' AND status IN ('queued','running','failed') "
            "ORDER BY created DESC LIMIT 1",
            (owner, sid),
        ).fetchone()
        analysis = db.execute(
            "SELECT source_revision FROM semantic_analyses WHERE owner=? AND session=?",
            (owner, sid),
        ).fetchone()
        # A saved analysis stays readable while a newer revision is parsed or
        # analyzed. The job revision is only a fallback before the first result.
        target = analysis[0] if analysis else active[0] if active else None
        try:
            return self._resolve_ir(db, owner, sid, target)
        except IRSnapshotUnavailable:
            # Old rows with missing snapshots remain an explicit coverage gap.
            return self._resolve_ir(db, owner, sid)

    def session_record(
        self, owner: str, sid: str, source_revision: str | None = None
    ) -> dict[str, Any]:
        with self.domain.connect() as db:
            db.execute("BEGIN")
            return self._resolve_ir(db, owner, sid, source_revision)

    def save_analysis(
        self,
        owner: str,
        sid: str,
        source_revision: str,
        value: dict[str, Any],
        expected_revision: str | None = None,
    ) -> str:
        revision = uuid.uuid4().hex
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT source_revision FROM semantic_sessions WHERE owner=? AND id=?", (owner, sid)
            ).fetchone()
            if not current or current[0] != source_revision:
                raise ValueError("Source changed during analysis; result is stale")
            previous = db.execute(
                "SELECT revision FROM semantic_analyses WHERE owner=? AND session=?", (owner, sid)
            ).fetchone()
            if (
                expected_revision is not None
                and (previous[0] if previous else "") != expected_revision
            ):
                raise ValueError("Analysis changed during processing; human edits preserved")
            db.execute(
                "INSERT OR REPLACE INTO semantic_analyses VALUES(?,?,?,?,?,?,?)",
                (
                    owner,
                    sid,
                    revision,
                    source_revision,
                    "complete",
                    json.dumps(value, ensure_ascii=False),
                    stamp(),
                ),
            )
        return revision

    def _measure_operations(
        self,
        owner: str,
        record: dict[str, Any],
        operations: list[dict[str, Any]],
        contributions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        selected = [
            c
            for c in contributions
            if c["record"]["collector"] == record["collector"]
            and c["record"]["source"] == record["source"]
        ]
        usage_available = any(c["record"]["kind"] == "usage" for c in selected)
        interaction_availability = next(
            (
                item["interaction_availability"]
                for item in selected
                if "interaction_availability" in item
            ),
            self.domain.interaction_availability(
                sum(item["record"]["kind"] == "request" for item in selected)
            ),
        )
        zero = dict.fromkeys(COUNTERS, 0)
        for operation in operations:
            operation["metrics"] = total_metrics([zero]) if selected else total_metrics([])
            operation["attribution"] = {"exact_records": 0, "estimated_records": 0, "methods": {}}
            location = operation.get("location") or {}
            operation["source"] = {
                "line": location.get("source_line"),
                "path": record.get("source_name", "session.jsonl"),
            }
            if not operation.get("timestamp") and operation.get("timestamp_ms") is not None:
                operation["timestamp"] = datetime.fromtimestamp(
                    operation["timestamp_ms"] / 1000, UTC
                ).isoformat()
        # Source-line proximity is an attribution estimate, never proof of a call boundary.
        line_nodes = sorted(
            (int((o.get("location") or {}).get("source_line") or 0), i)
            for i, o in enumerate(operations)
        )
        keys = [pair[0] for pair in line_nodes]
        call_nodes: dict[str, list[int]] = {}
        source_nodes: dict[int, list[int]] = {}
        for index, operation in enumerate(operations):
            if operation.get("call_id"):
                call_nodes.setdefault(operation["call_id"], []).append(index)
        for source_line, index in line_nodes:
            source_nodes.setdefault(source_line, []).append(index)
        exact = estimated = unassigned = 0
        for contribution in selected:
            event = contribution["record"]
            if not operations:
                unassigned += 1
                continue
            matches = call_nodes.get(event.get("call"), [])
            line = int(event.get("source_line") or 0)
            precise = len(matches) == 1
            method = "call_id" if precise else "ambiguous_call_id"
            if not matches:
                same_line = source_nodes.get(line, []) if line > 0 else []
                if len(same_line) == 1:
                    matches, precise, method = same_line, True, "source_line"
                else:
                    position = bisect.bisect_right(keys, line) - 1
                    matches = [line_nodes[max(0, position)][1]]
                    method = (
                        "preceding_source_line"
                        if position >= 0 and line > 0
                        else "unknown_location"
                    )
            target = operations[matches[0]]
            attribution = target["attribution"]
            key = "exact_records" if precise else "estimated_records"
            attribution[key] += 1
            attribution["methods"][method] = attribution["methods"].get(method, 0) + 1
            exact += int(precise)
            estimated += int(not precise)
            metrics = {
                key: value
                for key, value in contribution.items()
                if key not in {"record", "id", "name"}
            }
            metrics["estimated_usage_records"] = int(not precise and event["kind"] == "usage")
            target["metrics"] = total_metrics([target["metrics"], metrics])
        if not usage_available:
            for operation in operations:
                for key in (
                    "input",
                    "output",
                    "cached",
                    "cache_write",
                    "reasoning",
                    "calls",
                    "recorded_tokens",
                    "known_subtotal_usd",
                    "priced_calls",
                    "unpriced_calls",
                    "unknown_usage",
                ):
                    operation["metrics"][key] = None
                operation["metrics"]["cost_status"] = "unknown"
                operation["metrics"]["estimated_usd"] = None
        for operation in operations:
            self.domain.apply_interaction_availability(
                operation["metrics"], interaction_availability
            )
        return {
            "interaction_availability": interaction_availability,
            "ledger_available": bool(selected),
            "usage_available": usage_available,
            "exact_records": exact,
            "estimated_records": estimated,
            "unassigned_records": unassigned,
        }

    def _detail_revision(
        self, owner: str, sid: str, source_revision: str | None
    ) -> tuple[Any, ...] | None:
        """Read cheap authority heads, never source/IR bodies or request traces."""
        with self.domain.connect() as db:
            db.execute("BEGIN")
            session = db.execute(
                "SELECT collector,source,source_revision,updated FROM semantic_sessions "
                "WHERE owner=? AND id=?",
                (owner, sid),
            ).fetchone()
            if session is None:
                return None
            job = db.execute(
                "SELECT id,status,updated FROM semantic_jobs WHERE owner=? AND session=? "
                "AND kind='analyze' ORDER BY created DESC LIMIT 1",
                (owner, sid),
            ).fetchone()
            # Active progress and failed-job recovery eligibility are always read fresh.
            if job and job["status"] != "complete":
                return None
            heads = [tuple(session), tuple(job) if job else None]
            for query, params in (
                (
                    "SELECT revision,source_revision,updated FROM semantic_analyses "
                    "WHERE owner=? AND session=?",
                    (owner, sid),
                ),
                (
                    "SELECT generation,received_bytes,source_bytes,updated FROM source_archives "
                    "WHERE owner=? AND collector=? AND source=?",
                    (owner, *tuple(session)[:2]),
                ),
                (
                    "SELECT revision,read_bytes,source_bytes,errors,unknown,received FROM sources "
                    "WHERE owner=? AND collector=? AND source=?",
                    (owner, *tuple(session)[:2]),
                ),
                (
                    "SELECT updated FROM semantic_session_metadata WHERE owner=? AND session=?",
                    (owner, sid),
                ),
            ):
                row = db.execute(query, params).fetchone()
                heads.append(tuple(row) if row else None)
            heads.append((self.domain.ledger_revision(db),))
        return (owner, sid, source_revision, *heads)

    def detail(
        self,
        owner: str,
        sid: str,
        contributions: list[dict[str, Any]] | None = None,
        *,
        source_revision: str | None = None,
    ) -> dict[str, Any]:
        # Explicit contributions are used by isolated measurement callers and must
        # never be confused with the canonical ledger revision.
        if contributions is None:
            for _ in range(2):
                key = self._detail_revision(owner, sid, source_revision)
                if key is None:
                    break
                result: dict[str, Any] = self._detail_cache.get(
                    key, lambda: self._detail(owner, sid, source_revision=source_revision)
                )
                if key == self._detail_revision(owner, sid, source_revision):
                    return result
        return self._detail(owner, sid, contributions, source_revision=source_revision)

    def operation(
        self, owner: str, sid: str, oid: str, *, source_revision: str | None = None
    ) -> dict[str, Any]:
        detail = self.detail(owner, sid, source_revision=source_revision)
        for operation in detail["operations"]:
            if operation["id"] == oid:
                return cast(dict[str, Any], operation)
        raise ValueError("Unknown operation")

    def _detail(
        self,
        owner: str,
        sid: str,
        contributions: list[dict[str, Any]] | None = None,
        *,
        source_revision: str | None = None,
    ) -> dict[str, Any]:
        try:
            with self.domain.connect() as db:
                db.execute("BEGIN")
                latest = db.execute(
                    "SELECT source_revision FROM semantic_sessions WHERE owner=? AND id=?",
                    (owner, sid),
                ).fetchone()
                if latest is None:
                    raise IRSnapshotUnavailable("Unknown session")
                latest_revision = latest["source_revision"]
                record = self._display_ir(db, owner, sid, source_revision)
        except IRSnapshotUnavailable:
            if source_revision:
                raise
            listing = self.sessions(owner)
            session = next((item for item in listing["sessions"] if item["id"] == sid), None)
            if session is None:
                raise
            with self.domain.connect() as db:
                source = next(
                    (
                        dict(row)
                        for row in db.execute(
                            "SELECT collector,source FROM sources WHERE owner=?", (owner,)
                        )
                        if self.session_id(row["collector"], row["source"]) == sid
                    ),
                    None,
                )
            values = (
                contributions
                if contributions is not None
                else (
                    self.domain.source_contributions(owner, source["collector"], source["source"])
                    if source
                    else []
                )
            )
            metrics = total_metrics(values)
            metrics["collection_status"] = session["collection"]["status"]
            self.domain.apply_interaction_availability(metrics, session["interaction_availability"])
            session = {**session, "metrics": metrics}
            return {
                "session": session,
                "status": "partial",
                "message": "仅有用量记录，需同步执行内容后分析。",
                "analysis_revision": "",
                "tasks": [],
                "operations": [],
                "unassigned_operation_ids": [],
                "coverage": {
                    "content_available": False,
                    "collection": session["collection"],
                    "interaction_availability": session["interaction_availability"],
                    "warnings": session["coverage"]["warnings"],
                },
            }
        parsed = json.loads(record["body"])
        metadata = extract_metadata(parsed, record["title"])
        operations = parsed.get("operations", [])
        with self.domain.connect() as db:
            source = db.execute(
                "SELECT generation,received_bytes FROM source_archives "
                "WHERE owner=? AND collector=? AND source=?",
                (owner, record["collector"], record["source"]),
            ).fetchone()
            current_source_revision = archive_revision(source)
            source_pending = current_source_revision != latest_revision
            collection = collection_progress(
                db.execute(
                    "SELECT read_bytes,source_bytes,errors,unknown FROM sources "
                    "WHERE owner=? AND collector=? AND source=?",
                    (owner, record["collector"], record["source"]),
                ).fetchone()
            )
            analysis = db.execute(
                "SELECT * FROM semantic_analyses WHERE owner=? AND session=?", (owner, sid)
            ).fetchone()
            job = db.execute(
                "SELECT j.*,e.job AS execution_job,COALESCE((SELECT max(generation) "
                "FROM semantic_job_resumes r WHERE r.job=j.id),0) AS resume_generation "
                "FROM semantic_jobs j LEFT JOIN semantic_job_execution e ON e.job=j.id "
                "WHERE j.owner=? AND j.session=? AND j.kind='analyze' "
                "ORDER BY j.created DESC LIMIT 1",
                (owner, sid),
            ).fetchone()
            progress_row = (
                db.execute(
                    "SELECT body FROM semantic_job_progress WHERE job=?", (job["id"],)
                ).fetchone()
                if job
                else None
            )
            progress = json.loads(progress_row[0]) if progress_row else {}
            resume = self.resume_state(db, dict(job) if job else None, progress, latest_revision)
        # A pending append does not invalidate the saved analysis snapshot, but newer
        # ledger records must never be estimated onto its last operation. Attribute
        # only records the displayed snapshot can prove it contains, and count the
        # rest separately so a retained result keeps its measured cost.
        historical_snapshot = record["source_revision"] != latest_revision
        if contributions is None:
            contributions = self.domain.source_contributions(
                owner, record["collector"], record["source"]
            )
        with self.domain.connect() as db:
            head = db.execute(
                "SELECT s.source_revision,a.generation,a.received_bytes "
                "FROM semantic_sessions s "
                "LEFT JOIN source_archives a ON a.owner=s.owner AND a.collector=s.collector "
                "AND a.source=s.source WHERE s.owner=? AND s.id=?",
                (owner, sid),
            ).fetchone()
            if head is not None:
                resume = self.resume_state(
                    db, dict(job) if job else None, progress, head["source_revision"]
                )
        if head is None:
            raise ValueError("Session changed during snapshot measurement")
        latest_revision = head["source_revision"]
        current_source_revision = archive_revision(head) if head["generation"] is not None else None
        source_pending = current_source_revision != latest_revision
        historical_snapshot = record["source_revision"] != latest_revision
        ledger_available = any(
            item["record"]["collector"] == record["collector"]
            and item["record"]["source"] == record["source"]
            for item in contributions
        )
        snapshot_scope = "current"
        excluded_records = 0
        watermark = snapshot_line_watermark(parsed, head["generation"])
        if record["source_revision"] != current_source_revision:
            owned = [
                item
                for item in contributions
                if item["record"]["collector"] == record["collector"]
                and item["record"]["source"] == record["source"]
            ]
            if watermark is None:
                snapshot_scope = "unavailable"
                excluded_records = len(owned)
                owned = []
            else:
                snapshot_scope = "bounded"
                owned = [
                    item
                    for item in owned
                    if 0 < int(item["record"].get("source_line") or 0) <= watermark
                ]
                excluded_records = sum(
                    1
                    for item in contributions
                    if item["record"]["collector"] == record["collector"]
                    and item["record"]["source"] == record["source"]
                ) - len(owned)
            contributions = owned
        attribution = self._measure_operations(owner, record, operations, contributions)
        attribution["snapshot_scope"] = snapshot_scope
        attribution["snapshot_line_watermark"] = watermark if snapshot_scope != "current" else None
        attribution["excluded_records"] = excluded_records
        attribution["ledger_available"] = attribution["ledger_available"] or ledger_available
        analysis_matches_parsed = (
            analysis is not None and analysis["source_revision"] == latest_revision
        )
        analysis_snapshot_available = (
            analysis is not None and analysis["source_revision"] == record["source_revision"]
        )
        current_analysis = (
            analysis_matches_parsed and analysis_snapshot_available and not source_pending
        )
        value = json.loads(analysis["body"]) if analysis_snapshot_available else {"tasks": []}
        status = "complete" if current_analysis else "stale" if analysis else "not_started"
        reanalysis = None
        if (
            job
            and job["status"] in {"queued", "running", "failed"}
            and job["source_revision"] != record["source_revision"]
        ):
            # A job for another revision never replaces the result on screen.
            reanalysis = {
                "status": job["status"],
                "source_revision": job["source_revision"],
                "progress": progress,
            }
        if (
            job
            and job["source_revision"] == record["source_revision"]
            and job["status"] in {"queued", "running", "failed"}
        ):
            status = job["status"]
            if not analysis_snapshot_available and progress:
                value["provenance"] = {
                    **progress,
                    "chunks": progress.get("total_chunks"),
                    "provisional": True,
                }
        else:
            progress = {}
        tasks = value.get("tasks", [])
        by_id = {o["id"]: o for o in operations}
        memberships: dict[str, str] = {}
        for task in tasks:
            for oid in task.get("operation_ids", []):
                if oid in by_id:
                    memberships[oid] = task["id"]
        for operation in operations:
            operation["task_id"] = memberships.get(operation["id"])

        task_by_id = {task["id"]: task for task in tasks}
        children: dict[str, list[str]] = {}
        for task in tasks:
            children.setdefault(task.get("parent_id"), []).append(task["id"])
        member_cache: dict[str, set[str]] = {}

        def members(task_id: str, visiting: set[str]) -> set[str]:
            if task_id in visiting:
                raise ValueError("Task hierarchy contains a cycle")
            if task_id in member_cache:
                return member_cache[task_id]
            task = task_by_id[task_id]
            result = set(task.get("operation_ids", []))
            for child in children.get(task_id, []):
                result.update(members(child, visiting | {task_id}))
            member_cache[task_id] = result
            return result

        operation_index = {operation["id"]: index for index, operation in enumerate(operations)}
        for task in tasks:
            ids = members(task["id"], set())
            task["metrics"] = total_metrics([by_id[i]["metrics"] for i in ids if i in by_id])
            task["metrics"]["collection_status"] = collection["status"]
            task["segments"] = []
            previous = -2
            for index in sorted(operation_index[oid] for oid in ids if oid in operation_index):
                operation = operations[index]
                if index != previous + 1:
                    task["segments"].append(
                        {
                            "start_operation_id": operation["id"],
                            "end_operation_id": operation["id"],
                            "start_time": operation.get("timestamp"),
                            "end_time": operation.get("timestamp"),
                        }
                    )
                else:
                    task["segments"][-1].update(
                        end_operation_id=operation["id"], end_time=operation.get("timestamp")
                    )
                previous = index
        metrics = total_metrics([o["metrics"] for o in operations])
        if not operations:
            metrics = total_metrics(
                [
                    item
                    for item in contributions
                    if item["record"]["collector"] == record["collector"]
                    and item["record"]["source"] == record["source"]
                ]
            )
        metrics["collection_status"] = collection["status"]
        self.domain.apply_interaction_availability(metrics, attribution["interaction_availability"])
        for operation in operations:
            operation["metrics"]["collection_status"] = collection["status"]
        parser_notes = list(parsed.get("warnings", []))
        generic_notes = (
            "upstream IR usage zero does not establish source availability;",
            "upstream parser accepts complete snapshots,",
            "source_records are retained for provenance,",
        )
        warnings = [note for note in parser_notes if not str(note).startswith(generic_notes)]
        if historical_snapshot:
            warnings.append("当前展示已保存分析的历史快照，最新内容已另行解析；不会自动重新分析。")
        elif source_pending:
            warnings.append(
                "源记录有追加，尚未重新解析。当前展示上次解析结果及其已有分析；不会自动重新分析。"
            )
        if attribution["snapshot_scope"] == "bounded":
            warnings.append(
                "只在快照自身的记录水位以内归属账本记录；新增记录的用量不计入当前任务开销。"
            )
        elif attribution["snapshot_scope"] == "unavailable":
            warnings.append(
                "源内容已更换版本，历史快照无法证明与当前账本对应；"
                "执行用量与任务开销保持未知，分析调用开销单独保留。"
            )
        if reanalysis is not None:
            warnings.append("新版本的任务分析尚未完成；完成后会替换当前展示。")
        if analysis and not analysis_snapshot_available:
            warnings.append(
                "当前展示快照与已有分析的输入不同，任务树暂不可用；不会用其他版本操作替代。"
            )
        parser_coverage = parsed.get("coverage") or {}
        if parser_coverage.get("quarantined_records"):
            warnings.append("部分损坏记录已隔离，原始字节保留；分析仅覆盖有效记录。")
        if not attribution["ledger_available"]:
            warnings.append("尚未收到对应的用量账本，开销和人类投入保持未知。")
        elif not attribution["usage_available"]:
            warnings.append("尚未收到模型用量，token和费用保持未知。")
        if not attribution["interaction_availability"]["available"]:
            warnings.append("尚未收到请求交互测量，人类交互次数和输入字数保持未知。")
        if attribution["estimated_records"]:
            warnings.append("部分用量按源记录位置估计归属，任务级开销不是精确调用对齐。")
        return {
            "session": {
                **metadata,
                "id": sid,
                "title": record["title"],
                "agent": record["agent"],
                "project": "",
                "metrics": metrics,
            },
            "status": status,
            "progress": progress,
            "resume": resume,
            "has_analysis": analysis is not None,
            "analysis_current": current_analysis,
            "analysis_matches_parsed": analysis_matches_parsed,
            "analysis_snapshot_available": analysis_snapshot_available,
            "historical_snapshot": historical_snapshot,
            "current_parsed_source_revision": latest_revision,
            "source_pending": source_pending,
            "reanalysis": reanalysis,
            "current_source_revision": current_source_revision,
            "analysis_source_revision": analysis["source_revision"] if analysis else None,
            "message": job["message"] if job and status == "failed" else "",
            "analysis_revision": analysis["revision"] if analysis else "",
            "source_revision": record["source_revision"],
            "generated_at": analysis["updated"] if analysis else None,
            "tasks": tasks,
            "operations": operations,
            "unassigned_operation_ids": [o["id"] for o in operations if o["id"] not in memberships],
            "provenance": value.get("provenance", {}),
            "analysis_cost": self.domain.analysis_cost(owner, value.get("provenance", {})),
            "coverage": {
                "parser": parsed.get("parser"),
                "normalization": {
                    "worker_version": parsed.get("worker_version"),
                    "schema": parsed.get("schema"),
                    "recorded_measurement_schema": parsed.get("recorded_measurement_schema"),
                },
                "parser_coverage": parser_coverage,
                "parser_notes": parser_notes,
                "warnings": warnings,
                "content_available": True,
                "ledger_available": attribution["ledger_available"],
                "usage_available": attribution["usage_available"],
                "interaction_availability": attribution["interaction_availability"],
                "attribution": attribution,
                "collection": collection,
            },
        }

    def task_query(
        self,
        owner: str,
        *,
        batch_id: str = "",
        session_id: str = "",
        q: str = "",
        cwd: str = "",
        depth: int | None = None,
        limit: int = 100,
        cursor: str = "",
    ) -> dict[str, Any]:
        """Query saved task structure without loading IR, recalculating measures or models."""
        if not 1 <= limit <= 500 or (depth is not None and not 0 <= depth <= 100):
            raise ValueError("Invalid task query page or depth")
        if len(q) > 1000 or len(cwd) > 4096:
            raise ValueError("Task query filter too long")
        with self.domain.connect() as db:
            db.execute("BEGIN")
            if (
                batch_id
                and not db.execute(
                    "SELECT 1 FROM semantic_batches WHERE id=? AND owner=?", (batch_id, owner)
                ).fetchone()
            ):
                raise PermissionError("Unknown analysis batch")
            rows = db.execute(
                "SELECT a.session,a.revision,a.source_revision,a.updated,a.body,"
                "s.title,s.agent,s.source_revision AS parsed_revision,m.body AS metadata,"
                "j.source_revision AS batch_revision "
                "FROM semantic_analyses a JOIN semantic_sessions s "
                "ON s.owner=a.owner AND s.id=a.session "
                "LEFT JOIN semantic_session_metadata m ON m.owner=a.owner AND m.session=a.session "
                "LEFT JOIN semantic_batch_items i ON i.session=a.session AND i.batch=? "
                "LEFT JOIN semantic_jobs j ON j.id=i.job AND j.owner=a.owner "
                "WHERE a.owner=? AND (?='' OR a.session=?) "
                "AND (?='' OR i.batch IS NOT NULL) ORDER BY a.session",
                (batch_id, owner, session_id, session_id, batch_id),
            ).fetchall()
        heads = [
            (
                row["session"],
                row["revision"],
                row["source_revision"],
                row["metadata"],
                row["parsed_revision"],
                row["batch_revision"],
                row["title"],
                row["agent"],
            )
            for row in rows
        ]
        revision = digest(json.dumps([owner, batch_id, session_id, q, cwd, depth, heads]))
        offset = 0
        if cursor:
            parts = cursor.split(":")
            if len(parts) != 2 or parts[0] != revision or not parts[1].isdecimal():
                raise ValueError("Task query changed; restart pagination")
            offset = int(parts[1])
        items = []
        skipped = []
        for row in rows:
            # A later reanalysis must not silently substitute the original batch result.
            if batch_id and row["batch_revision"] != row["source_revision"]:
                skipped.append({"session_id": row["session"], "reason": "batch_snapshot_replaced"})
                continue
            meta = read_metadata(json.loads(row["metadata"])) if row["metadata"] else {}
            directory = str(meta.get("cwd") or "")
            if cwd and directory != cwd and not directory.startswith(cwd.rstrip("/") + "/"):
                continue
            tasks = json.loads(row["body"]).get("tasks", [])
            by_id = {task["id"]: task for task in tasks}
            for task in tasks:
                ancestors = []
                parent = task.get("parent_id")
                while parent and parent in by_id:
                    if parent == task["id"] or parent in ancestors:
                        raise ValueError("Task hierarchy contains a cycle")
                    ancestors.append(parent)
                    parent = by_id[parent].get("parent_id")
                ancestors.reverse()
                if depth is not None and len(ancestors) != depth:
                    continue
                title = str(task.get("title") or "")
                if (
                    q
                    and q.casefold()
                    not in " ".join(
                        [task["id"], title, *[str(by_id[a].get("title") or "") for a in ancestors]]
                    ).casefold()
                ):
                    continue
                items.append(
                    {
                        "id": task["id"],
                        "title": title,
                        "parent_id": task.get("parent_id"),
                        "ancestor_ids": ancestors,
                        "depth": len(ancestors),
                        "direct_operation_count": len(set(task.get("operation_ids", []))),
                        "session_id": row["session"],
                        "session_title": meta.get("display_title") or row["title"],
                        "cwd": meta.get("cwd"),
                        "agent": row["agent"],
                        "started_at": meta.get("started_at"),
                        "analysis_revision": row["revision"],
                        "source_revision": row["source_revision"],
                        "matches_latest_parsed": row["source_revision"] == row["parsed_revision"],
                    }
                )
        page = items[offset : offset + limit]
        return {
            "items": page,
            "total": len(items),
            "query_revision": revision,
            "next_cursor": (
                f"{revision}:{offset + len(page)}" if offset + len(page) < len(items) else None
            ),
            "skipped_sessions": skipped,
            "measurement_scope": "saved_task_structure_only",
            "metrics_included": False,
        }

    @staticmethod
    def _directory_page(
        value: dict[str, Any], scope: str, limit: int, offset: int = 0
    ) -> dict[str, Any]:
        rows = value["sessions"]
        page = rows[offset : offset + limit] if limit else rows[offset:]
        more = offset + len(page) < len(rows)
        cursor = None
        if more:
            payload = json.dumps(
                {
                    "offset": offset + len(page),
                    "snapshot": value["listing_snapshot_id"],
                    "scope": scope,
                }
            )
            cursor = "v1." + base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
        return {**value, "sessions": page, "next_cursor": cursor}

    def sessions(
        self,
        owner: str,
        project: str = "",
        since: str = "",
        until: str = "",
        analysis_status: str = "all",
        cwd: str = "",
        sort: str = "last_activity_desc",
        q: str = "",
        limit: int = 0,
        cursor: str = "",
        cwd_presence: str = "all",
    ) -> dict[str, Any]:
        allowed = {"all", "analyzed", "not_started", "busy", "failed", "stale"}
        if analysis_status not in allowed or sort not in {
            "last_activity_desc",
            "started_desc",
            "directory",
        }:
            raise ValueError("Unsupported session filter or sort")
        if cwd_presence not in {"all", "unknown"} or (cwd and cwd_presence == "unknown"):
            raise ValueError("Invalid directory presence scope")
        if not 0 <= limit <= 1000:
            raise ValueError("Invalid session page")
        scope = digest(
            json.dumps(
                [
                    project,
                    since,
                    until,
                    analysis_status,
                    cwd,
                    sort,
                    q.casefold(),
                    limit,
                    cwd_presence,
                ]
            )
        )
        if cursor:
            try:
                if not cursor.startswith("v1.") or len(cursor) > 512:
                    raise ValueError("Invalid session cursor")
                token = json.loads(
                    base64.urlsafe_b64decode(cursor[3:] + "=" * (-len(cursor[3:]) % 4))
                )
                offset, snapshot = token["offset"], token["snapshot"]
                if type(offset) is not int or offset < 1 or token["scope"] != scope:
                    raise ValueError("Session cursor scope changed")
                if not isinstance(snapshot, str) or len(snapshot) != 32:
                    raise ValueError("Invalid session snapshot")
            except (ValueError, KeyError, TypeError) as error:
                raise SessionCursorExpired("会话列表快照已失效，请刷新列表。") from error

            def expired() -> Any:
                raise SessionCursorExpired("会话列表快照已失效，请刷新列表。")

            cached = self._directory_cache.get((owner, scope, snapshot), expired)
            return self._directory_page(cached, scope, limit, offset)
        from trajectory.product.session_directory import source_directory

        with self.domain.connect() as db:
            db.execute("BEGIN")
            groups = {
                self.session_id(item["record"]["collector"], item["record"]["source"]): item
                for item in source_directory(db, owner)
            }
            source_rows = {
                (row["collector"], row["source"]): dict(row)
                for row in db.execute("SELECT * FROM sources WHERE owner=?", (owner,))
            }
            ledger_sources = {key: collection_progress(row) for key, row in source_rows.items()}
            records = {
                row["id"]: dict(row)
                for row in db.execute(
                    "SELECT id,title,agent,collector,source,source_revision,updated "
                    "FROM semantic_sessions WHERE owner=?",
                    (owner,),
                )
            }
            metadata = {
                row["session"]: read_metadata(json.loads(row["body"]))
                for row in db.execute(
                    "SELECT session,body FROM semantic_session_metadata WHERE owner=?", (owner,)
                )
            }
            analyses = {
                row["session"]: dict(row)
                for row in db.execute(
                    "SELECT session,source_revision,updated FROM semantic_analyses WHERE owner=?",
                    (owner,),
                )
            }
            jobs = [
                dict(row)
                for row in db.execute(
                    "SELECT session,source_revision,status,message FROM semantic_jobs "
                    "WHERE owner=? AND kind='analyze' ORDER BY created",
                    (owner,),
                )
            ]
            archive_rows = list(
                db.execute(
                    "SELECT collector,source,generation,received_bytes,"
                    "received_bytes AS read_bytes,"
                    "source_bytes,0 AS errors,0 AS unknown FROM source_archives WHERE owner=?",
                    (owner,),
                )
            )
            archive_revisions = {
                (row["collector"], row["source"]): archive_revision(row) for row in archive_rows
            }
            archives = {
                (row["collector"], row["source"]): collection_progress(row) for row in archive_rows
            }
        native_to_id = {
            value["native_session_id"]: sid
            for sid, value in metadata.items()
            if value.get("native_session_id")
        }
        recent_jobs = {row["session"]: row for row in jobs}
        items = []
        projects: dict[str, str] = {}
        for sid in groups.keys() | records.keys():
            own = groups.get(sid)
            event = own["record"] if own else {}
            record, analysis, meta = (
                records.get(sid, {}),
                analyses.get(sid, {}),
                metadata.get(sid, {}),
            )
            has_analysis = bool(analysis)
            current_source_revision = archive_revisions.get(
                (record.get("collector"), record.get("source"))
            )
            source_pending = bool(record) and current_source_revision != record.get(
                "source_revision"
            )
            current = (
                has_analysis
                and not source_pending
                and analysis["source_revision"] == record.get("source_revision")
            )
            status = (
                "complete"
                if current
                else "stale" if has_analysis else "not_started" if record else "partial"
            )
            job = recent_jobs.get(sid)
            if (
                job
                and job["source_revision"] == record.get("source_revision")
                and job["status"] in {"queued", "running", "failed"}
            ):
                status = job["status"]
            measured_time = own["last_timestamp"] if own else ""
            last = meta.get("last_activity_at") or measured_time or None
            key = (
                record.get("collector") or event.get("collector"),
                record.get("source") or event.get("source"),
            )
            collection = ledger_sources.get(key) or archives.get(key) or collection_progress(None)
            interaction_availability = (
                self.domain.interaction_availability(own["request_records"], source_rows.get(key))
                if own
                else self.domain.interaction_availability(0)
            )
            parent_native = meta.get("parent_native_session_id")
            item = {
                "id": sid,
                "title": record.get("title") or str(event.get("session", sid)),
                "display_title": meta.get("display_title")
                or ("会话 " + str(meta.get("native_session_id") or sid)[:8]),
                "cwd": meta.get("cwd"),
                "started_at": meta.get("started_at"),
                "last_activity_at": last,
                "first_user_message": meta.get("first_user_message"),
                "summary": meta.get("summary"),
                "native_session_id": meta.get("native_session_id") or event.get("session"),
                "parent_session_id": native_to_id.get(parent_native),
                "parent_native_session_id": parent_native,
                "agent_path": meta.get("agent_path"),
                "agent": record.get("agent") or event.get("ecosystem", "unknown"),
                "project": event.get("project", "unassigned"),
                "project_name": event.get("project_name", "未归属"),
                "updated_at": record.get("updated") or measured_time,
                "analysis_status": status,
                "has_analysis": has_analysis,
                "analysis_current": current,
                "source_pending": source_pending,
                "source_revision": record.get("source_revision"),
                "current_source_revision": current_source_revision,
                "analysis_source_revision": analysis.get("source_revision"),
                "content_available": bool(record),
                "collection": collection,
                "interaction_availability": interaction_availability,
                "coverage": {
                    "interaction_availability": interaction_availability,
                    "warnings": (
                        []
                        if interaction_availability["available"]
                        else ["尚未收到请求交互测量，人类交互次数和输入字数保持未知。"]
                    ),
                },
            }
            projects[str(item["project"])] = str(item["project_name"])
            if project and item["project"] != project:
                continue
            day = (last or "")[:10]
            if (since or until) and (not day or (since and day < since) or (until and day > until)):
                continue
            haystack = " ".join(
                str(item.get(k) or "")
                for k in (
                    "id",
                    "parent_session_id",
                    "agent",
                    "project",
                    "project_name",
                    "title",
                    "display_title",
                    "cwd",
                    "first_user_message",
                    "summary",
                    "native_session_id",
                    "agent_path",
                )
            ).casefold()
            if q and q.casefold() not in haystack:
                continue
            items.append(item)
        directory_items = items
        directories = sorted({str(item["cwd"]) for item in items if item["cwd"]})
        if cwd_presence == "unknown":
            items = [item for item in items if not item["cwd"]]
        if cwd:
            items = [
                i
                for i in items
                if i["cwd"] == cwd or str(i["cwd"] or "").startswith(cwd.rstrip("/") + "/")
            ]

        def matches(item: dict[str, Any], value: str) -> bool:
            if value == "all":
                return True
            if value == "analyzed":
                return bool(item["has_analysis"])
            if value == "busy":
                return item["analysis_status"] in {"queued", "running"}
            if value == "stale":
                return bool(item["has_analysis"]) and not item["analysis_current"]
            if value == "not_started":
                return not item["has_analysis"] and item["analysis_status"] in {
                    "not_started",
                    "partial",
                }
            return str(item["analysis_status"]) == value

        facet_counts: dict[str | None, int] = {}
        for item in directory_items:
            if matches(item, analysis_status):
                directory = item["cwd"] or None
                facet_counts[directory] = facet_counts.get(directory, 0) + 1
        directory_facets = [
            {"cwd": directory, "count": count}
            for directory, count in sorted(
                facet_counts.items(), key=lambda pair: pair[0] or "\uffff"
            )
        ]
        counts = {value: sum(matches(item, value) for item in items) for value in allowed}
        items = [i for i in items if matches(i, analysis_status)]
        items.sort(key=lambda i: (str(i.get("last_activity_at") or ""), i["id"]), reverse=True)
        if sort == "started_desc":
            items.sort(key=lambda i: str(i.get("started_at") or ""), reverse=True)
        elif sort == "directory":
            items.sort(key=lambda i: str(i.get("cwd") or "\uffff").casefold())
        total = len(items)
        value = {
            "sessions": items,
            "metrics_included": False,
            "listing_snapshot_id": uuid.uuid4().hex,
            "total": total,
            "status_counts": counts,
            "directories": directories,
            "directory_facets": directory_facets,
            "directory_facets_scope": "owner_project_dates_search_status_before_cwd_and_pagination",
            "projects": [
                {"id": key, "name": name}
                for key, name in sorted(projects.items(), key=lambda pair: (pair[1], pair[0]))
            ],
            "coverage": {
                "content_sessions": len(records),
                "total_sessions": total,
                "message": "历史仅用量记录需补传执行内容后才能分段。",
            },
        }
        if limit and total > limit:
            if (
                len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
                > self._directory_cache.max_bytes
            ):
                raise ValueError("目录范围过大，请缩小筛选范围后分页。")
            self._directory_cache.get((owner, scope, value["listing_snapshot_id"]), lambda: value)
        return self._directory_page(value, scope, limit)

    def evidence(
        self, owner: str, sid: str, operation_id: str, *, source_revision: str | None = None
    ) -> dict[str, Any]:
        with self.domain.connect() as db:
            db.execute("BEGIN")
            record = self._display_ir(db, owner, sid, source_revision)
        parsed = json.loads(record["body"])
        operation = next((o for o in parsed.get("operations", []) if o["id"] == operation_id), None)
        if operation is None:
            raise ValueError("Unknown operation")
        location = operation.get("location") or {}
        start, end = location.get("byte_start"), location.get("byte_end")
        if not isinstance(start, int) or not isinstance(end, int):
            return {"available": False, "message": "源记录位置不明确，保留原文预览。", "text": ""}
        if start < 0 or end <= start:
            return {"available": False, "message": "源记录位置无效，无法读取原文。", "text": ""}
        limit = min(end, start + 256 * 1024)
        with self.domain.connect() as db:
            # Read the archive version and bytes in one snapshot. A pending generation
            # must never be interpreted using offsets from an older parsed session.
            db.execute("BEGIN")
            source = db.execute(
                "SELECT * FROM source_archives WHERE owner=? AND collector=? AND source=?",
                (owner, record["collector"], record["source"]),
            ).fetchone()
            snapshot = parsed.get("source_snapshot") or {}
            snapshot_size = snapshot.get("received_bytes")
            # Existing worker output records complete_bytes. Accept it only when
            # its exact cursor under the current immutable generation reproduces
            # the stored revision; a trailing partial record cannot pass this test.
            if not snapshot and source:
                snapshot_size = parsed.get("complete_bytes")
                snapshot = {"generation": source["generation"], "received_bytes": snapshot_size}
            historical_prefix = bool(
                source
                and isinstance(snapshot_size, int)
                and not isinstance(snapshot_size, bool)
                and snapshot_size >= end
                and source["received_bytes"] >= snapshot_size
                and snapshot.get("generation") == source["generation"]
                and archive_revision(snapshot) == record["source_revision"]
            )
            if archive_revision(source) != record["source_revision"] and not historical_prefix:
                return {
                    "available": False,
                    "message": "源记录已更新，等待重新解析后查看原文。",
                    "text": "",
                }
            if end > source["received_bytes"]:
                return {"available": False, "message": "源记录范围尚未完整同步。", "text": ""}
            chunks = db.execute(
                "SELECT start,end,content FROM source_chunks WHERE owner=? "
                "AND collector=? AND source=? AND generation=? "
                "AND end>? AND start<? ORDER BY start",
                (owner, record["collector"], record["source"], source["generation"], start, limit),
            ).fetchall()
        content = b"".join(
            bytes(row["content"])[
                max(0, start - row["start"]) : min(row["end"], limit) - row["start"]
            ]
            for row in chunks
        )
        if len(content) != limit - start:
            return {"available": False, "message": "源记录存在缺口，无法读取完整原文。", "text": ""}
        return {
            "available": True,
            "source_revision": record["source_revision"],
            "current_source_revision": archive_revision(source),
            "snapshot_current": archive_revision(source) == record["source_revision"],
            "text": content.decode("utf-8", errors="replace"),
            "byte_start": start,
            "byte_end": end,
            "truncated": end > limit,
            "source": {"line": location.get("source_line"), "path": source["source_name"]},
        }

    def edit_task(self, owner: str, sid: str, value: TaskEdit) -> dict[str, Any]:
        body = value.model_dump_json() + ":" + sid
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = self.domain._prior(db, owner, value.mutation_id, body)
            if prior:
                return prior
            row = db.execute(
                "SELECT * FROM semantic_analyses WHERE owner=? AND session=?", (owner, sid)
            ).fetchone()
            if not row or row["revision"] != value.analysis_revision:
                raise ValueError("Analysis changed; refresh before editing")
            current = db.execute(
                "SELECT source_revision FROM semantic_sessions WHERE owner=? AND id=?", (owner, sid)
            ).fetchone()
            if not current or current[0] != row["source_revision"]:
                raise ValueError("Source changed; analyze current revision before editing")
            result = json.loads(row["body"])
            tasks = result["tasks"]
            task = next((t for t in tasks if t["id"] == value.task_id), None)
            if not task:
                raise ValueError("Unknown task")
            if value.action == "rename":
                if not value.title or not value.title.strip():
                    raise ValueError("Task title is required")
                task["title"] = value.title.strip()
            elif value.action == "merge":
                other = next((t for t in tasks if t["id"] == value.other_task_id), None)
                if not other or other is task or other.get("parent_id") != task.get("parent_id"):
                    raise ValueError("Merge requires two different sibling tasks")
                parsed = db.execute(
                    "SELECT body FROM semantic_sessions WHERE owner=? AND id=?", (owner, sid)
                ).fetchone()
                order = {
                    operation["id"]: index
                    for index, operation in enumerate(json.loads(parsed[0]).get("operations", []))
                }
                task["operation_ids"] = sorted(
                    set(task.get("operation_ids", []) + other.get("operation_ids", [])),
                    key=order.__getitem__,
                )
                for child in tasks:
                    if child.get("parent_id") == other["id"]:
                        child["parent_id"] = task["id"]
                tasks.remove(other)
            else:
                ids = task.get("operation_ids", [])
                if value.operation_id not in ids or ids.index(value.operation_id) == 0:
                    raise ValueError("Split needs a non-first direct member operation")
                position = ids.index(value.operation_id)
                task["operation_ids"] = ids[:position]
                tasks.append(
                    {
                        "id": uuid.uuid4().hex,
                        "parent_id": task.get("parent_id"),
                        "title": task["title"] + "（后续）",
                        "operation_ids": ids[position:],
                    }
                )
            revision = uuid.uuid4().hex
            provenance = result.setdefault("provenance", {})
            provenance["task_revision"] = revision
            provenance["edited_at"] = stamp()
            if isinstance(provenance.get("profiler"), dict):
                provenance["profiler"]["stale"] = True
                provenance["profiler"]["stale_reason"] = "task_annotations_changed"
            db.execute(
                "UPDATE semantic_analyses SET revision=?,body=?,updated=? "
                "WHERE owner=? AND session=?",
                (revision, json.dumps(result, ensure_ascii=False), stamp(), owner, sid),
            )
            return self.domain._receipt(
                db,
                owner,
                value.mutation_id,
                body,
                "analysis.edit",
                {"session_id": sid, "analysis_revision": revision},
            )
