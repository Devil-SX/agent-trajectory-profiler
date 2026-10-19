#!/usr/bin/env python3
"""Single native-source uploader for agents and Sparkstead schedulers (stdlib only)."""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import ntpath
import os
import re
import sqlite3
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

CHUNK_BYTES = 512 * 1024
OUTBOX_BYTES = 32 * 1024 * 1024


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def source_id(collector: str, legacy_path: str) -> str:
    return digest((collector + ":" + legacy_path).encode())


class RecoveryRequired(ValueError):
    """Checkpoint cannot be reconciled without explicit verified recovery."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Sync redirects are prohibited")


def http_opener(config: dict):
    mode = config.get("proxy", "environment")
    if mode == "direct":
        return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
    if mode == "environment":
        return urllib.request.build_opener(NoRedirect)
    raise ValueError("Unsupported source-sync proxy mode")


def credentials(path: Path, url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Unsafe sync URL")
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("HTTPS is required")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 16384:
        raise ValueError("Unsafe credential file")
    if os.name != "nt" and info.st_mode & 0o077:
        raise ValueError("Credential file must be private")
    data = json.loads(path.read_text())
    if data.get("origin") != f"{parsed.scheme}://{parsed.netloc}" or not data.get("api_key"):
        raise ValueError("Credential origin mismatch")
    return data["api_key"]


@contextlib.contextmanager
def process_lock(path: Path):
    """OS lock survives exceptions and is released automatically on process death."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise BlockingIOError("Shared source-sync lock is busy") from None
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class SyncState:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path)
        self.hash_cache = {}
        if os.name != "nt":
            path.chmod(0o600)
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sources(
              source TEXT PRIMARY KEY, generation TEXT, prefix_size INTEGER,
              prefix TEXT, offset INTEGER);
            CREATE TABLE IF NOT EXISTS outbox(
              id INTEGER PRIMARY KEY, body TEXT NOT NULL, bytes INTEGER NOT NULL);
        """)

    def bind(self, collector: str, url: str):
        binding = json.dumps({"collector": collector, "url": url}, sort_keys=True)
        with self.db:
            previous = self.db.execute("SELECT value FROM metadata WHERE key='binding'").fetchone()
            if previous and previous[0] != binding:
                raise ValueError("Sync state belongs to another endpoint or collector")
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES('binding',?)", (binding,))

    def close(self):
        self.db.close()

    def prepare(self, collector: str, spec: dict) -> bool:
        source = source_id(collector, spec["legacy_path"])
        row = self.db.execute("SELECT * FROM sources WHERE source=?", (source,)).fetchone()
        info = Path(spec["path"]).stat()
        fingerprint = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        size = info.st_size
        key = "verified-prefix:" + source
        saved = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        if (
            row
            and row[2] == row[4]
            and saved
            and tuple(json.loads(saved[0])) == fingerprint
            and row[4] == size
        ):
            return False
        if row and row[2] != row[4]:
            raise RecoveryRequired(
                "Legacy checkpoint lacks full-prefix integrity; explicit recovery required"
            )
        with open(spec["path"], "rb") as stream:
            cached = self.hash_cache.get(source)
            if row and cached and cached[0] == fingerprint and cached[1] == row[4]:
                hasher = cached[2].copy()
                stream.seek(row[4])
                remaining = 0
            else:
                hasher = hashlib.sha256()
                remaining = row[4] if row else 0
            while remaining:
                block = stream.read(min(CHUNK_BYTES, remaining))
                if not block:
                    break
                hasher.update(block)
                remaining -= len(block)
            reset = bool(row and (remaining or hasher.hexdigest() != row[3]))
            generation = row[1] if row and not reset else str(uuid.uuid4())
            offset = row[4] if row and not reset else 0
            if not reset and offset >= size:
                after = os.fstat(stream.fileno())
                verified = (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                )
                if verified != fingerprint:
                    raise ValueError("Source changed during prefix validation; retry required")
                with self.db:
                    self.db.execute(
                        "INSERT OR REPLACE INTO metadata VALUES(?,?)",
                        (key, json.dumps(fingerprint)),
                    )
                self.hash_cache[source] = (fingerprint, offset, hasher.copy())
                return False
            if reset:
                stream.seek(0)
                hasher = hashlib.sha256()
            content = stream.read(min(CHUNK_BYTES, max(0, size - offset)))
            if not content and not size:
                return False
            hasher.update(content)
            prefix_size = offset + len(content)
            prefix = hasher.hexdigest()
            after = os.fstat(stream.fileno())
            if (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ) != fingerprint:
                raise ValueError("Source changed during prefix validation; retry required")
        body = {
            "schema_id": "trajectory-source-chunk/1",
            "mutation_id": str(uuid.uuid4()),
            "collector": collector,
            "source": source,
            "ecosystem": spec["ecosystem"],
            "generation": generation,
            "start": offset,
            "end": offset + len(content),
            "source_bytes": size,
            "content": base64.b64encode(content).decode(),
            "sha256": digest(content),
            "source_name": Path(spec["path"]).name,
        }
        encoded = json.dumps(body, separators=(",", ":"))
        pending = self.db.execute("SELECT coalesce(sum(bytes),0) FROM outbox").fetchone()[0]
        if pending + len(encoded) > OUTBOX_BYTES:
            return False
        with self.db:
            self.db.execute("INSERT INTO outbox(body,bytes) VALUES(?,?)", (encoded, len(encoded)))
            self.db.execute(
                "INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?)",
                (source, generation, prefix_size, prefix, offset + len(content)),
            )
            self.db.execute(
                "INSERT OR REPLACE INTO metadata VALUES(?,?)", (key, json.dumps(fingerprint))
            )
        self.hash_cache[source] = (fingerprint, offset + len(content), hasher.copy())
        return True

    def next(self):
        return self.db.execute("SELECT id,body FROM outbox ORDER BY id LIMIT 1").fetchone()

    def acknowledge(self, row, receipt: dict):
        body = json.loads(row[1])
        if (
            receipt.get("durable") is not True
            or receipt.get("mutation_id") != body["mutation_id"]
            or receipt.get("accepted_bytes") != body["end"] - body["start"]
            or receipt.get("next_offset") != body["end"]
        ):
            raise ValueError("Invalid durable source receipt")
        with self.db:
            self.db.execute("DELETE FROM outbox WHERE id=?", (row[0],))


def legacy_identity(path: Path) -> tuple[str, set[str]]:
    # Deliberately readonly: never share the old collector's writer/checkpoint.
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute("SELECT value FROM metadata WHERE key='collector'").fetchone()
        if not row:
            raise ValueError("Legacy collector identity is missing")
        return row[0], {r[0] for r in db.execute("SELECT id FROM sources")}


def native_node_identity(executable: str, database: str) -> tuple[str, set[str]]:
    # Execute on the OS owning the live WAL; never copy the DB or request a writer.
    code = """
