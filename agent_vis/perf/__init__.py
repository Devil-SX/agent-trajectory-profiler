"""Performance utilities for backend benchmarking and budget evaluation."""

from .framework import (
    BudgetEvaluationReport,
    MetricBudget,
    MetricEvaluation,
    evaluate_metrics,
    load_metric_budgets,
    render_markdown_summary,
    serialize_report,
)
from .parser_benchmark import (
    render_parser_benchmark_markdown,
    run_parser_decoder_benchmarks,
    write_parser_benchmark_artifacts,
)
from .sync_profiler import (
    PRIVATE_SYNC_FILE_ENV,
    PRIVATE_SYNC_ROOT_ENV,
    profile_session_file,
    profile_sync_directory,
    render_sync_profile_markdown,
    resolve_private_sync_file,
    resolve_private_sync_root,
    write_sync_profile_artifacts,
)

__all__ = [
    "render_parser_benchmark_markdown",
    "run_parser_decoder_benchmarks",
    "write_parser_benchmark_artifacts",
    "PRIVATE_SYNC_FILE_ENV",
    "PRIVATE_SYNC_ROOT_ENV",
    "profile_session_file",
    "profile_sync_directory",
    "render_sync_profile_markdown",
    "resolve_private_sync_file",
    "resolve_private_sync_root",
    "write_sync_profile_artifacts",
    "BudgetEvaluationReport",
    "MetricBudget",
    "MetricEvaluation",
    "evaluate_metrics",
    "load_metric_budgets",
    "render_markdown_summary",
    "serialize_report",
]
