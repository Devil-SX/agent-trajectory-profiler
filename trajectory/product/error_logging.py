"""Server-only exception locations without messages, source lines or local values."""

import json
import logging
import sqlite3
from typing import Any

LOGGER = logging.getLogger("trajectory.request_errors")


def log_request_exception(request_id: str, error: BaseException) -> None:
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    exceptions: list[dict[str, Any]] = []
    frame_budget = 80
    while pending and len(exceptions) < 8:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        frames = []
        trace = current.__traceback__
        while trace is not None and frame_budget:
            code = trace.tb_frame.f_code
            frames.append(
                {"file": code.co_filename, "function": code.co_name, "line": trace.tb_lineno}
            )
            frame_budget -= 1
            trace = trace.tb_next
        entry: dict[str, Any] = {"type": type(current).__name__, "frames": frames}
        if isinstance(current, sqlite3.Error):
            sqlite_code = getattr(current, "sqlite_errorcode", None)
            name = getattr(current, "sqlite_errorname", None)
            if isinstance(sqlite_code, int):
                entry["sqlite_errorcode"] = sqlite_code
            if (
                isinstance(name, str)
                and name.startswith("SQLITE_")
                and all(character in "ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789" for character in name)
            ):
                entry["sqlite_errorname"] = name
        exceptions.append(entry)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        elif current.__context__ is not None and not current.__suppress_context__:
            pending.append(current.__context__)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions[:8])
    # Never pass exc_info, exception objects, request objects, message values,
    # formatted source lines, locals or caller-provided identifiers to logging.
    LOGGER.error(
        "request_failure %s", json.dumps({"request_id": request_id, "exceptions": exceptions})
    )
