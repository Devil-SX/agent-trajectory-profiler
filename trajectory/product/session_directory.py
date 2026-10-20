"""Lightweight source identity and routing, independent of usage aggregation."""

from __future__ import annotations

import json
from typing import Any

from trajectory.product.ledger_scan import LedgerScan
from trajectory.product.projects import classify_record


def source_directory(db: Any, owner: str) -> list[dict[str, Any]]:
    routes = LedgerScan(db, owner, {}).routes
    corrections = {
        row["task"]: row for row in db.execute("SELECT * FROM corrections WHERE owner=?", (owner,))
    }
    requests = {
        (row["collector"], row["source"]): row["records"]
        for row in db.execute(
            "SELECT collector,source,count(*) AS records FROM events "
            "WHERE owner=? AND json_extract(body,'$.kind')='request' GROUP BY collector,source",
            (owner,),
        )
    }
    result = []
    # Keep sources outermost: a reordered join probes the first event once for
    # every account event, rather than once for each indexed source.
    for row in db.execute(
        "SELECT s.collector,s.source,e.body,"
        "(SELECT max(json_extract(t.body,'$.timestamp')) FROM events t "
        "WHERE t.owner=s.owner AND t.collector=s.collector "
        "AND t.source=s.source) AS last_timestamp "
        "FROM sources s CROSS JOIN events e ON e.owner=s.owner AND e.collector=s.collector "
        "AND e.source=s.source AND e.id=(SELECT f.id FROM events f WHERE f.owner=s.owner "
        "AND f.collector=s.collector AND f.source=s.source ORDER BY f.id LIMIT 1) "
        "WHERE s.owner=?",
        (owner,),
    ):
        record = json.loads(row["body"])
        record.update(owner=owner, collector=row["collector"], source=row["source"])
        classify_record(record, routes)
        correction = corrections.get(record["task"])
        if correction:
            record.update(project=correction["project"], project_name=correction["name"])
        result.append(
            {
                "record": record,
                "last_timestamp": row["last_timestamp"] or "",
                "request_records": requests.get((row["collector"], row["source"]), 0),
            }
        )
    return result
