#!/usr/bin/env python3
"""Single native-source uploader for agents and Sparkstead schedulers (stdlib only)."""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

CHUNK_BYTES = 512 * 1024
OUTBOX_BYTES = 32 * 1024 * 1024


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def source_id(collector: str, legacy_path: str) -> str:
    return digest((collector + ":" + legacy_path).encode())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Sync redirects are prohibited")


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
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
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
        size = Path(spec["path"]).stat().st_size
        if not size:
            return False
        prefix_size = row[2] if row else min(size, 1024)
        with open(spec["path"], "rb") as stream:
            prefix = digest(stream.read(prefix_size))
            reset = bool(row and (size < row[4] or prefix != row[3]))
            generation = row[1] if row and not reset else str(uuid.uuid4())
            offset = row[4] if row and not reset else 0
            if offset >= size:
                return False
            if reset:
                prefix_size = min(size, 1024)
                stream.seek(0)
                prefix = digest(stream.read(prefix_size))
            stream.seek(offset)
            content = stream.read(min(CHUNK_BYTES, size - offset))
        body = {
            "schema_id": "trajectory-source-chunk/1",
            "mutation_id": str(uuid.uuid4()), "collector": collector,
            "source": source, "ecosystem": spec["ecosystem"],
            "generation": generation, "start": offset, "end": offset + len(content),
            "source_bytes": size, "content": base64.b64encode(content).decode(),
            "sha256": digest(content), "source_name": Path(spec["path"]).name,
        }
        encoded = json.dumps(body, separators=(",", ":"))
        pending = self.db.execute("SELECT coalesce(sum(bytes),0) FROM outbox").fetchone()[0]
        if pending + len(encoded) > OUTBOX_BYTES:
            return False
        with self.db:
            self.db.execute("INSERT INTO outbox(body,bytes) VALUES(?,?)", (encoded, len(encoded)))
            self.db.execute("INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?)", (
                source, generation, prefix_size, prefix, offset + len(content)))
        return True

    def next(self):
        return self.db.execute("SELECT id,body FROM outbox ORDER BY id LIMIT 1").fetchone()

    def acknowledge(self, row, receipt: dict):
        body = json.loads(row[1])
        if (receipt.get("durable") is not True
                or receipt.get("mutation_id") != body["mutation_id"]
                or receipt.get("accepted_bytes") != body["end"] - body["start"]
                or receipt.get("next_offset") != body["end"]):
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


def validate_manifest(config: dict) -> tuple[str, list[dict]]:
    if config.get("legacy_state"):
        collector, known = legacy_identity(Path(config["legacy_state"]))
    elif config.get("legacy_identity_snapshot"):
        # Snapshot must be exported through readonly SQLite on its native OS.
        identity = json.loads(Path(config["legacy_identity_snapshot"]).read_text())
        collector, known = identity["collector"], set(identity["sources"])
    else:
        raise ValueError("Existing collector identity and source membership are required")
    specs = config["sources"]
    for spec in specs:
        if spec["ecosystem"] not in {"codex", "claude_code"}:
            raise ValueError("Unsupported ecosystem")
        if source_id(collector, spec["legacy_path"]) not in known:
            raise ValueError("Source path does not match the existing collector")
        if not Path(spec["path"]).is_file():
            raise ValueError("Source file is unavailable")
    return collector, specs


def sync_once(config: dict, max_chunks: int = 100) -> dict:
    collector, specs = validate_manifest(config)
    state_path = Path(config["state"])
    sent = 0
    uploaded_bytes = 0
    with process_lock(state_path.with_suffix(".lock")):
        state = SyncState(state_path)
        try:
            state.bind(collector, config["url"])
            token = credentials(Path(config["credential"]), config["url"])
            opener = urllib.request.build_opener(NoRedirect)
            while sent < max_chunks:
                row = state.next()
                if row is None:
                    # Finish one source before starting the next; replay remains ordered.
                    if not any(state.prepare(collector, spec) for spec in specs):
                        break
                    row = state.next()
                request = urllib.request.Request(config["url"], data=row[1].encode(),
                    headers={"Authorization": "Bearer " + token,
                             "Content-Type": "application/json"}, method="POST")
                with opener.open(request, timeout=config.get("timeout", 30)) as response:
                    raw = response.read(16385)
                    if len(raw) > 16384:
                        raise ValueError("Oversized receipt")
                    receipt = json.loads(raw)
                state.acknowledge(row, receipt)
                sent += 1
                uploaded_bytes += receipt["accepted_bytes"]
            return {"chunks": sent, "uploaded_bytes": uploaded_bytes,
                    "pending": state.next() is not None, "collector": collector}
        finally:
            state.close()


def describe(config: dict) -> dict:
    collector, specs = validate_manifest(config)
    parsed = urllib.parse.urlsplit(config["url"])
    help_url = f"{parsed.scheme}://{parsed.netloc}/trajectory/help"
    token = credentials(Path(config["credential"]), config["url"])
    request = urllib.request.Request(help_url, headers={"Authorization": "Bearer " + token})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
        help_data = json.loads(response.read(1024 * 1024))
    state_path = Path(config["state"])
    progress = []
    if state_path.exists():
        with sqlite3.connect(state_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            progress = [{"source": row[0], "generation": row[1], "offset": row[2]}
                        for row in db.execute("SELECT source,generation,offset FROM sources")]
    return {"version": help_data.get("version"), "caller": help_data.get("caller"),
            "scopes": help_data.get("scopes"), "collector": collector,
            "source_count": len(specs), "progress": progress}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--max-chunks", type=int, default=100)
    parser.add_argument("--watch", type=float, help="Repeat every N seconds; same lock/state as one-shot")
    parser.add_argument("--status", "--describe", action="store_true", dest="describe")
    args = parser.parse_args()
    if args.max_chunks < 1 or args.watch is not None and args.watch < 1:
        parser.error("Chunk limit and interval must be positive")
    if args.describe:
        print(json.dumps(describe(json.loads(args.config.read_text()))))
        return 0
    while True:
        try:
            print(json.dumps(sync_once(json.loads(args.config.read_text()), args.max_chunks)), flush=True)
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
