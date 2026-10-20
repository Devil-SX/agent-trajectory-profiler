"""Account-owned sampling plans, committed with the existing analysis queue.

Only the existing gated worker coordinator invokes tick. SQLite transactions also
make direct/manual submissions safe against concurrent ticks and process restarts.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import sqlite3
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ConfigDict, Field, field_validator

from trajectory.product.contracts import AnalysisBatchRequest, AnalysisRequest
from trajectory.product.semantic import SemanticStore, archive_revision

ALGORITHM = "exponential-race-operation-count-v1"
POLICY = {
    "algorithm": ALGORITHM,
    "weight_basis": "normalized_operation_count, excludes image/base64 byte size",
    "quiet_basis": "max(source content cursor change, metadata last activity)",
    "active_status": (
        "Explicit active metadata excluded; otherwise >=quiet_hours " "is an inactivity proxy"
    ),
    "lineage": "one native ID per cohort; exclude known forks and already attempted native copies",
    "catch_up": (
        "Only today, once, after enabled_at; past/disabled dates skipped. "
        "Enabling after the daily time starts tomorrow."
    ),
    "dst": "one slot per local date; nonexistent time runs after gap; fold runs once",
    "cost": "Configured maximum operations is a preflight guard, not a USD price estimate",
    "failures": "No automatic retry/resume; inspect existing stable job and Jindu receipts",
}


def instant(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def path_key(value: str) -> str:
    value = value.replace("\\", "/").rstrip("/")
    return value.casefold() if len(value) > 1 and value[1] == ":" else value


class ScheduleWrite(AnalysisRequest):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schedule_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    expected_revision: str | None = None
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = False
    archived: bool = False
    directories: list[str] = Field(min_length=1, max_length=20)
    timezone: str = "Asia/Shanghai"
    local_time: str = Field(default="01:00", pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    daily_count: int = Field(default=3, ge=1, le=20)
    quiet_hours: int = Field(default=24, ge=1, le=8760)
    recent_days: int = Field(default=30, ge=1, le=3650)
    concurrency: int = Field(default=2, ge=1, le=4)
    max_operations: int = Field(default=20000, ge=1, le=200000)
    weight_basis: Literal["operation_count"] = "operation_count"

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value

    @field_validator("directories")
    @classmethod
    def scoped_paths(cls, values: list[str]) -> list[str]:
        if any(
            len(v) < 3
            or len(v) > 600
            or "\x00" in v
            or not (
                v.startswith("/") or v.startswith("\\") or (len(v) > 2 and v[1:3] in {":/", ":\\"})
            )
            for v in values
        ):
            raise ValueError("Explicit directory subtrees required")
        return list(dict.fromkeys(path_key(v) for v in values))


class AnalysisAutomationGrant(AnalysisRequest):
    machine: uuid.UUID
    machine_client: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    expected_revision: str | None = None


class ScheduleDelete(AnalysisRequest):
    expected_revision: str


class ScheduleRun(AnalysisRequest):
    expected_revision: str
    count: int | None = Field(default=None, ge=1, le=20)


class AnalysisSchedules:
    def __init__(self, store: SemanticStore):
        self.store = store
        self.domain = store.domain
        self._lengths: dict[tuple[str, str, str], int] = {}
        with self.domain.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS analysis_automation_grants(
                    owner TEXT,machine TEXT,client TEXT,revision TEXT,body TEXT,
                    PRIMARY KEY(owner,machine,client));
                CREATE TABLE IF NOT EXISTS analysis_schedules(
                    owner TEXT,id TEXT,revision TEXT,body TEXT,created TEXT,updated TEXT,
                    PRIMARY KEY(owner,id));
                CREATE TABLE IF NOT EXISTS analysis_schedule_runs(
                    owner TEXT,schedule TEXT,slot TEXT,id TEXT UNIQUE,body TEXT,created TEXT,
                    PRIMARY KEY(owner,schedule,slot));
            """)

    def grants(self, owner: str) -> dict[str, Any]:
        with self.domain.connect() as db:
            return {
                "grants": [
                    json.loads(r[0])
                    for r in db.execute(
                        "SELECT body FROM analysis_automation_grants WHERE owner=?", (owner,)
                    )
                ]
            }

    def grant(self, owner: str, value: AnalysisAutomationGrant) -> dict[str, Any]:
        body = "analysis.automation.grant:" + value.model_dump_json()
        key = (owner, str(value.machine), value.machine_client)
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = self.domain._prior(db, owner, value.mutation_id, body)
            if prior:
                return prior
            row = db.execute(
                "SELECT revision FROM analysis_automation_grants "
                "WHERE owner=? AND machine=? AND client=?",
                key,
            ).fetchone()
            if (row[0] if row else None) != value.expected_revision:
                raise ValueError("Automation grant revision changed")
            result = {
                "resource_owner": owner,
                "machine": str(value.machine),
                "machine_client": value.machine_client,
                "enabled": value.enabled,
                "revision": uuid.uuid4().hex,
                "updated_at": datetime.now(UTC).isoformat(),
                "permissions": ["analysis.read", "analysis.configure"],
            }
            db.execute(
                "INSERT OR REPLACE INTO analysis_automation_grants VALUES(?,?,?,?,?)",
                (*key, result["revision"], json.dumps(result)),
            )
            return self.domain._receipt(
                db, owner, value.mutation_id, body, "analysis.automation.grant", result
            )

    def resolve_owner(self, machine: str, client: str | None, owner: str) -> str:
        if not client:
            raise PermissionError("Resource delegation requires a native machine client")
        with self.domain.connect() as db:
            row = db.execute(
                "SELECT body FROM analysis_automation_grants "
                "WHERE owner=? AND machine=? AND client=?",
                (owner, machine, client),
            ).fetchone()
        if not row or not json.loads(row[0]).get("enabled"):
            raise PermissionError("Explicit analysis automation delegation required")
        return owner

    def _read(self, db: sqlite3.Connection, owner: str, sid: str) -> dict[str, Any]:
        row = db.execute(
            "SELECT * FROM analysis_schedules WHERE owner=? AND id=?", (owner, sid)
        ).fetchone()
        if row is None:
            raise PermissionError("Schedule unavailable")
        return {
            **json.loads(row["body"]),
            "revision": row["revision"],
            "created_at": row["created"],
            "updated_at": row["updated"],
        }

    @staticmethod
    def due(config: dict[str, Any], day: date) -> datetime:
        hour, minute = map(int, config["local_time"].split(":"))
        return datetime.combine(day, time(hour, minute), ZoneInfo(config["timezone"]))

    def _view(self, db: sqlite3.Connection, owner: str, sid: str, now: datetime) -> dict[str, Any]:
        config = self._read(db, owner, sid)
        local = now.astimezone(ZoneInfo(config["timezone"]))
        today_run = db.execute(
            "SELECT 1 FROM analysis_schedule_runs WHERE owner=? AND schedule=? AND slot=?",
            (owner, sid, "daily:" + local.date().isoformat()),
        ).fetchone()
        enabled_at = instant(config.get("enabled_at"))
        missed_before_enable = enabled_at and self.due(config, local.date()) < enabled_at
        next_day = local.date() + timedelta(days=int(bool(today_run or missed_before_enable)))
        next_due = self.due(config, next_day)
        # Today's overdue run is a pending catch-up, not incorrectly tomorrow.
        runs = [
            json.loads(r[0])
            for r in db.execute(
                "SELECT body FROM analysis_schedule_runs WHERE owner=? AND schedule=? "
                "ORDER BY created DESC LIMIT 30",
                (owner, sid),
            )
        ]
        for run in runs:
            snapshot = run.pop("snapshot", {})
            run["candidate_count"] = len(snapshot.get("eligible", []))
            run["excluded_count"] = len(snapshot.get("excluded", []))
            if run.get("batch_id"):
                rows = db.execute(
                    "SELECT j.status,count(*) AS n FROM semantic_batch_items i "
                    "JOIN semantic_jobs j ON j.id=i.job WHERE i.batch=? "
                    "GROUP BY j.status",
                    (run["batch_id"],),
                ).fetchall()
                run["counts"] = {r["status"]: r["n"] for r in rows}
        return {
            **config,
            "next_run_at": next_due.isoformat() if config["enabled"] else None,
            "overdue": bool(config["enabled"] and next_due < now),
            "policy": POLICY,
            "runs": runs,
        }

    def catalog(self, owner: str) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self.domain.connect() as db:
            ids = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM analysis_schedules WHERE owner=? ORDER BY created", (owner,)
                )
            ]
            return {"schedules": [self._view(db, owner, sid, now) for sid in ids], "policy": POLICY}

    def write(self, owner: str, value: ScheduleWrite, caller: dict[str, Any]) -> dict[str, Any]:
        if value.archived and value.enabled:
            raise ValueError("Archived plans must be disabled")
        now = datetime.now(UTC).isoformat()
        body = "schedule.write:" + value.model_dump_json()
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = self.domain._prior(db, owner, value.mutation_id, body)
            if prior:
                return prior
            old = db.execute(
                "SELECT revision,created FROM analysis_schedules WHERE owner=? AND id=?",
                (owner, value.schedule_id),
            ).fetchone()
            if (old["revision"] if old else None) != value.expected_revision:
                raise ValueError("Schedule revision changed")
            config = value.model_dump(exclude={"mutation_id", "expected_revision"})
            previous = self._read(db, owner, value.schedule_id) if old else {}
            config["enabled_at"] = (
                previous.get("enabled_at")
                if previous.get("enabled") and value.enabled
                else now if value.enabled else None
            )
            config["authorized_by"] = caller
            serialized = json.dumps(config, sort_keys=True)
            revision = hashlib.sha256((serialized + now).encode()).hexdigest()
            db.execute(
                "INSERT OR REPLACE INTO analysis_schedules VALUES(?,?,?,?,?,?)",
                (
                    owner,
                    value.schedule_id,
                    revision,
                    serialized,
                    old["created"] if old else now,
                    now,
                ),
            )
            return self.domain._receipt(
                db,
                owner,
                value.mutation_id,
                body,
                "schedule.write",
                {"schedule_id": value.schedule_id, "revision": revision},
            )

    def candidates(
        self, db: sqlite3.Connection, owner: str, config: dict[str, Any], now: datetime
    ) -> dict[str, Any]:
        rows = db.execute(
            "SELECT s.id,s.title,s.source_revision,s.updated,m.body AS metadata,"
            "a.generation,a.received_bytes,a.source_bytes,a.updated AS upload_updated,"
            "c.changed AS content_changed,c.revision AS observed_cursor FROM semantic_sessions s "
            "LEFT JOIN semantic_session_metadata m ON m.owner=s.owner AND m.session=s.id "
            "LEFT JOIN source_archives a ON a.owner=s.owner AND a.collector=s.collector "
            "AND a.source=s.source LEFT JOIN source_content_activity c ON c.owner=s.owner "
            "AND c.collector=s.collector AND c.source=s.source WHERE s.owner=?",
            (owner,),
        ).fetchall()
        attempts = {
            r[0]
            for r in db.execute(
                "SELECT DISTINCT session FROM semantic_jobs WHERE owner=? AND kind='analyze' "
                "UNION SELECT session FROM semantic_analyses WHERE owner=?",
                (owner, owner),
            )
        }
        natives = {
            r["id"]: str(json.loads(r["metadata"] or "{}").get("native_session_id") or r["id"])
            for r in rows
        }
        attempted_native = {natives.get(s, s) for s in attempts}
        native_activity: dict[str, datetime] = {}
        for r in rows:
            meta = json.loads(r["metadata"] or "{}")
            dates = [
                instant(meta.get("last_activity_at")),
                instant(
                    r["content_changed"]
                    if r["observed_cursor"] == str(r["generation"]) + ":" + str(r["received_bytes"])
                    else r["upload_updated"]
                ),
            ]
            latest = max((d for d in dates if d), default=None)
            if latest:
                native = natives[r["id"]]
                native_activity[native] = max(native_activity.get(native, latest), latest)
        candidates: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        for r in rows:
            meta = json.loads(r["metadata"] or "{}")
            cwd = path_key(str(meta.get("cwd") or ""))
            reasons = []
            if not any(cwd == p or cwd.startswith(p + "/") for p in config["directories"]):
                reasons.append("directory_outside_scope")
            latest = native_activity.get(natives[r["id"]])
            if not latest:
                reasons.append("activity_unknown")
            elif latest > now - timedelta(hours=config["quiet_hours"]):
                reasons.append("recently_active")
            elif latest < now - timedelta(days=config["recent_days"]):
                reasons.append("outside_recent_window")
            if meta.get("active") is True or meta.get("status") in {"active", "running"}:
                reasons.append("explicitly_active")
            if not r["generation"] or archive_revision(r) != r["source_revision"]:
                reasons.append("source_revision_pending")
            if r["received_bytes"] != r["source_bytes"]:
                reasons.append("upload_incomplete")
            if natives[r["id"]] in attempted_native:
                reasons.append("native_session_previously_attempted")
            parent = meta.get("parent_native_session_id")
            if parent and parent != natives[r["id"]]:
                reasons.append("known_fork_shared_context")
            count = None
            if not reasons:
                key = (owner, r["id"], r["source_revision"])
                if key not in self._lengths:
                    result = db.execute(
                        "SELECT json_array_length(body,'$.operations') "
                        "FROM semantic_sessions WHERE owner=? AND id=?",
                        (owner, r["id"]),
                    ).fetchone()
                    if len(self._lengths) >= 10000:
                        self._lengths.clear()
                    self._lengths[key] = int(result[0] or 0)
                count = self._lengths[key]
                if count <= 0:
                    reasons.append("empty_context")
                elif count > config["max_operations"]:
                    reasons.append("exceeds_operation_budget_guard")
            item = {
                "session_id": r["id"],
                "title": meta.get("display_title") or r["title"],
                "native_session_id": natives[r["id"]],
                "cwd": cwd,
                "source_revision": r["source_revision"],
                "weight": count,
                "operation_count": count,
                "last_change_at": latest.isoformat() if latest else None,
                "reasons": reasons,
            }
            (excluded if reasons else candidates).append(item)
        candidates.sort(key=lambda x: (x["last_change_at"] or "", x["session_id"]), reverse=True)
        unique = {}
        for item in candidates:
            if item["native_session_id"] in unique:
                excluded.append({**item, "reasons": ["duplicate_native_session"]})
            else:
                unique[item["native_session_id"]] = item
        return {
            "eligible": list(unique.values()),
            "excluded": excluded,
            "observed_at": now.isoformat(),
            "policy": POLICY,
        }

    def remove(
        self, owner: str, sid: str, value: ScheduleDelete, caller: dict[str, Any]
    ) -> dict[str, Any]:
        with self.domain.connect() as db:
            config = self._read(db, owner, sid)
        payload = {k: v for k, v in config.items() if k in ScheduleWrite.model_fields}
        payload.update(
            mutation_id=value.mutation_id,
            expected_revision=value.expected_revision,
            enabled=False,
            archived=True,
        )
        return self.write(owner, ScheduleWrite.model_validate(payload), caller)

    def run_detail(self, owner: str, sid: str, run_id: str) -> dict[str, Any]:
        with self.domain.connect() as db:
            row = db.execute(
                "SELECT body FROM analysis_schedule_runs " "WHERE owner=? AND schedule=? AND id=?",
                (owner, sid, run_id),
            ).fetchone()
            if row is None:
                raise PermissionError("Schedule run unavailable")
            result: dict[str, Any] = json.loads(row[0])
        if result.get("batch_id"):
            result["batch"] = self.store.batch_detail(owner, result["batch_id"])
        return result

    def preview(self, owner: str, sid: str) -> dict[str, Any]:
        with self.domain.connect() as db:
            db.execute("BEGIN")
            config = self._read(db, owner, sid)
            return {
                "schedule_id": sid,
                "revision": config["revision"],
                **self.candidates(db, owner, config, datetime.now(UTC)),
            }

    def _run(
        self,
        db: sqlite3.Connection,
        owner: str,
        config: dict[str, Any],
        slot: str,
        count: int,
        now: datetime,
    ) -> dict[str, Any]:
        prior = db.execute(
            "SELECT body FROM analysis_schedule_runs WHERE owner=? AND schedule=? " "AND slot=?",
            (owner, config["schedule_id"], slot),
        ).fetchone()
        if prior:
            return dict(json.loads(prior[0]))
        snapshot = self.candidates(db, owner, config, now)
        seed = uuid.uuid4().hex
        rng = random.Random(seed)
        # Independent exponential clocks select proportionally to positive weight
        # without replacement, rather than sorting by length.
        ranked = sorted(
            snapshot["eligible"],
            key=lambda r: (-math.log(1.0 - rng.random()) / r["weight"], r["session_id"]),
        )
        selected = ranked[:count]
        run_id = uuid.uuid4().hex
        batch = None
        if selected:
            batch = self.store.queue_batch(
                db,
                owner,
                AnalysisBatchRequest(
                    mutation_id="schedule-run-" + run_id,
                    session_ids=[r["session_id"] for r in selected],
                    concurrency=config["concurrency"],
                    expected_source_revisions={
                        r["session_id"]: r["source_revision"] for r in selected
                    },
                ),
            )
        result = {
            "run_id": run_id,
            "schedule_id": config["schedule_id"],
            "schedule_revision": config["revision"],
            "slot": slot,
            "seed": seed,
            "algorithm": ALGORITHM,
            "execution_configuration": {
                "model": os.environ.get("TRAJECTORY_MODEL_NAME"),
                "jindu_route": os.environ.get("TRAJECTORY_JINDU_ROUTE"),
                "reasoning_effort": os.environ.get("TRAJECTORY_MODEL_REASONING_EFFORT"),
                "actual_configuration": "Pinned by existing worker before first paid window",
            },
            "requested_count": count,
            "selected": selected,
            "snapshot": snapshot,
            "batch_id": batch["batch_id"] if batch else None,
            "status": "submitted" if selected else "no_candidates",
            "created_at": now.isoformat(),
            "authorized_by": config.get("authorized_by"),
        }
        db.execute(
            "INSERT INTO analysis_schedule_runs VALUES(?,?,?,?,?,?)",
            (owner, config["schedule_id"], slot, run_id, json.dumps(result), now.isoformat()),
        )
        return result

    def run(self, owner: str, sid: str, value: ScheduleRun) -> dict[str, Any]:
        body = "schedule.run:" + sid + ":" + value.model_dump_json()
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = self.domain._prior(db, owner, value.mutation_id, body)
            if prior:
                return prior
            config = self._read(db, owner, sid)
            if config["revision"] != value.expected_revision:
                raise ValueError("Schedule revision changed")
            if config.get("archived"):
                raise ValueError("Archived plan cannot submit paid work")
            result = self._run(
                db,
                owner,
                config,
                "manual:" + value.mutation_id,
                value.count or config["daily_count"],
                datetime.now(UTC),
            )
            return self.domain._receipt(db, owner, value.mutation_id, body, "schedule.run", result)

    def tick(self, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute("SELECT owner,id FROM analysis_schedules").fetchall():
                config = self._read(db, row["owner"], row["id"])
                local = now.astimezone(ZoneInfo(config["timezone"]))
                due = self.due(config, local.date())
                enabled_at = instant(config.get("enabled_at"))
                if config["enabled"] and local >= due and enabled_at and due >= enabled_at:
                    db.execute("SAVEPOINT scheduled_draw")
                    slot = "daily:" + local.date().isoformat()
                    try:
                        self._run(db, row["owner"], config, slot, config["daily_count"], now)
                    except ValueError as error:
                        # A configuration failure must not stop unrelated queued jobs,
                        # repeatedly retry a paid draw, or leave a partially queued batch.
                        db.execute("ROLLBACK TO SAVEPOINT scheduled_draw")
                        result = {
                            "run_id": uuid.uuid4().hex,
                            "schedule_id": row["id"],
                            "schedule_revision": config["revision"],
                            "slot": slot,
                            "status": "blocked",
                            "error": str(error)[:500],
                            "selected": [],
                            "requested_count": config["daily_count"],
                            "batch_id": None,
                            "created_at": now.isoformat(),
                        }
                        db.execute(
                            "INSERT OR IGNORE INTO analysis_schedule_runs VALUES(?,?,?,?,?,?)",
                            (
                                row["owner"],
                                row["id"],
                                slot,
                                result["run_id"],
                                json.dumps(result),
                                now.isoformat(),
                            ),
                        )
                    finally:
                        db.execute("RELEASE SAVEPOINT scheduled_draw")
