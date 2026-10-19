#!/usr/bin/env bash
# Build only in an isolated remote checkout; install artifacts with the release.
set -euo pipefail
task_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
artifact_root=${1:?Usage: build-workers.sh OUTPUT_DIRECTORY [UPSTREAM_CACHE]}
upstream_root=${2:-"$artifact_root/upstream-agentsight"}
upstream_revision=60cc321ceb4b677fec1a69df6ec055a456b75675
mkdir -p -- "$artifact_root"
if [[ ! -d "$upstream_root/.git" ]]; then
  git init "$upstream_root"
  git -C "$upstream_root" remote add origin https://github.com/eunomia-bpf/agentsight.git
fi
if ! git -C "$upstream_root" cat-file -e "$upstream_revision^{commit}" 2>/dev/null; then
  git -C "$upstream_root" fetch --depth=1 origin "$upstream_revision"
fi
git -C "$upstream_root" checkout --detach "$upstream_revision"
test "$(git -C "$upstream_root" rev-parse HEAD)" = "$upstream_revision"
cargo build --locked --release --manifest-path "$task_root/native/session-worker/Cargo.toml"
cargo build --locked --release --manifest-path "$upstream_root/agentpprof/Cargo.toml"
install -m 755 "$task_root/native/session-worker/target/release/trajectory-session-worker" "$artifact_root/trajectory-session-worker"
install -m 755 "$upstream_root/agentpprof/target/release/agentpprof" "$artifact_root/agentpprof"
install -m 644 "$upstream_root/LICENSE" "$artifact_root/AGENTSIGHT-LICENSE"
cat > "$artifact_root/native-components.json" <<EOF
{"schema":1,"agent_session":"0.5.17","agentpprof_revision":"$upstream_revision","agentpprof_version":"0.2.37","protocol":"trajectory.agent-session/1"}
EOF
