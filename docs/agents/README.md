# Agent Ecosystem Parsing Docs

This directory is the canonical index for per-ecosystem parsing behavior.

Goal: keep Path 1 (`source format -> canonical/unified model`) explicit and scalable.

## Directory Contract

Each ecosystem file must document:

1. Source roots and file discovery rules.
2. Session identity strategy (session ID, logical/physical lineage).
3. Raw event shapes and mapping rules.
4. Canonical conversion behavior and fallback strategy.
5. Known limitations and data-quality caveats.

Use [`_template.md`](./_template.md) for new ecosystems.

## Supported Ecosystems

| Ecosystem | Parser module | Doc | Default root |
| --- | --- | --- | --- |
| `claude_code` | `agent_vis/parsers/claude_code.py` | [`claude_code.md`](./claude_code.md) | `~/.claude/projects` |
| `codex` | `agent_vis/parsers/codex.py` | [`codex.md`](./codex.md) | `~/.codex/sessions` |

## Related Standards

- Capability manifest contract: `docs/agent-capability-manifest.md`
- Canonical schema: `docs/standards/canonical-trajectory-schema.md`
- Sync contract: `docs/standards/canonical-db-sync-contract.md`
- Query/export contract: `docs/standards/query-export-contract.md`

When adding a new ecosystem, update all of the above and keep parser docs aligned with manifest capabilities.
