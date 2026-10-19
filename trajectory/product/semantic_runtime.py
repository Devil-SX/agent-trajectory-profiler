"""Restartable background analysis; one leased worker, no work in browser requests."""

from __future__ import annotations

import fcntl
import json
import os
import selectors
import subprocess
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from trajectory.product.semantic import SemanticStore, digest
from trajectory.product.semantic_model import AnalysisPaused


class AnalysisRuntime:
    def __init__(self, store: SemanticStore):
        self.store = store
        self.child: subprocess.Popen[str] | None = None
        self.lock = threading.Lock()
        self.parser_lock = threading.Lock()
        self.capacity = max(1, min(8, int(os.environ.get("TRAJECTORY_ANALYSIS_CONCURRENCY", "4"))))
        self.pool = ThreadPoolExecutor(max_workers=self.capacity)
        self.futures: set[Future[bool]] = set()
        self.lease: Any = None
        self.stopping = False
        self.root = store.domain.path.parent / "analysis-artifacts"

    def close(self) -> None:
        self.stopping = True
        self.pool.shutdown(wait=True)
        self._close_parser()
        if self.lease is not None:
            self.lease.close()
            self.lease = None

    def _close_parser(self) -> None:
        if self.child is not None:
            self.child.terminate()
            try:
                self.child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.child.kill()
            self.child = None

    def parse(self, path: Path, source: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
        binary = os.environ.get("TRAJECTORY_SESSION_WORKER")
        if not binary:
            raise ValueError("Session parser is not installed")
        if self.child is None or self.child.poll() is not None:
            self.child = subprocess.Popen(
                [binary],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        assert self.child.stdin is not None and self.child.stdout is not None
        request = {
            "id": job["id"],
            "op": "parse",
            "source_id": source["source"],
            "agent": "claude" if source["ecosystem"] == "claude_code" else source["ecosystem"],
            "input_file": str(path),
            "source_path": source["source_name"],
        }
        self.child.stdin.write(json.dumps(request) + "\n")
        self.child.stdin.flush()
        with selectors.DefaultSelector() as selector:
            selector.register(self.child.stdout, selectors.EVENT_READ)
            if not selector.select(timeout=180):
                self._close_parser()
                raise ValueError("Session parser timed out")
        output = self.child.stdout.readline()
        value: dict[str, Any] = json.loads(output)
        if value.get("id") != job["id"] or not value.get("ok"):
            raise ValueError("Session parser rejected source; inspect source coverage")
        result: dict[str, Any] = value["result"]
        return result

    def _coordinate(self) -> bool:
        gate = os.environ.get("TRAJECTORY_WORKER_GATE")
        if self.stopping or (gate and not Path(gate).is_file()):
            return False
        if self.lease is None:
            lease = (self.store.domain.path.parent / "analysis-worker.lock").open("a")
            try:
                fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lease.close()
                return False
            self.lease = lease
            self.store.recover_jobs()
        return True

    def _pause_requested(self) -> bool:
        gate = os.environ.get("TRAJECTORY_WORKER_GATE")
        return self.stopping or bool(gate and not Path(gate).is_file())

    def tick(self) -> bool:
        """Dispatch independent sessions while one process owns the coordinator lease."""
        with self.lock:
            self.futures = {future for future in self.futures if not future.done()}
            # Relinquish the lease only after natural drain, before handoff.
            gate = os.environ.get("TRAJECTORY_WORKER_GATE")
            if not self.futures and gate and not Path(gate).is_file() and self.lease:
                self.lease.close()
                self.lease = None
            if not self._coordinate():
                return False
            dispatched = False
            while len(self.futures) < self.capacity:
                job = self.store.claim_job()
                if job is None:
                    break
                self.futures.add(self.pool.submit(self._process_job, job))
                dispatched = True
            return dispatched

    def process_next(self) -> bool:
        """Synchronous single-job entry retained for isolated integration exercises."""
        with self.lock:
            if not self._coordinate():
                return False
            job = self.store.claim_job()
            return self._process_job(job) if job is not None else False

    def _process_job(self, job: dict[str, Any]) -> bool:
        try:
            directory = (
                self.root / digest(job["owner"])[:24] / job["session"] / job["source_revision"]
            )
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if job["kind"] == "parse":
                source, chunks = self.store.archive(job["owner"], job["session"])
                actual = digest(source["generation"] + ":" + str(source["received_bytes"]))
                if actual != job["source_revision"]:
                    self.store.finish_job(job)
                    return True
                source_file = directory / "source.jsonl"
                try:
                    with source_file.open("wb") as stream:
                        for chunk in chunks:
                            stream.write(chunk)
                    source_file.chmod(0o600)
                    with self.parser_lock:
                        parsed = self.parse(source_file, source, job)
                    self.store.save_session(job["owner"], job["session"], source, actual, parsed)
                finally:
                    # The domain archive is the authority; this is only parser input.
                    source_file.unlink(missing_ok=True)
            else:
                from trajectory.product.semantic_model import PROMPT_VERSION, segment

                record = self.store.session_record(
                    job["owner"], job["session"], source_revision=job["source_revision"]
                )
                if record["source_revision"] != job["source_revision"]:
                    raise ValueError("Source changed; request analysis of current revision")
                parsed = json.loads(record["body"])
                raw_input = {"operations": parsed.get("operations", []), "title": record["title"]}
                input_context = {
                    "source_revision": job["source_revision"],
                    "ir_body_sha256": digest(record["body"]),
                    "session_id": job["session"],
                    "owner_hash": digest(job["owner"]),
                }
                self.store.pin_execution(
                    job,
                    {
                        "model": os.environ.get("TRAJECTORY_MODEL_NAME", ""),
                        "route": os.environ.get("TRAJECTORY_JINDU_ROUTE", ""),
                        "reasoning_effort": os.environ.get("TRAJECTORY_MODEL_REASONING_EFFORT", ""),
                        "prompt_version": PROMPT_VERSION,
                        "source_revision": job["source_revision"],
                        "input_chars": os.environ.get("TRAJECTORY_MODEL_INPUT_CHARS", "24000"),
                        "operation_chars": os.environ.get(
                            "TRAJECTORY_MODEL_OPERATION_CHARS", "2000"
                        ),
                        "output_tokens": os.environ.get("TRAJECTORY_MODEL_OUTPUT_TOKENS", "8192"),
                    },
                )
                checkpoint = directory / "model-result.json"
                result = json.loads(checkpoint.read_text()) if checkpoint.is_file() else None
                if (
                    result is None
                    or result.get("provenance", {}).get("model")
                    != os.environ.get("TRAJECTORY_MODEL_NAME")
                    or result.get("provenance", {}).get("route")
                    != os.environ.get("TRAJECTORY_JINDU_ROUTE", "")
                    or result.get("provenance", {}).get("reasoning_effort", "")
                    != os.environ.get("TRAJECTORY_MODEL_REASONING_EFFORT", "")
                    or result.get("provenance", {}).get("prompt_version") != PROMPT_VERSION
                ):
                    resume = self.store.resume_context(job)
                    input_checkpoint = directory / ("chunks-" + job["id"] + ".json")
                    legacy_paths = [
                        input_checkpoint,
                        input_checkpoint.with_name(input_checkpoint.name + ".v2"),
                    ]
                    if not input_checkpoint.with_name(
                        input_checkpoint.name + ".input.json"
                    ).exists() and any(
                        path.exists() or path.with_name(path.name + ".calls").exists()
                        for path in legacy_paths
                    ):
                        # Existing paid inputs used the legacy display projection.
                        # It may be frozen only after its original full identity matches.
                        detail = self.store.detail(
                            job["owner"], job["session"], source_revision=job["source_revision"]
                        )
                        execution_input = {
                            "operations": detail["operations"],
                            "title": detail["session"]["title"],
                        }
                    else:
                        execution_input = raw_input
                    result = segment(
                        execution_input["operations"],
                        execution_input["title"],
                        analysis_id=job["id"],
                        prior_progress=resume["prior_progress"],
                        resume_generation=resume["generation"],
                        authorized_recomputations=resume["authorized_recomputations"],
                        checkpoint=input_checkpoint,
                        source_context=input_context,
                        fresh_input=raw_input,
                        progress=lambda value: self.store.job_progress(job, value),
                        should_pause=self._pause_requested,
                    )
                    temporary = checkpoint.with_name(".model-result-" + job["id"] + ".json")
                    try:
                        descriptor = os.open(
                            temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600
                        )
                        with os.fdopen(descriptor, "w") as out:
                            json.dump(result, out, ensure_ascii=False)
                            out.flush()
                            os.fsync(out.fileno())
                        os.replace(temporary, checkpoint)
                        directory_fd = os.open(directory, os.O_DIRECTORY)
                        try:
                            os.fsync(directory_fd)
                        finally:
                            os.close(directory_fd)
                    finally:
                        temporary.unlink(missing_ok=True)
                detail = self.store.detail(
                    job["owner"], job["session"], source_revision=job["source_revision"]
                )
                result["provenance"]["source_revision"] = job["source_revision"]
                result["provenance"]["profiler"] = self.profile(directory, detail, result)
                self.store.save_analysis(
                    job["owner"],
                    job["session"],
                    job["source_revision"],
                    result,
                    expected_revision=detail["analysis_revision"],
                )
            self.store.finish_job(job)
            return True
        except AnalysisPaused:
            self.store.park_job(job)
            return True
        except Exception as error:
            if job is not None:
                # Never return provider response bodies or private source content in errors.
                from trajectory.product.semantic_model import SemanticModelError

                message = (
                    str(error)
                    if isinstance(error, (ValueError, SemanticModelError))
                    else type(error).__name__
                )
                self.store.finish_job(job, message[:300])
                provenance = getattr(error, "provenance", None)
                if provenance:
                    # Failed provider calls remain visible as analysis overhead.
                    with self.store.domain.connect() as db:
                        db.execute(
                            "INSERT INTO audit VALUES(?,?,?,?,?)",
                            (
                                job["owner"],
                                job["id"],
                                "analysis.failed",
                                json.dumps(
                                    {"session_id": job["session"], "provenance": provenance}
                                ),
                                __import__("datetime")
                                .datetime.now(__import__("datetime").UTC)
                                .isoformat(),
                            ),
                        )
            return True

    def profile(
        self, directory: Path, detail: dict[str, Any], analysis: dict[str, Any]
    ) -> dict[str, Any]:
        binary = os.environ.get("TRAJECTORY_AGENTPPROF")
        if not binary:
            raise ValueError("Task profiler is not installed")
        tasks = {t["id"]: t for t in analysis["tasks"]}
        membership = {
            oid: task["id"] for task in tasks.values() for oid in task.get("operation_ids", [])
        }
        root = "source-root"
        trace: list[dict[str, Any]] = [
            {
                "id": root,
                "parent": None,
                "kind": "session",
                "data": {"name": detail["session"]["title"]},
                "metrics": {},
                "path": [],
            }
        ]
        annotations: dict[str, Any] = {root: {"tag": "分析会话", "parent": None, "next": None}}
        active: list[tuple[str, str]] = []
        for index, operation in enumerate(detail["operations"]):
            task_id = membership.get(operation["id"])
            path: list[str] = []
            visited: set[str] = set()
            while task_id is not None:
                if task_id in visited or task_id not in tasks:
                    raise ValueError("Invalid task hierarchy")
                visited.add(task_id)
                path.insert(0, task_id)
                task_id = tasks[task_id].get("parent_id")
            shared = 0
            while shared < min(len(path), len(active)) and path[shared] == active[shared][0]:
                shared += 1
            boundary = f"mark-{index}-{shared}" if len(path) > shared else operation["id"]
            for _, node_id in active[shared:]:
                annotations[node_id]["next"] = boundary
            active = active[:shared]
            for depth, tid in enumerate(path[shared:], start=shared):
                node_id = f"mark-{index}-{depth}"
                trace.append(
                    {
                        "id": node_id,
                        "parent": root,
                        "kind": "operation",
                        "data": {"name": tasks[tid]["title"]},
                        "metrics": {},
                        "path": [],
                    }
                )
                # Stable task identity is kept separately; profiler tags are short labels.
                tag = " ".join(tasks[tid]["title"].split()[:3])
                annotations[node_id] = {
                    "tag": tag,
                    "parent": active[-1][1] if active else root,
                    "next": None,
                }
                active.append((tid, node_id))
            metrics = operation["metrics"]
            trace.append(
                {
                    "id": operation["id"],
                    "parent": root,
                    "kind": "operation",
                    "data": {
                        "name": operation.get("title", operation["kind"]),
                        "source_kind": operation["kind"],
                    },
                    "metrics": {
                        "tokens": int(metrics.get("recorded_tokens", 0) or 0),
                        "operations": 1,
                        "time_ns": int(
                            (metrics.get("active_seconds_estimate", 0) or 0) * 1_000_000_000
                        ),
                    },
                    "path": [],
                }
            )
        (directory / "trace.jsonl").write_text(
            "".join(json.dumps(n, ensure_ascii=False) + "\n" for n in trace)
        )
        (directory / "annotation.json").write_text(json.dumps(annotations, ensure_ascii=False))
        profile = directory / "profile.pb.gz"
        view = (
            "tokens"
            if any((o["metrics"].get("recorded_tokens", 0) or 0) > 0 for o in detail["operations"])
            else "operations"
        )
        completed = subprocess.run(
            [
                binary,
                "--annotation-file",
                str(directory / "annotation.json"),
                "--view",
                view,
                "-o",
                str(profile),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode or not profile.is_file():
            raise ValueError("Profiler rejected task intervals")
        return {
            "name": "agentpprof",
            "source_commit": "60cc321ceb4b677fec1a69df6ec055a456b75675",
            "profile_sha256": __import__("hashlib").sha256(profile.read_bytes()).hexdigest(),
            "format": "pprof",
            "view": view,
            "operation_count": len(detail["operations"]),
        }
