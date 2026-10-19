"""Remote-only stdlib tests for the shared source-sync writer."""

import base64
import importlib.util
import io
import json
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
        new = self.root / "new.jsonl"
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
        new_spec = {"path": str(new), "legacy_path": r"C:\logs\new.jsonl", "ecosystem": "codex"}
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
                    "sources": [new_spec, self.spec],
                },
                1,
                sources=[sync.source_id("collector", new_spec["legacy_path"])],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(result["chunks"], 1)
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
