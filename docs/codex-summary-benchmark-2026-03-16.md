# Codex Summary Benchmark 2026-03-16

## Metadata

- Benchmark recorded at: `2026-03-16T01:50:29+08:00`
- Repository: `agent_trajectory_profiler`
- Codex CLI version: `codex-cli 0.114.0`
- Summary pipeline under test: `agent_vis.session_summaries.CodexSessionSummaryRunner.generate`
- Timing scope: `codex exec` summary generation only
- Excluded from timing: session parsing and synopsis construction

## Goal

Compare summary-generation latency for three Codex models using the repository's real summary path and three real `claude_code` session files to reduce single-run jitter.

Models tested:

- `gpt-5.1-codex-mini`
- `gpt-5.4`
- `gpt-5.3-codex`

## Method

For each sample session:

1. Parse the raw Claude session JSONL with the repository parser.
2. Build a `SessionSynopsis` via `build_session_synopsis(...)`.
3. Run `CodexSessionSummaryRunner.generate(...)` with one explicit model override.
4. Measure elapsed wall-clock time around `runner.generate(...)`.

This benchmark intentionally measures the production summary path rather than a synthetic prompt-only probe.

## Sample Sessions

| Label | Session ID | Messages | Tokens | File |
| --- | --- | ---: | ---: | --- |
| `small` | `5a087db8-4644-4149-a409-9e94565790f6` | 8 | 249 | `/home/sdu/.claude/projects/-home-sdu/5a087db8-4644-4149-a409-9e94565790f6.jsonl` |
| `medium` | `3b1883bb-bd07-4d32-a539-0043a2f1ab30` | 85 | 1931 | `/home/sdu/.claude/projects/-home-sdu-pure-auto-agent-watchboard/3b1883bb-bd07-4d32-a539-0043a2f1ab30.jsonl` |
| `large` | `55398e0c-24a0-4091-a6dc-f66e2ea22355` | 231 | 14294 | `/home/sdu/.claude/projects/-home-sdu-pure-auto-agent-watchboard/55398e0c-24a0-4091-a6dc-f66e2ea22355.jsonl` |

## Results

### Per-run latency

| Model | Small (s) | Medium (s) | Large (s) | Mean (s) | Median (s) | Min (s) | Max (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `gpt-5.1-codex-mini` | 3.914 | 3.333 | 2.673 | 3.307 | 3.333 | 2.673 | 3.914 |
| `gpt-5.4` | 4.149 | 4.686 | 6.154 | 4.996 | 4.686 | 4.149 | 6.154 |
| `gpt-5.3-codex` | 8.407 | 8.226 | 6.967 | 7.867 | 8.226 | 6.967 | 8.407 |

### Per-run output size

| Model | Small chars | Medium chars | Large chars |
| --- | ---: | ---: | ---: |
| `gpt-5.1-codex-mini` | 246 | 380 | 333 |
| `gpt-5.4` | 302 | 389 | 401 |
| `gpt-5.3-codex` | 380 | 411 | 424 |

## Interpretation

- All 9 runs completed successfully.
- In this environment, latency ranking was stable: `gpt-5.1-codex-mini` fastest, `gpt-5.4` second, `gpt-5.3-codex` slowest.
- The largest raw session file was not always the slowest summary call, because the model sees a synthesized synopsis rather than the full JSONL payload.
- If the main objective is bulk summary throughput, `gpt-5.1-codex-mini` is the best current choice among these three.
- If latency is acceptable and higher-end general reasoning is preferred, `gpt-5.4` is a reasonable balance.

## Caveats

- These measurements are local wall-clock timings and include network/provider variability.
- The active local Codex installation was `codex-cli 0.114.0`; different CLI versions may behave differently.
- Provider routing, account tier, and backend load can materially affect results even for the same model ID.
- This benchmark used real sessions from the local SQLite-backed corpus, not a controlled synthetic fixture.
