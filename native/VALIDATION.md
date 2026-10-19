# Native component acceptance, 2026-10-19

Environment: `batcave-wsl`, isolated
`/home/saveer/BatCave/tests/trajectory-parser-worker`, x86_64 Linux.
Rust 1.99.1 and Zig 0.17.0 were installed only under this task's toolchain
directory. No production service, system package, or Sparkstead restart was
needed. Zig's release SHA-256 was checked against its download manifest.

Results:

- `cargo test --locked`: 8 passed (worker 0.1.1). Covers Codex cache normalization,
  cumulative-usage replay, inherited fork-context exclusion, Claude cache
  write/read categories, source byte identity and partial append handling,
  malformed complete-record rejection, half-UTF-8 pending bytes with successful
  later append, and invalid UTF-8 in complete records/full JSON documents.
- `cargo build --locked --release`: passed for the worker and pinned research
  AgentPProf CLI.
- `ruff check scripts/native/verify-workers.py`: passed remotely.
- `verify-workers.py`: worker health, internal file input, source location,
  invalid request recovery and deterministic replay passed. The actual
  AgentPProf CLI consumed a synthetic annotation workspace, wrote semantic
  paths and folded stacks, and emitted a nonempty gzip pprof profile.

Built artifacts are under the task's `artifacts` directory:

| Artifact | SHA-256 |
| --- | --- |
| trajectory-session-worker | 07b8119926aa7c5398067b7e6379d72c21153ec2c236151caa7d9e54e79832ba |
| agentpprof | 88724f4a29029f8f94142bb5e1d3ec5682fe4d0020cdcf43b2d2042cd6b2a21a |

The profile test used synthetic data only. Real multi-session accounting,
semantic annotation quality, authenticated API flow and production browser
acceptance remain service integration responsibilities; these component tests
do not establish that the website has been deployed.


## Pi adapter and damaged JSONL acceptance, 2026-10-19

Worker 0.1.2 was built and tested on `batcave-wsl` under the isolated
`/home/saveer/BatCave/tests/trajectory-pi-20261019` directory, using the existing
isolated Rust 1.99.1/Zig toolchain. Production and Sparkstead were unchanged.

- `cargo test --locked --offline`: 9 passed, including native Pi branch and
  cache-write/cache-read preservation, missing-field handling, stable replay,
  and quarantined-line offsets without rewriting source bytes.
- Source sync stdlib suite: 21 passed, including Pi root discovery and shared
  checkpoint reopen/append without duplicate upload.
- Ruff and Black use the repository's `pyproject.toml`; both passed remotely.
- Three private original sources were parsed without any model call. Two Pi
  sessions yielded 352 and 1,018 operations. The damaged Codex source yielded
  2,072 operations and explicit partial coverage: 14,234 valid records and one
  quarantined record at line 9,939. Each source hash and every valid record byte
  range was checked against its unchanged original bytes. No source text is
  committed in this repository.

Built worker SHA-256:
`de83a602faf4a881e68d2f299a61854f046bab53bb1418eaa85fb566f40cebea`.
The private isolated test directory retains `real-source-acceptance.json` as the
verification receipt. The source gap must also remain visible in service analysis
results; native acceptance alone does not certify the integrated web release.


### Targeted collection and root registration follow-up

The same isolated remote source-sync suite now passes 23 tests. New coverage
checks explicit machine-bound registration before admitting an unanchored Pi root,
failed authentication without approval, unchanged legacy membership, exact mapping
and endpoint binding, source/native-session selectors and original pending-body
replay even when selectors exclude that pending source. Ruff and Black pass with
the repository configuration. The installed collector configuration and its
live checkpoint/outbox were inspected read-only and were not changed by these tests.
