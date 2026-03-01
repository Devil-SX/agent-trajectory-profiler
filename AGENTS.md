# AGENTS.md

This document defines the mandatory quality contract for agents contributing to this repository.

## Purpose

- Prevent silent regressions in UI behavior and analytics correctness.
- Ensure every code change is backed by targeted and maintainable test coverage.
- Align local validation, PR review expectations, and CI enforcement.

## Non-Negotiable Rule

- If code changes, tests must change.
- For any production code edit, agents must either:
  - add/update tests in the same PR, or
  - provide a clear, explicit justification in the PR description for why no test change is required.

## Change-to-Test Matrix

Use this matrix to determine minimum required test updates.

| Changed paths | Required test updates |
| --- | --- |
| `frontend/src/components/MessageTimeline*` | E2E scroll-position behavior test, long-content layout test |
| `frontend/src/components/DateRangePicker*` | E2E viewport clipping test, keyboard open/close test, filter state persistence test |
| `frontend/src/components/StatisticsDashboard*` | E2E statistics page visibility/scrollability test, chart/table render assertions |
| `frontend/src/components/AdvancedAnalytics*` | E2E analytics tab render + cross-session aggregate assertions |
| `frontend/src/components/SessionBrowser*` | E2E loading/empty/error state assertions, session selection flow |
| `frontend/src/components/SessionFilter*` | E2E search/sort/filter synchronization assertions |
| `frontend/src/App*` | E2E tab-state persistence and session-switch behavior |
| `frontend/src/api/*` / `frontend/src/hooks/*` | Integration/E2E request-state assertions (loading, stale data, error recovery) |
| `claude_vis/api/*` | API integration tests for response schema and error handling |
| `claude_vis/parsers/*` / `claude_vis/db/*` | Pytest parser/repository regression tests and edge-case coverage |

## Test Levels and Tagging Contract

- `@smoke`: PR blocking tests for critical paths.
- `@full`: nightly broad regression tests.
- `@visual`: visual snapshot contract tests.
- `@a11y`: accessibility and keyboard interaction tests.

Agents should mark new Playwright tests with one of these tags in the test title.

## PR Checklist (Required)

- [ ] Code changes are covered by updated/added tests.
- [ ] `frontend` checks passed locally when frontend code changed:
  - [ ] `npm run lint`
  - [ ] `npm run type-check`
  - [ ] `npm run build`
  - [ ] `npm run test:e2e:smoke`
- [ ] `backend` checks passed locally when backend code changed:
  - [ ] `uv run ruff check .`
  - [ ] `uv run black --check .`
  - [ ] `uv run mypy .`
  - [ ] `uv run pytest --tb=short`
- [ ] Visual baseline changes (if any) are intentional and documented in PR description.
- [ ] No test runtime artifacts are committed (`frontend/playwright-report/`, `frontend/test-results/`).

## CI Expectations

Required checks for merge:

- `backend-quality`
- `frontend-static-checks`
- `frontend-e2e-smoke`

Nightly quality checks:

- `frontend-e2e-full`
- `frontend-visual-regression`
- `frontend-a11y`

## Flaky Test Policy

- First failure: retry using the configured CI retry strategy and inspect Playwright trace.
- Repeated failure: mark as flaky issue and assign an owner in the same day.
- Persistent flake (> 3 consecutive CI runs): test must be fixed or quarantined with an issue link and planned removal date.

## No Silent Regression Rule

- It is not acceptable to merge behavior or UI changes that reduce test coverage.
- It is not acceptable to disable failing tests without a linked issue and mitigation plan.
