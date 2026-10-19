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

## Automatic source discovery and native Windows identity

For a Windows-owned live collector, configure `legacy_node` with the native Windows
Node executable and `legacy_state_windows` with its Windows database path. Every
invocation queries collector/source IDs through a read-only native SQLite connection;
stdout is parsed internally and no source contents or credentials are read. This
avoids the WSL mount's SQLite WAL locking incompatibility without copying live DBs.

Dynamic source roots supplement the optional explicit `sources` list:

```json
{
  "legacy_node": "/mnt/c/Program Files/nodejs/node.exe",
  "legacy_state_windows": "C:\\Users\\USER\\AppData\\Roaming\\agent-watchboard\\trajectory\\collector.db",
  "roots": [{
    "local_root": "/home/USER/.codex/sessions",
    "legacy_root": "\\\\wsl.localhost\\Ubuntu-22.04\\home\\USER\\.codex\\sessions",
    "ecosystem": "codex"
  }]
}
```

By default, new files are deferred until the existing collector registers their
canonical source ID. A root may explicitly set `allow_new_sources: true` after its
local/legacy mapping has at least one currently registered deterministic source-ID
anchor. The uploader then derives new source IDs from the same collector and
exact legacy-root spelling without waiting for Sparkstead. When Sparkstead later
discovers those files, it computes the identical ID. An unanchored root is rejected;
this option does not authorize arbitrary explicit source paths or a new collector.
Resolved source paths must remain inside their declared local root.
The state is private, endpoint-bound and collector-bound; changing the target or
collector fails rather than silently reusing offsets against another destination.

The example user service and timer under `tools/systemd/` schedule this same CLI.
Install the script at `~/.local/lib/trajectory/trajectory_source_sync.py`, the shared
configuration at `~/.config/trajectory/source-sync.json`, and both units at
`~/.config/systemd/user/`. Enable with `systemctl --user enable --now
trajectory-source-sync.timer`. Manual calls must use the same configuration/state.
The timer starts one-shot jobs with a 20-chunk limit (at most 10 MiB) after the preceding job finishes; the OS lock also
protects against concurrent Agent calls. This does not restart or reconfigure
Sparkstead. The timer runs on the log-owning machine, not the remote BatCave server.

## Prefix integrity and checkpoint loss

Each checkpoint stores SHA-256 of the entire queued byte prefix, not a fixed-size
file header. Source mutation after byte 1024 is therefore detected. Successful
validation also records `(dev, ino, size, mtime_ns, ctime_ns)` in the same SQLite
transaction. A completed file with an unchanged full fingerprint needs no reread;
changed files receive full-prefix validation. During a multi-chunk invocation,
validated hash state is reused only while the full fingerprint remains unchanged.
The client rejects files that change while a prefix is being validated.

Before starting any source without local state, the uploader performs authenticated
GET `/trajectory/api/source-progress?collector=...&source=...`. If a remote generation
already exists, it exits with `recovery_required` instead of generating a new source
generation or trusting the remote offset without content verification. The current
progress interface does not provide the prefix digest needed for automatic state
reconstruction. Restore a verified checkpoint backup; do not delete state as a
retry mechanism. Old checkpoints containing only a partial prefix hash are also
rejected and require explicit verified recovery.

Competing invocations report `state=busy` and exit successfully for rescheduling.
They do not emit a traceback or acquire a second writer. The example unit runs at
Nice 10 with idle I/O scheduling priority.

## Explicit proxy transport

The optional configuration field `proxy` accepts `environment` (default) or
`direct`. Direct mode installs an empty `urllib.ProxyHandler` for this uploader's
own HTTP opener, covering Help, progress and upload requests. It does not modify
system proxy settings or process environment, and keeps the original HTTPS URL,
TLS hostname and certificate verification. Use it when the service's confirmed
public DNS route works directly and a local environment proxy causes handshake
failures. A changed proxy transport never changes source identity, pending body,
mutation ID or checkpoints.

All discovered sources are ordered by newest `mtime_ns`, then stable legacy path.
An existing pending outbox body is always replayed unchanged before preparing any
new chunk. This makes recent and actively growing sessions visible promptly;
historical sources use remaining cycle capacity. It does not promise strict
fairness or a deadline for completing all historical backfill.
