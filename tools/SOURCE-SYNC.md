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
discovers those files, it computes the identical ID. An unanchored root requires explicit authenticated registration as described below;
`allow_new_sources` alone does not authorize arbitrary paths or a new collector.
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

Supported `ecosystem` values are `codex`, `claude_code` and `pi`. A Pi root uses
its native `~/.pi/agent/sessions` tree and the exact path spelling registered by
the existing collector. It follows the same registered-root anchor checks,
checkpoint/outbox and process lock as other ecosystems. Adding a Pi root never
resets existing Codex/Claude state or creates another collector identity.

## Registering a new ecosystem root

When an ecosystem has no legacy source anchor, first add its exact local/legacy
mapping to the shared owner-private configuration with `allow_new_sources: true`.
Then explicitly register that configured local root:

```sh
python3 tools/trajectory_source_sync.py --config /private/source-sync.json --register-root /home/user/.pi/agent/sessions
```

Registration verifies a native machine identity and upload permission through
authenticated Help, then makes a `source-progress` read for a real file in the root. The server verifies the current native machine, its permission and the
collector's owner binding. Only a successful response authorizes the exact
`local_root`, `legacy_root` and `ecosystem` mapping in the existing shared SQLite
state, recording the machine account, client and credential SHA-256 fingerprint.
It does not create a remote source or invent a legacy anchor. Changed
mappings or another endpoint/collector require their own explicit registration.
Normal uploads continue to verify credentials and the server binding on every
request. Never edit the legacy identity snapshot or add a fabricated source ID.

## Selecting sessions without resetting delivery

`--source CANONICAL_SOURCE_SHA256` and `--only-session NATIVE_SESSION_UUID` are
repeatable and combine as a union. Session UUID matching uses the original source
filename, without reading the entire log or generating a summary. They restrict
only preparation of new chunks. Every existing pending outbox body is still sent
first, unchanged, even if it belongs to another source. Neither option changes
state binding, generation, mutation ID or checkpoint ownership.

```sh
python3 tools/trajectory_source_sync.py --config /private/source-sync.json --only-session 01a0f312-da54-77e1-99da-92e1d2b5568b --max-chunks 100
python3 tools/trajectory_source_sync.py --config /private/source-sync.json --source CANONICAL_SOURCE_SHA256 --status
```

Status reports the selected source identities, names and sizes. An invocation
without selectors retains normal all-source discovery. If an automatic timer also
runs without selectors it retains its configured discovery scope; selection on a
manual invocation does not silently reconfigure that timer.

## Keeping an automatic root limited to selected sessions

A root may set `only_sessions` to a list of native session UUIDs. The uploader
reuses the CLI session selector when discovering files in that root. Other roots
keep their normal discovery scope. For example, an authorized Pi root can track
only two chosen sessions while Codex roots continue normal automatic collection:

```json
{
  "local_root": "/home/user/.pi/agent/sessions",
  "legacy_root": "\\\\wsl.localhost\\Ubuntu-22.04\\home\\user\\.pi\\agent\\sessions",
  "ecosystem": "pi",
  "allow_new_sources": true,
  "only_sessions": [
    "01a0f312-da54-77e1-99da-92e1d2b5568b",
    "01a0f304-0850-7373-a518-9292f78d73c5"
  ]
}
```

An omitted allowlist discovers normally; an empty list discovers no files from
that root. Invalid types and invalid UUIDs are rejected. The allowlist affects
new work preparation only: existing pending outbox bodies replay unchanged even
when their session has been excluded. Root authorization identity still consists
of `local_root`, `legacy_root` and `ecosystem`; changing this discovery scope does
not create another registration, collector or checkpoint/outbox chain. Explicit
entries in the configuration's `sources` list remain explicitly selected.

The isolated `batcave-wsl` source-sync suite passes 24 tests, including two selected
Pi sessions, an excluded historical file never prepared, unchanged other-root
discovery and actual HTTP replay of an excluded pending source. Ruff and Black
pass with the repository configuration. No live configuration/state is changed
by this verification.
