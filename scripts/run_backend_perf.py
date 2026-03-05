#!/usr/bin/env python3
"""Run backend performance benchmarks and export JSON/Markdown summaries."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_vis.perf.backend_runner import run_backend_performance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["quick", "full"],
        default="quick",
        help="Benchmark mode: quick (PR) or full (nightly)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output") / "perf",
        help="Directory for benchmark artifacts",
    )
    parser.add_argument(
        "--budgets",
        type=Path,
        default=Path("tests") / "perf" / "budgets.json",
        help="Budget config path",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail with non-zero exit code when budget status is WARN",
    )
    parser.add_argument("--session-count", type=int, default=None, help="Override session count")
    parser.add_argument(
        "--turns-per-session",
        type=int,
        default=None,
        help="Override turns per synthetic session",
    )
    parser.add_argument(
        "--api-iterations",
        type=int,
        default=None,
        help="Override analytics API benchmark iterations",
    )
    parser.add_argument(
        "--stats-iterations",
        type=int,
        default=None,
        help="Override statistics hotpath benchmark iterations",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    report, payload, json_path, markdown_path = run_backend_performance(
        mode=args.mode,
        output_dir=args.output_dir,
        budgets_path=args.budgets,
        session_count=args.session_count,
        turns_per_session=args.turns_per_session,
        api_iterations=args.api_iterations,
        stats_iterations=args.stats_iterations,
    )

    print(f"Performance status: {report.status.upper()} (warn_count={report.warn_count})")
    print(f"Metrics written to: {json_path}")
    print(f"Summary written to: {markdown_path}")
    print(f"Measured metrics: {payload['metrics']}")

    if args.strict and report.status == "warn":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
