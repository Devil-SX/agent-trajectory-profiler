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
        with patch.object(sync.sys, "argv", ["sync", "--config", str(config)]), patch.object(
            sync, "sync_once", side_effect=BlockingIOError
        ), redirect_stdout(output):
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

    def test_state_cannot_silently_change_endpoint_or_collector(self):
        self.state.bind("collector", "https://example.com/trajectory/api/source-chunks")
        self.state.bind("collector", "https://example.com/trajectory/api/source-chunks")
        with self.assertRaises(ValueError):
            self.state.bind("collector", "https://other.example/trajectory/api/source-chunks")
        with self.assertRaises(ValueError):
            self.state.bind("other-collector", "https://example.com/trajectory/api/source-chunks")

    def test_redirect_is_never_followed(self):
        with self.assertRaises(ValueError):
            sync.NoRedirect().redirect_request(None, None, None, None, None, None)


if __name__ == "__main__":
    unittest.main()
