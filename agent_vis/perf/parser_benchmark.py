"""Parser decoder benchmark runner for staged Claude parse paths."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from typing import Any

from agent_vis.parsers.claude_code import parse_jsonl_file_with_compact_events
from agent_vis.parsers.decoders import available_json_line_decoders, get_json_line_decoder
from agent_vis.perf.backend_runner import _create_dataset


@dataclass(frozen=True)
class ParserBenchmarkProfile:
    session_count: int
    turns_per_session: int
    iterations: int


PARSER_BENCHMARK_PROFILES: dict[str, ParserBenchmarkProfile] = {
    "quick": ParserBenchmarkProfile(session_count=12, turns_per_session=12, iterations=6),
    "full": ParserBenchmarkProfile(session_count=36, turns_per_session=18, iterations=12),
}


def _resolve_profile(
    mode: str,
    *,
    session_count: int | None,
    turns_per_session: int | None,
    iterations: int | None,
) -> ParserBenchmarkProfile:
    if mode not in PARSER_BENCHMARK_PROFILES:
        raise ValueError(
            f"Unsupported mode '{mode}'. Expected one of: {', '.join(PARSER_BENCHMARK_PROFILES)}"
        )
    profile = PARSER_BENCHMARK_PROFILES[mode]
    return ParserBenchmarkProfile(
        session_count=session_count or profile.session_count,
        turns_per_session=turns_per_session or profile.turns_per_session,
        iterations=iterations or profile.iterations,
    )


def _measure_decode_only(file_path: Path, *, decoder_name: str) -> int:
    decoder = get_json_line_decoder(decoder_name)
    line_count = 0
    if decoder.read_mode == "binary":
        with file_path.open("rb") as handle:
            for raw_line in handle:
                if not raw_line or raw_line.isspace():
                    continue
                decoder.decode(raw_line)
                line_count += 1
    else:
        with file_path.open("r", encoding="utf-8") as handle:
            for text_line in handle:
                if not text_line or text_line.isspace():
                    continue
                decoder.decode(text_line)
                line_count += 1
    return line_count


def _run_decode_only(
    file_path: Path, *, decoder_name: str, iterations: int
) -> tuple[list[float], int]:
    samples: list[float] = []
    line_count = 0
    for _ in range(iterations):
        started = time.perf_counter()
        line_count = _measure_decode_only(file_path, decoder_name=decoder_name)
        samples.append((time.perf_counter() - started) * 1000.0)
    return samples, line_count


def _run_production_like(
    file_path: Path, *, decoder_name: str, iterations: int
) -> tuple[list[float], int, int]:
    samples: list[float] = []
    message_count = 0
    compact_count = 0
    for _ in range(iterations):
        started = time.perf_counter()
        messages, compact_events = parse_jsonl_file_with_compact_events(
            file_path,
            decoder_name=decoder_name,
        )
        samples.append((time.perf_counter() - started) * 1000.0)
        message_count = len(messages)
        compact_count = len(compact_events)
    return samples, message_count, compact_count


def render_parser_benchmark_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "## Parser Decoder Benchmark Summary",
        "",
        f"- Profiled at: `{payload['generated_at']}`",
        f"- Mode: `{payload['mode']}`",
        f"- Dataset sessions: `{payload['profile']['session_count']}`",
        f"- Turns per session: `{payload['profile']['turns_per_session']}`",
        f"- Iterations: `{payload['profile']['iterations']}`",
        f"- Sample file: `{payload['sample_file']}`",
        "",
        "### Decoder Comparison",
        "",
        "| Decoder | Decode-only p50 ms | Production-like p50 ms | Messages | Compact events |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in payload["results"]:
        lines.append(
            f"| `{row['decoder']}` | {row['decode_only_p50_ms']:.2f} | "
            f"{row['production_like_p50_ms']:.2f} | "
            f"{row['message_count']} | {row['compact_count']} |"
        )
    return "\n".join(lines) + "\n"


def write_parser_benchmark_artifacts(
    payload: dict[str, Any],
    *,
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / "parser-benchmark-results.json"
    markdown_path = output_dir / "parser-benchmark-summary.md"
    archived_json = output_dir / f"parser-benchmark-results-{stamp}.json"
    archived_markdown = output_dir / f"parser-benchmark-summary-{stamp}.md"
    markdown = render_parser_benchmark_markdown(payload)
    for path in (json_path, archived_json):
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for path in (markdown_path, archived_markdown):
        path.write_text(markdown, encoding="utf-8")
    return json_path, markdown_path


def run_parser_decoder_benchmarks(
    *,
    mode: str,
    output_dir: Path,
    session_count: int | None = None,
    turns_per_session: int | None = None,
    iterations: int | None = None,
    decoder_names: list[str] | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    profile = _resolve_profile(
        mode,
        session_count=session_count,
        turns_per_session=turns_per_session,
        iterations=iterations,
    )
    decoders = decoder_names or available_json_line_decoders()

    with TemporaryDirectory(prefix="agent-vis-parser-bench-") as temp_dir:
        base_dir = Path(temp_dir)
        sessions_dir, _, _ = _create_dataset(
            base_dir,
            session_count=profile.session_count,
            turns_per_session=profile.turns_per_session,
        )
        sample_file = next(sessions_dir.glob("*.jsonl"))

        rows: list[dict[str, Any]] = []
        for decoder_name in decoders:
            decode_only_samples, line_count = _run_decode_only(
                sample_file,
                decoder_name=decoder_name,
                iterations=profile.iterations,
            )
            production_like_samples, message_count, compact_count = _run_production_like(
                sample_file,
                decoder_name=decoder_name,
                iterations=profile.iterations,
            )
            rows.append(
                {
                    "decoder": decoder_name,
                    "line_count": line_count,
                    "message_count": message_count,
                    "compact_count": compact_count,
                    "decode_only_samples_ms": decode_only_samples,
                    "decode_only_p50_ms": float(median(decode_only_samples)),
                    "production_like_samples_ms": production_like_samples,
                    "production_like_p50_ms": float(median(production_like_samples)),
                }
            )

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "profile": {
                "session_count": profile.session_count,
                "turns_per_session": profile.turns_per_session,
                "iterations": profile.iterations,
            },
            "sample_file": str(sample_file.name),
            "results": rows,
        }
    json_path, markdown_path = write_parser_benchmark_artifacts(payload, output_dir=output_dir)
    return payload, json_path, markdown_path
