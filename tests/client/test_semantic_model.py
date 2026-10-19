import importlib.util
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[2] / "trajectory/product/semantic_model.py"
spec = importlib.util.spec_from_file_location("semantic_model", MODULE)
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


class SemanticModelTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.invalid = False
        self.truncate = False
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(request)
                packet = json.loads(request["messages"][1]["content"])
                ids = [o["id"] for o in packet["operations"]]
                result = {
                    "tasks": [
                        {
                            "id": "repair",
                            "parent_id": "root",
                            "title": "修复同步",
                            "operation_ids": ids[:-1] if outer.invalid else ids,
                        }
                    ]
                }
                body = json.dumps(
                    {
                        "choices": [
                            {
                                "finish_reason": "length" if outer.truncate else "stop",
                                "message": {"content": json.dumps(result)},
                            }
                        ],
                        "usage": {"prompt_tokens": 42, "completion_tokens": 12},
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.environment = patch.dict(
            os.environ,
            {
                "TRAJECTORY_MODEL_BASE_URL": f"http://127.0.0.1:{self.server.server_port}/v1",
                "TRAJECTORY_MODEL_NAME": "mock-model",
                "TRAJECTORY_MODEL_API_KEY": "test-only",
                "TRAJECTORY_MODEL_API_MODE": "chat_completions",
            },
            clear=True,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_real_http_structured_segmentation_and_separate_analysis_usage(self):
        result = model.segment([{"id": "op1", "kind": "tool", "text": "检查认证"}], "打通同步")
        self.assertEqual(result["tasks"][1]["operation_ids"], ["op1"])
        self.assertEqual(result["provenance"]["analysis_usage"][0]["usage"]["prompt_tokens"], 42)
        self.assertIsNone(result["provenance"]["cost"])
        request = self.requests[0]
        self.assertNotIn("tools", request)
        self.assertIn("不可信证据", request["messages"][0]["content"])

    def test_chunking_preserves_every_operation_and_continues_task_identity(self):
        operations = [{"id": str(i), "text": "读取文件" * 1000} for i in range(30)]
        result = model.segment(operations, "调查认证")
        self.assertGreater(len(self.requests), 1)
        self.assertEqual(result["tasks"][1]["operation_ids"], [str(i) for i in range(30)])
        self.assertEqual(result["provenance"]["truncated_operations"], 30)
        self.assertTrue(json.loads(self.requests[1]["messages"][1]["content"])["existing_tasks"])

    def test_missing_coverage_explicitly_fails_with_charged_usage(self):
        self.invalid = True
        with self.assertRaises(model.SemanticModelError) as caught:
            model.segment([{"id": "a"}], "测试")
        self.assertEqual(
            caught.exception.provenance["analysis_usage"][0]["usage"]["prompt_tokens"], 42
        )

    def test_incomplete_output_fails_and_retains_usage(self):
        self.truncate = True
        with self.assertRaises(model.SemanticModelError) as caught:
            model.segment([{"id": "a"}], "测试")
        self.assertTrue(caught.exception.provenance["analysis_usage"][0]["failed"])
        self.assertEqual(
            caught.exception.provenance["analysis_usage"][0]["usage"]["prompt_tokens"], 42
        )

    def test_missing_model_config_never_falls_back(self):
        del os.environ["TRAJECTORY_MODEL_API_KEY"]
        with self.assertRaises(model.SemanticModelError):
            model.segment([{"id": "a"}], "测试")
        self.assertFalse(self.requests)

    def test_tree_and_membership_reject_cycles_duplicates_and_unknown_ids(self):
        known = {"root": {"id": "root", "parent_id": None}}
        invalid = [
            [
                {"id": "a", "parent_id": "b", "title": "A", "operation_ids": ["o"]},
                {"id": "b", "parent_id": "a", "title": "B", "operation_ids": []},
            ],
            [{"id": "a", "parent_id": "root", "title": "A", "operation_ids": ["o", "o"]}],
            [{"id": "a", "parent_id": "root", "title": "A", "operation_ids": ["unknown"]}],
        ]
        for tasks in invalid:
            with self.assertRaises(model.SemanticModelError):
                model._validate(tasks, known, {"o"})


if __name__ == "__main__":
    unittest.main()
