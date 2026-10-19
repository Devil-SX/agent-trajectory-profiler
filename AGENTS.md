# Trajectory contributor contract

## Product authority

- Maintain one authenticated remote product under `trajectory/product`. The public HTTP operation registry generates current Help and schemas. Do not recreate a local analysis server, direct-user database API, or separate dashboard.
- Read [README.md](README.md) for supported use, [ARCHITECTURE.md](ARCHITECTURE.md) for ownership and data flow, and [docs/PROTOCOL.md](docs/PROTOCOL.md) for collector delivery semantics. Runtime operations and permissions are discovered through current Help.
- Agent-session is a pinned parsing dependency. Keep source-specific interpretation in the parser adapter, not in the browser. Keep real consumption and price rules in the domain; task labels may change without duplicating consumption.
- Retain raw source identity, revision, operation evidence and explicit metric gaps. Unknown values are not zero. Human-origin and cached-token semantics must not be inferred from absent evidence.

## Changes and tests

- Production changes require meaningful regression coverage or an explicit justification for why existing coverage suffices. Exercise behavior, not private implementation details.
- Domain and interface changes require authenticated, account-isolated tests, durable replay/idempotency tests, revision conflicts and malformed-input coverage as appropriate.
- Parser changes require representative original-source fixtures, inherited-context deduplication, usage semantics and missing-field checks.
- Dashboard changes require browser coverage for loading, empty, partial, failed and stale states; filtering, task/evidence navigation, keyboard access and mobile layout as relevant. Use `tests/browser`, not the retired React app.
- Client changes must verify automatic and Agent-initiated synchronization share checkpoint/outbox ownership and do not duplicate uploads.
- Run tests on `batcave-wsl` in isolated environments under `/home/saveer/BatCave/tests`. Local work is source editing, static inspection and result review. Never point tests at production databases, account stores or real identity credentials.
- Python requires 3.12 or newer. Use project-local uv environments and the committed dependency lock. Run Ruff, Black, mypy and pytest for current packages. Native workers use their own pinned Cargo dependencies and targeted Rust tests.
- CI runs only on a remote isolated BatCave test runner. A missing runner is a blocked check, not authorization to substitute local execution. Browser test dependencies belong under `tests/browser`.
- Fix or explicitly track recurring flaky checks. Do not suppress failures or remove active behavior tests to obtain a green result.

## Delivery and coordination

- Follow the workspace production-online, remote-test, release-lock and backup rules. Do not restart Sparkstead as part of parser or web development.
- Migration candidates must preserve running collectors, real data and durable receipts. Retire obsolete source only after its active replacements are accepted; do not keep a second analysis implementation as a permanent compatibility layer.
- Keep README focused on the human and Agent interface. Internal architecture belongs in ARCHITECTURE or developer docs; deployment maintenance is discovered through Ops Help.
- Website UI must not contain Unicode U+00B7, including generated labels and accessibility text. Preserve quoted paper titles and original user data.
- Use independent worktrees for concurrent changes and revalidate after integration.
- Do not auto-use `todo_preview` or read/write `~/.todo/todo.md` without explicit user instruction.
