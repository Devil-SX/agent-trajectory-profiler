"""Replayable SQLite scans: decoded events never form a global Python list."""

import json
import sqlite3
from collections.abc import Iterator
from typing import Any, cast

from trajectory.product.projects import classify_record, request_route


class LedgerScan:
    def __init__(
        self,
        db: sqlite3.Connection,
        owner: str | None,
        corrections: dict[Any, Any],
        *,
        source: tuple[str, str] | None = None,
    ):
        self.db, self.owner, self.corrections = db, owner, corrections
        self.params: tuple[Any, ...]
        self.where, self.params = (" WHERE owner=?", (owner,)) if owner else ("", ())
        self.routes: dict[tuple[str, str], tuple[str, str]] = {}
        extra = "json_extract(body,'$.kind')='request'"
        extra_params: tuple[Any, ...] = ()
        if source is not None:
            sessions = self.source_sessions(source)
            extra += (
                " AND json_extract(body,'$.task') IN (SELECT json_extract(body,'$.task') "
                "FROM events"
                + self.where
                + (" AND " if self.where else " WHERE ")
                + "json_extract(body,'$.session') IN (SELECT value FROM json_each(?)))"
            )
            extra_params = self.params + (json.dumps(sorted(sessions)),)
        for record in self._scan(extra, classify=False, extra_params=extra_params):
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
            yield self.decode(row, classify=classify)

    def decode(self, row: sqlite3.Row, *, classify: bool = True) -> dict[str, Any]:
        record: dict[str, Any] = json.loads(row["body"])
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
        return record

    def usage_candidates(
        self, sessions: set[str], *, relevant_only: bool = False
    ) -> Iterator[sqlite3.Row]:
        # Every account-wide candidate still participates in winner selection.
        # Only the eventual winner's selected session needs a decoded body. This
        # projection avoids sending unrelated event bodies to Python twice.
        where = self.where + (" AND " if self.where else " WHERE ")
        matching = ""
        params: tuple[Any, ...] = (json.dumps(sorted(sessions)),) + self.params
        if relevant_only:
            # A source detail needs only winners for identities appearing in its
            # sessions, but candidates from every session must still compete.
            matching = (
                " AND (json_extract(body,'$.ecosystem'),"
                "COALESCE(NULLIF(json_extract(body,'$.consumption'),''),"
                "json_extract(body,'$.id'))) IN ("
                "SELECT json_extract(body,'$.ecosystem'),"
                "COALESCE(NULLIF(json_extract(body,'$.consumption'),''),"
                "json_extract(body,'$.id')) FROM events"
                + self.where
                + (" AND " if self.where else " WHERE ")
                + "json_extract(body,'$.kind')='usage' AND "
                "json_extract(body,'$.session') IN (SELECT value FROM json_each(?)))"
            )
            params += self.params + (json.dumps(sorted(sessions)),)
        query = (
            "SELECT owner,collector,source,"
            "json_extract(body,'$.ecosystem') AS ecosystem,"
            "json_extract(body,'$.consumption') AS consumption,"
            "json_extract(body,'$.id') AS event_id,"
            "CASE WHEN json_extract(body,'$.session') IN "
            "(SELECT value FROM json_each(?)) THEN body END AS body "
            "FROM events"
            + where
            + "json_extract(body,'$.kind')='usage'"
            + matching
            + " ORDER BY "
            + self.ordering(True)
        )
        yield from self.db.execute(query, params)

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

    def requests(self, sessions: set[str] | None = None) -> Iterator[dict[str, Any]]:
        order = (
            "CASE WHEN json_extract(body,'$.input_origin')='human' THEN 1 ELSE 0 END DESC,"
            "CASE WHEN json_extract(body,'$.input_chars') IS NOT NULL THEN 1 ELSE 0 END DESC,"
            + self.ordering(True)
        )
        extra = "json_extract(body,'$.kind')='request'"
        params: tuple[Any, ...] = ()
        if sessions is not None:
            # Retain every account-wide competitor of a selected interaction.
            extra += (
                " AND (json_extract(body,'$.session') IN (SELECT value FROM json_each(?))"
                " OR (json_extract(body,'$.interaction_id') IS NOT NULL AND "
                "json_extract(body,'$.interaction_id') IN (SELECT "
                "json_extract(body,'$.interaction_id') FROM events"
                + self.where
                + (" AND " if self.where else " WHERE ")
                + "json_extract(body,'$.kind')='request' AND "
                "json_extract(body,'$.session') IN (SELECT value FROM json_each(?)))))"
            )
            selected = json.dumps(sorted(sessions))
            params = (selected,) + self.params + (selected,)
        return self._scan(extra, order=order, extra_params=params)

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
    def __init__(
        self, records: LedgerScan, *, sessions: set[str] | None = None, relevant_only: bool = False
    ):
        self.records = records
        self.sessions = sessions
        self.relevant_only = relevant_only
        self.duplicates = 0

    def __iter__(self) -> Iterator[dict[str, Any]]:
        seen: set[tuple[str, str, str]] = set()
        self.duplicates = 0
        candidates: Iterator[dict[str, Any] | sqlite3.Row]
        if self.sessions is None:
            candidates = self.records._scan(
                "json_extract(body,'$.kind')='usage'", order=self.records.ordering(True)
            )
        else:
            candidates = self.records.usage_candidates(
                self.sessions, relevant_only=self.relevant_only
            )
        for candidate in candidates:
            if self.sessions is None:
                record = cast(dict[str, Any], candidate)
                key = (
                    record["owner"],
                    record["ecosystem"],
                    record.get("consumption") or record["id"],
                )
            else:
                key = (
                    candidate["owner"],
                    candidate["ecosystem"],
                    candidate["consumption"] or candidate["event_id"],
                )
            if key in seen:
                self.duplicates += 1
                continue
            seen.add(key)
            if self.sessions is not None:
                if candidate["body"] is None:
                    continue
                record = self.records.decode(cast(sqlite3.Row, candidate))
            yield record
