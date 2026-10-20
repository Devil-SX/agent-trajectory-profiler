#!/usr/bin/env python3
"""Repair request measurements using the existing collector identity/projector.

No usage writes, no collector checkpoint changes, no transcript text in output.
Shares the raw uploader's OS lock so Sparkstead and Agent invocations serialize.
"""

import argparse
import hashlib
import json
import re
import subprocess
import urllib.request
from pathlib import Path

import trajectory_source_sync as sync


def project(spec, source, end, projector, node):
    command = [node, str(Path(__file__).with_name("trajectory_request_projection.mjs"))]
    request = {
        "projector": str(Path(projector).resolve(strict=True)),
        "path": spec["path"],
        "source": source,
        "ecosystem": spec["ecosystem"],
        "end": end,
    }
    completed = subprocess.run(
        command, input=json.dumps(request), text=True, capture_output=True, timeout=180, check=True
    )
    result = json.loads(completed.stdout)
    return result


def run(config, projector, node="node", sources=(), sessions=(), max_sources=20, apply=False):
    collector, specs = sync.validate_manifest(config)
    native_sources = {}
    for spec in specs:
        matches = re.findall(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", Path(spec["path"]).name, re.IGNORECASE
        )
        for native in matches:
            native_sources.setdefault(native.lower(), set()).add(
                sync.source_id(collector, spec["legacy_path"])
            )
    specs = sync.select_sources(collector, specs, sources, sessions)
    token = sync.credentials(Path(config["credential"]), config["url"])
    endpoint = config["url"].rsplit("/", 1)[0] + "/request-measurements/repair"
    outcomes = []
    projector_digest = hashlib.sha256(Path(projector).read_bytes()).hexdigest()
    with sync.process_lock(Path(config["state"]).with_suffix(".lock")):
        for spec in specs[:max_sources]:
            source = sync.source_id(collector, spec["legacy_path"])
            if spec["ecosystem"] not in ("codex", "claude_code"):
                outcomes.append({"source": source, "status": "native_producer"})
                continue
            try:
                progress = sync.remote_progress(config, collector, source, token)
                if not progress.get("ledger_revision") or not progress.get("next_offset"):
                    outcomes.append(
                        {"source": source, "status": "missing_archived_or_ledger_evidence"}
                    )
                    continue
                projected = project(spec, source, progress["next_offset"], projector, node)
                if hashlib.sha256(Path(projector).read_bytes()).hexdigest() != projector_digest:
                    raise ValueError("Projector changed during request measurement")
                # Multiple archived copies of one native session need an explicit
                # provider message identity. Do not guess identity from text/time.
                ambiguous = [
                    record
                    for record in projected["records"]
                    if record.get("input_origin") == "human"
                    and not record.get("interaction_id")
                    and len(native_sources.get(str(record.get("session", "")).lower(), set())) > 1
                ]
                ambiguous_ids = {record["id"] for record in ambiguous}
                projected["records"] = [
                    record
                    for record in projected["records"]
                    if record.get("id") not in ambiguous_ids
                ]
                projected["quarantined_source_lines"] = sorted(
                    set(
                        projected.get("quarantined_source_lines", [])
                        + [record["source_line"] for record in ambiguous]
                    )
                )
                source_revision = sync.digest(
                    f"{progress['generation']}:{progress['next_offset']}".encode()
                )
                body = {
                    "collector": collector,
                    "source": source,
                    "projector_sha256": projector_digest,
                    "expected_ledger_revision": progress["ledger_revision"],
                    "quarantined_source_lines": projected.get("quarantined_source_lines", []),
                    "source_revision": source_revision,
                    **{
                        key: projected[key]
                        for key in ("parser_version", "complete_bytes", "source_sha256", "records")
                    },
                }
                body["mutation_id"] = hashlib.sha256(
                    json.dumps(body, sort_keys=True).encode()
                ).hexdigest()
                outcome = {
                    "source": source,
                    "status": "ready",
                    "requests": len(projected["records"]),
                    "identity_unverified_requests": len(ambiguous),
                    "human_requests": sum(
                        r.get("input_origin") == "human" for r in projected["records"]
                    ),
                }
                if apply:
                    request = urllib.request.Request(
                        endpoint,
                        data=json.dumps(body).encode(),
                        headers={
                            "Authorization": "Bearer " + token,
                            "Content-Type": "application/json",
                        },
                        method="POST",
                    )
                    with sync.http_opener(config).open(request, timeout=180) as response:
                        receipt = json.loads(response.read(65537))
                    if receipt.get("mutation_id") != body["mutation_id"] or not receipt.get(
                        "durable"
                    ):
                        raise ValueError("Invalid durable measurement receipt")
                    if Path(config["state"]).exists():
                        state = sync.SyncState(Path(config["state"]))
                        try:
                            state.finish_request_repair(
                                source, progress["generation"], progress["next_offset"]
                            )
                        finally:
                            state.close()
                    outcome.update(status="repaired", receipt=receipt)
                outcomes.append(outcome)
            except Exception as error:
                outcomes.append(
                    {"source": source, "status": "deferred", "error": type(error).__name__}
                )
            finally:
                if (
                    apply
                    and Path(config["state"]).exists()
                    and outcomes[-1]["status"] != "repaired"
                ):
                    state = sync.SyncState(Path(config["state"]))
                    try:
                        state.defer_request_repair(source)
                    finally:
                        state.close()
    return {
        "collector": collector,
        "apply": apply,
        "sources": outcomes,
        "usage_writes": 0,
        "collector_checkpoint_writes": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--projector", required=True, help="Bundled current Sparkstead trajectory projector"
    )
    parser.add_argument("--node", default="node")
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--session", action="append", default=[])
    parser.add_argument("--max-sources", type=int, default=20)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.max_sources <= 10000:
        parser.error("max-sources must be 1..10000")
    config = json.loads(args.config.read_text())
    result = run(
        config, args.projector, args.node, args.source, args.session, args.max_sources, args.apply
    )
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "deferred", "error": type(error).__name__}))
        raise SystemExit(1) from None
