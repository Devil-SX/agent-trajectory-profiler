# Backend Performance Baseline

This document defines how backend performance is measured, persisted, and reviewed in this repository.

## Goals

- Keep backend performance checks as a long-lived repository asset (not ad-hoc one-off runs).
- Detect regressions early in pull requests using a non-blocking budget gate.
- Produce trend-friendly artifacts for nightly runs.

## Scope

Current benchmark scope includes four backend paths:

- Sync ingestion path (`SyncEngine.sync`)
- Claude parse decoder benchmark (`parse_jsonl_file_with_compact_events` via staged decoder pipeline)
- Parser statistics hotspot (`calculate_session_statistics`) backed by the required Rust character classifier
- Cross-session analytics APIs (`get_analytics_overview`, `get_analytics_timeseries`)

## Benchmark Assets

- Budget configuration: `tests/perf/budgets.json`
- Runner implementation: `agent_vis/perf/backend_runner.py`
- Backend perf payloads record the active `character_classifier` runtime implementation
- Parser benchmark runner: `agent_vis/perf/parser_benchmark.py`
- CLI entries: `scripts/run_backend_perf.py`, `scripts/run_parser_bench.py`

## Run Locally

Quick profile (PR-equivalent):

```bash
uv run python scripts/run_backend_perf.py --mode quick
```

Full profile (nightly-equivalent):

```bash
uv run python scripts/run_backend_perf.py --mode full
```

Outputs are written to `output/perf/`:

- `backend-perf-results.json` (machine-readable)
- `backend-perf-summary.md` (human-readable)
- timestamped archive files for historical comparison

## Real Local Sync Profiling

For real-data bottleneck analysis, use a git-ignored private softlink under `tests/fixtures/private/` and run:

```bash
uv run python scripts/profile_real_sync.py
```

Default private paths:

- Directory root: `tests/fixtures/private/claude_sync_root`
- Optional env override: `AGENT_VIS_PRIVATE_SYNC_ROOT`

Example setup:

```bash
mkdir -p tests/fixtures/private
ln -s ~/.claude/projects tests/fixtures/private/claude_sync_root
```

Outputs are written to `output/private-perf/` and are ignored by git.


## Metric Semantics

Budgets use two threshold levels:

- `target`: desired operating level
- `warn`: soft-gate boundary

Direction is explicit per metric:

- `lower_is_better` for latency/duration metrics
- `higher_is_better` for throughput metrics

If any metric breaches the `warn` threshold, run status becomes `WARN`.

## Soft Gate Policy

Performance checks are intentionally non-blocking by default:

- CI reports `OK/WARN` in job summary.
- Regressions upload artifacts for review.
- Merge is not blocked unless strict mode is explicitly enabled (`--strict`).

This keeps signal visible while avoiding flaky hard failures from noisy environments.

## CI Integration

Workflow: `.github/workflows/backend-performance.yml`

- Pull request: `quick` profile
- Nightly schedule: `full` profile
- Both upload JSON + Markdown artifacts and publish markdown summary

## Budget Governance

When performance improves or workload changes substantially:

1. Run both quick and full profiles locally.
2. Compare against recent CI artifacts.
3. Update `tests/perf/budgets.json` with rationale in PR description.
4. Keep thresholds realistic: avoid tuning for one machine only.

## Dataset Definition

The runner generates deterministic synthetic session fixtures with:

- configurable session count
- configurable turns per session
- consistent tool-use/tool-result patterns
- fixed timestamp ranges for stable analytics windows

This keeps benchmark behavior reproducible across developers and CI runners.
