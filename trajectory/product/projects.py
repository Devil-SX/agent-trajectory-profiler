"""Server-owned, conservative task attribution from protocol evidence."""

import hashlib
import re
from typing import Any

ALIASES = {
    "wenshu": ("wenshu", "文枢", "Paper-Library"),
    "singlou": ("singlou", "聲路", "声路", "Canto-Study"),
    "ops": ("BatCave-Ops", "哨台"),
    "identity": ("BatCave-Identity", "身份服务"),
    "calendar": ("Calendar-Service", "日轨"),
    "duzhi": ("Duzhi-Finance", "度支"),
    "panshi": ("panshi", "磐石"),
    "trajectory": ("BatCave-Trajectory", "trajectory", "profiler", "行迹"),
    "sparkstead": ("Sparkstead", "agent_watchboard", "agent-watchboard"),
}
NAMES = {key: values[1] for key, values in ALIASES.items()}
NAMES.update(identity="身份服务", trajectory="行迹 Trajectory", ops="哨台 Ops")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def identify(text: str, mapping: dict[str, Any], cwd: str = "") -> tuple[str, str]:
    # Broad discovery commands and inherited global instructions are not project work.
    hits: set[str] = set()
    for path, key in mapping["paths"].items():
        if path in text:
            hits.add(key)
    if len(hits) == 1:
        return next(iter(hits)), "path"
    if len(hits) > 1:
        return "shared", "path"
    service_hits = {
        service
        for service in ALIASES
        if re.search(r"(?:batcave (?:call|help)|/api/|/)(?:" + service + r")(?:\b|/)", text)
    }
    if len(service_hits) == 1:
        return next(iter(service_hits)), "service"
    explicit = {
        key
        for key, aliases in ALIASES.items()
        if text.lower() == key or any(alias.lower() in text.lower() for alias in aliases)
    }
    if len(explicit) == 1:
        return next(iter(explicit)), "request"
    if len(explicit) > 1:
        return "shared", "request"
    for path in sorted(mapping["paths"], key=len, reverse=True):
        if cwd == path or cwd.startswith(path + "/"):
            return mapping["paths"][path], "inherited"
    return "unassigned", "unknown"


def request_route(record: dict[str, Any]) -> tuple[str, str] | None:
    matches = [
        identify(reference, {"paths": {}, "names": NAMES})
        for reference in record.get("references", [])
    ]
    known = {key for key, _ in matches if key != "unassigned"}
    key = next(iter(known)) if len(known) == 1 else "shared" if known else "unassigned"
    return (key, "request") if key != "unassigned" else None


def classify_record(record: dict[str, Any], routes: dict[tuple[str, str], tuple[str, str]]) -> None:
    key, evidence = routes.get((record["owner"], record["task"]), ("unassigned", "unknown"))
    workspace = record.get("workspace")
    if key == "unassigned" and workspace:
        key, _ = identify(workspace, {"paths": {}, "names": NAMES})
        if key == "unassigned":
            key = "repo-" + digest(workspace)[:20]
        evidence = "inherited"
    record.update(
        project=key,
        project_name=NAMES.get(
            key,
            workspace if key.startswith("repo-") else "公共运维" if key == "shared" else "未归属",
        ),
        evidence=evidence,
    )


def classify_records(records: list[dict[str, Any]]) -> None:
    """Remote authority: references are evidence, never collector-computed attribution."""
    routes = {}
    for record in records:
        if record["kind"] == "request" and (route := request_route(record)) is not None:
            routes[(record["owner"], record["task"])] = route
    for record in records:
        classify_record(record, routes)
