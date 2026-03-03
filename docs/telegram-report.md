# Telegram Incremental Report

`agent-vis` supports Telegram Bot incremental summary delivery via CLI.

## Command

```bash
agent-vis report telegram --dry-run
agent-vis report telegram
agent-vis report telegram --window 7d
agent-vis report telegram --days 5
agent-vis report telegram --days 3 --format markdownv2 --style advanced
```

Optional paths:

```bash
agent-vis report telegram \
  --config-path ~/.agent-vis/config/telegram.toml \
  --state-path ~/.agent-vis/state/report-state.json \
  --db-path ~/.agent-vis/profiler.db \
  --window auto \
  --style advanced \
  --detail-level medium \
  --split-mode auto
```

Window options:

- `--window auto` (default): incremental mode using `last_report_sent_at`.
- `--window 1d|3d|7d|14d|30d|90d`: manual rolling window by common day ranges.
- `--window all`: full-range summary (all sessions in DB).
- `--days N`: manual custom rolling window (`N` days), overrides `--window`.
- `--style advanced|compact`: report layout style.
- `--format markdownv2|html|plain`: rich-text mode for Telegram messages.
- `--detail-level low|medium|high`: detail granularity.
- `--split-mode auto|single`: auto split by section/chunk, or force one message.
- `--max-message-chars N`: split/truncate threshold (512-4096, default 3800).
- `--send-details/--no-send-details`: include or skip detail sections.

## Config File

Default path: `~/.agent-vis/config/telegram.toml`

```toml
[telegram]
enabled = true
bot_token = "123456789:telegram-bot-token"
chat_id = "-1001234567890"
timezone = "UTC"
disable_web_page_preview = true

[telegram.report]
style = "advanced"
format = "markdownv2"
detail_level = "medium"
split_mode = "auto"
max_message_chars = 3800
send_details = true
```

Field notes:

- `enabled`: set `false` to disable sending without deleting config.
- `bot_token`: Telegram Bot API token.
- `chat_id`: target chat or channel id.
- `timezone`: reserved for future localized formatting.
- `disable_web_page_preview`: pass-through option for Telegram sendMessage API.
- `report.*`: default rendering and message segmentation behavior for telegram reports.

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
- Manual windows (`--window` not `auto`, or `--days`) do **not** update `last_report_sent_at`, even when send succeeds.
- In `auto` mode, checkpoint updates only when all message chunks are sent successfully.

## Summary Content

Current message includes at least:

- overview KPI (sessions/messages/tokens/tool-calls/errors)
- user/model/tool time breakdown (inactive shown separately)
- tool-error category summary and recent error excerpts
- source and bottleneck distribution

By default reports are sent in **MarkdownV2** rich-text mode.

## Rich Text Notes

- Telegram supports rich text via `parse_mode` (`MarkdownV2` / `HTML`).
- This command defaults to `MarkdownV2`.
- Long reports are split automatically when `split_mode=auto`.
- Telegram single-message limit is 4096 characters; the tool uses a lower default threshold (3800) for safety.

## Security Notes

- Keep `~/.agent-vis/config` and config files private (`0700` / `0600`).
- Never commit `telegram.toml` or state files into git.
- Treat `bot_token` as secret and rotate if leaked.
