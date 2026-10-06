"""One transactional writer and one set of account-scoped metric semantics."""

import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from trajectory.product.contracts import Batch, Correction, Price
from trajectory.product.projects import classify_records


def now() -> str:
    return datetime.now(UTC).isoformat()


class Domain:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS request_traces(
                    id TEXT PRIMARY KEY, body TEXT, created TEXT);
                CREATE TABLE IF NOT EXISTS collectors(owner TEXT, machine TEXT, collector TEXT,
                    PRIMARY KEY(machine,collector));
                CREATE TABLE IF NOT EXISTS events(owner TEXT, collector TEXT, source TEXT,
                    id TEXT, body TEXT, PRIMARY KEY(owner,collector,source,id));
                CREATE TABLE IF NOT EXISTS sources(owner TEXT, collector TEXT, source TEXT,
                    revision INTEGER, source_bytes INTEGER, read_bytes INTEGER, parser TEXT,
                    errors INTEGER, unknown INTEGER, received TEXT,
                    PRIMARY KEY(owner,collector,source));
                CREATE TABLE IF NOT EXISTS receipts(actor TEXT, id TEXT, digest TEXT, body TEXT,
                    PRIMARY KEY(actor,id));
                CREATE TABLE IF NOT EXISTS corrections(owner TEXT, task TEXT, project TEXT,
                    name TEXT, actor TEXT, updated TEXT, PRIMARY KEY(owner,task));
                CREATE TABLE IF NOT EXISTS prices(owner TEXT, model TEXT, effective TEXT,
                    body TEXT, PRIMARY KEY(owner,model,effective));
                CREATE TABLE IF NOT EXISTS audit(actor TEXT, id TEXT, operation TEXT,
                    body TEXT, created TEXT);
            """)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def trace(self, record: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO request_traces VALUES(?,?,?)",
                (record["request_id"], json.dumps(record), now()),
            )
            db.execute(
                "DELETE FROM request_traces WHERE id NOT IN "
                "(SELECT id FROM request_traces ORDER BY rowid DESC LIMIT 10000)"
            )

    def traces(self) -> dict[str, Any]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT body FROM request_traces ORDER BY rowid DESC LIMIT 200"
            ).fetchall()
        return {
            "schema": "trajectory-request-traces/1",
            "items": [json.loads(row[0]) for row in rows],
            "retention_limit": 10000,
        }

    def register(self, owner: str, machine: str, collector: str) -> dict[str, Any]:
        with self.connect() as db:
            old = db.execute(
                "SELECT owner FROM collectors WHERE machine=? AND collector=?",
                (machine, collector),
            ).fetchone()
            if old and old[0] != owner:
                raise PermissionError("Collector already belongs to another account")
            db.execute(
                "INSERT OR IGNORE INTO collectors VALUES(?,?,?)",
                (owner, machine, collector),
            )
        return {"owner": owner, "machine": machine, "collector": collector}

    def _prior(
        self, db: sqlite3.Connection, actor: str, mutation: str, body: str
    ) -> dict[str, Any] | None:
        old = db.execute(
            "SELECT * FROM receipts WHERE actor=? AND id=?", (actor, mutation)
        ).fetchone()
        if old:
            if old["digest"] != hashlib.sha256(body.encode()).hexdigest():
                raise ValueError("Mutation ID reused with a different payload")
            receipt: dict[str, Any] = json.loads(old["body"])
            return receipt
        return None

    def _receipt(
        self,
        db: sqlite3.Connection,
        actor: str,
        mutation: str,
        body: str,
        operation: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        result = {
            **result,
            "mutation_id": mutation,
            "durable": True,
            "received_at": now(),
        }
        db.execute(
            "INSERT INTO receipts VALUES(?,?,?,?)",
            (
                actor,
                mutation,
                hashlib.sha256(body.encode()).hexdigest(),
                json.dumps(result),
            ),
        )
        db.execute(
            "INSERT INTO audit VALUES(?,?,?,?,?)",
            (actor, mutation, operation, body, now()),
        )
        return result

    def ingest(
        self, actor: str, batch: Batch, key_id: str | None = None, machine_client: str | None = None
    ) -> dict[str, Any]:
        body = batch.model_dump_json()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            binding = db.execute(
                "SELECT owner FROM collectors WHERE machine=? AND collector=?",
                (actor, batch.collector),
            ).fetchone()
            if not binding:
                raise PermissionError("Collector is not bound to an owner")
            owner = binding[0]
            prior = self._prior(db, actor, batch.mutation_id, body)
            if prior:
                return prior
            old = db.execute(
                "SELECT revision,read_bytes FROM sources "
                "WHERE owner=? AND collector=? AND source=?",
                (owner, batch.collector, batch.source),
            ).fetchone()
            if old and batch.revision <= old[0]:
                raise ValueError("Source revision must increase")
            if old and not batch.replace and batch.revision != old[0] + 1:
                raise ValueError("Missing source revision; replay or replace the source")
            if old and not batch.replace and batch.read_bytes < old["read_bytes"]:
                raise ValueError("Read position cannot regress without source replacement")
            if batch.read_bytes > batch.source_bytes:
                raise ValueError("Read position exceeds source size")
            if batch.replace:
                db.execute(
                    "DELETE FROM events WHERE owner=? AND collector=? AND source=?",
                    (owner, batch.collector, batch.source),
                )
            for record in batch.records:
                db.execute(
                    "INSERT OR REPLACE INTO events VALUES(?,?,?,?,?)",
                    (
                        owner,
                        batch.collector,
                        batch.source,
                        record.id,
                        record.model_dump_json(),
                    ),
                )
            db.execute(
                "INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    owner,
                    batch.collector,
                    batch.source,
                    batch.revision,
                    batch.source_bytes,
                    batch.read_bytes,
                    batch.parser_version,
                    batch.parse_errors,
                    batch.unknown_events,
                    now(),
                ),
            )
            # Receipts audit metadata only; never duplicate all event bodies in the audit table.
            result = self._receipt(
                db,
                actor,
                batch.mutation_id,
                body,
                "ingest",
                {
                    "owner": owner,
                    "source": batch.source,
                    "revision": batch.revision,
                    "accepted": len(batch.records),
                },
            )
            db.execute(
                "UPDATE audit SET body=? WHERE actor=? AND id=?",
                (
                    json.dumps(
                        {
                            "source": batch.source,
                            "revision": batch.revision,
                            "key_id": key_id,
                            "machine_client": machine_client,
                        }
                    ),
                    actor,
                    batch.mutation_id,
                ),
            )
        return result

    def correct(self, owner: str, value: Correction) -> dict[str, Any]:
        body = value.model_dump_json()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = self._prior(db, owner, value.mutation_id, body)
            if prior:
                return prior
            exists = any(
                json.loads(row[0])["task"] == value.task
                for row in db.execute("SELECT body FROM events WHERE owner=?", (owner,))
            )
            if not exists:
                raise ValueError("Task not found in this account")
            db.execute(
                "INSERT OR REPLACE INTO corrections VALUES(?,?,?,?,?,?)",
                (owner, value.task, value.project, value.project_name, owner, now()),
            )
            result = self._receipt(
                db, owner, value.mutation_id, body, "correct", {"task": value.task}
            )
        return result

    def price(self, owner: str, value: Price) -> dict[str, Any]:
        body = value.model_dump_json()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = self._prior(db, owner, value.mutation_id, body)
            if prior:
                return prior
            db.execute(
                "INSERT OR REPLACE INTO prices VALUES(?,?,?,?)",
                (
                    owner,
                    value.model,
                    value.effective_from.astimezone(UTC).isoformat(),
                    body,
                ),
            )
            result = self._receipt(
                db, owner, value.mutation_id, body, "price", {"model": value.model}
            )
        return result

    def overview(self, owner: str | None, since: str = "", until: str = "") -> dict[str, Any]:
        with self.connect() as db:
            where, params = (" WHERE owner=?", (owner,)) if owner else ("", ())
            rows = db.execute(
                "SELECT owner,collector,source,body FROM events" + where, params
            ).fetchall()
            sources = [dict(row) for row in db.execute("SELECT * FROM sources" + where, params)]
            corrections = {
                (r["owner"], r["task"]): dict(r)
                for r in db.execute("SELECT * FROM corrections" + where, params)
            }
            prices: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
            for row in db.execute("SELECT * FROM prices" + where + " ORDER BY effective", params):
                prices[(row["owner"], row["model"])].append(json.loads(row["body"]))
        records = []
        for row in rows:
            record = json.loads(row["body"])
            record.update(owner=row["owner"], collector=row["collector"], source=row["source"])
            records.append(record)
        classify_records(records)
        for record in records:
            correction = corrections.get((record["owner"], record["task"]))
            if correction:
                record.update(
                    project=correction["project"],
                    project_name=correction["name"],
                    evidence="corrected",
                )
        records.sort(key=lambda r: (r["timestamp"] or "", r["source_line"]))
        seen: set[tuple[str, str, str]] = set()
        usages = []
        duplicates = 0
        for record in reversed(records):
            if record["kind"] != "usage":
                continue
            key = (
                record["owner"],
                record["ecosystem"],
                record.get("consumption") or record["id"],
            )
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            usages.append(record)
        groups: dict[str, dict[str, Any]] = {}
        days: dict[str, dict[str, Any]] = {}
        tasks: dict[str, dict[str, Any]] = {}

        def bucket(key: str, name: str) -> dict[str, Any]:
            return {
                "id": key,
                "name": name,
                "input": 0,
                "output": 0,
                "cached": 0,
                "cache_write": 0,
                "reasoning": 0,
                "calls": 0,
                "unknown_usage": 0,
                "missing_counters": dict.fromkeys(
                    ("input", "output", "cached", "cache_write", "reasoning"), 0
                ),
                "estimated_usd": 0.0,
                "unpriced_calls": 0,
                "tool_seconds": 0.0,
                "tool_errors": 0,
                "active_seconds_estimate": 0.0,
            }

        def date_for(record: dict[str, Any]) -> str:
            return (
                datetime.fromisoformat(record["timestamp"])
                .astimezone(ZoneInfo("Asia/Shanghai"))
                .date()
                .isoformat()
                if record["timestamp"]
                else "unknown"
            )

        def included(record: dict[str, Any]) -> bool:
            day = date_for(record)
            return day == "unknown" or ((not since or day >= since) and (not until or day <= until))

        for record in records:
            if not included(record):
                continue
            project = record["project"]
            groups.setdefault(project, bucket(project, record["project_name"]))
            task = tasks.setdefault(
                record["task"],
                {
                    "id": record["task"],
                    "session": record["session"],
                    "project": project,
                    "project_name": record["project_name"],
                    "evidence": record["evidence"],
                    "started": record["timestamp"],
                    "ended": record["timestamp"],
                    "calls": 0,
                    "errors": 0,
                    "source": record["source"],
                    "source_line": record["source_line"],
                },
            )
            task["ended"] = record["timestamp"] or task["ended"]
            if record["evidence"] in ("path", "service", "corrected"):
                task.update(
                    project=project,
                    project_name=record["project_name"],
                    evidence=record["evidence"],
                )
        for record in usages:
            if not included(record):
                continue
            day = date_for(record)
            daily = days.setdefault(day, bucket(day, day))
            project = groups.setdefault(
                record["project"], bucket(record["project"], record["project_name"])
            )
            price = None
            if record["timestamp"]:
                for candidate in prices.get((record["owner"], record.get("model")), []):
                    if datetime.fromisoformat(
                        candidate["effective_from"]
                    ) <= datetime.fromisoformat(record["timestamp"]):
                        price = candidate
            cost = None
            can_price = all(record[field] is not None for field in ("input", "output", "cached"))
            if record["ecosystem"] == "claude_code" and record["cache_write"] is None:
                can_price = False
            if price and can_price:
                cached = record["cached"] or 0
                net_input = (
                    max(0, record["input"] - cached)
                    if record["input_includes_cache"]
                    else record["input"]
                )
                cost = (
                    net_input * price["input"]
                    + record["output"] * price["output"]
                    + cached * price["cached"]
                    + (record["cache_write"] or 0) * price["cache_write"]
                ) / 1_000_000
            for target in (project, daily):
                target["calls"] += 1
                if record["input"] is None or record["output"] is None:
                    target["unknown_usage"] += 1
                for field in ("input", "output", "cached", "cache_write", "reasoning"):
                    if record[field] is None:
                        target["missing_counters"][field] += 1
                    else:
                        target[field] += record[field]
                if cost is None:
                    target["unpriced_calls"] += 1
                else:
                    target["estimated_usd"] += cost
            if record["task"] in tasks:
                tasks[record["task"]]["calls"] += 1
        zone = ZoneInfo("Asia/Shanghai")
        lower = datetime.combine(date.fromisoformat(since), time.min, zone) if since else None
        upper = (
            datetime.combine(date.fromisoformat(until) + timedelta(days=1), time.min, zone)
            if until
            else None
        )
        if lower and upper and lower >= upper:
            raise ValueError("Invalid date range")

        def allocate(start: dict[str, Any], end: dict[str, Any], metric: str) -> None:
            if not start["timestamp"] or not end["timestamp"]:
                return
            beginning = datetime.fromisoformat(start["timestamp"]).astimezone(zone)
            ending = datetime.fromisoformat(end["timestamp"]).astimezone(zone)
            if lower:
                beginning = max(beginning, lower)
            if upper:
                ending = min(ending, upper)
            if ending <= beginning:
                return
            target = groups.setdefault(
                start["project"], bucket(start["project"], start["project_name"])
            )
            target[metric] += (ending - beginning).total_seconds()
            while beginning < ending:
                day = beginning.date().isoformat()
                midnight = datetime.combine(beginning.date() + timedelta(days=1), time.min, zone)
                boundary = min(ending, midnight)
                days.setdefault(day, bucket(day, day))[metric] += (
                    boundary - beginning
                ).total_seconds()
                beginning = boundary

        starts: dict[tuple[str, str, str], dict[str, Any]] = {}
        anomalies = []
        previous: dict[tuple[str, str], dict[str, Any]] = {}
        for record in records:
            visible = included(record)
            identity = (record["owner"], record["session"])
            prior = previous.get(identity)
            if prior and record["timestamp"] and prior["timestamp"] and record["kind"] != "request":
                gap = (
                    datetime.fromisoformat(record["timestamp"])
                    - datetime.fromisoformat(prior["timestamp"])
                ).total_seconds()
                if 0 < gap <= 1800:
                    allocate(prior, record, "active_seconds_estimate")
            previous[identity] = record
            call = (record["owner"], record["session"], record["call"] or record["id"])
            if record["kind"] == "tool_start":
                starts[call] = record
            if record["kind"] == "tool_end":
                start = starts.pop(call, None)
                elapsed = None
                if start and start["timestamp"] and record["timestamp"]:
                    elapsed = (
                        datetime.fromisoformat(record["timestamp"])
                        - datetime.fromisoformat(start["timestamp"])
                    ).total_seconds()
                    if elapsed >= 0:
                        allocate(start, record, "tool_seconds")
                if not visible:
                    continue
                project = groups[record["project"]]
                if record["error"]:
                    project["tool_errors"] += 1
                    tasks[record["task"]]["errors"] += 1
                    day = date_for(record)
                    days.setdefault(day, bucket(day, day))["tool_errors"] += 1
                if record["error"] or (elapsed is not None and elapsed > 60):
                    anomalies.append(
                        {
                            "kind": "tool_error" if record["error"] else "slow_tool",
                            "task": record["task"],
                            "project": record["project_name"],
                            "timestamp": record["timestamp"],
                            "tool": start["tool"] if start else None,
                            "seconds": elapsed,
                            "source": record["source"],
                            "line": record["source_line"],
                            "cause": "unknown",
                        }
                    )
        for start in starts.values():
            if included(start):
                anomalies.append(
                    {
                        "kind": "unpaired_tool",
                        "task": start["task"],
                        "project": start["project_name"],
                        "timestamp": start["timestamp"],
                        "tool": start["tool"],
                        "source": start["source"],
                        "line": start["source_line"],
                        "cause": "unknown",
                    }
                )
        return {
            "schema": "trajectory-overview/1",
            "generated_at": now(),
            "projects": sorted(
                groups.values(), key=lambda r: r["input"] + r["output"], reverse=True
            ),
            "daily": sorted(days.values(), key=lambda r: r["id"]),
            "tasks": list(reversed(list(tasks.values())))[:500],
            "anomalies": anomalies[-200:],
            "models": sorted({r["model"] for r in usages if r.get("model")}),
            "coverage": {
                "sources": len(sources),
                "read_bytes": sum(r["read_bytes"] for r in sources),
                "source_bytes": sum(r["source_bytes"] for r in sources),
                "parse_errors": sum(r["errors"] for r in sources),
                "unknown_events": sum(r["unknown"] for r in sources),
                "latest_received": max((r["received"] for r in sources), default=None),
                "deduplicated_usage_records": duplicates,
                "unknown_timestamps": sum(r["timestamp"] is None for r in records),
            },
            "methodology": {
                "cost": "API-equivalent estimate, USD; missing prices remain unknown",
                "time": (
                    "Per-session event gaps up to 30 minutes, excluding gaps ending at requests; "
                    "estimated agent activity, not human work time"
                ),
                "tool_time": "Paired tool timestamps; overlapping durations are cumulative",
                "classification": (
                    "Server attribution from explicit protocol references, "
                    "account-scoped corrections; ambiguous work remains "
                    "shared or unassigned"
                ),
            },
        }

    def backup(self, target: Path) -> None:
        with self.connect() as source, sqlite3.connect(target) as destination:
            source.backup(destination)