const {DatabaseSync}=require('node:sqlite');
const d=new DatabaseSync(process.argv[1],{readOnly:true});
try {console.log(JSON.stringify({collector:d.prepare(
  "SELECT value FROM metadata WHERE key='collector'").get().value,
  sources:d.prepare('SELECT id FROM sources').all().map(x=>x.id)}));}
finally {d.close();}
"""
    result = subprocess.run(
        [executable, "--no-warnings", "-e", code, database],
        cwd="/mnt/c/Windows/System32" if os.name != "nt" else None,
        capture_output=True,
        timeout=15,
        check=True,
    )
    identity = json.loads(result.stdout)
    return identity["collector"], set(identity["sources"])


def collector_identity(config: dict) -> tuple[str, set[str]]:
    if config.get("legacy_node"):
        collector, known = native_node_identity(
            config["legacy_node"], config["legacy_state_windows"]
        )
    elif config.get("legacy_state"):
        collector, known = legacy_identity(Path(config["legacy_state"]))
    elif config.get("legacy_identity_snapshot"):
        # Snapshot must be exported through readonly SQLite on its native OS.
        identity = json.loads(Path(config["legacy_identity_snapshot"]).read_text())
        collector, known = identity["collector"], set(identity["sources"])
    else:
        raise ValueError("Existing collector identity and source membership are required")
    return collector, known


def root_identity(root: dict) -> str:
    return digest(
        json.dumps(
            {key: root[key] for key in ("local_root", "legacy_root", "ecosystem")}, sort_keys=True
        ).encode()
    )


def registered_roots(config: dict, collector: str) -> set[str]:
    path = Path(config.get("state", ""))
    if not config.get("state") or not path.is_file():
        return set()
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        binding = db.execute("SELECT value FROM metadata WHERE key='binding'").fetchone()
        expected = json.dumps({"collector": collector, "url": config["url"]}, sort_keys=True)
        if binding is None:
            return set()
        if binding[0] != expected:
            raise ValueError("Root registration state belongs to another endpoint or collector")
        return {
            row[0].removeprefix("registered-root:")
            for row in db.execute("SELECT key FROM metadata WHERE key LIKE 'registered-root:%'")
        }


def validate_manifest(config: dict) -> tuple[str, list[dict]]:
    collector, known = collector_identity(config)
    approved = registered_roots(config, collector)
    specs = list(config.get("sources", []))
    anchored_new_sources = set()
    for root in config.get("roots", []):
        local_root = Path(root["local_root"])
        legacy_root = root["legacy_root"]
        if not local_root.is_absolute() or not (
            ntpath.isabs(legacy_root) or Path(legacy_root).is_absolute()
        ):
            raise ValueError("Source roots must be absolute")
        discovered = []
        for path in sorted(local_root.rglob("*.jsonl")):
            if not path.resolve().is_relative_to(local_root.resolve()):
                raise ValueError("Source symlink escapes its authorized root")
            relative = path.relative_to(local_root)
            legacy_path = (
                ntpath.join(legacy_root, *relative.parts)
                if "\\" in legacy_root or ":" in legacy_root
                else str(Path(legacy_root).joinpath(relative))
            )
            discovered.append(
                {"path": str(path), "legacy_path": legacy_path, "ecosystem": root["ecosystem"]}
            )
        allow_new = root.get("allow_new_sources", False)
        if not isinstance(allow_new, bool):
            raise ValueError("allow_new_sources must be a boolean")
        anchors = sum(source_id(collector, spec["legacy_path"]) in known for spec in discovered)
        if allow_new and not anchors and root_identity(root) not in approved:
            raise ValueError(
                "New-source discovery requires a registered source anchor "
                "or authenticated root registration"
            )
        for spec in discovered:
            identity = source_id(collector, spec["legacy_path"])
            if identity in known or allow_new:
                specs.append(spec)
                if identity not in known:
                    anchored_new_sources.add(identity)
    unique = {}
    for spec in specs:
        identity = source_id(collector, spec["legacy_path"])
        if identity in unique and unique[identity] != spec:
            raise ValueError("Conflicting local paths for the same source")
        unique[identity] = spec
    specs = list(unique.values())
    for spec in specs:
        if spec["ecosystem"] not in {"codex", "claude_code", "pi"}:
            raise ValueError("Unsupported ecosystem")
        if (
            source_id(collector, spec["legacy_path"]) not in known
            and source_id(collector, spec["legacy_path"]) not in anchored_new_sources
        ):
            raise ValueError("Source path does not match the existing collector")
        if not Path(spec["path"]).is_file():
            raise ValueError("Source file is unavailable")
    specs.sort(key=lambda spec: (-Path(spec["path"]).stat().st_mtime_ns, spec["legacy_path"]))
    return collector, specs


def select_sources(collector: str, specs: list[dict], sources=(), sessions=()) -> list[dict]:
    """Scope new preparation only. The persisted outbox is never filtered."""
    if not sources and not sessions:
        return specs
    for source in sources:
        if not re.fullmatch(r"[0-9a-f]{64}", source):
            raise ValueError("Source selector must be a SHA-256 source ID")
    for session in sessions:
        if str(uuid.UUID(session)) != session.lower():
            raise ValueError("Session selector must be a native UUID")
    return [
        spec
        for spec in specs
        if source_id(collector, spec["legacy_path"]) in sources
        or any(
            re.search(
                r"(?<![0-9a-f])" + re.escape(session) + r"(?![0-9a-f])",
                Path(spec["path"]).stem,
                re.IGNORECASE,
            )
            for session in sessions
        )
    ]


def remote_identity(config: dict, token: str) -> dict:
    parsed = urllib.parse.urlsplit(config["url"])
    path = parsed.path.rsplit("/api/", 1)[0] + "/help"
    url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with http_opener(config).open(request, timeout=config.get("timeout", 30)) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Oversized Help response")
    data = json.loads(raw)
    caller = data.get("caller", {})
    if (
        not isinstance(caller, dict)
        or not caller.get("account_id")
        or not caller.get("machine_client")
    ):
        raise ValueError("Root registration requires a native machine identity")
    if "upload" not in data.get("scopes", []):
        raise ValueError("Root registration requires upload permission")
    return caller


def register_root(config: dict, local_root: str) -> dict:
    """Explicitly authorize one exact mapping using the existing machine binding.

    The authenticated read verifies the machine/collector/owner relation remotely.
    It does not create a remote source, a legacy anchor or another collector.
    """
    collector, _ = collector_identity(config)
    registered_roots(config, collector)  # reject an already mismatched shared-state binding
    matches = [root for root in config.get("roots", []) if root["local_root"] == local_root]
    if len(matches) != 1:
        raise ValueError("Registration requires exactly one configured root")
    root = matches[0]
    if root.get("allow_new_sources") is not True:
        raise ValueError("Root registration requires explicit new-source discovery")
    local = Path(local_root)
    legacy = root["legacy_root"]
    if not local.is_absolute() or not (ntpath.isabs(legacy) or Path(legacy).is_absolute()):
        raise ValueError("Source roots must be absolute")
    if root["ecosystem"] not in {"codex", "claude_code", "pi"}:
        raise ValueError("Unsupported ecosystem")
    # Use an actual source as the binding probe, never fabricate a source anchor.
    probe = next(iter(sorted(local.rglob("*.jsonl"))), None)
    if probe is None or not probe.is_file() or not probe.resolve().is_relative_to(local.resolve()):
        raise ValueError("Registered root requires an in-root native source file")
    relative = probe.relative_to(local)
    legacy_path = (
        ntpath.join(legacy, *relative.parts)
        if "\\" in legacy or ":" in legacy
        else str(Path(legacy).joinpath(relative))
    )
    source = source_id(collector, legacy_path)
    token = credentials(Path(config["credential"]), config["url"])
    state_path = Path(config["state"])
    with process_lock(state_path.with_suffix(".lock")):
        # A successful source-progress response proves current native machine and
        # collector binding. Credential revocation remains enforced on every HTTP call.
        caller = remote_identity(config, token)
        remote_progress(config, collector, source, token)
        state = SyncState(state_path)
        try:
            state.bind(collector, config["url"])
            approval = {
                "root": root_identity(root),
                "collector": collector,
                "url": config["url"],
                "verified_source": source,
                "verified_at": time.time(),
                "account_id": caller["account_id"],
                "machine_client": caller["machine_client"],
                "credential_sha256": digest(token.encode()),
            }
            with state.db:
                state.db.execute(
                    "INSERT OR REPLACE INTO metadata VALUES(?,?)",
                    (
                        "registered-root:" + root_identity(root),
                        json.dumps(approval, sort_keys=True),
                    ),
                )
        finally:
            state.close()
    return {"registered": True, "collector": collector, "root_id": root_identity(root)}


def remote_progress(config: dict, collector: str, source: str, token: str) -> dict:
    parsed = urllib.parse.urlsplit(config["url"])
    path = parsed.path.rsplit("/", 1)[0] + "/source-progress"
    query = urllib.parse.urlencode({"collector": collector, "source": source})
    url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with http_opener(config).open(request, timeout=config.get("timeout", 30)) as response:
        raw = response.read(16385)
    if len(raw) > 16384:
        raise ValueError("Oversized source-progress response")
    result = json.loads(raw)
    if (
        not isinstance(result, dict)
        or "generation" not in result
        or type(result.get("next_offset")) is not int
        or result["next_offset"] < 0
        or result["generation"] is not None
        and not isinstance(result["generation"], str)
    ):
        raise ValueError("Invalid source-progress response")
    return result


def guard_new_sources(state: SyncState, config: dict, collector: str, specs: list, token: str):
    for spec in specs:
        source = source_id(collector, spec["legacy_path"])
        if state.db.execute("SELECT 1 FROM sources WHERE source=?", (source,)).fetchone():
            continue
        progress = remote_progress(config, collector, source, token)
        # Even an empty existing generation needs verified explicit reconciliation.
        if progress.get("generation") is not None or progress["next_offset"] != 0:
            raise RecoveryRequired(
                "Remote source exists without local checkpoint; explicit recovery required"
            )


def sync_once(config: dict, max_chunks: int = 100, sources=(), sessions=()) -> dict:
    collector, specs = validate_manifest(config)
    specs = select_sources(collector, specs, sources, sessions)
    state_path = Path(config["state"])
    sent = 0
    uploaded_bytes = 0
    with process_lock(state_path.with_suffix(".lock")):
        state = SyncState(state_path)
        try:
            state.bind(collector, config["url"])
            token = credentials(Path(config["credential"]), config["url"])

            def prepare_source(spec):
                guard_new_sources(state, config, collector, [spec], token)
                return state.prepare(collector, spec)

            opener = http_opener(config)
            while sent < max_chunks:
                row = state.next()
                if row is None:
                    # Finish one source before starting the next; replay remains ordered.
                    if not any(prepare_source(spec) for spec in specs):
                        break
                    row = state.next()
                request = urllib.request.Request(
                    config["url"],
                    data=row[1].encode(),
                    headers={
                        "Authorization": "Bearer " + token,
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with opener.open(request, timeout=config.get("timeout", 30)) as response:
                    raw = response.read(16385)
                    if len(raw) > 16384:
                        raise ValueError("Oversized receipt")
                    receipt = json.loads(raw)
                state.acknowledge(row, receipt)
                sent += 1
                uploaded_bytes += receipt["accepted_bytes"]
            return {
                "chunks": sent,
                "uploaded_bytes": uploaded_bytes,
                "pending": state.next() is not None,
                "collector": collector,
                "selected_sources": len(specs),
            }
        finally:
            state.close()


def describe(config: dict, sources=(), sessions=()) -> dict:
    collector, specs = validate_manifest(config)
    specs = select_sources(collector, specs, sources, sessions)
    parsed = urllib.parse.urlsplit(config["url"])
    help_url = f"{parsed.scheme}://{parsed.netloc}/trajectory/help"
    token = credentials(Path(config["credential"]), config["url"])
    request = urllib.request.Request(help_url, headers={"Authorization": "Bearer " + token})
    with http_opener(config).open(request, timeout=15) as response:
        help_data = json.loads(response.read(1024 * 1024))
    state_path = Path(config["state"])
    progress = []
    if state_path.exists():
        with sqlite3.connect(state_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            progress = [
                {"source": row[0], "generation": row[1], "offset": row[2]}
                for row in db.execute("SELECT source,generation,offset FROM sources")
            ]
    return {
        "version": help_data.get("version"),
        "caller": help_data.get("caller"),
        "scopes": help_data.get("scopes"),
        "collector": collector,
        "source_count": len(specs),
        "selected_sources": [
            {
                "source": source_id(collector, spec["legacy_path"]),
                "ecosystem": spec["ecosystem"],
                "source_name": Path(spec["path"]).name,
                "source_bytes": Path(spec["path"]).stat().st_size,
            }
            for spec in specs
        ],
        "progress": progress,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--max-chunks", type=int, default=100)
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="Prepare only this canonical source ID; repeatable",
    )
    parser.add_argument(
        "--only-session",
        action="append",
        default=[],
        help="Prepare only this native UUID in source filenames; repeatable",
    )
    parser.add_argument(
        "--register-root",
        help="Authorize an exact configured root through the current machine binding",
    )
    parser.add_argument(
        "--watch", type=float, help="Repeat every N seconds; same lock/state as one-shot"
    )
    parser.add_argument("--status", "--describe", action="store_true", dest="describe")
    args = parser.parse_args()
    if args.max_chunks < 1 or args.watch is not None and args.watch < 1:
        parser.error("Chunk limit and interval must be positive")
    if args.register_root:
        if args.watch or args.describe or args.source or args.only_session:
            parser.error("Root registration cannot be combined with sync selectors or watch/status")
        try:
            print(
                json.dumps(register_root(json.loads(args.config.read_text()), args.register_root))
            )
        except (OSError, ValueError, sqlite3.Error, urllib.error.URLError) as error:
            print(
                json.dumps({"error": type(error).__name__, "registered": False, "retryable": True}),
                file=sys.stderr,
            )
            return 1
        return 0
    if args.describe:
        print(
            json.dumps(
                describe(json.loads(args.config.read_text()), args.source, args.only_session)
            )
        )
        return 0
    while True:
        try:
            print(
                json.dumps(
                    sync_once(
                        json.loads(args.config.read_text()),
                        args.max_chunks,
                        args.source,
                        args.only_session,
                    )
                ),
                flush=True,
            )
        except RecoveryRequired as error:
            print(
                json.dumps(
                    {"error": "recovery_required", "reason": str(error), "retryable": False}
                ),
                file=sys.stderr,
            )
            return 2
        except BlockingIOError:
            print(json.dumps({"state": "busy", "retryable": True}), flush=True)
            if args.watch is None:
                return 0
        except (OSError, ValueError, sqlite3.Error, urllib.error.URLError) as error:
            # Never include exception message, response body, URL or source content.
            print(json.dumps({"error": type(error).__name__, "retryable": True}), file=sys.stderr)
            if args.watch is None:
                return 1
        if args.watch is None:
            return 0
        time.sleep(args.watch)


if __name__ == "__main__":
    raise SystemExit(main())
