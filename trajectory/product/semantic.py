"""Source evidence, derived sessions and jobs owned by the existing domain database.

Raw content never generates another usage ledger. All displayed measures come
from Domain.overview's deduplicated event contributions.
"""

from __future__ import annotations

import base64
import bisect
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from trajectory.product.contracts import AnalysisRequest, SourceChunk, TaskEdit

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
                CREATE INDEX IF NOT EXISTS semantic_jobs_pending ON semantic_jobs(status,created);
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
    def _queue(db: Any, owner: str, sid: str, kind: str, revision: str) -> str:
        row = db.execute(
            "SELECT id FROM semantic_jobs WHERE owner=? AND session=? AND kind=? "
            "AND source_revision=? AND status IN ('queued','running','complete')",
            (owner, sid, kind, revision),
        ).fetchone()
        if row:
            return str(row[0])
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
                    "status": "queued",
                    "session_id": sid,
                },
            )

    def claim_job(self) -> dict[str, Any] | None:
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE semantic_jobs SET status='queued' WHERE status='running' AND updated<?",
                ((datetime.now(UTC) - timedelta(minutes=30)).isoformat(),),
            )
            row = db.execute(
                "SELECT * FROM semantic_jobs WHERE status='queued' ORDER BY created LIMIT 1"
            ).fetchone()
            if not row:
                return None
            db.execute(
                "UPDATE semantic_jobs SET status='running',updated=? WHERE id=?",
                (stamp(), row["id"]),
            )
            return dict(row)

    def finish_job(self, job: dict[str, Any], error: str = "") -> None:
        with self.domain.connect() as db:
            db.execute(
                "UPDATE semantic_jobs SET status=?,message=?,updated=? WHERE id=?",
                ("failed" if error else "complete", error[:500], stamp(), job["id"]),
            )

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
        return {
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
                "coverage": {"content_available": False, "collection": session["collection"]},
            }
        parsed = json.loads(record["body"])
        operations = parsed.get("operations", [])
        if contributions is None:
            contributions = self.domain.overview(owner, contributions=True)["event_contributions"]
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
                "SELECT * FROM semantic_jobs WHERE owner=? AND session=? AND kind='analyze' "
                "ORDER BY created DESC LIMIT 1",
                (owner, sid),
            ).fetchone()
        current_analysis = (
            analysis is not None and analysis["source_revision"] == record["source_revision"]
        )
        value = json.loads(analysis["body"]) if current_analysis else {"tasks": []}
        status = (
            "complete"
            if analysis and analysis["source_revision"] == record["source_revision"]
            else "not_started"
        )
        if (
            job
            and job["source_revision"] == record["source_revision"]
            and job["status"] in {"queued", "running", "failed"}
        ):
            status = job["status"]
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
        for operation in operations:
            operation["metrics"]["collection_status"] = collection["status"]
        parser_notes = list(parsed.get("warnings", []))
        generic_notes = (
            "upstream IR usage zero does not establish source availability;",
            "upstream parser accepts complete snapshots,",
            "source_records are retained for provenance,",
        )
        warnings = [note for note in parser_notes if not str(note).startswith(generic_notes)]
        if not attribution["ledger_available"]:
            warnings.append("尚未收到对应的用量账本，开销和人类投入保持未知。")
        elif not attribution["usage_available"]:
            warnings.append("尚未收到模型用量，token和费用保持未知。")
        if attribution["estimated_records"]:
            warnings.append("部分用量按源记录位置估计归属，任务级开销不是精确调用对齐。")
        return {
            "session": {
                "id": sid,
                "title": record["title"],
                "agent": record["agent"],
                "project": "",
                "metrics": metrics,
            },
            "status": status,
            "message": job["message"] if job and status == "failed" else "",
            "analysis_revision": analysis["revision"] if analysis else "",
            "source_revision": record["source_revision"],
            "generated_at": analysis["updated"] if analysis else None,
            "tasks": tasks,
            "operations": operations,
            "unassigned_operation_ids": [o["id"] for o in operations if o["id"] not in memberships],
            "provenance": value.get("provenance", {}),
            "coverage": {
                "parser": parsed.get("parser"),
                "parser_notes": parser_notes,
                "warnings": warnings,
                "content_available": True,
                "ledger_available": attribution["ledger_available"],
                "usage_available": attribution["usage_available"],
                "attribution": attribution,
                "collection": collection,
            },
        }

    def sessions(
        self, owner: str, project: str = "", since: str = "", until: str = ""
    ) -> dict[str, Any]:
        contributions = self.domain.overview(owner, contributions=True)["event_contributions"]
        groups: dict[str, list[dict[str, Any]]] = {}
        for contribution in contributions:
            event = contribution["record"]
            sid = self.session_id(event["collector"], event["source"])
            groups.setdefault(sid, []).append(contribution)
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
        recent_jobs = {row["session"]: row for row in jobs}
        items = []
        for sid in groups.keys() | records.keys():
            own = groups.get(sid, [])
            event = own[0]["record"] if own else {}
            record = records.get(sid, {})
            analysis = analyses.get(sid, {})
            status = (
                "complete"
                if analysis and analysis["source_revision"] == record.get("source_revision")
                else "not_started" if record else "partial"
            )
            job = recent_jobs.get(sid)
            if (
                job
                and job["source_revision"] == record.get("source_revision")
                and job["status"] in {"queued", "running", "failed"}
            ):
                status = job["status"]
            metrics = total_metrics(own)
            collection = ledger_sources.get(
                (
                    record.get("collector") or event.get("collector"),
                    record.get("source") or event.get("source"),
                ),
                collection_progress(None),
            )
            metrics["collection_status"] = collection["status"]
            item = {
                "id": sid,
                "title": record.get("title") or str(event.get("session", sid)),
                "agent": record.get("agent") or event.get("ecosystem", "unknown"),
                "project": event.get("project", "unassigned"),
                "project_name": event.get("project_name", "未归属"),
                "updated_at": record.get("updated")
                or max((c["record"].get("timestamp") or "" for c in own), default=""),
                "analysis_status": status,
                "metrics": metrics,
                "content_available": bool(record),
                "collection": collection,
            }
            if project and item["project"] != project:
                continue
            day = (item["updated_at"] or "")[:10]
            if day and ((since and day < since) or (until and day > until)):
                continue
            items.append(item)
        items.sort(key=lambda item: item["updated_at"] or "", reverse=True)
        return {
            "sessions": items,
            "next_cursor": None,
            "coverage": {
                "content_sessions": len(records),
                "total_sessions": len(items),
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
