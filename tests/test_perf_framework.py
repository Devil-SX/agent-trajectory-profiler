from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_vis.perf.framework import (
    evaluate_metrics,
    load_metric_budgets,
    render_markdown_summary,
    serialize_report,
)


def _write_budget(path: Path) -> None:
    payload = {
        "modes": {
            "quick": {
                "metrics": {
                    "latency": {
                        "description": "Latency",
                        "unit": "ms",
                        "direction": "lower_is_better",
                        "target": 100,
                        "warn": 130,
                    },
                    "throughput": {
                        "description": "Throughput",
                        "unit": "req/s",
                        "direction": "higher_is_better",
                        "target": 10,
                        "warn": 8,
                    },
                }
            }
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_metric_budgets_success(tmp_path: Path) -> None:
    budget_path = tmp_path / "budgets.json"
    _write_budget(budget_path)

    budgets = load_metric_budgets(budget_path, "quick")
    assert set(budgets.keys()) == {"latency", "throughput"}
    assert budgets["latency"].direction == "lower_is_better"
    assert budgets["throughput"].direction == "higher_is_better"


def test_load_metric_budgets_unknown_mode(tmp_path: Path) -> None:
    budget_path = tmp_path / "budgets.json"
    _write_budget(budget_path)

    with pytest.raises(ValueError, match="Budget mode"):
        load_metric_budgets(budget_path, "full")


def test_evaluate_metrics_warn_and_ok(tmp_path: Path) -> None:
    budget_path = tmp_path / "budgets.json"
    _write_budget(budget_path)
    budgets = load_metric_budgets(budget_path, "quick")

    report = evaluate_metrics(
        {
            "latency": 150,
            "throughput": 9,
        },
        budgets,
        mode="quick",
    )

    assert report.status == "warn"
    assert report.warn_count == 1
    by_key = {item.key: item for item in report.evaluations}
    assert by_key["latency"].status == "warn"
    assert by_key["throughput"].status == "ok"


def test_render_and_serialize_report(tmp_path: Path) -> None:
    budget_path = tmp_path / "budgets.json"
    _write_budget(budget_path)
    budgets = load_metric_budgets(budget_path, "quick")

    report = evaluate_metrics({"latency": 90, "throughput": 11}, budgets, mode="quick")
    markdown = render_markdown_summary(report, title="Perf Summary")

    assert "Perf Summary" in markdown
    assert "`latency`" in markdown
    assert "Status" in markdown

    payload = serialize_report(report)
    assert payload["mode"] == "quick"
    assert payload["status"] == "ok"
    assert payload["warn_count"] == 0
