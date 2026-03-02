# ~/.agent-vis Directory Specification

This document defines the canonical local directory layout for `~/.agent-vis`, including naming, file roles, permission guidance, and security notes.

> Scope boundary: this specification **does not include version migration strategy**.

## Goals

- Keep all local state in one auditable home directory.
- Make file roles explicit (config vs runtime state vs data vs logs).
- Minimize accidental leakage of sensitive content.

## Recommended Tree

```text
~/.agent-vis/
├── config/
│   ├── settings.toml
│   └── telegram.toml
├── state/
│   ├── frontend-preferences.json
│   ├── sync-state.json
│   └── report-state.json
├── data/
│   ├── profiler.db
│   ├── profiler.db-wal
│   └── profiler.db-shm
└── logs/
    ├── app.log
    └── sync.log
```

Notes:
- Files are created lazily when related features are used.
- `profiler.db`, `profiler.db-wal`, and `profiler.db-shm` are managed by SQLite.

## Naming Rules

- Root path is fixed to `~/.agent-vis`.
- Directory names use lowercase kebab-case.
- Config files use `*.toml`.
- Runtime state files use `*.json`.
- Database file name is fixed: `profiler.db`.
- Log files use `*.log`.

## File Roles

- `config/settings.toml`: user-level persistent settings (paths, UI defaults, feature toggles).
- `config/telegram.toml`: Telegram integration credentials and delivery settings.
- `state/frontend-preferences.json`: frontend preference snapshot (for example locale/theme/density/view mode).
- `state/sync-state.json`: sync runtime checkpoints and last sync metadata.
- `state/report-state.json`: reporting checkpoint (for example last report time/window).
- `data/profiler.db`: canonical parsed-session database.
- `logs/*.log`: operational logs for troubleshooting.

## Permission Guidance (Least Privilege)

Recommended permissions:

- `~/.agent-vis` and all subdirectories: `0700`
- Sensitive files (`config/*.toml`, `state/*.json`, `data/profiler.db*`): `0600`
- Log files (`logs/*.log`): `0600`

Example hardening commands:

```bash
chmod 700 ~/.agent-vis ~/.agent-vis/config ~/.agent-vis/state ~/.agent-vis/data ~/.agent-vis/logs
chmod 600 ~/.agent-vis/config/*.toml ~/.agent-vis/state/*.json ~/.agent-vis/data/profiler.db*
chmod 600 ~/.agent-vis/logs/*.log
```

## Security Notes

- Treat any secret-like field (for example bot token, API token, webhook secret) as sensitive; do not commit or share these files.
- Do not grant group/world read permission for `~/.agent-vis`.
- Avoid storing raw session content in config/state files; keep large content in DB only.
- If diagnostics must be shared, redact tokens, absolute home paths, and project identifiers before export.
- Do not symlink `~/.agent-vis` to shared or world-readable directories.

## Non-goals

- No migration policy or cross-version upgrade workflow is defined here.
- No guarantee that every file above already exists in all installations.
