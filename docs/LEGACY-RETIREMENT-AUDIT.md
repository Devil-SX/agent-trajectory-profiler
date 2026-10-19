# Legacy retirement audit, 2026-10-19

Status: source retirement prepared after integrating-Agent authorization. The obsolete dependency closure below was removed from the working tree; production migration acceptance remains the integrating Agent's release responsibility. No user database was opened or deleted. Findings refer to baseline `ee9a920`; the task-analysis UI was added in `b53a6c0`. This document records migration evidence and does not replace current HTTP Help or maintenance instructions.

## Installed authority

`pyproject.toml` includes only `trajectory` and `trajectory.product`. Its sole executable is `trajectory-server = trajectory.product.server:main`; default pytest collection is `tests/product`, and mypy targets `trajectory/product`. The production dashboard is `trajectory/product/dashboard.html`.

An AST inspection of every production Python module found zero `agent_vis` imports. Production imports are Python standard library, FastAPI, Pydantic, Uvicorn and shared `batcave_http`, plus the product package itself. This establishes no static runtime dependency on the former local profiler; dynamic imports, external wrappers and actual installed artifacts still require release acceptance.

## Retired source and former consumers

| Candidate | Tracked scope at baseline | Remaining consumers | Acceptance before removal |
| --- | --- | --- | --- |
| `agent_vis/` | 50 files, 697031 bytes, including API, CLI, local DB, parsers, prompts, summaries, embeddings and clustering | Old tests, four old scripts, install wrapper, old frontend and documentation | Unified parser, remote source ingestion, task analysis and real usage reconciliation accepted; keep all user DB files untouched |
| `frontend/` | 156 files, 5604158 bytes | Old CLI `check_and_build_frontend`, old API static mounts, old CI workflows and docs | Current installed dashboard and its browser tests accepted, including historical gaps and failures |
| Root `Cargo.toml`, `src/lib.rs` | PyO3 `agent-vis-native` character classifier | `agent_vis/parsers/character_classifier.py` dynamically imports `agent_vis._native`; legacy native tests | Unified character metric tests accepted; remove this old crate separately from the new agent-session worker crate |
| `tests/test_*.py`, `tests/perf/` | All 37 top-level test modules import `agent_vis`; old perf budgets only cover old implementation | Legacy pytest suite and backend-performance workflow | Relevant assertions represented in production parser, ingestion, cost, provenance, deduplication and browser suites; retire implementation-specific assertions with old code |
| `tests/conftest.py` | Legacy global fixture setup | **Also loaded when collecting `tests/product`**, importing old API at module import time | Remove or replace with fixtures used only by the production suite; do not leave old imports as a hidden test dependency |
| Four old scripts: `export_openapi_schema.py`, `profile_real_sync.py`, `run_backend_perf.py`, `run_parser_bench.py` | Every script imports `agent_vis` | Old frontend type generation and old performance CI | Retire together with consumers; current Help/contract registry remains the authority, do not regenerate old OpenAPI |
| `install.sh`, `uninstall.sh` | Installs/removes `~/.local/bin/agent-vis` wrappers | Old READMEs and CLAUDE instructions | Delete source scripts after confirming release paths do not invoke them; never run uninstall automatically against a user's home |
| `skills/chat_trajectory/` | Three files promote direct reads of `~/.agent-vis/profiler.db` | External Agents following repository skill instructions | Remove obsolete skill source; authorized business reads use the authenticated HTTP interface |
| `.github/workflows/backend-performance.yml`, `nightly-frontend.yml` | Targets retired parser and React stack | GitHub scheduled and PR checks | Replace needed coverage on current stack before removing workflows |

## Files requiring rewrite rather than blind deletion

- `.github/workflows/ci.yml` currently uses Python 3.10 and 3.11 despite project minimum 3.12; it also executes the obsolete React app. Replace it with quality checks for the actual product, Rust worker and dashboard. All service execution tests must follow the remote-isolation rule; do not silently add local-only acceptance.
- `AGENTS.md` has quality obligations and a full path matrix for the retired stack. Preserve the requirement for meaningful tests, failure/empty/mobile coverage and coordination restrictions; replace obsolete paths and commands.
- `CLAUDE.md` duplicates obsolete local installation, CLI, DB and frontend instructions. Prefer a concise pointer to the maintained AGENTS, README and architecture instead of another command catalogue.
- `README.zh.md` currently describes the former local database and CLI. Rewrite from the current product interface or remove duplicate documentation deliberately; it must not remain a competing usage guide.
- `ARCHITECTURE.md` needs its temporary legacy-retirement paragraph replaced after acceptance, and the canonical raw-source, parser-worker and analysis pipeline documented by the integrating Agent.
- Keep `docs/PROTOCOL.md` until its current collector contract is migrated with running Sparkstead compatibility and replay reconciliation. Do not drop old wire delivery acceptance merely because the analyzer is replaced.
- The other 18 existing `docs/` files describe former local contracts, commands and benchmarks. Contract and operation guides should retire with their implementation. The historical March benchmark must remain identifiable as historical evidence if retained; old benchmark results cannot certify the new pipeline.
- Preserve `CHANGELOG.md` history. `.prd/` and `.original_spec/` are historical planning artifacts, not runtime inputs; they may be removed from the working tree while remaining in Git history, but are not user database migrations.
- Do not touch `trajectory/product`, the new Rust worker, current deployment assets, new tests, generated raw source archives or any real user database during mechanical cleanup.

## Validation and scope

The UI replacement has passed remote browser tests on `batcave-wsl`, isolated directory `/home/saveer/BatCave/tests/trajectory-semantic-ui-20261019`. These are fixture-based interaction tests, not proof of production parser equivalence or live deployment.

Run the read-only `scripts/audit_legacy_retirement.py` from the checked-out revision to obtain exact candidate paths, production imports and package boundaries. It only reads tracked source and emits JSON; it does not load application code, open SQLite, remove files, or automatically authorize removals.

After approval of the candidate, remove the old dependency closure together, rerun current remote tests against the installed wheel, inspect wheel members, and confirm old namespaces, launch scripts and active documentation have no remaining consumers. Keep the migration receipt and real usage reconciliation before cleaning up any historical database storage.


## Retirement validation

All 34 current product tests passed after removing legacy source and the global legacy conftest. Remote Ruff and Black checks passed, mypy passed for all six product Python files, and a wheel was built in `/home/saveer/BatCave/tests/trajectory-retirement-20261019`. Its payload includes only `trajectory` and `trajectory.product`, including the current dashboard; it contains no `agent_vis`, old frontend or former PyO3 extension. Tests use a disposable virtual environment and the shared SDK directly through its read-only published Python zip, without copying SDK source.

No GitHub runner was found in the checked common runner locations or systemd unit listing. The workflow therefore remains manual and requires explicit registration/configuration; no CI run is claimed by this audit. Direct SSH execution on batcave-wsl is the observed validation path.
