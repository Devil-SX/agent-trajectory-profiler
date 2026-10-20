"""Account-owned immutable research snapshots, exclusive metrics and hierarchy diagnostics.

Study imports preserve an audited measurement snapshot, never create ledger usage,
rerun segmentation or turn classifier confidence into segmentation accuracy.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
import statistics
from collections import defaultdict
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trajectory.product.domain import Domain, now
from trajectory.product.read_cache import RevisionCache

TAGS = {
    "understand_decide": "理解与决策",
    "build_execute": "构建与执行",
    "validate_debug": "验证与纠错",
    "coordinate_maintain": "协调与维护",
    "uncertain": "待确认",
}
METRICS = (
    "recorded_tokens",
    "output",
    "calls",
    "active_seconds_estimate",
    "tool_seconds",
    "human_interactions",
    "human_input_chars",
    "wall_span_seconds",
    "prompt_buckets",
    "known_subtotal_usd",
)


class StageLabel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    session_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=3000)
    operation_ids: list[str] = Field(max_length=50000)
    primary_tag: str
    confidence: float = Field(ge=0, le=1)
    mixed_probability: float = Field(ge=0, le=1)
    probabilities: dict[str, float]
    secondary_tags: list[str] = Field(default_factory=list, max_length=4)
    call_id: str = Field(min_length=16, max_length=180)
    receipt_id: str = Field(min_length=16, max_length=100)
    metrics: dict[str, float | None]

    @model_validator(mode="after")
    def finite_semantics(self) -> StageLabel:
        if self.primary_tag not in TAGS or set(self.probabilities) != set(TAGS):
            raise ValueError("Unknown activity taxonomy")
        if any(not 0 <= v <= 1 for v in self.probabilities.values()):
            raise ValueError("Invalid class probabilities")
        if abs(sum(self.probabilities.values()) - 1) > 0.02:
            raise ValueError("Class probabilities must sum to one")
        if any(tag not in TAGS or tag == self.primary_tag for tag in self.secondary_tags):
            raise ValueError("Invalid secondary labels")
        if set(self.metrics) != set(METRICS):
            raise ValueError("Explicit known or null metrics required")
        if any(v is not None and v < 0 for v in self.metrics.values()):
            raise ValueError("Negative metric")
        if len(self.operation_ids) != len(set(self.operation_ids)):
            raise ValueError("Duplicate direct operation identity")
        return self


class StudySession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=128)
    analysis_revision: str = Field(min_length=1, max_length=128)
    source_revision: str = Field(min_length=1, max_length=128)
    measurement_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    segmentation: dict[str, Any]


class StageStudyImport(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mutation_id: str = Field(min_length=16, max_length=128)
    study_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    title: str = Field(min_length=1, max_length=150)
    batch_id: str = Field(min_length=1, max_length=128)
    sessions: list[StudySession] = Field(min_length=1, max_length=200)
    stages: list[StageLabel] = Field(min_length=1, max_length=10000)
    classification: dict[str, Any]
    measurement_policy: dict[str, Any]
    confidence_threshold: float = Field(default=0.5, ge=0, le=1)
    secondary_threshold: float = Field(default=0.2, ge=0, le=1)


def distribution(values: list[float | int | None]) -> dict[str, Any]:
    known = sorted(float(v) for v in values if v is not None)

    def quantile(p: float) -> float | None:
        if not known:
            return None
        position = (len(known) - 1) * p
        lo = int(position)
        return known[lo] + (known[min(lo + 1, len(known) - 1)] - known[lo]) * (position - lo)

    return {
        "available": len(known),
        "missing": len(values) - len(known),
        "mean": statistics.fmean(known) if known else None,
        "median": quantile(0.5),
        "p90": quantile(0.9),
        "min": known[0] if known else None,
        "max": known[-1] if known else None,
        "sum": sum(known) if known else None,
        "sample_sd": statistics.stdev(known) if len(known) > 1 else None,
        "sample_variance": statistics.variance(known) if len(known) > 1 else None,
    }


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + end - 1) / 2
        for index in order[start:end]:
            result[index] = rank
        start = end
    return result


def spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3 or len(set(x)) < 2 or len(set(y)) < 2:
        return None
    a, b = ranks(x), ranks(y)
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    denominator = math.sqrt(sum((v - ma) ** 2 for v in a) * sum((v - mb) ** 2 for v in b))
    return sum((u - ma) * (v - mb) for u, v in zip(a, b, strict=True)) / denominator


class StageStudies:
    def __init__(self, domain: Domain):
        self.domain = domain
        self.cache = RevisionCache(max_bytes=16 * 1024**2, max_entries=16)
        with domain.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS stage_studies(owner TEXT,id TEXT,revision TEXT,"
                "mutation TEXT,digest TEXT,title TEXT,body TEXT,created TEXT,"
                "PRIMARY KEY(owner,id),UNIQUE(owner,mutation))"
            )

    def import_study(self, owner: str, value: StageStudyImport) -> dict[str, Any]:
        payload = value.model_dump()
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(body.encode()).hexdigest()
        with self.domain.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT id,revision,digest FROM stage_studies WHERE owner=? AND "
                "(id=? OR mutation=?)",
                (owner, value.study_id, value.mutation_id),
            ).fetchall()
            if old:
                if len(old) != 1 or old[0]["digest"] != digest:
                    raise ValueError(
                        "Immutable study or mutation changed; create a new study identity"
                    )
                return {"study_id": old[0]["id"], "revision": old[0]["revision"], "replayed": True}
            sessions = {s.session_id: s for s in value.sessions}
            if len(sessions) != len(value.sessions):
                raise ValueError("Duplicate session")
            batch = db.execute(
                "SELECT owner FROM semantic_batches WHERE id=?", (value.batch_id,)
            ).fetchone()
            if batch is None or batch["owner"] != owner:
                raise PermissionError("Study batch unavailable for this account")
            batch_sessions = {
                r["session"]
                for r in db.execute(
                    "SELECT session FROM semantic_batch_items WHERE batch=?", (value.batch_id,)
                )
            }
            if not set(sessions) <= batch_sessions:
                raise ValueError("Study session is not part of the selected batch")
            saved: dict[tuple[str, str], dict[str, Any]] = {}
            metadata: dict[str, Any] = {}
            for sid, reference in sessions.items():
                row = db.execute(
                    "SELECT a.*,s.title,s.agent,m.body AS metadata FROM semantic_analyses a "
                    "JOIN semantic_sessions s ON s.owner=a.owner AND s.id=a.session "
                    "LEFT JOIN semantic_session_metadata m ON m.owner=s.owner AND m.session=s.id "
                    "WHERE a.owner=? AND a.session=?",
                    (owner, sid),
                ).fetchone()
                if not row:
                    raise PermissionError("Study session is not owned or has no saved analysis")
                if (row["revision"], row["source_revision"]) != (
                    reference.analysis_revision,
                    reference.source_revision,
                ):
                    raise ValueError("Analysis or source revision changed before study import")
                analysis = json.loads(row["body"])
                info = json.loads(row["metadata"]) if row["metadata"] else {}
                metadata[sid] = {
                    "title": info.get("display_title")
                    or info.get("first_user_message")
                    or row["title"],
                    "cwd": info.get("cwd"),
                    "agent": row["agent"],
                    "started_at": info.get("started_at"),
                }
                saved.update({(sid, t["id"]): t for t in analysis["tasks"]})
            rows = []
            seen: set[tuple[str, str]] = set()
            operation_ids: set[tuple[str, str]] = set()
            for stage in value.stages:
                identity = (stage.session_id, stage.task_id)
                if identity in seen or identity not in saved:
                    raise ValueError("Duplicate or unknown stage")
                seen.add(identity)
                task = saved[identity]
                if task.get("parent_id") is None:
                    raise ValueError("Session roots are not activity stages")
                if stage.title != task["title"] or stage.operation_ids != task["operation_ids"]:
                    raise ValueError("Stage title or direct operation membership changed")
                for oid in stage.operation_ids:
                    if (stage.session_id, oid) in operation_ids:
                        raise ValueError("An operation has multiple direct stage owners")
                    operation_ids.add((stage.session_id, oid))
                item = stage.model_dump(exclude={"operation_ids"})
                item.update(
                    parent_id=task.get("parent_id"), operation_count=len(stage.operation_ids)
                )
                rows.append(item)
            expected = {key for key, t in saved.items() if t.get("parent_id") is not None}
            if seen != expected:
                raise ValueError("Study must label every non-root stage in the selected analyses")
            payload.update(
                stages=rows,
                session_metadata=metadata,
                imported_at=now(),
                provenance_kind="authenticated_import_of_audited_frozen_measurements",
            )
            stored = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            db.execute(
                "INSERT INTO stage_studies VALUES(?,?,?,?,?,?,?,?)",
                (
                    owner,
                    value.study_id,
                    digest,
                    value.mutation_id,
                    digest,
                    value.title,
                    stored,
                    now(),
                ),
            )
            db.execute(
                "INSERT INTO audit VALUES(?,?,?,?,?)",
                (
                    owner,
                    value.mutation_id,
                    "stage_study_import",
                    json.dumps(
                        {"study_id": value.study_id, "revision": digest, "stages": len(rows)}
                    ),
                    now(),
                ),
            )
        return {
            "study_id": value.study_id,
            "revision": digest,
            "stages": len(rows),
            "unique_operations": len(operation_ids),
            "replayed": False,
            "model_calls": 0,
        }

    def catalog(self, owner: str) -> dict[str, Any]:
        with self.domain.connect() as db:
            rows = db.execute(
                "SELECT id,revision,title,created FROM stage_studies WHERE owner=? "
                "ORDER BY created DESC LIMIT 100",
                (owner,),
            ).fetchall()
        return {"items": [dict(row) for row in rows]}

    def _read(self, owner: str, study: str) -> dict[str, Any]:
        with self.domain.connect() as db:
            row = db.execute(
                "SELECT revision,body FROM stage_studies WHERE owner=? AND id=?", (owner, study)
            ).fetchone()
        if row is None:
            raise PermissionError("Study unavailable for this account")
        return cast(
            dict[str, Any],
            self.cache.get(
                (owner, study, row["revision"]),
                lambda: {**json.loads(row["body"]), "revision": row["revision"]},
            ),
        )

    def _prepared(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        rows = {(r["session_id"], r["task_id"]): dict(r) for r in data["stages"]}
        children: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows.values():
            sid = row["session_id"]
            row["effective_tag"] = (
                row["primary_tag"]
                if row["confidence"] >= data["confidence_threshold"]
                else "uncertain"
            )
            row["secondary_tags"] = [
                tag for tag in row["secondary_tags"] if tag != row["effective_tag"]
            ]
            children[(sid, row["parent_id"])].append(row)
        visiting: set[tuple[str, str]] = set()

        def populate(row: dict[str, Any]) -> None:
            key = (row["session_id"], row["task_id"])
            if "subtree_metrics" in row:
                return
            if key in visiting:
                raise ValueError("Task hierarchy contains a cycle")
            visiting.add(key)
            parent = rows.get((key[0], row["parent_id"]))
            depth, cursor, lineage = 1, parent, []
            while cursor:
                if cursor["task_id"] in lineage:
                    raise ValueError("Task hierarchy contains a cycle")
                lineage.append(cursor["task_id"])
                depth += 1
                cursor = rows.get((key[0], cursor["parent_id"]))
            row["depth"] = depth
            row["is_leaf"] = not bool(children[key])
            row["child_count"] = len(children[key])
            row["subtree_operation_count"] = row["operation_count"]
            row["subtree_metrics"] = dict(row["metrics"])
            if not row["operation_count"]:
                row["subtree_metrics"] = {
                    m: None if m in {"wall_span_seconds", "prompt_buckets"} else 0 for m in METRICS
                }
            row["subtree_stage_count"] = 1
            row["subtree_tag_operations"] = dict.fromkeys(TAGS, 0)
            row["subtree_tag_operations"][row["effective_tag"]] += row["operation_count"]
            for child in children[key]:
                populate(child)
                row["subtree_operation_count"] += child["subtree_operation_count"]
                row["subtree_stage_count"] += child["subtree_stage_count"]
                for metric in METRICS:
                    a, b = row["subtree_metrics"][metric], child["subtree_metrics"][metric]
                    # Wall span / prompt groups are not additive across descendants.
                    row["subtree_metrics"][metric] = (
                        None
                        if metric in {"wall_span_seconds", "prompt_buckets"}
                        or a is None
                        or b is None
                        else a + b
                    )
                for tag in TAGS:
                    row["subtree_tag_operations"][tag] += child["subtree_tag_operations"][tag]
            total = row["subtree_operation_count"]
            probabilities = [
                v / total for v in row["subtree_tag_operations"].values() if v and total
            ]
            row["subtree_tag_entropy"] = (
                -sum(p * math.log(p) for p in probabilities) / math.log(len(TAGS))
                if total
                else None
            )
            row["descendant_tag_count"] = len({c["effective_tag"] for c in children[key]})
            visiting.remove(key)

        for row in rows.values():
            populate(row)
        return list(rows.values())

    def select(
        self, owner: str, study: str, filters: dict[str, str]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        allowed = {
            "session_id",
            "depth",
            "node_kind",
            "tag",
            "membership",
            "q",
            "metric",
            "limit",
            "offset",
            "format",
            "confidence_min",
            "mixed",
        }
        if set(filters) - allowed:
            raise ValueError("Unknown study filter")
        data = self._read(owner, study)
        if filters.get("tag") and filters["tag"] not in TAGS:
            raise ValueError("Unknown activity tag")
        kind, membership = filters.get("node_kind", "all"), filters.get("membership", "direct")
        if kind not in {"all", "leaf", "parent"} or membership not in {"direct", "subtree"}:
            raise ValueError("Invalid hierarchy scope")
        if filters.get("depth") and not 1 <= int(filters["depth"]) <= 100:
            raise ValueError("Depth must be 1 to 100")
        minimum = float(filters.get("confidence_min", "0"))
        if not math.isfinite(minimum) or not 0 <= minimum <= 1:
            raise ValueError("Confidence minimum must be 0 to 1")
        mixture = filters.get("mixed", "all")
        if mixture not in {"all", "mixed", "single"}:
            raise ValueError("Unknown mixed-activity filter")
        rows = self._prepared(data)
        selected = [
            r
            for r in rows
            if (not filters.get("session_id") or r["session_id"] == filters["session_id"])
            and (not filters.get("depth") or r["depth"] == int(filters["depth"]))
            and (kind == "all" or r["is_leaf"] == (kind == "leaf"))
            and r["confidence"] >= minimum
            and (mixture == "all" or (r["mixed_probability"] >= 0.5) == (mixture == "mixed"))
            and (
                not filters.get("tag")
                or r["effective_tag"] == filters["tag"]
                or filters["tag"] in r["secondary_tags"]
            )
            and (
                not filters.get("q")
                or filters["q"].casefold() in (r["title"] + r["task_id"]).casefold()
            )
        ]
        for row in selected:
            row["selected_metrics"] = (
                row["metrics"] if membership == "direct" else row["subtree_metrics"]
            )
        return data, selected

    def stages(self, owner: str, study: str, filters: dict[str, str]) -> dict[str, Any]:
        data, rows = self.select(owner, study, filters)
        limit, offset = int(filters.get("limit", "50")), int(filters.get("offset", "0"))
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError("Invalid stage pagination")
        return {
            "study_id": study,
            "revision": data["revision"],
            "total": len(rows),
            "items": rows[offset : offset + limit],
            "next_offset": offset + limit if offset + limit < len(rows) else None,
        }

    def csv(self, owner: str, study: str, filters: dict[str, str]) -> str:
        data, rows = self.select(owner, study, filters)
        out = io.StringIO()
        fields = [
            "session_id",
            "task_id",
            "title",
            "parent_id",
            "depth",
            "is_leaf",
            "primary_tag",
            "effective_tag",
            "confidence",
            "mixed_probability",
            "secondary_tags",
            "operation_count",
            "subtree_operation_count",
            "subtree_tag_entropy",
            "call_id",
            "receipt_id",
            *METRICS,
        ]
        writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            item = {
                **row,
                **row["selected_metrics"],
                "secondary_tags": ",".join(row["secondary_tags"]),
            }
            # Spreadsheet formula injection is not a reason to mutate saved task titles.
            item["title"] = (
                "'" + item["title"]
                if item["title"].startswith(("=", "+", "-", "@"))
                else item["title"]
            )
            writer.writerow(item)
        return out.getvalue()

    def summary(self, owner: str, study: str, filters: dict[str, str]) -> dict[str, Any]:
        data, rows = self.select(owner, study, filters)
        metric = filters.get("metric", "recorded_tokens")
        if metric not in METRICS:
            raise ValueError("Unknown metric")
        key = ("summary", owner, study, data["revision"], tuple(sorted(filters.items())))
        result = cast(
            dict[str, Any],
            self.cache.get(key, lambda: self._summarize(data, rows, metric, filters)),
        )
        with self.domain.connect() as db:
            heads = {
                r["session"]: r["revision"]
                for r in db.execute(
                    "SELECT session,revision FROM semantic_analyses WHERE owner=?", (owner,)
                )
            }
        result["changed_analysis_sessions"] = [
            s["session_id"]
            for s in data["sessions"]
            if heads.get(s["session_id"]) != s["analysis_revision"]
        ]
        return result

    def _summarize(
        self, data: dict[str, Any], rows: list[dict[str, Any]], metric: str, filters: dict[str, str]
    ) -> dict[str, Any]:
        def group(group_rows: list[dict[str, Any]]) -> dict[str, Any]:
            n = len(group_rows)
            return {
                "stages": n,
                "direct_operations": sum(r["operation_count"] for r in group_rows),
                "leaf_stages": sum(r["is_leaf"] for r in group_rows),
                "direct_nonempty_stages": sum(bool(r["operation_count"]) for r in group_rows),
                "multiple_label_stages": sum(bool(r["secondary_tags"]) for r in group_rows),
                "multiple_label_rate": (
                    sum(bool(r["secondary_tags"]) for r in group_rows) / n if n else None
                ),
                "uncertain_rate": (
                    sum(r["effective_tag"] == "uncertain" for r in group_rows) / n if n else None
                ),
                "mixed_rate": (
                    sum(r["mixed_probability"] >= 0.5 for r in group_rows) / n if n else None
                ),
                "confidence": distribution([r["confidence"] for r in group_rows]),
                "mixed_probability": distribution([r["mixed_probability"] for r in group_rows]),
                "operation_count": distribution([r["operation_count"] for r in group_rows]),
                "subtree_operation_count": distribution(
                    [r["subtree_operation_count"] for r in group_rows]
                ),
                "subtree_tag_entropy": distribution([r["subtree_tag_entropy"] for r in group_rows]),
                "metric": distribution([r["selected_metrics"][metric] for r in group_rows]),
            }

        # Only selected nodes without a selected ancestor contribute subtree totals.
        identities = {(r["session_id"], r["task_id"]) for r in rows}
        all_rows = {(r["session_id"], r["task_id"]): r for r in self._prepared(data)}
        frontier = []
        for row in rows:
            parent = all_rows.get((row["session_id"], row["parent_id"]))
            overlaps = False
            while parent:
                overlaps |= (parent["session_id"], parent["task_id"]) in identities
                parent = all_rows.get((parent["session_id"], parent["parent_id"]))
            if not overlaps or filters.get("membership", "direct") == "direct":
                frontier.append(row)
        categories = []
        sessions = sorted({r["session_id"] for r in rows})
        for tag, name in TAGS.items():
            primary = [r for r in rows if r["effective_tag"] == tag]
            secondary = sum(tag in r["secondary_tags"] for r in rows)
            selected = [r for r in frontier if r["effective_tag"] == tag]
            known = [r for r in frontier if r["selected_metrics"][metric] is not None]
            denominator = sum(r["selected_metrics"][metric] for r in known)
            numerator = sum(
                r["selected_metrics"][metric]
                for r in selected
                if r["selected_metrics"][metric] is not None
            )
            cluster = []
            for sid in sessions:
                sr = [r for r in rows if r["session_id"] == sid]
                fk = [r for r in known if r["session_id"] == sid]
                cluster.append(
                    (
                        sum(r["effective_tag"] == tag for r in sr),
                        len(sr),
                        sum(r["selected_metrics"][metric] for r in fk if r["effective_tag"] == tag),
                        sum(r["selected_metrics"][metric] for r in fk),
                    )
                )
            randomizer = random.Random(20261020)
            stage_boot: list[float] = []
            resource_boot: list[float] = []
            resource_cluster = [x for x in cluster if x[3] > 0]
            if cluster:
                for _ in range(10000):
                    sample = [cluster[randomizer.randrange(len(cluster))] for _ in cluster]
                    stage_boot.append(sum(x[0] for x in sample) / sum(x[1] for x in sample))
            if resource_cluster:
                for _ in range(10000):
                    resource_sample = [
                        resource_cluster[randomizer.randrange(len(resource_cluster))]
                        for _ in resource_cluster
                    ]
                    resource_boot.append(
                        sum(x[2] for x in resource_sample) / sum(x[3] for x in resource_sample)
                    )

            def interval(values: list[float], units: int) -> list[float] | None:
                if units < 2 or not values:
                    return None
                values.sort()
                return [
                    values[int((len(values) - 1) * 0.025)],
                    values[int((len(values) - 1) * 0.975)],
                ]

            categories.append(
                {
                    "tag": tag,
                    "name": name,
                    **group(primary),
                    "secondary_stages": secondary,
                    "label_coverage": (len(primary) + secondary) / len(rows) if rows else None,
                    "stage_share": len(primary) / len(rows) if rows else None,
                    "stage_share_ci95": interval(stage_boot, len(cluster)),
                    "stage_share_sessions": len(cluster),
                    "session_stage_share_mean": (
                        statistics.fmean(x[0] / x[1] for x in cluster) if cluster else None
                    ),
                    "session_stage_share_sd": (
                        statistics.stdev(x[0] / x[1] for x in cluster) if len(cluster) > 1 else None
                    ),
                    "session_stage_share_variance": (
                        statistics.variance(x[0] / x[1] for x in cluster)
                        if len(cluster) > 1
                        else None
                    ),
                    "resource_known_subtotal": numerator if known else None,
                    "resource_share": numerator / denominator if denominator else None,
                    "resource_share_ci95": interval(resource_boot, len(resource_cluster)),
                    "resource_share_sessions": len(resource_cluster),
                    "session_resource_share_mean": (
                        statistics.fmean(x[2] / x[3] for x in resource_cluster)
                        if resource_cluster
                        else None
                    ),
                    "session_resource_share_sd": (
                        statistics.stdev(x[2] / x[3] for x in resource_cluster)
                        if len(resource_cluster) > 1
                        else None
                    ),
                    "session_resource_share_variance": (
                        statistics.variance(x[2] / x[3] for x in resource_cluster)
                        if len(resource_cluster) > 1
                        else None
                    ),
                    "resource_denominator_known_subtotal": denominator if known else None,
                }
            )
        depth_groups = [
            {"depth": depth, **group([r for r in rows if r["depth"] == depth])}
            for depth in sorted({r["depth"] for r in rows})
        ]
        depth_x = [float(r["depth"]) for r in rows]
        depth_relations = {}
        for target in ("mixed_probability", "confidence"):
            values = [r[target] for r in rows]
            rho = spearman(depth_x, values)
            by_session = {sid: [r for r in rows if r["session_id"] == sid] for sid in sessions}
            boot = []
            randomizer = random.Random(20261020)
            if rho is not None and len(sessions) > 1:
                for _ in range(300):
                    sample_rows = [
                        r
                        for _ in sessions
                        for r in by_session[sessions[randomizer.randrange(len(sessions))]]
                    ]
                    value = spearman(
                        [float(r["depth"]) for r in sample_rows], [r[target] for r in sample_rows]
                    )
                    if value is not None:
                        boot.append(value)
            boot.sort()
            depth_relations[target] = {
                "spearman_rho": rho,
                "session_cluster_ci95": (
                    [boot[int((len(boot) - 1) * 0.025)], boot[int((len(boot) - 1) * 0.975)]]
                    if boot
                    else None
                ),
                "sessions": len(sessions),
                "stages": len(rows),
                "bootstrap_replicates": 300,
                "interpretation": "Exploratory association, not proof of purity or causation",
            }
        return {
            "study_id": data["study_id"],
            "title": data["title"],
            "revision": data["revision"],
            "batch_id": data["batch_id"],
            "filters": filters,
            "metric": metric,
            "summary": group(rows),
            "sessions": [
                {**s, **data["session_metadata"].get(s["session_id"], {})} for s in data["sessions"]
            ],
            "categories": categories,
            "by_depth": depth_groups,
            "by_node_kind": [
                {"node_kind": kind, **group([r for r in rows if r["is_leaf"] == (kind == "leaf")])}
                for kind in ("leaf", "parent")
            ],
            "confidence_histogram": [
                sum(
                    i / 10 <= r["confidence"] < (i + 1) / 10 or i == 9 and r["confidence"] == 1
                    for r in rows
                )
                for i in range(10)
            ],
            "depth_relations": depth_relations,
            "resource_frontier_stages": len(frontier),
            "unique_resource_metric": distribution(
                [r["selected_metrics"][metric] for r in frontier]
            ),
            "classification": data["classification"],
            "confidence_threshold": data["confidence_threshold"],
            "secondary_threshold": data["secondary_threshold"],
            "measurement_policy": data["measurement_policy"],
            "segmentation_confidence": None,
            "human_gold_accuracy": None,
            "uncertainty_method": "10000 session-cluster percentile bootstrap, seed20261020; "
            "at least2 sessions; missing denominators omitted",
            "limitations": [
                "分类模型confidence不是分段置信度或人工准确率。当前没有随机人工gold。",
                "统计区间未覆盖分段错误、模型错标和定向筛选偏差，不代表总体或因果结论。",
                "没有直接操作的父节点仍保留原始模型标签，不能把它的混合判断当作直接操作证据。",
                "次标签覆盖率可超过100%，主标签份额才使用互斥分母。",
                "子树总量使用无重叠选中祖先前沿，逐行子树指标不可再相加。",
                "这是固定源版本的审计快照，不随原会话追加自动重新分类。",
                "历史人类交互缺口保留未知，活跃时间估计不等于LLM请求延时。",
            ],
        }
