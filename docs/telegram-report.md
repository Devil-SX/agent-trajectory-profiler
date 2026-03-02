# Telegram Incremental Report

`agent-vis` supports Telegram Bot incremental summary delivery via CLI.

## Command

```bash
agent-vis report telegram --dry-run
agent-vis report telegram
```

Optional paths:

```bash
agent-vis report telegram \
  --config-path ~/.agent-vis/config/telegram.toml \
  --state-path ~/.agent-vis/state/report-state.json \
  --db-path ~/.agent-vis/profiler.db
```

## Config File

Default path: `~/.agent-vis/config/telegram.toml`

```toml
[telegram]
enabled = true
bot_token = "123456789:telegram-bot-token"
chat_id = "-1001234567890"
timezone = "UTC"
disable_web_page_preview = true
```

Field notes:

- `enabled`: set `false` to disable sending without deleting config.
- `bot_token`: Telegram Bot API token.
- `chat_id`: target chat or channel id.
- `timezone`: reserved for future localized formatting.
- `disable_web_page_preview`: pass-through option for Telegram sendMessage API.

## State File

Default path: `~/.agent-vis/state/report-state.json`

State currently stores:

- `last_report_sent_at`
- `last_report_status`
- `last_report_error`

Behavior:

- First run (`last_report_sent_at` missing): summary uses all sessions in DB.
- Incremental run: summary includes sessions created strictly after `last_report_sent_at`.
- Failed send does **not** advance `last_report_sent_at`.

## Summary Content

Current message includes at least:

- new session count in window
- source distribution (`claude_code` / `codex`)
- bottleneck distribution
- total tool-error count and categorized counts

## Security Notes

- Keep `~/.agent-vis/config` and config files private (`0700` / `0600`).
- Never commit `telegram.toml` or state files into git.
- Treat `bot_token` as secret and rotate if leaked.
