"""One transactional writer and one set of account-scoped metric semantics."""

import fcntl
import hashlib
import json
import os
import sqlite3
import threading
from collections import OrderedDict, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from itertools import chain
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from trajectory.product.contracts import Batch, Correction, Price
from trajectory.product.costing import quote_record, select_price, usage_record
from trajectory.product.ledger_scan import LedgerScan, UniqueUsages
from trajectory.product.read_cache import RevisionCache

INTERACTION_COUNTERS = (
    "human_interactions",
    "human_input_chars",
    "missing_human_input_chars",
    "unknown_origin_interactions",
    "agent_interactions",
    "system_interactions",
)


def now() -> str:
    return datetime.now(UTC).isoformat()


class Domain:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._overview_lock = threading.Lock()
        self._overview_cache: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
        self._source_cache = RevisionCache(max_bytes=16 * 1024 * 1024, max_entries=16)
        self._source_scan_slots = threading.BoundedSemaphore(2)
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
                "SELECT revision,read_bytes,parser FROM sources "
                "WHERE owner=? AND collector=? AND source=?",
                (owner, batch.collector, batch.source),
            ).fetchone()
            if old and str(old["parser"]).startswith("pi-native-measurements/"):
                raise ValueError("Source ledger is owned by the native measurement importer")
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

    def import_native_measurements(
        self,
        db: sqlite3.Connection,
        owner: str,
        source: dict[str, Any],
        revision: str,
        parsed: dict[str, Any],
    ) -> dict[str, Any]:
        """Project worker-recorded Pi measurements inside the archive commit.

        The caller must hold the existing parse/save transaction. This path owns
        its source ledger exclusively; a second statistical producer is rejected.
        No original JSONL is parsed here and no missing metric becomes zero.
        """
        if source.get("ecosystem") != "pi":
            return {"status": "not_applicable"}
        if not db.in_transaction:
            raise ValueError("Native measurements require the archive transaction")
        if parsed.get("recorded_measurement_schema") != "trajectory.recorded-measurements/1":
            raise ValueError("Source must be reparsed by the recorded measurement adapter")
        collector, identity = source["collector"], source["source"]
        archive = db.execute(
            "SELECT * FROM source_archives WHERE owner=? AND collector=? AND source=?",
            (owner, collector, identity),
        ).fetchone()
        if not archive or archive["ecosystem"] != "pi":
            raise PermissionError("Native source does not belong to this account")
        actual = hashlib.sha256(
            f"{archive['generation']}:{archive['received_bytes']}".encode()
        ).hexdigest()
        if actual != revision or parsed.get("source_id") != identity:
            raise ValueError("Source changed during measurement import")
        complete = parsed.get("complete_bytes")
        if type(complete) is not int or not 0 <= complete <= archive["received_bytes"]:
            raise ValueError("Invalid native measurement byte coverage")
        # Hash authoritative archived bytes, without interpreting source syntax.
        hasher = hashlib.sha256()
        remaining = complete
        for chunk in db.execute(
            "SELECT content FROM source_chunks WHERE owner=? AND collector=? AND source=? "
            "AND generation=? ORDER BY start",
            (owner, collector, identity, archive["generation"]),
        ):
            block = bytes(chunk[0])[:remaining]
            hasher.update(block)
            remaining -= len(block)
            if not remaining:
                break
        if remaining or hasher.hexdigest() != parsed.get("source_sha256"):
            raise ValueError("Native measurements do not match archived source bytes")
        old = db.execute(
            "SELECT revision,parser FROM sources WHERE owner=? AND collector=? AND source=?",
            (owner, collector, identity),
        ).fetchone()
        if old and not str(old["parser"]).startswith("pi-native-measurements/"):
            raise ValueError("Source already has a statistical ledger; reconcile its writer first")
        from trajectory.product.native_measurements import pi_records

        records, gaps = pi_records(source, parsed)
        parser = "pi-native-measurements/1:worker-" + str(parsed.get("worker_version", "unknown"))
        encoded = [record.model_dump_json() for record in records]
        summary = {
            "source": identity,
            "source_revision": revision,
            "source_sha256": parsed["source_sha256"],
            "parser": parser,
            "records_sha256": hashlib.sha256("\n".join(encoded).encode()).hexdigest(),
            "accepted": len(records),
            "gaps": gaps,
        }
        body = json.dumps(summary, sort_keys=True)
        mutation = hashlib.sha256(f"{owner}:{collector}:{body}".encode()).hexdigest()
        actor = "native-measurement-importer"
        prior = self._prior(db, actor, mutation, body)
        if prior:
            return prior
        db.execute(
            "DELETE FROM events WHERE owner=? AND collector=? AND source=?",
            (owner, collector, identity),
        )
        db.executemany(
            "INSERT INTO events VALUES(?,?,?,?,?)",
            [
                (owner, collector, identity, record.id, value)
                for record, value in zip(records, encoded, strict=True)
            ],
        )
        coverage = parsed.get("coverage", {})
        db.execute(
            "INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                owner,
                collector,
                identity,
                int(old["revision"]) + 1 if old else 1,
                archive["source_bytes"],
                complete,
                parser,
                int(coverage.get("quarantined_records", 0)),
                0,  # Origin uncertainty belongs to request metrics, not unparsed-source events.
                now(),
            ),
        )
        # Existing overview cache invalidation observes the same authoritative audit.
        return self._receipt(db, actor, mutation, body, "ingest", summary)

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

    def analysis_cost(self, owner: str, provenance: dict[str, Any]) -> dict[str, Any]:
        """Read-only API-equivalent valuation from the same account price registry."""
        with self.connect() as db:
            prices: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in db.execute(
                "SELECT model,body FROM prices WHERE owner=? ORDER BY effective", (owner,)
            ):
                prices[row["model"]].append(json.loads(row["body"]))
        calls = provenance.get("analysis_usage")
        calls = calls if isinstance(calls, list) else []
        quoted: list[dict[str, Any]] = []
        seen: dict[str, dict[str, Any]] = {}
        reasons: dict[str, int] = defaultdict(int)
        subtotal = 0.0
        for call in calls:
            if not isinstance(call, dict):
                reasons["invalid_call_usage"] += 1
                continue
            usage = call.get("usage")
            usage = usage if isinstance(usage, dict) else {}
            call_id = call.get("call_id")
            if isinstance(call_id, str) and call_id:
                if call_id in seen:
                    if seen[call_id] != usage:
                        reasons["conflicting_call_usage"] += 1
                    continue
                seen[call_id] = usage
            model = call.get("model") or provenance.get("model")
            model = model if isinstance(model, str) else ""
            timestamp = call.get("created_at") or provenance.get("created_at")
            timestamp = timestamp if isinstance(timestamp, str) else None
            record = usage_record(usage, timestamp)
            price = select_price(prices.get(model, []), timestamp)
            amount, gaps = quote_record(record, price, record["input"])
            # A session-wide price tier cannot be guessed from one analysis request.
            if (
                price
                and price.get("context_scope") == "session"
                and price.get("long_context_threshold")
            ):
                amount, gaps = quote_record(record, price, None)
            subtotal += amount
            for gap in gaps:
                reasons[gap] += 1
            quoted.append(
                {
                    "call_id": call_id,
                    "chunk": call.get("chunk"),
                    "attempt": call.get("attempt"),
                    "model": model,
                    "estimated_usd": None if gaps else amount,
                    "known_subtotal_usd": amount,
                    "cost_status": (
                        "partial" if gaps and amount else "unknown" if gaps else "complete"
                    ),
                    "unknown_reasons": gaps,
                    "price": (
                        {key: value for key, value in price.items() if key != "mutation_id"}
                        if price
                        else None
                    ),
                }
            )
        if not quoted:
            reasons["missing_usage"] += 1
        complete = bool(quoted) and not reasons
        return {
            "basis": "api_equivalent_reference",
            "currency": "USD",
            "estimated_usd": subtotal if complete else None,
            "known_subtotal_usd": subtotal,
            "cost_status": "complete" if complete else "partial" if subtotal else "unknown",
            "actual_charge": None,
            "actual_charge_currency": None,
            "actual_charge_status": "unknown",
            "unknown_reason_counts": dict(reasons),
            "calls": quoted,
        }

    def ledger_revision(self, db: sqlite3.Connection | None = None) -> int:
        """Global winners, prices and corrections share one transactional revision."""
        if db is None:
            with self.connect() as connection:
                return self.ledger_revision(connection)
        revision = db.execute(
            "SELECT rowid FROM audit WHERE operation IN ('ingest','price','correct') "
            "ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        return revision[0] if revision else 0

    def _snapshot(self, owner: str | None, since: str = "", until: str = "") -> dict[str, Any]:
        # Public and session summaries share a compact aggregate snapshot.
        # Only ledger mutations invalidate it; raw uploads and request traces do not.
        key = (owner, since, until, self.ledger_revision())
        with self._overview_lock:
            if key not in self._overview_cache:
                # Two compact slots allow global/account alternation without retaining
                # unbounded owners or date filters. Evict before building a new value.
                if len(self._overview_cache) >= 2:
                    self._overview_cache.popitem(last=False)
                self._overview_cache[key] = self._calculate_overview(owner, since, until)
            self._overview_cache.move_to_end(key)
            return self._overview_cache[key]

    def overview(self, owner: str | None, since: str = "", until: str = "") -> dict[str, Any]:
        return {
            key: value
            for key, value in self._snapshot(owner, since, until).items()
            if key != "source_summaries"
        }

    def session_summaries(self, owner: str) -> list[dict[str, Any]]:
        return list(self._snapshot(owner)["source_summaries"])

    @staticmethod
    def interaction_availability(
        request_records: int, source: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Recorded request evidence is independent of token/byte coverage.

        An absent request ledger cannot prove zero interactions, even when the
        collector read every byte. User-role IR is not evidence of human origin.
        """
        source = source or {}
        complete = (
            source.get("read_bytes") == source.get("source_bytes")
            and source.get("read_bytes") is not None
            and source.get("errors") == 0
        )
        parser = str(source.get("parser", ""))
        request_contract = parser == "sparkstead-trajectory/3" or parser.startswith(
            "pi-native-measurements/1:"
        )
        coverage_complete = bool(request_records and complete and request_contract)
        return {
            "available": request_records > 0,
            "status": "observed" if request_records else "unknown",
            "request_records": request_records,
            "collector_parser": source.get("parser"),
            "reason": (
                "request_measurements_missing"
                if not request_records
                else None if coverage_complete else "request_collection_coverage_unverified"
            ),
            "coverage_status": (
                "complete" if coverage_complete else "partial" if request_records else "unknown"
            ),
            "collection_complete": complete,
        }

    @staticmethod
    def apply_interaction_availability(
        metrics: dict[str, Any], availability: dict[str, Any]
    ) -> None:
        if not availability["available"]:
            for key in INTERACTION_COUNTERS:
                metrics[key] = None

    def source_contributions(self, owner: str, collector: str, source: str) -> list[dict[str, Any]]:
        key = (owner, collector, source, self.ledger_revision())

        def load() -> list[dict[str, Any]]:
            # Separate from overview work: identical sources coalesce in the cache;
            # different cold sources retain a bounded number of global identity maps.
            with self._source_scan_slots:
                return list(
                    self._calculate_overview(owner, contribution_source=(collector, source))[
                        "event_contributions"
                    ]
                )

        selected: list[dict[str, Any]] = self._source_cache.get(key, load)
        return selected

    def _calculate_overview(
        self,
        owner: str | None,
        since: str = "",
        until: str = "",
        *,
        contribution_source: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        with self.connect() as db:
            db.execute("PRAGMA temp_store=FILE")
            db.execute("PRAGMA cache_size=-4096")
            db.execute("BEGIN")
            return self._calculate_snapshot(db, owner, since, until, contribution_source)

    def _calculate_snapshot(
        self,
        db: sqlite3.Connection,
        owner: str | None,
        since: str,
        until: str,
        contribution_source: tuple[str, str] | None,
    ) -> dict[str, Any]:
        where, params = (" WHERE owner=?", (owner,)) if owner else ("", ())
        sources = [dict(row) for row in db.execute("SELECT * FROM sources" + where, params)]
        corrections = {
            (r["owner"], r["task"]): dict(r)
            for r in db.execute("SELECT * FROM corrections" + where, params)
        }
        prices: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in db.execute("SELECT * FROM prices" + where + " ORDER BY effective", params):
            prices[(row["owner"], row["model"])].append(json.loads(row["body"]))
        source_coverage = {(row["owner"], row["collector"], row["source"]): row for row in sources}
        request_records: dict[tuple[str, str, str], int] = defaultdict(int)
        records = LedgerScan(db, owner, corrections)
        scoped_sessions = (
            records.source_sessions(contribution_source) if contribution_source else None
        )
        chronological = records.chronological(scoped_sessions)
        usages = UniqueUsages(records, sessions=scoped_sessions)

        def context_length(record: dict[str, Any]) -> int | None:
            if record["input"] is None:
                return None
            length = record["input"]
            if not record["input_includes_cache"]:
                if record["cached"] is None:
                    return None
                length += record["cached"]
            if record.get("input_includes_cache_write") is False:
                if record["cache_write"] is None:
                    return None
                length += record["cache_write"]
            elif record["cache_write"] and record.get("input_includes_cache_write") is None:
                return None
            return int(length)

        session_context: dict[tuple[str, str, str | None], int] = {}
        models: set[str] = set()
        for usage in usages:
            if scoped_sessions is not None and usage["session"] not in scoped_sessions:
                continue
            if usage.get("model"):
                models.add(usage["model"])
            length = context_length(usage)
            if length is not None:
                key = (usage["owner"], usage["session"], usage.get("model"))
                session_context[key] = max(session_context.get(key, 0), length)
        groups: dict[str, dict[str, Any]] = {}
        days: dict[str, dict[str, Any]] = {}
        tasks: dict[str, dict[str, Any]] = {}

        def human_metrics() -> dict[str, int]:
            return dict.fromkeys(INTERACTION_COUNTERS, 0)

        def bucket(key: str, name: str) -> dict[str, Any]:
            return {
                "id": key,
                "name": name,
                **human_metrics(),
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
                "known_subtotal_usd": 0.0,
                "priced_calls": 0,
                "unpriced_calls": 0,
                "unknown_reason_counts": {},
                "tool_seconds": 0.0,
                "tool_errors": 0,
                "active_seconds_estimate": 0.0,
            }

        def metric_bucket(
            targets: dict[str, dict[str, Any]], key: str, name: str
        ) -> dict[str, Any]:
            target = targets.get(key)
            if target is None:
                target = targets[key] = bucket(key, name)
            return target

        event_metrics: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        source_metrics: dict[tuple[str, str, str], dict[str, Any]] = {}
        token_events: set[tuple[str, str, str, str]] = set()

        def event_bucket(record: dict[str, Any]) -> dict[str, Any]:
            key = (record["owner"], record["collector"], record["source"], record["id"])
            if contribution_source is not None:
                target = event_metrics.get(key)
                if target is None:
                    target = event_metrics[key] = {
                        **bucket(record["id"], ""),
                        "record": record,
                        "recorded_tokens": records.tokens(record),
                    }
                return target
            source_key = key[:3]
            target = source_metrics.get(source_key)
            if target is None:
                target = source_metrics[source_key] = {
                    **bucket(record["source"], ""),
                    "record": {
                        field: record.get(field)
                        for field in (
                            "owner",
                            "collector",
                            "source",
                            "session",
                            "ecosystem",
                            "project",
                            "project_name",
                            "timestamp",
                        )
                    },
                    "recorded_tokens": 0,
                    "last_timestamp": "",
                }
            target["last_timestamp"] = max(target["last_timestamp"], record["timestamp"] or "")
            if record["kind"] == "usage" and key not in token_events:
                target["recorded_tokens"] += records.tokens(record)
                token_events.add(key)
            return target

        def event_targets(record: dict[str, Any]) -> list[dict[str, Any]]:
            if (
                contribution_source is not None
                and (record["collector"], record["source"]) != contribution_source
            ):
                return []
            return [event_bucket(record)]

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

        unknown_timestamps = 0
        for record in chronological:
            if record["kind"] == "request":
                request_records[(record["owner"], record["collector"], record["source"])] += 1
            unknown_timestamps += int(record["timestamp"] is None)
            if not included(record):
                continue
            project = record["project"]
            metric_bucket(groups, project, record["project_name"])
            task = tasks.get(record["task"])
            if task is None:
                task = tasks[record["task"]] = {
                    "id": record["task"],
                    "session": record["session"],
                    "project": project,
                    "project_name": record["project_name"],
                    "evidence": record["evidence"],
                    "started": record["timestamp"],
                    "ended": record["timestamp"],
                    "calls": 0,
                    "errors": 0,
                    **human_metrics(),
                    "source": record["source"],
                    "source_line": record["source_line"],
                }
            task["ended"] = record["timestamp"] or task["ended"]
            if record["evidence"] in ("path", "service", "corrected"):
                task.update(
                    project=project,
                    project_name=record["project_name"],
                    evidence=record["evidence"],
                )
        request_seen: set[tuple[str, ...]] = set()
        request_duplicates = 0
        requests = records.requests()
        for record in requests:
            if record["kind"] != "request" or not included(record):
                continue
            # Interaction identity hashes provider message identity and revision, never the text.
            request_identity = (
                (record["owner"], record["ecosystem"], record["interaction_id"])
                if record.get("interaction_id")
                else (record["owner"], record["collector"], record["source"], record["id"])
            )
            if request_identity in request_seen:
                request_duplicates += 1
                continue
            request_seen.add(request_identity)
            if scoped_sessions is not None and record["session"] not in scoped_sessions:
                continue
            day = date_for(record)
            targets = (
                groups[record["project"]],
                metric_bucket(days, day, day),
                tasks[record["task"]],
                *event_targets(record),
            )
            origin = record.get("input_origin")
            for target in targets:
                if origin == "human":
                    target["human_interactions"] += 1
                    chars = record.get("input_chars")
                    if chars is None:
                        target["missing_human_input_chars"] += 1
                    else:
                        target["human_input_chars"] += chars
                elif origin in ("agent", "system"):
                    target[origin + "_interactions"] += 1
                else:
                    target["unknown_origin_interactions"] += 1
        for record in usages:
            if scoped_sessions is not None and record["session"] not in scoped_sessions:
                continue
            if not included(record):
                continue
            day = date_for(record)
            daily = metric_bucket(days, day, day)
            project = metric_bucket(groups, record["project"], record["project_name"])
            candidates = prices.get((record["owner"], str(record.get("model") or "")), [])
            price = select_price(candidates, record["timestamp"])
            context = context_length(record)
            if price and price.get("context_scope") == "session":
                context = session_context.get(
                    (record["owner"], record["session"], record.get("model"))
                )
            subtotal, reasons = quote_record(record, price, context)
            cost = None if reasons else subtotal
            for target in (project, daily, *event_targets(record)):
                target["calls"] += 1
                if record["input"] is None or record["output"] is None:
                    target["unknown_usage"] += 1
                for field in ("input", "output", "cached", "cache_write", "reasoning"):
                    if record[field] is None:
                        target["missing_counters"][field] += 1
                    else:
                        target[field] += record[field]
                target["known_subtotal_usd"] += subtotal
                for reason in reasons:
                    counts = target["unknown_reason_counts"]
                    counts[reason] = counts.get(reason, 0) + 1
                if cost is None:
                    target["unpriced_calls"] += 1
                else:
                    target["priced_calls"] += 1
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
            target = metric_bucket(groups, start["project"], start["project_name"])
            target[metric] += (ending - beginning).total_seconds()
            for contribution in event_targets(start):
                contribution[metric] += (ending - beginning).total_seconds()
            while beginning < ending:
                day = beginning.date().isoformat()
                midnight = datetime.combine(beginning.date() + timedelta(days=1), time.min, zone)
                boundary = min(ending, midnight)
                metric_bucket(days, day, day)[metric] += (boundary - beginning).total_seconds()
                beginning = boundary

        starts: dict[tuple[str, str, str], dict[str, Any]] = {}
        from collections import deque

        anomalies: deque[dict[str, Any]] = deque(maxlen=200)
        previous: dict[tuple[str, str], dict[str, Any]] = {}
        for record in records.chronological(scoped_sessions):
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
                    metric_bucket(days, day, day)["tool_errors"] += 1
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
        for target in (
            *groups.values(),
            *days.values(),
            *event_metrics.values(),
            *source_metrics.values(),
        ):
            target["cost_status"] = (
                "complete"
                if not target["unpriced_calls"]
                else (
                    "partial"
                    if target["known_subtotal_usd"] > 0 or target["priced_calls"]
                    else "unknown"
                )
            )
            if target["unpriced_calls"]:
                target["estimated_usd"] = None
        # Reuse the existing ledger scan; no extra scan or per-source query.
        for target in chain(source_metrics.values(), event_metrics.values()):
            measured = target["record"]
            source_key = (measured["owner"], measured["collector"], measured["source"])
            availability = self.interaction_availability(
                request_records.get(source_key, 0), source_coverage.get(source_key)
            )
            target["interaction_availability"] = availability
            self.apply_interaction_availability(target, availability)
        return {
            **(
                {"event_contributions": list(event_metrics.values())} if contribution_source else {}
            ),
            "source_summaries": list(source_metrics.values()),
            "schema": "trajectory-overview/1",
            "generated_at": now(),
            "projects": sorted(
                groups.values(), key=lambda r: r["input"] + r["output"], reverse=True
            ),
            "daily": sorted(days.values(), key=lambda r: r["id"]),
            "tasks": list(reversed(list(tasks.values())))[:500],
            "anomalies": list(anomalies),
            "models": sorted(models),
            "coverage": {
                "sources": len(sources),
                "read_bytes": sum(r["read_bytes"] for r in sources),
                "source_bytes": sum(r["source_bytes"] for r in sources),
                "parse_errors": sum(r["errors"] for r in sources),
                "unknown_events": sum(r["unknown"] for r in sources),
                "latest_received": max((r["received"] for r in sources), default=None),
                "deduplicated_usage_records": usages.duplicates,
                "deduplicated_request_records": request_duplicates,
                "request_deduplication": "Account, ecosystem and provider message identity "
                "when present; "
                "otherwise account, collector, source and stable projection ID; "
                "cross-source copies without a provider message identity are not deduplicated",
                "unknown_timestamps": unknown_timestamps,
            },
            "pricing": {
                "currency": "USD",
                "unit": "per million tokens",
                "prices": [
                    {key: value for key, value in price.items() if key != "mutation_id"}
                    for versions in prices.values()
                    for price in versions
                ],
                "reference_assumptions": [
                    "Standard API reference rates; actual subscription bills, discounts, "
                    "service tiers and region adjustments are not recorded.",
                    "Context tiers use observed input length per request or maximum recorded "
                    "session input; incomplete session history can understate the applicable tier.",
                    "Current reference prices revalue historical usage, not historical bills.",
                    "Known subtotal excludes unknown components and is not a complete estimate.",
                ],
            },
            "methodology": {
                "human_input": (
                    "Human interactions require an explicit human origin on request records. "
                    "Characters are non-whitespace Unicode code points in textual input only; "
                    "images and other non-text attachments are not counted. Unknown origins "
                    "and missing human character counts are reported separately. "
                    "These counts measure recorded input, not elapsed human working time."
                ),
                "cost": "API-equivalent estimate, USD; missing rates or counters remain unknown; "
                "current reference rates revalue history and do not represent actual bills",
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
        """Export online, then persist file and directory before any success receipt."""
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as source, sqlite3.connect(target) as destination:
            source.backup(destination)
        target.chmod(0o600)
        with target.open("rb") as stream:
            os.fsync(stream.fileno())
        descriptor = os.open(target.parent, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def online_backup(self, actor: str, mutation: str) -> dict[str, Any]:
        directory = self.path.parent / "backups"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        parent_fd = os.open(directory.parent, os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        body = json.dumps({"operation": "backup", "mutation_id": mutation}, sort_keys=True)
        with (directory / "backup.lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            with self.connect() as db:
                prior = self._prior(db, actor, mutation, body)
            if prior:
                return prior
            target = directory / (
                hashlib.sha256((actor + ":" + mutation).encode()).hexdigest() + ".sqlite"
            )
            self.backup(target)
            with sqlite3.connect(f"file:{target}?mode=ro", uri=True) as check:
                valid = check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            if not valid:
                raise ValueError("Backup integrity verification failed")
            checksum = hashlib.sha256()
            with target.open("rb") as stream:
                while data := stream.read(1024 * 1024):
                    checksum.update(data)
            result = {
                "mutation_id": mutation,
                "path": str(target),
                "sha256": checksum.hexdigest(),
                "bytes": target.stat().st_size,
                "fsynced": True,
                "integrity_verified": True,
                "full_system_restore_verified": False,
                "created": now(),
            }
            with self.connect() as db:
                result = self._receipt(db, actor, mutation, body, "backup", result)
            return result
