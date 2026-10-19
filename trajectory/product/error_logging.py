"""Server-only exception locations without messages, source lines or local values."""

import json
import logging
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
        exceptions.append({"type": type(current).__name__, "frames": frames})
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
