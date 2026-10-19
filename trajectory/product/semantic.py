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
from typing import TYPE_CHECKING, Any

from trajectory.product.contracts import (
    AnalysisBatchRequest,
    AnalysisRequest,
    SourceChunk,
    TaskEdit,
)
from trajectory.product.session_metadata import VERSION as METADATA_VERSION
from trajectory.product.session_metadata import extract as extract_metadata
from trajectory.product.session_metadata import read as read_metadata

if TYPE_CHECKING:
    from trajectory.product.domain import Domain


def stamp() -> str:
    return datetime.now(UTC).isoformat()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


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
        values = [item[key] for item in items if isinstance(item.get(key), (int, float))]
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


class SemanticStore:
    def __init__(self, domain: Domain):
        self.domain = domain
        with domain.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS source_archives(
                    owner TEXT,collector TEXT,source TEXT,generation TEXT,ecosystem TEXT,
                    source_name TEXT,received_bytes INTEGER,source_bytes INTEGER,updated TEXT,
                    PRIMARY KEY(owner,collector,source));
                CREATE TABLE IF NOT EXISTS source_chunks(
                    owner TEXT,collector TEXT,source TEXT,generation TEXT,start INTEGER,
                    end INTEGER,sha256 TEXT,content BLOB,
                    PRIMARY KEY(owner,collector,source,generation,start));
                CREATE TABLE IF NOT EXISTS semantic_sessions(
                    owner TEXT,id TEXT,collector TEXT,source TEXT,title TEXT,agent TEXT,
                    source_revision TEXT,body TEXT,updated TEXT,
                    PRIMARY KEY(owner,id),UNIQUE(owner,collector,source));
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
        return dict(row) if row else {"generation": None, "next_offset": 0, "source_bytes": 0}

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
    def resume_eligibility(job: dict[str, Any], progress: dict[str, Any], generation: int) -> str:
        if job["kind"] != "analyze" or job["status"] != "failed":
            return "analysis_not_failed"
        if generation >= 3:
            return "resume_limit_reached"
        calls = progress.get("analysis_usage", [])
        if "result uncertain" in job.get("message", "") or any(
            call.get("failed") or call.get("state") in {"prepared", "uncertain"} for call in calls
        ):
            return "prior_call_uncertain"
        if not calls or not (
            calls[-1].get("valid") is False
            and calls[-1].get("receipt_id")
            and isinstance(calls[-1].get("usage"), dict)
            and calls[-1]["usage"]
        ):
            return "received_invalid_result_required"
        if progress.get("state") != "failed":
            return "failed_progress_required"
        return "eligible"

    def resume_state(
        self,
        job: dict[str, Any] | None,
        progress: dict[str, Any],
        current_source_revision: str,
    ) -> dict[str, Any]:
        generation = job.get("resume_generation", 0) if job else 0
        reason = (
            self.resume_eligibility(job, progress, generation) if job else "analysis_not_failed"
        )
        if reason == "eligible" and job:
            if job["source_revision"] != current_source_revision:
                reason = "analysis_source_changed"
            elif not job.get("execution_job"):
                reason = "execution_identity_missing"
        return {
            "eligible": reason == "eligible",
            "reason": reason,
            "job_id": job["id"] if job else None,
            "generation": generation,
            "completed_chunks": progress.get("completed_chunks", 0),
            "max_generations": 3,
        }

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
        return {
            "generation": row["generation"] if row else 0,
            "authorization": json.loads(row["body"]) if row else None,
            "prior_progress": json.loads(progress[0]) if progress else {},
        }

    def resume_analysis(self, owner: str, job_id: str, value: AnalysisRequest) -> dict[str, Any]:
        """Authorize bounded continuation of the same failed job, never a fresh analysis."""
        from trajectory.product.semantic_model import PROMPT_VERSION

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
            generation = db.execute(
                "SELECT COALESCE(max(generation),0) FROM semantic_job_resumes " "WHERE job=?",
                (job_id,),
            ).fetchone()[0]
            reason = self.resume_eligibility(dict(row), progress, generation)
            if reason != "eligible":
                raise AnalysisResumeError(reason)
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
                "analysis.resume",
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
        body = "analysis.batch:" + value.model_dump_json()
        maximum = max(1, min(8, int(os.environ.get("TRAJECTORY_ANALYSIS_CONCURRENCY", "4"))))
        if value.concurrency > maximum:
            raise ValueError(f"Concurrency exceeds configured maximum {maximum}")
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
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
                revisions.append(row[0])
            batch_id = uuid.uuid4().hex
            db.execute(
                "INSERT INTO semantic_batches VALUES(?,?,?,?)",
                (batch_id, owner, value.concurrency, stamp()),
            )
            items = []
            for sid, revision in zip(sessions, revisions, strict=True):
                job_id = self._queue(db, owner, sid, "analyze", revision)
                db.execute(
                    "INSERT INTO semantic_batch_items VALUES(?,?,?)", (batch_id, sid, job_id)
                )
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
                            dict(row), progress, row["current_source_revision"]
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
            self.domain.import_native_measurements(db, owner, source, revision, parsed)
            previous = db.execute(
                "SELECT body FROM semantic_sessions WHERE owner=? AND id=?", (owner, sid)
            ).fetchone()
            if previous and json.loads(previous["body"]).get("operations") != parsed.get(
                "operations"
            ):
                db.execute(
                    "UPDATE semantic_analyses SET source_revision=? WHERE owner=? AND session=?",
                    ("parser-stale:" + revision, owner, sid),
                )
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

    def session_record(self, owner: str, sid: str) -> dict[str, Any]:
        with self.domain.connect() as db:
            row = db.execute(
                "SELECT * FROM semantic_sessions WHERE owner=? AND id=?", (owner, sid)
            ).fetchone()
        if not row:
            raise ValueError("Unknown session")
        return dict(row)

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
        exact = estimated = unassigned = 0
        for contribution in selected:
            event = contribution["record"]
            if not operations:
                unassigned += 1
                continue
            matches = [
                i
                for i, operation in enumerate(operations)
                if event.get("call") and operation.get("call_id") == event["call"]
            ]
            line = int(event.get("source_line") or 0)
            precise = len(matches) == 1
            method = "call_id" if precise else "ambiguous_call_id"
            if not matches:
                same_line = [
                    index for source_line, index in line_nodes if line > 0 and source_line == line
                ]
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

    def detail(
        self, owner: str, sid: str, contributions: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        try:
            record = self.session_record(owner, sid)
        except ValueError:
            listing = self.sessions(owner)
            session = next((item for item in listing["sessions"] if item["id"] == sid), None)
            if session is None:
                raise
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
        if contributions is None:
            contributions = self.domain.source_contributions(
                owner, record["collector"], record["source"]
            )
        attribution = self._measure_operations(owner, record, operations, contributions)
        with self.domain.connect() as db:
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
        current_analysis = (
            analysis is not None and analysis["source_revision"] == record["source_revision"]
        )
        value = json.loads(analysis["body"]) if current_analysis else {"tasks": []}
        status = (
            "complete"
            if analysis and analysis["source_revision"] == record["source_revision"]
            else "stale" if analysis else "not_started"
        )
        if (
            job
            and job["source_revision"] == record["source_revision"]
            and job["status"] in {"queued", "running", "failed"}
        ):
            status = job["status"]
            if not current_analysis and progress:
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

        def members(task_id: str, visiting: set[str]) -> set[str]:
            if task_id in visiting:
                raise ValueError("Task hierarchy contains a cycle")
            task = next(t for t in tasks if t["id"] == task_id)
            result = set(task.get("operation_ids", []))
            for child in tasks:
                if child.get("parent_id") == task_id:
                    result.update(members(child["id"], visiting | {task_id}))
            return result

        for task in tasks:
            ids = members(task["id"], set())
            task["metrics"] = total_metrics([by_id[i]["metrics"] for i in ids if i in by_id])
            task["metrics"]["collection_status"] = collection["status"]
            task["segments"] = []
            previous = -2
            for index, operation in enumerate(operations):
                if operation["id"] not in ids:
                    continue
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
        if analysis and not current_analysis:
            warnings.append(
                "分析来自旧源版本；任务名称供参考，开销与证据仅覆盖仍可匹配的当前操作。"
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
            "resume": self.resume_state(
                dict(job) if job else None, progress, record["source_revision"]
            ),
            "has_analysis": analysis is not None,
            "analysis_current": current_analysis,
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
    ) -> dict[str, Any]:
        allowed = {"all", "analyzed", "not_started", "busy", "failed", "stale"}
        if analysis_status not in allowed or sort not in {
            "last_activity_desc",
            "started_desc",
            "directory",
        }:
            raise ValueError("Unsupported session filter or sort")
        if not 0 <= limit <= 1000 or (cursor and not cursor.isdecimal()):
            raise ValueError("Invalid session page")
        offset = int(cursor or "0")
        self.backfill_metadata(owner)
        groups = {
            self.session_id(item["record"]["collector"], item["record"]["source"]): item
            for item in self.domain.session_summaries(owner)
        }
        with self.domain.connect() as db:
            ledger_sources = {
                (row["collector"], row["source"]): collection_progress(row)
                for row in db.execute(
                    "SELECT collector,source,read_bytes,source_bytes,errors,unknown "
                    "FROM sources WHERE owner=?",
                    (owner,),
                )
            }
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
            archives = {
                (row["collector"], row["source"]): collection_progress(row)
                for row in db.execute(
                    "SELECT collector,source,received_bytes AS read_bytes,source_bytes,"
                    "0 AS errors,0 AS unknown "
                    "FROM source_archives WHERE owner=?",
                    (owner,),
                )
            }
        native_to_id = {
            value["native_session_id"]: sid
            for sid, value in metadata.items()
            if value.get("native_session_id")
        }
        recent_jobs = {row["session"]: row for row in jobs}
        items = []
        for sid in groups.keys() | records.keys():
            own = groups.get(sid)
            event = own["record"] if own else {}
            record, analysis, meta = (
                records.get(sid, {}),
                analyses.get(sid, {}),
                metadata.get(sid, {}),
            )
            has_analysis = bool(analysis)
            current = has_analysis and analysis["source_revision"] == record.get("source_revision")
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
            metrics = total_metrics([own]) if own else total_metrics([])
            metrics["collection_status"] = collection["status"]
            interaction_availability = (
                own["interaction_availability"] if own else self.domain.interaction_availability(0)
            )
            self.domain.apply_interaction_availability(metrics, interaction_availability)
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
                "metrics": metrics,
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
        directories = sorted({str(item["cwd"]) for item in items if item["cwd"]})
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

        counts = {value: sum(matches(item, value) for item in items) for value in allowed}
        items = [i for i in items if matches(i, analysis_status)]
        items.sort(key=lambda i: (str(i.get("last_activity_at") or ""), i["id"]), reverse=True)
        if sort == "started_desc":
            items.sort(key=lambda i: str(i.get("started_at") or ""), reverse=True)
        elif sort == "directory":
            items.sort(key=lambda i: str(i.get("cwd") or "\uffff").casefold())
        total = len(items)
        page = items[offset : offset + limit] if limit else items[offset:]
        next_cursor = str(offset + len(page)) if limit and offset + len(page) < total else None
        return {
            "sessions": page,
            "next_cursor": next_cursor,
            "total": total,
            "status_counts": counts,
            "directories": directories,
            "coverage": {
                "content_sessions": len(records),
                "total_sessions": total,
                "message": "历史仅用量记录需补传执行内容后才能分段。",
            },
        }

    def evidence(self, owner: str, sid: str, operation_id: str) -> dict[str, Any]:
        record = self.session_record(owner, sid)
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
            if (
                not source
                or digest(source["generation"] + ":" + str(source["received_bytes"]))
                != record["source_revision"]
            ):
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
