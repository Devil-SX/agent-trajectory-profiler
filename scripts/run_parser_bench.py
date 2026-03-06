#!/usr/bin/env python3
"""Run parser decoder benchmarks on synthetic public fixtures."""

from __future__ import annotations

import argparse
from pathlib import Path

from agent_vis.perf.parser_benchmark import run_parser_decoder_benchmarks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["quick", "full"], default="quick")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output") / "perf",
        help="Directory for parser benchmark JSON/Markdown artifacts",
    )
    parser.add_argument("--session-count", type=int, default=None)
    parser.add_argument("--turns-per-session", type=int, default=None)
    parser.add_argument("--iterations", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload, json_path, markdown_path = run_parser_decoder_benchmarks(
        mode=args.mode,
        output_dir=args.output_dir,
        session_count=args.session_count,
        turns_per_session=args.turns_per_session,
        iterations=args.iterations,
    )
    print(f"Mode: {payload['mode']}")
    print(f"Decoders: {', '.join(item['decoder'] for item in payload['results'])}")
    print(f"Artifacts: {json_path} | {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
