# Native source synchronization

`trajectory_source_sync.py` is the one uploader for interactive Agents and future
Sparkstead scheduling. It runs with Python's standard library and never writes the
running Sparkstead collector database or restarts its worker.

## Contract

POST `/trajectory/api/source-chunks` authenticates with the existing native machine
account API key. Fields are `schema_id=trajectory-source-chunk/1`, `mutation_id`,
`collector`, `source`, `ecosystem`, `generation`, `start`, `end`, `source_bytes`,
`content` (base64), `sha256` (decoded content) and `source_name` (basename only).
Each decoded chunk is at most 512 KiB. Ranges are half-open byte ranges and may
split JSON lines or UTF-8 characters: the server must assemble bytes before parsing.

The receipt must contain `durable=true`, the same `mutation_id`, `accepted_bytes`
equal to the decoded length, and `next_offset` equal to that chunk's `end`.
Replay of an accepted mutation returns its original receipt. The server validates
source generation, contiguous ranges and content hash, and never adds these bytes
to the existing usage ledger a second time.

## Shared configuration

Use one owner-private JSON configuration and state path for all callers:

```json
{
  "url": "https://SERVICE/trajectory/api/source-chunks",
  "credential": "/private/existing-machine-credential.json",
  "legacy_state": "/existing/sparkstead/trajectory/collector.db",
  "state": "/private/trajectory-source-sync/state.sqlite",
  "sources": [{
    "path": "/home/user/.codex/sessions/example.jsonl",
    "legacy_path": "\\\\wsl.localhost\\Ubuntu-22.04\\home\\user\\.codex\\sessions\\example.jsonl",
    "ecosystem": "codex"
  }]
}
```

`source` is SHA-256 of `collector + ':' + legacy_path` with exactly the original
path spelling and separators. Never generate a second collector identity. The
client opens `legacy_state` read-only. If Windows owns a WAL-mode legacy database,
read it on Windows rather than copying DB/WAL or opening it through WSL's mounted
filesystem. Alternatively provide `legacy_identity_snapshot`, a JSON file exported
through a native read-only SQLite connection, containing `collector` and `sources`
(the existing source ID list), instead of `legacy_state`.

```sh
python3 tools/trajectory_source_sync.py --config /private/source-sync.json
python3 tools/trajectory_source_sync.py --config /private/source-sync.json --watch 15
```

Both modes use the same OS process lock and SQLite state. Competing invocations
fail with a retryable result instead of modifying each other's offsets. Checkpoint
advancement and outbox insertion are one FULL-synchronous transaction; retry sends
the exact stored body and mutation ID. Only a verified durable receipt removes it.
The outbox is bounded to 32 MiB. A crash after remote acceptance safely replays the
same mutation. Status output contains only counts and collector identity.

Legacy statistical uploads continue unchanged until the server canonical parser
and consumption migration are verified. Content synchronization is separate from
legacy byte checkpoints because it transports a different payload, but both bind
to the same collector/source identity and only the server owns usage accounting.
Future Sparkstead integration should invoke this executable with this shared
configuration rather than add another uploader or state directory.

## Verification

Run on an isolated `batcave-wsl` source checkout:

```sh
python3 -m unittest discover -s tests/client -v
```

Tests cover durable replay, bad receipts, append/replacement generations, byte
chunking independent of JSON line size, and competing writers. They do not contact
production or modify native collector data.
