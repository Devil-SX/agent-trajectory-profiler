#!/usr/bin/env python3
"""Profile real local sync workloads using private git-ignored fixtures."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_vis.perf.sync_profiler import (
    PRIVATE_SYNC_ROOT_ENV,
    profile_sync_directory,
    resolve_private_sync_root,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=resolve_private_sync_root(),
        help="Real sync root to profile (default: private softlink or env override)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output") / "private-perf",
        help="Directory for local profiling artifacts",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Profile only the first N discovered files",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="Number of slow files to include in the summary",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = args.path.expanduser()
    if not path.exists():
        print(
            f"Private sync root not found: {path}\n"
            f"Create a git-ignored softlink there or set {PRIVATE_SYNC_ROOT_ENV}.",
            file=sys.stderr,
        )
        return 1

    payload, json_path, markdown_path = profile_sync_directory(
        path,
        output_dir=args.output_dir,
        max_files=args.max_files,
        top_n=args.top_n,
    )

    print(f"Profiled source: {payload['source']}")
    print(f"Files parsed: {payload['summary']['parsed_files']}")
    print(f"Total sync time: {payload['summary']['total_sync_ms']:.2f} ms")
    if payload["stage_breakdown"]:
        top_stage = payload["stage_breakdown"][0]
        print(
            "Top stage: "
            f"{top_stage['stage']} "
            f"({top_stage['total_ms']:.2f} ms, {top_stage['share_percent']:.1f}%)"
        )
    if json_path is not None:
        print(f"Metrics written to: {json_path}")
    if markdown_path is not None:
        print(f"Summary written to: {markdown_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
