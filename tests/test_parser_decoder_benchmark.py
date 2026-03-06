from __future__ import annotations

from pathlib import Path

from agent_vis.perf.parser_benchmark import (
    render_parser_benchmark_markdown,
    run_parser_decoder_benchmarks,
)


def test_run_parser_decoder_benchmarks_writes_artifacts(tmp_path: Path) -> None:
    payload, json_path, markdown_path = run_parser_decoder_benchmarks(
        mode="quick",
        output_dir=tmp_path,
        session_count=3,
        turns_per_session=3,
        iterations=2,
        decoder_names=["json", "orjson"],
    )

    assert json_path.exists()
    assert markdown_path.exists()
    assert payload["results"]
    names = [item["decoder"] for item in payload["results"]]
    assert names == ["json", "orjson"]
    assert all(item["decode_only_p50_ms"] > 0 for item in payload["results"])
    assert all(item["production_like_p50_ms"] > 0 for item in payload["results"])

    markdown = render_parser_benchmark_markdown(payload)
    assert "Parser Decoder Benchmark Summary" in markdown
    assert "`json`" in markdown
    assert "`orjson`" in markdown
