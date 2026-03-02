# Output Levels (`--human --level`)

The `agent-vis parse --human` command supports three verbosity levels that control how much detail is displayed. Select a level with `--level <1|2|3>` (default: 2).

| Level | Name     | Use case                                      |
|-------|----------|-----------------------------------------------|
| 1     | SUMMARY  | Quick scan of many sessions at once            |
| 2     | STANDARD | Day-to-day review of a single session          |
| 3     | DETAILED | Deep-dive debugging and full event inspection  |

---

## Level 1 -- SUMMARY

A single pipe-delimited line per session. Ideal for scripting or scanning a batch of sessions.

**Format:**

```
<session_id> | <duration> | <tokens> tok | Bottleneck: <category> | Auto: <ratio>
```

- **session_id** -- the session identifier
- **duration** -- wall-clock duration (e.g. `12m 34s`, `1h 5m`)
- **tokens** -- total token count in compact form (e.g. `45K`, `1.2M`)
- **Bottleneck** -- whichever of Model / Tool / User consumed the highest percentage of active time, or `--` if time breakdown is unavailable
- **Auto** -- tool-calls-to-user-interactions ratio (e.g. `8:1`), or `--` when not available

**Example:**

```
a1b2c3d4 | 23m 15s | 127.4K tok | Bottleneck: Model | Auto: 12:1
```

---

## Level 2 -- STANDARD (default)

The default `--human` output. Produces a full multi-section report for one session. Sections appear in the order listed below; some are omitted when data is absent.

### Header

```
============================================================
  Session: a1b2c3d4
============================================================
```

### Messages

```
  Messages
    Total:      42
    User:       8
    Assistant:  34
    System:     0        # shown only when > 0
```

### Tokens

Token counts with percentage breakdown.

```
  Tokens
    Total:       127,432
    Input:       98,210  (77.1%)
    Output:      29,222  (22.9%)
    Cache Read:  64,500  (50.6%)     # shown only when > 0
    Cache Write: 12,300  (9.7%)      # shown only when > 0
```

### Tool Calls (top 15)

Table of tools sorted by usage count, capped at 15 rows. MCP tool names are shortened to just the method name for display.

```
  Tool Calls (156 total)
    Tool                         Count  Avg Lat  Errors
    ---                          -----  --------  ------
    Read                            38     0.12s      --
    Edit                            25     0.18s       2
    Bash                            22     1.45s       1
    Grep                            19     0.09s      --
    Write                           14     0.15s      --
    Glob                            12     0.07s      --
    ... and 3 more tools
```

### Tool Groups (MCP)

Aggregated statistics for MCP servers that expose multiple tools. Groups with only one tool are omitted.

```
  Tool Groups (MCP)
    Group                        Count  Avg Lat  Errors  Tools
    ---                          -----  --------  ------  -----
    obsidian (MCP)                  18     0.31s      --      6
    WaveTool (MCP)                   9     0.05s      --      4
```

### Bash Breakdown (top 10)

Detailed breakdown of commands executed inside `Bash` tool calls.

```
  Bash Breakdown (22 calls, 47 sub-commands, avg 2.1/call)
    Commands/Call    1: 8, 2: 6, 3: 5, 4+: 3
    Command              Count   Total Lat   Avg Lat    Output
    ---                  -----  ----------  --------    ------
    git                     12      18.3s     1.53s     4.2K
    npm                      8    1m 12s     9.00s    12.8K
    python                   6      32.5s     5.42s     2.1K
    uv                       5      15.0s     3.00s     1.5K
    cat                      4       0.8s     0.20s     3.4K
    ls                       3       0.3s     0.10s      856
    grep                     3       1.2s     0.40s     1.8K
    mkdir                    2       0.1s     0.05s        --
    cd                       2       0.0s     0.00s        --
    curl                     2       4.6s     2.30s     5.6K
    ... and 3 more
```

- **Commands/Call** -- distribution of how many sub-commands each Bash invocation contained (keys 1, 2, 3, then 4+ aggregated)
- **Total Lat** -- cumulative wall-clock latency across all invocations of that command
- **Avg Lat** -- average latency per invocation
- **Output** -- total characters of output produced (formatted as K/M)

### Subagents

```
  Subagents: 3
    Explore: 2
    Bash: 1
```

### Time Breakdown

Active-time breakdown by category with bottleneck identification and interaction rate.

```
  Time Breakdown (active: 18m 42s)
    Model:            11m 15s  ( 60.2%)
    Tool:              5m 30s  ( 29.4%)
    User:              1m 57s  ( 10.4%)
    Inactive:          4m 33s  (gaps > 30m 0s)
    Bottleneck: Model (60.2% of active time)
    Interactions: 8  (3.2/hour)
```

- **Inactive** is shown only when gaps exceeding the inactivity threshold were detected
- **Bottleneck** identifies the category with the highest percentage of active time

### Duration / Timestamps

```
  Duration:     23m 15s
  Start:        2026-02-25 10:30:00
  End:          2026-02-25 10:53:15
  Auto Compacts: 2                     # shown only when > 0
```

---

## Level 3 -- DETAILED

Level 3 includes everything from Level 2 plus the following additional sections appended after the standard output.

### All Tool Calls (continued)

When Level 2 capped the tool list at 15, Level 3 appends the remaining tools.

```
  All Tool Calls (continued)
    Tool                         Count  Avg Lat  Errors
    ---                          -----  --------  ------
    TaskCreate                       2     0.04s      --
    TaskUpdate                       1     0.03s      --
    WebFetch                         1     2.10s      --
```

### All Bash Commands (continued)

When Level 2 capped the bash command table at 10, Level 3 appends the remaining commands.

```
  All Bash Commands (continued)
    Command              Count   Total Lat   Avg Lat    Output
    ---                  -----  ----------  --------    ------
    chmod                    1       0.0s     0.00s        --
    echo                     1       0.0s     0.00s        24
    rm                       1       0.0s     0.00s        --
```

### Compact Events

Table of every auto-compact (context summarization) event detected in the session.

```
  Compact Events (2)
    Timestamp                    Trigger              Pre-Tokens
    ---                          ---                  ----------
    2026-02-25T10:42:18          auto                    198,000
    2026-02-25T10:51:03          auto                    195,500
```

- **Timestamp** -- when the compaction occurred (truncated to seconds)
- **Trigger** -- what initiated the compaction (typically `auto`)
- **Pre-Tokens** -- token count just before the compaction was triggered

---

## CLI Examples

```bash
# One-line summary
agent-vis parse --file session.jsonl --human --level 1

# Standard report (default)
agent-vis parse --file session.jsonl --human
agent-vis parse --file session.jsonl --human --level 2

# Full detail with all tools, all commands, compact events
agent-vis parse --file session.jsonl --human --level 3
```

The same levels apply to `agent-vis stats` when used with `--human`:

```bash
agent-vis stats --level 1                              # All sessions, one-line each
agent-vis stats --session-id abc123 --level 3          # Single session, full detail
```
