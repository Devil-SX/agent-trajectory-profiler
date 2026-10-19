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
