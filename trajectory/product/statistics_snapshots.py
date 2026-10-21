"""Persistent, account-scoped published statistics, built by the existing coordinator."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from trajectory.product.domain import Domain, now

ALGORITHM = "trajectory-account-statistics/1"
MAX_SCOPES = 12
MIN_BUILD_INTERVAL_SECONDS = 30
MAX_SNAPSHOT_BYTES = 32 * 1024**2
ZONE = ZoneInfo("Asia/Shanghai")


class StatisticsRefresh(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mutation_id: str = Field(min_length=8, max_length=200)
    since: str = ""
    until: str = ""


def scope_dates(since: str = "", until: str = "") -> tuple[str, str, str]:
    for value in (since, until):
        if value and date.fromisoformat(value).isoformat() != value:
            raise ValueError("Invalid statistics date")
    if since and until and since > until:
        raise ValueError("Statistics start date follows end date")
    body = json.dumps({"since": since, "until": until}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest(), since, until


def schedule(clock: datetime | None = None) -> dict[str, Any]:
    local = (clock or datetime.now(UTC)).astimezone(ZONE)
    slot = datetime.combine(local.date(), time(1), ZONE)
    next_slot = slot if local < slot else slot + timedelta(days=1)
    return {
        "timezone": "Asia/Shanghai",
        "local_time": "01:00",
        "next_run_at": next_slot.isoformat(),
    }


class StatisticsSnapshots:
    def __init__(self, domain: Domain):
        self.domain = domain
        self.verify_actor: Callable[[dict[str, Any]], None] = self.unconfigured_actor
        with domain.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS statistics_scopes(
                    owner TEXT,scope TEXT,algorithm TEXT,body TEXT,created TEXT,
                    PRIMARY KEY(owner,scope,algorithm));
                CREATE TABLE IF NOT EXISTS statistics_snapshots(
                    owner TEXT,scope TEXT,algorithm TEXT,watermark INTEGER,
                    observed TEXT,generated TEXT,
                    published TEXT,digest TEXT,body TEXT,
                    PRIMARY KEY(owner,scope,algorithm));
                CREATE TABLE IF NOT EXISTS statistics_jobs(
                    id TEXT PRIMARY KEY,owner TEXT,scope TEXT,algorithm TEXT,trigger TEXT,
                    status TEXT,requested TEXT,started TEXT,finished TEXT,error TEXT,
                    attempt INTEGER NOT NULL DEFAULT 0,requested_by TEXT,
                    UNIQUE(owner,scope,algorithm,trigger));
                CREATE UNIQUE INDEX IF NOT EXISTS statistics_one_active_job
                    ON statistics_jobs(owner,scope,algorithm)
                    WHERE status IN ('queued','running');
                CREATE INDEX IF NOT EXISTS statistics_jobs_queue
                    ON statistics_jobs(status,requested);
                CREATE INDEX IF NOT EXISTS statistics_jobs_scope
                    ON statistics_jobs(owner,scope,algorithm,requested DESC);
                CREATE INDEX IF NOT EXISTS statistics_jobs_finished
                    ON statistics_jobs(finished DESC)
                    WHERE status IN ('complete','failed');
            """)

    @staticmethod
    def unconfigured_actor(actor: dict[str, Any]) -> None:
        raise PermissionError("Statistics identity verification is not configured")

    @staticmethod
    def owner_key(owner: str | None) -> str:
        return owner if owner is not None else "@platform"

    def _scope(
        self,
        db: sqlite3.Connection,
        owner: str,
        key: str,
        since: str,
        until: str,
        actor: dict[str, Any],
    ) -> None:
        if db.execute(
            "SELECT 1 FROM statistics_scopes WHERE owner=? AND scope=? AND algorithm=?",
            (owner, key, ALGORITHM),
        ).fetchone():
            if actor.get("renew_authorization"):
                db.execute(
                    "UPDATE statistics_scopes SET body=? WHERE owner=? AND scope=? AND algorithm=?",
                    (
                        json.dumps({"since": since, "until": until, "authorized_by": actor}),
                        owner,
                        key,
                        ALGORITHM,
                    ),
                )
            return
        count = db.execute(
            "SELECT count(*) FROM statistics_scopes WHERE owner=? AND algorithm=?",
            (owner, ALGORITHM),
        ).fetchone()[0]
        # One slot is reserved for the complete account view.
        has_full = db.execute(
            "SELECT 1 FROM statistics_scopes WHERE owner=? AND scope=? AND algorithm=?",
            (owner, scope_dates()[0], ALGORITHM),
        ).fetchone()
        cap = MAX_SCOPES if has_full or (not since and not until) else MAX_SCOPES - 1
        if count >= cap:
            raise ValueError("统计日期范围已达上限，请复用已有范围。")
        db.execute(
            "INSERT INTO statistics_scopes VALUES(?,?,?,?,?)",
            (
                owner,
                key,
                ALGORITHM,
                json.dumps({"since": since, "until": until, "authorized_by": actor}),
                now(),
            ),
        )

    @staticmethod
    def _enqueue(
        db: sqlite3.Connection, owner: str, key: str, trigger: str, actor: dict[str, Any]
    ) -> dict[str, Any]:
        row = db.execute(
            "SELECT * FROM statistics_jobs WHERE owner=? AND scope=? AND algorithm=? "
            "AND (trigger=? OR status IN ('queued','running')) "
            "ORDER BY CASE WHEN trigger=? THEN 0 ELSE 1 END LIMIT 1",
            (owner, key, ALGORITHM, trigger, trigger),
        ).fetchone()
        if row:
            return {"job_id": row["id"], "status": row["status"], "coalesced": True}
        job = uuid.uuid4().hex
        db.execute(
            "INSERT INTO statistics_jobs(id,owner,scope,algorithm,trigger,status,"
            "requested,requested_by) "
            "VALUES(?,?,?,?,?,'queued',?,?)",
            (job, owner, key, ALGORITHM, trigger, now(), json.dumps(actor)),
        )
        return {"job_id": job, "status": "queued", "coalesced": False}

    def request(
        self, owner: str | None, actor: dict[str, Any], value: StatisticsRefresh
    ) -> dict[str, Any]:
        key, since, until = scope_dates(value.since, value.until)
        owner_key = self.owner_key(owner)
        body = json.dumps({"owner": owner, **value.model_dump()}, sort_keys=True)
        caller = str(actor["account_id"])
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = self.domain._prior(db, caller, value.mutation_id, body)
            if prior:
                return prior
            self._scope(db, owner_key, key, since, until, {**actor, "renew_authorization": True})
            result = self._enqueue(db, owner_key, key, "manual:" + value.mutation_id, actor)
            return self.domain._receipt(
                db, caller, value.mutation_id, body, "statistics.refresh", {**result, "scope": key}
            )

    def read(
        self,
        owner: str | None,
        since: str = "",
        until: str = "",
        actor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        actor = actor or {"kind": "isolated_internal_read"}
        key, since, until = scope_dates(since, until)
        owner_key = self.owner_key(owner)
        with self.domain.connect() as db:
            db.execute("BEGIN")
            snapshot = db.execute(
                "SELECT * FROM statistics_snapshots WHERE owner=? AND scope=? AND algorithm=?",
                (owner_key, key, ALGORITHM),
            ).fetchone()
            job = db.execute(
                "SELECT id,status,requested,started,finished,error FROM statistics_jobs "
                "WHERE owner=? AND scope=? AND algorithm=? AND status!='coalesced' "
                "ORDER BY CASE WHEN status IN ('queued','running') THEN 0 ELSE 1 END,"
                "requested DESC,id DESC LIMIT 1",
                (owner_key, key, ALGORITHM),
            ).fetchone()
            current = self.domain.ledger_revision(db)
        if snapshot is None and job is None:
            with self.domain.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self._scope(db, owner_key, key, since, until, actor)
                result = self._enqueue(db, owner_key, key, "initial", actor)
            job = {"id": result["job_id"], "status": result["status"]}
        updating = bool(job and job["status"] in {"queued", "running"})
        state = (
            "updating"
            if snapshot and updating
            else (
                "building"
                if updating
                else (
                    "failed"
                    if job and job["status"] == "failed"
                    else "ready" if snapshot else "not_ready"
                )
            )
        )
        generated = snapshot["generated"] if snapshot else None
        meta = {
            "schema": "trajectory-statistics-snapshot/1",
            "algorithm": ALGORITHM,
            "scope": {"since": since, "until": until},
            "scope_id": key,
            "available": bool(snapshot),
            "state": state,
            "generated_at": generated,
            "source_observed_at": snapshot["observed"] if snapshot else None,
            "published_at": snapshot["published"] if snapshot else None,
            "source_watermark": (
                self.watermark(owner_key, snapshot["watermark"]) if snapshot else None
            ),
            "current_watermark": self.watermark(owner_key, current),
            "stale": bool(snapshot and snapshot["watermark"] != current),
            "age_seconds": (
                max(0, (datetime.now(UTC) - datetime.fromisoformat(generated)).total_seconds())
                if generated
                else None
            ),
            "update": dict(job) if job else None,
            "schedule": schedule(),
        }
        return {**(json.loads(snapshot["body"]) if snapshot else {}), "statistics_snapshot": meta}

    @staticmethod
    def watermark(owner: str, revision: int) -> str:
        # An opaque account/schema-bound token, not an exposed cross-account audit counter.
        return hashlib.sha256(f"{ALGORITHM}:{owner}:{revision}".encode()).hexdigest()

    def tick(self, clock: datetime | None = None) -> int:
        local = (clock or datetime.now(UTC)).astimezone(ZONE)
        if local.time() < time(1):
            return 0
        trigger = "daily:" + local.date().isoformat()
        count = 0
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute(
                "SELECT owner,scope,body FROM statistics_scopes WHERE algorithm=?", (ALGORITHM,)
            ).fetchall():
                # Record the day's slot even if a manual job already covers its rebuild.
                if db.execute(
                    "SELECT 1 FROM statistics_jobs WHERE owner=? AND scope=? "
                    "AND algorithm=? AND trigger=?",
                    (row["owner"], row["scope"], ALGORITHM, trigger),
                ).fetchone():
                    continue
                result = self._enqueue(
                    db,
                    row["owner"],
                    row["scope"],
                    trigger,
                    {
                        **json.loads(row["body"]).get("authorized_by", {}),
                        "trigger_kind": "daily_maintenance",
                    },
                )
                if result["coalesced"]:
                    # Daily slot identity is durable; the active job remains the only builder.
                    db.execute(
                        "INSERT INTO statistics_jobs(id,owner,scope,algorithm,trigger,status,"
                        "requested,finished,requested_by) "
                        "VALUES(?,?,?,?,?,'coalesced',?,?,?)",
                        (
                            uuid.uuid4().hex,
                            row["owner"],
                            row["scope"],
                            ALGORITHM,
                            trigger,
                            now(),
                            now(),
                            json.dumps(
                                {"covered_by": result["job_id"], "kind": "daily_maintenance"}
                            ),
                        ),
                    )
                count += 1
        return count

    def recover(self) -> None:
        with self.domain.connect() as db:
            db.execute(
                "UPDATE statistics_jobs SET status='queued',started=NULL WHERE status='running'"
            )

    def pending(self) -> bool:
        with self.domain.connect() as db:
            return bool(
                db.execute("SELECT 1 FROM statistics_jobs WHERE status='queued' LIMIT 1").fetchone()
            )

    def can_start(self, clock: datetime | None = None) -> bool:
        """Persisted cooldown leaves room for queued analysis and ingestion between builds."""
        with self.domain.connect() as db:
            finished = db.execute(
                "SELECT max(finished) FROM statistics_jobs " "WHERE status IN ('complete','failed')"
            ).fetchone()[0]
        if finished is None:
            return True
        return (clock or datetime.now(UTC)) >= datetime.fromisoformat(finished) + timedelta(
            seconds=MIN_BUILD_INTERVAL_SECONDS
        )

    def claim(self) -> dict[str, Any] | None:
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM statistics_jobs WHERE status='queued' ORDER BY requested,id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE statistics_jobs SET status='running',started=?,"
                "attempt=attempt+1,error=NULL WHERE id=?",
                (now(), row["id"]),
            )
            return {**dict(row), "attempt": row["attempt"] + 1}

    def build(self, job: dict[str, Any]) -> bool:
        try:
            self.verify_actor(json.loads(job["requested_by"]))
            # Share the HTTP contribution scan budget; wait before opening a
            # read transaction so a busy slot cannot retain an old WAL reader.
            with self.domain._source_scan_slots, self.domain.connect() as db:
                db.execute("PRAGMA temp_store=FILE")
                db.execute("PRAGMA cache_size=-4096")
                db.execute("BEGIN")
                scope = db.execute(
                    "SELECT body FROM statistics_scopes WHERE owner=? AND scope=? AND algorithm=?",
                    (job["owner"], job["scope"], job["algorithm"]),
                ).fetchone()
                if scope is None or job["algorithm"] != ALGORITHM:
                    raise ValueError("Statistics scope unavailable")
                dates = json.loads(scope[0])
                observed = now()
                watermark = self.domain.ledger_revision(db)
                owner = None if job["owner"] == "@platform" else job["owner"]
                value = self.domain._calculate_snapshot(
                    db, owner, dates["since"], dates["until"], None
                )
                value.pop("source_summaries", None)
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            if len(body.encode()) > MAX_SNAPSHOT_BYTES:
                raise ValueError("Statistics snapshot exceeds the published size limit")
            self.verify_actor(json.loads(job["requested_by"]))
            with self.domain.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                current = db.execute(
                    "SELECT status,attempt FROM statistics_jobs WHERE id=?", (job["id"],)
                ).fetchone()
                if (
                    current is None
                    or current["status"] != "running"
                    or current["attempt"] != job["attempt"]
                ):
                    raise ValueError("Statistics job lease changed")
                db.execute(
                    "INSERT OR REPLACE INTO statistics_snapshots VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        job["owner"],
                        job["scope"],
                        ALGORITHM,
                        watermark,
                        observed,
                        value["generated_at"],
                        now(),
                        hashlib.sha256(body.encode()).hexdigest(),
                        body,
                    ),
                )
                db.execute(
                    "UPDATE statistics_jobs SET status='complete',finished=?,error=NULL WHERE id=?",
                    (now(), job["id"]),
                )
            return True
        except Exception as error:
            with self.domain.connect() as db:
                db.execute(
                    "UPDATE statistics_jobs SET status='failed',finished=?,error=? "
                    "WHERE id=? AND status='running' AND attempt=?",
                    (now(), type(error).__name__, job["id"], job["attempt"]),
                )
            return False
