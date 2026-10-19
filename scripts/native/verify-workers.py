"""Isolated binary/protocol integration acceptance; synthetic data only."""

from __future__ import annotations

import argparse
import gzip
import json
import pathlib
import subprocess
import tempfile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", required=True)
    parser.add_argument("--pprof", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="trajectory-native-acceptance-") as tmp:
        root = pathlib.Path(tmp)
        source = root / "source.jsonl"
        records = [
            {"type": "session_meta", "payload": {"id": "acceptance-session"}},
            {
                "type": "response_item",
                "timestamp": "2026-10-19T00:00:00Z",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "修复认证"}],
                },
            },
        ]
        source.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records))
        request = {
            "id": "source-1",
            "op": "parse",
            "agent": "codex",
            "source_id": "acceptance/source",
            "input_file": str(source),
        }
        messages = [
            {"id": "health-1", "op": "health"},
            request,
            {"id": "invalid", "op": "unsupported"},
            request,
        ]
        result = subprocess.run(
            [args.worker],
            input="".join(json.dumps(row) + "\n" for row in messages),
            text=True,
            capture_output=True,
            check=True,
        )
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        assert [response["ok"] for response in responses] == [True, True, False, True]
        assert responses[1]["result"] == responses[3]["result"], "replay changed normalized output"
        operation = responses[1]["result"]["operations"][0]
        assert operation["text"] == "修复认证"
        assert operation["location"]["source_line"] == 2
        assert operation["metrics"] == {}, "estimates must not become measured metrics"
        trace = [
            {
                "id": "S",
                "parent": None,
                "kind": "session",
                "data": {"name": "acceptance"},
                "metrics": {},
            },
            {
                "id": "P",
                "parent": "S",
                "kind": "prompt",
                "data": {"text": "修复认证"},
                "metrics": {},
            },
            {
                "id": "C",
                "parent": "P",
                "kind": "llm",
                "data": {"text": "检查配置"},
                "metrics": {"tokens": 23},
            },
        ]
        (root / "trace.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in trace)
        )
        annotation = {
            "S": {"tag": "打通同步", "parent": None, "next": None},
            "P": {"tag": "恢复认证", "parent": "S", "next": None},
        }
        (root / "annotation.json").write_text(json.dumps(annotation, ensure_ascii=False))
        subprocess.run(
            [
                args.pprof,
                "--annotation-file",
                str(root / "annotation.json"),
                "--view",
                "tokens",
                "-o",
                str(root / "profile.pb.gz"),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        updated = [json.loads(line) for line in (root / "trace.jsonl").read_text().splitlines()]
        assert updated[-1]["path"] == ["打通同步", "恢复认证"]
        assert (root / "stacks.folded").read_text().strip().endswith("23")
        assert gzip.decompress((root / "profile.pb.gz").read_bytes()), "empty pprof profile"
    print(
        json.dumps(
            {"worker_protocol": "passed", "agentpprof_workspace": "passed", "synthetic_only": True}
        )
    )


if __name__ == "__main__":
    main()
