"""Budget loading, regression evaluation, and summary rendering for perf runs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

MetricDirection = Literal["lower_is_better", "higher_is_better"]
MetricStatus = Literal["ok", "warn"]


@dataclass(frozen=True)
class MetricBudget:
    """Budget threshold for one performance metric."""

    key: str
    description: str
    unit: str
    direction: MetricDirection
    target: float
    warn: float


@dataclass(frozen=True)
class MetricEvaluation:
    """Evaluation result for one metric against its budget."""

    key: str
    description: str
    unit: str
    direction: MetricDirection
    measured: float | None
    target: float
    warn: float
    status: MetricStatus
    note: str | None = None


@dataclass(frozen=True)
class BudgetEvaluationReport:
    """Full evaluation report for one benchmark mode."""

    mode: str
    evaluations: list[MetricEvaluation]

    @property
    def status(self) -> MetricStatus:
        return "warn" if any(item.status == "warn" for item in self.evaluations) else "ok"

    @property
    def warn_count(self) -> int:
        return sum(1 for item in self.evaluations if item.status == "warn")


def load_metric_budgets(path: Path, mode: str) -> dict[str, MetricBudget]:
    """Load budget definitions for the selected mode from JSON config."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    try:
        mode_payload = payload["modes"][mode]
        metrics_payload = mode_payload["metrics"]
    except KeyError as exc:
        raise ValueError(f"Budget mode '{mode}' not found in {path}") from exc

    budgets: dict[str, MetricBudget] = {}
    for key, raw in metrics_payload.items():
        budgets[key] = MetricBudget(
            key=key,
            description=str(raw["description"]),
            unit=str(raw.get("unit", "")),
            direction=raw["direction"],
            target=float(raw["target"]),
            warn=float(raw["warn"]),
        )
    return budgets


def _evaluate_one_metric(
    budget: MetricBudget,
    measured: float | None,
) -> MetricEvaluation:
    if measured is None:
        return MetricEvaluation(
            key=budget.key,
            description=budget.description,
            unit=budget.unit,
            direction=budget.direction,
            measured=None,
            target=budget.target,
            warn=budget.warn,
            status="warn",
            note="missing metric",
        )

    if budget.direction == "lower_is_better":
        meets_warn = measured <= budget.warn
        note = None
        if measured > budget.warn:
            note = "above warn threshold"
        elif measured > budget.target:
            note = "above target"
    else:
        meets_warn = measured >= budget.warn
        note = None
        if measured < budget.warn:
            note = "below warn threshold"
        elif measured < budget.target:
            note = "below target"

    return MetricEvaluation(
        key=budget.key,
        description=budget.description,
        unit=budget.unit,
        direction=budget.direction,
        measured=float(measured),
        target=budget.target,
        warn=budget.warn,
        status="ok" if meets_warn else "warn",
        note=note,
    )


def evaluate_metrics(
    measured_metrics: dict[str, float],
    budgets: dict[str, MetricBudget],
    *,
    mode: str,
) -> BudgetEvaluationReport:
    """Compare measured metrics against budgets and return evaluation report."""
    evaluations = [
        _evaluate_one_metric(budget, measured_metrics.get(metric_key))
        for metric_key, budget in budgets.items()
    ]
    return BudgetEvaluationReport(mode=mode, evaluations=evaluations)


def _format_value(value: float | None, unit: str) -> str:
    if value is None:
        return "n/a"
    if unit:
        return f"{value:.2f} {unit}"
    return f"{value:.2f}"


def render_markdown_summary(report: BudgetEvaluationReport, *, title: str) -> str:
    """Render a markdown summary suitable for CI job summary and artifacts."""
    lines = [
        f"## {title}",
        "",
        f"- Mode: `{report.mode}`",
        f"- Status: **{report.status.upper()}**",
        f"- Warn count: `{report.warn_count}`",
        "",
        "| Metric | Measured | Target | Warn | Direction | Status | Notes |",
        "|---|---:|---:|---:|---|---|---|",
    ]

    for item in report.evaluations:
        lines.append(
            "| "
            f"`{item.key}` ({item.description}) | "
            f"{_format_value(item.measured, item.unit)} | "
            f"{_format_value(item.target, item.unit)} | "
            f"{_format_value(item.warn, item.unit)} | "
            f"`{item.direction}` | "
            f"**{item.status.upper()}** | "
            f"{item.note or ''} |"
        )

    return "\n".join(lines) + "\n"


def serialize_report(report: BudgetEvaluationReport) -> dict[str, object]:
    """Convert report to JSON-serializable dictionary."""
    return {
        "mode": report.mode,
        "status": report.status,
        "warn_count": report.warn_count,
        "evaluations": [asdict(item) for item in report.evaluations],
    }
