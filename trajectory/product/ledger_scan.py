"""Replayable SQLite scans: decoded events never form a global Python list."""

import json
import sqlite3
from collections.abc import Iterator
from typing import Any

from trajectory.product.projects import classify_record, request_route


class LedgerScan:
    def __init__(self, db: sqlite3.Connection, owner: str | None, corrections: dict[Any, Any]):
        self.db, self.owner, self.corrections = db, owner, corrections
        self.params: tuple[Any, ...]
        self.where, self.params = (" WHERE owner=?", (owner,)) if owner else ("", ())
        self.routes: dict[tuple[str, str], tuple[str, str]] = {}
        for record in self._scan("json_extract(body,'$.kind')='request'", classify=False):
            route = request_route(record)
            if route is not None:
                self.routes[(record["owner"], record["task"])] = route

    def _scan(
        self,
        extra: str = "",
        *,
        order: str = "",
        classify: bool = True,
        extra_params: tuple[Any, ...] = (),
    ) -> Iterator[dict[str, Any]]:
        where = self.where + ((" AND " if self.where else " WHERE ") + extra if extra else "")
        query = "SELECT owner,collector,source,body FROM events" + where
        if order:
            query += " ORDER BY " + order
        for row in self.db.execute(query, self.params + extra_params):
            record = json.loads(row["body"])
            record.update(owner=row["owner"], collector=row["collector"], source=row["source"])
            if classify:
                classify_record(record, self.routes)
                correction = self.corrections.get((record["owner"], record["task"]))
                if correction:
                    record.update(
                        project=correction["project"],
                        project_name=correction["name"],
                        evidence="corrected",
                    )
            yield record

    def ordering(self, reverse: bool = False) -> str:
        direction = " DESC" if reverse else " ASC"
        tie = ("collector", "source", "id") if self.owner else ("rowid",)
        fields = (
            "COALESCE(json_extract(body,'$.timestamp'),'')",
            "json_extract(body,'$.source_line')",
            *tie,
        )
        return ",".join(field + direction for field in fields)

    def chronological(self, sessions: set[str] | None = None) -> Iterator[dict[str, Any]]:
        if sessions is None:
            return self._scan(order=self.ordering())
        return self._scan(
            "json_extract(body,'$.session') IN (SELECT value FROM json_each(?))",
            order=self.ordering(),
            extra_params=(json.dumps(sorted(sessions)),),
        )

    def requests(self) -> Iterator[dict[str, Any]]:
        order = (
            "CASE WHEN json_extract(body,'$.input_origin')='human' THEN 1 ELSE 0 END DESC,"
            "CASE WHEN json_extract(body,'$.input_chars') IS NOT NULL THEN 1 ELSE 0 END DESC,"
            + self.ordering(True)
        )
        return self._scan("json_extract(body,'$.kind')='request'", order=order)

    def source_sessions(self, source: tuple[str, str]) -> set[str]:
        where = self.where + (" AND " if self.where else " WHERE ") + "collector=? AND source=?"
        return {
            row[0]
            for row in self.db.execute(
                "SELECT DISTINCT json_extract(body,'$.session') FROM events" + where,
                self.params + source,
            )
        }

    @staticmethod
    def tokens(record: dict[str, Any]) -> int:
        if record["kind"] != "usage":
            return 0
        tokens = (record.get("input") or 0) + (record.get("output") or 0)
        if not record.get("input_includes_cache"):
            tokens += record.get("cached") or 0
        if record.get("input_includes_cache_write") is False:
            tokens += record.get("cache_write") or 0
        return int(tokens)


class UniqueUsages:
    def __init__(self, records: LedgerScan):
        self.records = records
        self.duplicates = 0

    def __iter__(self) -> Iterator[dict[str, Any]]:
        seen: set[tuple[str, str, str]] = set()
        self.duplicates = 0
        for record in self.records._scan(
            "json_extract(body,'$.kind')='usage'", order=self.records.ordering(True)
        ):
            key = (record["owner"], record["ecosystem"], record.get("consumption") or record["id"])
            if key in seen:
                self.duplicates += 1
                continue
            seen.add(key)
            yield record
