"""Remote-only stdlib tests for the shared source-sync writer."""

import base64
import importlib.util
import io
import json
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[2] / "tools" / "trajectory_source_sync.py"
spec = importlib.util.spec_from_file_location("source_sync", MODULE)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class SourceSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "session.jsonl"
        self.path.write_bytes(b'{"x":1}\n')
        self.spec = {
            "path": str(self.path),
            "legacy_path": "C:\\logs\\session.jsonl",
            "ecosystem": "codex",
        }
        self.state = sync.SyncState(self.root / "state.sqlite")

    def tearDown(self):
        self.state.close()
        self.tmp.cleanup()

    def ack(self, row):
        body = json.loads(row[1])
        self.state.acknowledge(
            row,
            {
                "durable": True,
                "mutation_id": body["mutation_id"],
                "accepted_bytes": body["end"] - body["start"],
                "next_offset": body["end"],
            },
        )
        return body

    def test_pending_replay_survives_reopen_and_bad_receipt(self):
        self.state.prepare("collector", self.spec)
        first = self.state.next()
        self.state.close()
        self.state = sync.SyncState(self.root / "state.sqlite")
        self.assertEqual(first, self.state.next())
        with self.assertRaises(ValueError):
            self.state.acknowledge(first, {"durable": True})
        self.assertEqual(first, self.state.next())
        self.ack(first)
        self.assertIsNone(self.state.next())
        self.assertFalse(self.state.prepare("collector", self.spec))

    def test_append_retains_generation_offset_and_identity(self):
        self.state.prepare("collector", self.spec)
        first = self.ack(self.state.next())
        with self.path.open("ab") as stream:
            stream.write(b'{"x":2}\n')
        self.state.prepare("collector", self.spec)
        second = self.ack(self.state.next())
        self.assertEqual(second["generation"], first["generation"])
        self.assertEqual(second["start"], first["end"])
        self.assertEqual(second["source"], sync.source_id("collector", self.spec["legacy_path"]))
        self.assertEqual(base64.b64decode(second["content"]), b'{"x":2}\n')

    def test_replacement_starts_new_generation(self):
        self.state.prepare("collector", self.spec)
        first = self.ack(self.state.next())
        self.path.write_bytes(b'{"z":3}\n')
        self.state.prepare("collector", self.spec)
        second = self.ack(self.state.next())
        self.assertNotEqual(first["generation"], second["generation"])
        self.assertEqual(second["start"], 0)

    def test_chunk_bound_and_incomplete_json_line_preservation(self):
        content = b"x" * (sync.CHUNK_BYTES + 11)
        self.path.write_bytes(content)
        self.state.prepare("collector", self.spec)
        first = self.ack(self.state.next())
        self.assertEqual(len(base64.b64decode(first["content"])), sync.CHUNK_BYTES)
        self.state.prepare("collector", self.spec)
        second = self.ack(self.state.next())
        self.assertEqual(
            base64.b64decode(first["content"]) + base64.b64decode(second["content"]), content
        )

    def test_same_size_rewrite_after_first_kilobyte_starts_new_generation(self):
        self.path.write_bytes(b"a" * 4000)
        self.state.prepare("collector", self.spec)
        first = self.ack(self.state.next())
        with self.path.open("r+b") as stream:
            stream.seek(2000)
            stream.write(b"b")
        self.state.prepare("collector", self.spec)
        second = self.ack(self.state.next())
        self.assertNotEqual(first["generation"], second["generation"])
        self.assertEqual(second["start"], 0)
        self.assertEqual(base64.b64decode(second["content"])[2000:2001], b"b")

    def test_unchanged_completed_file_uses_persisted_full_stat_fingerprint(self):
        self.state.prepare("collector", self.spec)
        self.ack(self.state.next())
        self.state.close()
        self.state = sync.SyncState(self.root / "state.sqlite")
        with patch("builtins.open", side_effect=AssertionError("unchanged file reread")):
            self.assertFalse(self.state.prepare("collector", self.spec))

    def test_actual_http_progress_prevents_upload_after_checkpoint_loss(self):
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(("GET", self.path))
                body = b'{"generation":"already-uploaded","next_offset":8,"source_bytes":8}'
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                calls.append(("POST", self.path))
                self.send_response(500)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        credential = self.root / "credential.json"
        credential.write_text(json.dumps({"origin": origin, "api_key": "test-only"}))
        credential.chmod(0o600)
        identity = self.root / "identity.json"
        identity.write_text(
            json.dumps(
                {
                    "collector": "collector",
                    "sources": [sync.source_id("collector", self.spec["legacy_path"])],
                }
            )
        )
        try:
            with self.assertRaises(sync.RecoveryRequired):
                sync.sync_once(
                    {
                        "url": origin + "/trajectory/api/source-chunks",
                        "credential": str(credential),
                        "state": str(self.root / "lost.sqlite"),
                        "legacy_identity_snapshot": str(identity),
                        "sources": [self.spec],
                    }
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "GET")
        self.assertTrue(calls[0][1].startswith("/trajectory/api/source-progress?"))

    def test_remote_existing_source_without_local_state_fails_closed(self):
        with patch.object(
            sync, "remote_progress", return_value={"generation": "existing", "next_offset": 4000}
        ):
            with self.assertRaisesRegex(ValueError, "explicit recovery"):
                sync.guard_new_sources(self.state, {}, "collector", [self.spec], "test-key")
        self.assertIsNone(self.state.next())

    def test_missing_remote_source_is_checked_before_starting(self):
        with patch.object(
            sync, "remote_progress", return_value={"generation": None, "next_offset": 0}
        ) as progress:
            sync.guard_new_sources(self.state, {}, "collector", [self.spec], "test-key")
            progress.assert_called_once()
        self.assertIsNone(self.state.next())

    def test_legacy_partial_prefix_checkpoint_requires_explicit_recovery(self):
        self.path.write_bytes(b"a" * 4000)
        source = sync.source_id("collector", self.spec["legacy_path"])
        with self.state.db:
            self.state.db.execute(
                "INSERT INTO sources VALUES(?,?,?,?,?)",
                (source, "legacy-generation", 1024, sync.digest(b"a" * 1024), 4000),
            )
        with self.assertRaisesRegex(ValueError, "explicit recovery"):
            self.state.prepare("collector", self.spec)

    def test_lock_contention_cli_reports_busy_without_error(self):
        config = self.root / "config.json"
        config.write_text("{}")
        output = io.StringIO()
        with (
            patch.object(sync.sys, "argv", ["sync", "--config", str(config)]),
            patch.object(sync, "sync_once", side_effect=BlockingIOError),
            redirect_stdout(output),
        ):
            self.assertEqual(sync.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["state"], "busy")

    def test_process_lock_prevents_second_writer(self):
        with sync.process_lock(self.root / "state.lock"):
            with self.assertRaises(OSError):
                with sync.process_lock(self.root / "state.lock"):
                    self.fail("Second writer acquired same lock")

    def test_source_validation_race_preserves_checkpoint_and_pending_state(self):
        for existing in (False, True):
            with self.subTest(existing_checkpoint=existing):
                self.state.db.execute("DELETE FROM sources")
                self.state.db.execute("DELETE FROM metadata")
                self.state.hash_cache.clear()
                if existing:
                    self.state.prepare("collector", self.spec)
                    self.ack(self.state.next())
                    self.path.write_bytes(self.path.read_bytes() + b"appended\n")
                before = self.state.db.execute("SELECT * FROM sources").fetchall()
                stat = self.path.stat()
                changed = SimpleNamespace(
                    st_dev=stat.st_dev,
                    st_ino=stat.st_ino,
                    st_size=stat.st_size + 1,
                    st_mtime_ns=stat.st_mtime_ns,
                    st_ctime_ns=stat.st_ctime_ns,
                )
                with patch.object(sync.os, "fstat", return_value=changed):
                    with self.assertRaises(sync.SourceValidationRace) as caught:
                        self.state.prepare("collector", self.spec)
                diagnostic = sync.safe_error(caught.exception)
                self.assertEqual(diagnostic["code"], "source_changed_during_validation")
                self.assertEqual(
                    diagnostic["source_id"], sync.source_id("collector", self.spec["legacy_path"])
                )
                self.assertEqual(before, self.state.db.execute("SELECT * FROM sources").fetchall())
                self.assertIsNone(self.state.next())
                self.assertTrue(self.state.prepare("collector", self.spec))
                body = json.loads(self.state.next()[1])
                if existing:
                    self.assertEqual(body["generation"], before[0][1])
                    self.assertEqual(body["start"], before[0][4])
                self.ack(self.state.next())

    def test_cli_diagnostics_never_log_exception_message_paths_or_secrets(self):
        config = self.root / "config.json"
        config.write_text("{}")
        output = io.StringIO()
        with (
            patch.object(sync.sys, "argv", ["sync", "--config", str(config)]),
            patch.object(
                sync, "sync_once", side_effect=ValueError("SECRET https://private/source body")
            ),
            redirect_stderr(output),
        ):
            self.assertEqual(sync.main(), 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["code"], "sync_operation_failed")
        self.assertEqual(result["site"]["function"], "main")
        self.assertNotIn("SECRET", output.getvalue())
        self.assertNotIn("private", output.getvalue())

    def fake_sync(self, specs, prepare=None, limit=10, response=None):
        posts = []

        def send(request, timeout):
            body = json.loads(request.data)
            posts.append(body)
            receipt = {
                "durable": True,
                "mutation_id": body["mutation_id"],
                "accepted_bytes": body["end"] - body["start"],
                "next_offset": body["end"],
            }
            return io.BytesIO(json.dumps(receipt if response is None else response).encode())

        config = {
            "url": "https://test.invalid/source-chunks",
            "state": str(self.root / "state.sqlite"),
            "credential": "unused",
        }
        with (
            patch.object(sync, "validate_manifest", return_value=("collector", specs)),
            patch.object(sync, "credentials", return_value="PRIVATE-KEY-NOT-LOGGED"),
            patch.object(sync, "guard_new_sources"),
            patch.object(sync, "http_opener", return_value=SimpleNamespace(open=send)),
        ):
            if prepare is None:
                return sync.sync_once(config, limit), posts
            with patch.object(sync.SyncState, "prepare", new=prepare):
                return sync.sync_once(config, limit), posts

    def test_request_repair_runs_after_raw_writer_releases_shared_lock(self):
        import fcntl

        calls = []
        config = {
            "url": "https://test.invalid/source-chunks",
            "state": str(self.root / "state.sqlite"),
            "credential": "unused",
            "request_repair": {"projector": "sealed-projector", "node": "node"},
        }

        def send(request, timeout):
            body = json.loads(request.data)
            return io.BytesIO(
                json.dumps(
                    {
                        "durable": True,
                        "mutation_id": body["mutation_id"],
                        "accepted_bytes": body["end"] - body["start"],
                        "next_offset": body["end"],
                    }
                ).encode()
            )

        def repair(*args, **kwargs):
            with (self.root / "state.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(lock, fcntl.LOCK_UN)
            calls.append(kwargs)
            return {"sources": []}

        with (
            patch.object(sync, "validate_manifest", return_value=("collector", [self.spec])),
            patch.object(sync, "credentials", return_value="fixture"),
            patch.object(sync, "guard_new_sources"),
            patch.object(sync, "http_opener", return_value=SimpleNamespace(open=send)),
            patch.dict(sys.modules, {"trajectory_request_repair": SimpleNamespace(run=repair)}),
        ):
            result = sync.sync_once(config, 1)
            retry = sync.sync_once(config, 1)
        self.assertEqual(result["chunks"], 1)
        self.assertEqual(retry["chunks"], 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(self.state.pending_request_repairs()), 1)
        self.assertEqual(
            calls[0]["sources"], [sync.source_id("collector", self.spec["legacy_path"])]
        )
        self.assertTrue(calls[0]["apply"])

    def test_request_repair_queue_survives_restart_and_acknowledges_exact_generation(self):
        self.state.prepare("collector", self.spec)
        row = self.state.next()
        body = json.loads(row[1])
        receipt = {
            "durable": True,
            "mutation_id": body["mutation_id"],
            "accepted_bytes": body["end"] - body["start"],
            "next_offset": body["end"],
        }
        self.state.acknowledge(row, receipt, queue_requests=True)
        before = self.state.db.execute("SELECT * FROM sources").fetchall()
        self.state.close()
        self.state = sync.SyncState(self.root / "state.sqlite")
        self.assertEqual(len(self.state.pending_request_repairs()), 1)
        self.state.finish_request_repair(body["source"], "wrong-generation", body["end"])
        self.assertEqual(len(self.state.pending_request_repairs()), 1)
        self.state.defer_request_repair(body["source"])
        self.state.finish_request_repair(body["source"], body["generation"], body["end"])
        self.assertEqual(self.state.pending_request_repairs(), [])
        self.assertEqual(before, self.state.db.execute("SELECT * FROM sources").fetchall())

    def test_racing_source_defers_once_while_pending_and_stable_sources_progress(self):
        self.state.prepare("collector", self.spec)
        original = self.ack(self.state.next())
        self.path.write_bytes(self.path.read_bytes() + b"active append\n")
        active_before = self.state.db.execute("SELECT * FROM sources").fetchall()
        stable = {
            **self.spec,
            "path": str(self.root / "stable.jsonl"),
            "legacy_path": r"C:\logs\stable.jsonl",
        }
        Path(stable["path"]).write_bytes(b"stable pending\n")
        self.state.prepare("collector", stable)
        pending = json.loads(self.state.next()[1])
        Path(stable["path"]).write_bytes(b"stable pending\nmore stable\n")
        real_prepare = sync.SyncState.prepare
        active_calls = []

        def race(state, collector, spec):
            if spec != self.spec:
                return real_prepare(state, collector, spec)
            # Existing outbox was replayed before any attempt to prepare a source.
            self.assertIsNone(state.next())
            active_calls.append(spec)
            stat = self.path.stat()
            changed = SimpleNamespace(
                st_dev=stat.st_dev,
                st_ino=stat.st_ino,
                st_size=stat.st_size + 1,
                st_mtime_ns=stat.st_mtime_ns,
                st_ctime_ns=stat.st_ctime_ns,
            )
            with patch.object(sync.os, "fstat", return_value=changed):
                return real_prepare(state, collector, spec)

        result, posts = self.fake_sync([self.spec, stable], race)
        self.assertEqual(len(active_calls), 1)
        self.assertEqual(posts[0], pending)
        self.assertEqual(result["chunks"], 2)
        self.assertFalse(result["pending"])
        self.assertTrue(result["retryable"])
        source = sync.source_id("collector", self.spec["legacy_path"])
        self.assertEqual(
            result["deferred_sources"],
            [
                {
                    "source_id": source,
                    "reason": "source_changed_during_validation",
                    "retryable": True,
                }
            ],
        )
        self.assertEqual(
            active_before[0],
            self.state.db.execute("SELECT * FROM sources WHERE source=?", (source,)).fetchone(),
        )
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertNotIn(str(self.path), json.dumps(result))
        following, next_posts = self.fake_sync([self.spec, stable])
        self.assertEqual(following["chunks"], 1)
        self.assertEqual(following["deferred_sources"], [])
        self.assertFalse(following["retryable"])
        self.assertEqual(next_posts[0]["generation"], original["generation"])
        self.assertEqual(next_posts[0]["start"], original["end"])
        ids = [body["mutation_id"] for body in posts + next_posts]
        self.assertEqual(len(ids), len(set(ids)))

    def test_all_racing_sources_stop_without_busy_retry_or_checkpoint_changes(self):
        other = {**self.spec, "legacy_path": r"C:\logs\other.jsonl"}
        calls = []

        def race(state, collector, spec):
            calls.append(spec)
            raise sync.SourceValidationRace(sync.source_id(collector, spec["legacy_path"]))

        result, posts = self.fake_sync([self.spec, other], race, limit=100)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["chunks"], 0)
        self.assertEqual(len(result["deferred_sources"]), 2)
        self.assertTrue(result["retryable"])
        self.assertFalse(result["pending"])
        self.assertEqual(posts, [])
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM sources").fetchone()[0], 0)
        self.assertIsNone(self.state.next())

    def test_defer_does_not_swallow_other_validation_or_receipt_failures(self):
        for error in (ValueError("invalid metadata"), sync.RecoveryRequired("explicit recovery")):
            with self.subTest(error=type(error).__name__):

                def fail(state, collector, spec, failure=error):
                    raise failure

                with self.assertRaises(type(error)):
                    self.fake_sync([self.spec], fail)
        self.state.prepare("collector", self.spec)
        original = self.state.next()
        with self.assertRaisesRegex(ValueError, "durable source receipt"):
            self.fake_sync([self.spec], response={"durable": True})
        self.assertEqual(original, self.state.next())

    def test_dynamic_roots_keep_existing_source_identity_and_defer_new_files(self):
        identity = self.root / "identity.json"
        legacy_root = r"\\wsl.localhost\Ubuntu\home\user\sessions"
        legacy_path = legacy_root + r"\session.jsonl"
        identity.write_text(
            json.dumps(
                {"collector": "collector", "sources": [sync.source_id("collector", legacy_path)]}
            )
        )
        (self.root / "new.jsonl").write_text("{}")
        collector, specs = sync.validate_manifest(
            {
                "legacy_identity_snapshot": str(identity),
                "roots": [
                    {"local_root": str(self.root), "legacy_root": legacy_root, "ecosystem": "codex"}
                ],
            }
        )
        self.assertEqual(collector, "collector")
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["legacy_path"], legacy_path)
        data = json.loads(identity.read_text())
        data["sources"].append(sync.source_id("collector", legacy_root + r"\new.jsonl"))
        identity.write_text(json.dumps(data))
        self.assertEqual(
            len(
                sync.validate_manifest(
                    {
                        "legacy_identity_snapshot": str(identity),
                        "roots": [
                            {
                                "local_root": str(self.root),
                                "legacy_root": legacy_root,
                                "ecosystem": "codex",
                            }
                        ],
                    }
                )[1]
            ),
            2,
        )

    def test_pi_root_uses_shared_checkpoint_without_reupload(self):
        legacy_root = r"C:\pi\sessions"
        legacy_path = legacy_root + r"\session.jsonl"
        identity = self.root / "identity.json"
        identity.write_text(
            json.dumps(
                {"collector": "collector", "sources": [sync.source_id("collector", legacy_path)]}
            )
        )
        config = {
            "legacy_identity_snapshot": str(identity),
            "roots": [
                {
                    "local_root": str(self.root),
                    "legacy_root": legacy_root,
                    "ecosystem": "pi",
                    "allow_new_sources": True,
                }
            ],
        }
        collector, specs = sync.validate_manifest(config)
        self.assertEqual(specs[0]["ecosystem"], "pi")
        self.state.prepare(collector, specs[0])
        first = self.ack(self.state.next())
        self.state.close()
        self.state = sync.SyncState(self.root / "state.sqlite")
        self.assertFalse(self.state.prepare(collector, sync.validate_manifest(config)[1][0]))
        with self.path.open("ab") as stream:
            stream.write(b'{"type":"message"}\n')
        self.assertTrue(self.state.prepare(collector, specs[0]))
        second = self.ack(self.state.next())
        self.assertEqual(second["source"], first["source"])
        self.assertEqual(second["generation"], first["generation"])
        self.assertEqual(second["start"], first["end"])

    def test_anchored_root_can_discover_new_sources_before_legacy_worker(self):
        legacy_root = r"C:\logs"
        identity = self.root / "identity.json"
        identity.write_text(
            json.dumps(
                {
                    "collector": "collector",
                    "sources": [sync.source_id("collector", legacy_root + r"\session.jsonl")],
                }
            )
        )
        (self.root / "new.jsonl").write_text("{}")
        config = {
            "legacy_identity_snapshot": str(identity),
            "roots": [
                {
                    "local_root": str(self.root),
                    "legacy_root": legacy_root,
                    "ecosystem": "codex",
                    "allow_new_sources": True,
                }
            ],
        }
        collector, specs = sync.validate_manifest(config)
        self.assertEqual(len(specs), 2)
        new = next(spec for spec in specs if spec["path"].endswith("new.jsonl"))
        expected = sync.source_id(collector, legacy_root + r"\new.jsonl")
        self.assertEqual(sync.source_id(collector, new["legacy_path"]), expected)
        # Legacy discovery later produces exactly the same ID and manifest.
        identity.write_text(
            json.dumps(
                {
                    "collector": collector,
                    "sources": [
                        sync.source_id(collector, legacy_root + r"\session.jsonl"),
                        expected,
                    ],
                }
            )
        )
        self.assertEqual(sync.validate_manifest(config)[1], specs)

    def test_allow_new_sources_requires_correct_root_anchor_and_explicit_boolean(self):
        identity = self.root / "identity.json"
        identity.write_text(
            json.dumps(
                {
                    "collector": "collector",
                    "sources": [sync.source_id("collector", r"C:\logs\session.jsonl")],
                }
            )
        )
        root = {
            "local_root": str(self.root),
            "legacy_root": r"D:\wrong",
            "ecosystem": "codex",
            "allow_new_sources": True,
        }
        config = {"legacy_identity_snapshot": str(identity), "roots": [root]}
        with self.assertRaisesRegex(ValueError, "anchor"):
            sync.validate_manifest(config)
        root["allow_new_sources"] = "true"
        with self.assertRaisesRegex(ValueError, "boolean"):
            sync.validate_manifest(config)

    def test_newest_source_precedes_cold_with_stable_path_tiebreaker(self):
        new = self.root / "new.jsonl"
        new.write_text("{}")
        sync.os.utime(self.path, ns=(100, 100))
        sync.os.utime(new, ns=(200, 200))
        identity = self.root / "identity.json"
        identity.write_text(
            json.dumps(
                {
                    "collector": "collector",
                    "sources": [sync.source_id("collector", r"C:\logs\session.jsonl")],
                }
            )
        )
        config = {
            "legacy_identity_snapshot": str(identity),
            "roots": [
                {
                    "local_root": str(self.root),
                    "legacy_root": r"C:\logs",
                    "ecosystem": "codex",
                    "allow_new_sources": True,
                }
            ],
        }
        self.assertEqual(sync.validate_manifest(config)[1][0]["path"], str(new))
        sync.os.utime(new, ns=(100, 100))
        specs = sync.validate_manifest(config)[1]
        self.assertEqual(
            [spec["legacy_path"] for spec in specs], sorted(spec["legacy_path"] for spec in specs)
        )

    def test_root_session_allowlist_selects_two_and_keeps_other_roots(self):
        selected = ["01a0f312-da54-77e1-99da-92e1d2b5568b", "01a0f304-0850-7373-a518-9292f78d73c5"]
        excluded = "01a0f786-32c8-75a6-ab5b-552324ced973"
        pi = self.root / "pi"
        pi.mkdir()
        for native in [*selected, excluded]:
            (pi / (native + ".jsonl")).write_bytes(b"{}\n")
        identity = self.root / "identity.json"
        identity.write_text(
            json.dumps(
                {
                    "collector": "collector",
                    "sources": [sync.source_id("collector", self.spec["legacy_path"])],
                }
            )
        )
        root = {
            "local_root": str(pi),
            "legacy_root": r"C:\pi",
            "ecosystem": "pi",
            "allow_new_sources": True,
        }
        before = sync.root_identity(root)
        root["only_sessions"] = selected
        config = {
            "legacy_identity_snapshot": str(identity),
            "roots": [
                root,
                {"local_root": str(self.root), "legacy_root": r"C:\logs", "ecosystem": "codex"},
            ],
        }
        with patch.object(sync, "registered_roots", return_value={before}):
            collector, specs = sync.validate_manifest(config)
            self.assertEqual({Path(spec["path"]).stem for spec in specs}, {*selected, "session"})
            self.assertEqual(sync.root_identity(root), before)
            for spec in specs:
                self.state.prepare(collector, spec)
            sources = {row[0] for row in self.state.db.execute("SELECT source FROM sources")}
            self.assertNotIn(
                sync.source_id(collector, sync.ntpath.join(r"C:\pi", excluded + ".jsonl")), sources
            )
            root["only_sessions"] = []
            self.assertEqual(sync.validate_manifest(config)[1], [self.spec])
            for bad in (None, "all", [None], ["invalid-uuid"]):
                root["only_sessions"] = bad
                with self.assertRaises(ValueError):
                    sync.validate_manifest(config)

    def test_selectors_scope_new_work_by_source_or_native_session(self):
        native = "01a0f312-da54-77e1-99da-92e1d2b5568b"
        selected = {**self.spec, "path": str(self.root / (native + ".jsonl"))}
        specs = [self.spec, selected]
        self.assertEqual(sync.select_sources("collector", specs, sessions=[native]), [selected])
        source = sync.source_id("collector", self.spec["legacy_path"])
        self.assertEqual(sync.select_sources("collector", specs, sources=[source]), specs)
        self.assertEqual(sync.select_sources("collector", specs, sources=["0" * 64]), [])
        with self.assertRaises(ValueError):
            sync.select_sources("collector", specs, sources=["wrong"])
        with self.assertRaises(ValueError):
            sync.select_sources("collector", specs, sessions=["not-a-uuid"])

    @patch.object(
        sync,
        "remote_identity",
        return_value={"account_id": "machine-account", "machine_client": "registered-client"},
    )
    def test_explicit_new_ecosystem_root_requires_authenticated_machine_binding(
        self, identity_check
    ):
        identity = self.root / "identity.json"
        identity.write_text(json.dumps({"collector": "collector", "sources": []}))
        root = {
            "local_root": str(self.root),
            "legacy_root": r"C:\pi\sessions",
            "ecosystem": "pi",
            "allow_new_sources": True,
        }
        config = {
            "legacy_identity_snapshot": str(identity),
            "url": "https://service/trajectory/api/source-chunks",
            "credential": "/private/test",
            "state": str(self.root / "state.sqlite"),
            "roots": [root],
        }
        with self.assertRaisesRegex(ValueError, "anchor"):
            sync.validate_manifest(config)
        with (
            patch.object(sync, "credentials", return_value="test-key"),
            patch.object(sync, "remote_progress", side_effect=PermissionError("unbound machine")),
        ):
            with self.assertRaises(PermissionError):
                sync.register_root(config, str(self.root))
        self.assertEqual(sync.registered_roots(config, "collector"), set())
        with (
            patch.object(sync, "credentials", return_value="test-key"),
            patch.object(
                sync, "remote_progress", return_value={"generation": None, "next_offset": 0}
            ) as progress,
        ):
            result = sync.register_root(config, str(self.root))
        progress.assert_called_once_with(
            config,
            "collector",
            sync.source_id("collector", r"C:\pi\sessions\session.jsonl"),
            "test-key",
        )
        self.assertTrue(result["registered"])
        self.assertEqual(sync.validate_manifest(config)[1][0]["ecosystem"], "pi")
        self.assertEqual(json.loads(identity.read_text())["sources"], [])
        root["legacy_root"] = r"D:\another"
        with self.assertRaisesRegex(ValueError, "anchor"):
            sync.validate_manifest(config)
        config["url"] = "https://other/trajectory/api/source-chunks"
        with self.assertRaisesRegex(ValueError, "another endpoint"):
            sync.validate_manifest(config)

    def test_pending_body_replays_before_newer_source_is_prepared(self):
        self.state.prepare("collector", self.spec)
        original = self.state.next()[1]
        native = "01a0f312-da54-77e1-99da-92e1d2b5568b"
        new = self.root / (native + ".jsonl")
        new.write_text("{}")
        posts = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                posts.append(body.decode())
                batch = json.loads(body)
                response = json.dumps(
                    {
                        "durable": True,
                        "mutation_id": batch["mutation_id"],
                        "accepted_bytes": batch["end"] - batch["start"],
                        "next_offset": batch["end"],
                    }
                ).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        identity = self.root / "identity.json"
        new_spec = {
            "path": str(new),
            "legacy_path": sync.ntpath.join(r"C:\logs", native + ".jsonl"),
            "ecosystem": "codex",
        }
        identity.write_text(
            json.dumps(
                {
                    "collector": "collector",
                    "sources": [
                        sync.source_id("collector", s["legacy_path"]) for s in [self.spec, new_spec]
                    ],
                }
            )
        )
        credential = self.root / "credential.json"
        credential.write_text(json.dumps({"origin": origin, "api_key": "test-only"}))
        credential.chmod(0o600)
        try:
            result = sync.sync_once(
                {
                    "url": origin + "/trajectory/api/source-chunks",
                    "credential": str(credential),
                    "state": str(self.root / "state.sqlite"),
                    "legacy_identity_snapshot": str(identity),
                    "roots": [
                        {
                            "local_root": str(self.root),
                            "legacy_root": r"C:\logs",
                            "ecosystem": "codex",
                            "only_sessions": [native],
                        }
                    ],
                },
                1,
                sources=[sync.source_id("collector", new_spec["legacy_path"])],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(result["chunks"], 1)
        self.assertEqual(result["selected_sources"], 1)
        self.assertEqual(posts, [original])
        self.assertIsNone(
            self.state.db.execute(
                "SELECT 1 FROM sources WHERE source=?",
                (sync.source_id("collector", new_spec["legacy_path"]),),
            ).fetchone()
        )

    def test_state_cannot_silently_change_endpoint_or_collector(self):
        self.state.bind("collector", "https://example.com/trajectory/api/source-chunks")
        self.state.bind("collector", "https://example.com/trajectory/api/source-chunks")
        with self.assertRaises(ValueError):
            self.state.bind("collector", "https://other.example/trajectory/api/source-chunks")
        with self.assertRaises(ValueError):
            self.state.bind("other-collector", "https://example.com/trajectory/api/source-chunks")

    def test_direct_proxy_mode_is_per_opener_and_rejects_unknown_modes(self):
        with patch.object(sync.urllib.request, "build_opener") as build:
            sync.http_opener({"proxy": "direct"})
            handlers = build.call_args.args
            self.assertEqual(handlers[0].proxies, {})
            self.assertIs(handlers[1], sync.NoRedirect)
        with patch.object(sync.urllib.request, "build_opener") as build:
            sync.http_opener({})
            self.assertEqual(build.call_args.args, (sync.NoRedirect,))
        with self.assertRaises(ValueError):
            sync.http_opener({"proxy": "unknown"})

    def test_redirect_is_never_followed(self):
        with self.assertRaises(ValueError):
            sync.NoRedirect().redirect_request(None, None, None, None, None, None)


if __name__ == "__main__":
    unittest.main()
