"""
Multi-level human-readable formatters for session statistics.

Output levels:
    L1 (SUMMARY)  — single-line summary per session
    L2 (STANDARD) — default ``--human`` output (messages, tokens, tools, time)
    L3 (DETAILED) — everything in L2 plus full tool list, all bash commands,
                    compact events, and sub-agent details
"""

from enum import IntEnum

from claude_vis.models import SessionStatistics


class OutputLevel(IntEnum):
    """Verbosity level for human-readable output."""

    SUMMARY = 1
    STANDARD = 2
    DETAILED = 3


# ---------------------------------------------------------------------------
# Helper formatters
# ---------------------------------------------------------------------------


def _format_duration(seconds: float | None) -> str:
    """Format seconds into human-readable duration."""
    if seconds is None:
        return "N/A"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}m {secs:.0f}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


def _format_chars(chars: int) -> str:
    """Format character count into human-readable form (e.g. 1.2K, 3.4M)."""
    if chars < 1000:
        return f"{chars}"
    if chars < 1_000_000:
        return f"{chars / 1000:.1f}K"
    return f"{chars / 1_000_000:.1f}M"


def _format_tokens(tokens: int) -> str:
    """Format token count into compact form (e.g. 45K, 1.2M)."""
    if tokens < 1000:
        return str(tokens)
    if tokens < 1_000_000:
        return f"{tokens / 1000:.1f}K"
    return f"{tokens / 1_000_000:.1f}M"


def _bottleneck_label(stats: SessionStatistics) -> str:
    """Return the bottleneck category name or '--'."""
    if not stats.time_breakdown:
        return "--"
    tbd = stats.time_breakdown
    categories = [
        ("Model", tbd.model_time_percent),
        ("Tool", tbd.tool_time_percent),
        ("User", tbd.user_time_percent),
    ]
    return max(categories, key=lambda x: x[1])[0]


def _automation_ratio(stats: SessionStatistics) -> str:
    """Return tool_calls:user_interactions ratio string."""
    if not stats.time_breakdown or stats.time_breakdown.user_interaction_count == 0:
        return "--"
    ratio = stats.total_tool_calls / stats.time_breakdown.user_interaction_count
    return f"{ratio:.0f}:1"


# ---------------------------------------------------------------------------
# L1 — one-liner summary
# ---------------------------------------------------------------------------


def _format_summary(stats: SessionStatistics, session_id: str) -> str:
    """Single-line summary: session_id | duration | tokens | bottleneck | automation."""
    dur = _format_duration(stats.session_duration_seconds)
    tok = _format_tokens(stats.total_tokens)
    bn = _bottleneck_label(stats)
    auto = _automation_ratio(stats)
    return f"{session_id} | {dur} | {tok} tok | Bottleneck: {bn} | Auto: {auto}"


# ---------------------------------------------------------------------------
# L2 — standard (current --human output)
# ---------------------------------------------------------------------------


def _format_standard(stats: SessionStatistics, session_id: str) -> str:
    """Full human-readable output matching original ``--human`` format."""
    lines: list[str] = []

    header = f"Session: {session_id}" if session_id else "Session Statistics"
    lines.append(f"\n{'=' * 60}")
    lines.append(f"  {header}")
    lines.append(f"{'=' * 60}")

    # Messages
    lines.append(f"\n  Messages")
    lines.append(f"    Total:      {stats.message_count}")
    lines.append(f"    User:       {stats.user_message_count}")
    lines.append(f"    Assistant:  {stats.assistant_message_count}")
    if stats.system_message_count:
        lines.append(f"    System:     {stats.system_message_count}")

    # Tokens (with percentages)
    lines.append(f"\n  Tokens")
    lines.append(f"    Total:       {stats.total_tokens:,}")
    tb = stats.token_breakdown
    inp_pct = f"  ({tb.input_percent:.1f}%)" if tb else ""
    out_pct = f"  ({tb.output_percent:.1f}%)" if tb else ""
    lines.append(f"    Input:       {stats.total_input_tokens:,}{inp_pct}")
    lines.append(f"    Output:      {stats.total_output_tokens:,}{out_pct}")
    if stats.cache_read_tokens:
        cr_pct = f"  ({tb.cache_read_percent:.1f}%)" if tb else ""
        lines.append(f"    Cache Read:  {stats.cache_read_tokens:,}{cr_pct}")
    if stats.cache_creation_tokens:
        cc_pct = f"  ({tb.cache_creation_percent:.1f}%)" if tb else ""
        lines.append(f"    Cache Write: {stats.cache_creation_tokens:,}{cc_pct}")

    # Tools (with avg latency column) — top 15 in L2
    if stats.tool_calls:
        lines.append(f"\n  Tool Calls ({stats.total_tool_calls} total)")
        lines.append(f"    {'Tool':<28} {'Count':>5}  {'Avg Lat':>8}  {'Errors':>6}")
        lines.append(f"    {'---':<28} {'-----':>5}  {'--------':>8}  {'------':>6}")
        for tc in stats.tool_calls[:15]:
            lat_str = f"{tc.avg_latency_seconds:.2f}s" if tc.avg_latency_seconds > 0 else "--"
            err_str = str(tc.error_count) if tc.error_count > 0 else "--"
            display_name = tc.tool_name
            if tc.tool_name.startswith("mcp__"):
                parts = tc.tool_name.split("__")
                if len(parts) >= 3:
                    display_name = f"{parts[-1]}"
            lines.append(f"    {display_name:<28} {tc.count:>5}  {lat_str:>8}  {err_str:>6}")
        if len(stats.tool_calls) > 15:
            lines.append(f"    ... and {len(stats.tool_calls) - 15} more tools")

    # Tool Groups (only show groups with multiple tools, e.g. MCP servers)
    if stats.tool_groups:
        multi_tool_groups = [g for g in stats.tool_groups if g.tool_count > 1]
        if multi_tool_groups:
            lines.append(f"\n  Tool Groups (MCP)")
            lines.append(f"    {'Group':<28} {'Count':>5}  {'Avg Lat':>8}  {'Errors':>6}  {'Tools':>5}")
            lines.append(f"    {'---':<28} {'-----':>5}  {'--------':>8}  {'------':>6}  {'-----':>5}")
            for g in multi_tool_groups:
                lat_str = f"{g.avg_latency_seconds:.2f}s" if g.avg_latency_seconds > 0 else "--"
                err_str = str(g.error_count) if g.error_count > 0 else "--"
                lines.append(
                    f"    {g.group_name:<28} {g.count:>5}  {lat_str:>8}  {err_str:>6}  {g.tool_count:>5}"
                )

    # Bash Breakdown
    if stats.bash_breakdown:
        bb = stats.bash_breakdown
        lines.append(
            f"\n  Bash Breakdown ({bb.total_calls} calls, "
            f"{bb.total_sub_commands} sub-commands, avg {bb.avg_commands_per_call}/call)"
        )

        # Commands/call distribution — compact single line
        dist_parts = []
        for n in sorted(bb.commands_per_call_distribution.keys()):
            if n <= 3:
                dist_parts.append(f"{n}: {bb.commands_per_call_distribution[n]}")
            else:
                break
        four_plus = sum(
            cnt for n, cnt in bb.commands_per_call_distribution.items() if n >= 4
        )
        if four_plus:
            dist_parts.append(f"4+: {four_plus}")
        lines.append(f"    Commands/Call    {', '.join(dist_parts)}")

        # Top commands table with latency and output
        top_n = 10
        lines.append(f"    {'Command':<20} {'Count':>5}  {'Total Lat':>10}  {'Avg Lat':>8}  {'Output':>8}")
        lines.append(f"    {'---':<20} {'-----':>5}  {'----------':>10}  {'--------':>8}  {'------':>8}")
        for cs in bb.command_stats[:top_n]:
            tot_lat = _format_duration(cs.total_latency_seconds) if cs.total_latency_seconds > 0 else "--"
            avg_lat = f"{cs.avg_latency_seconds:.2f}s" if cs.avg_latency_seconds > 0 else "--"
            out_str = _format_chars(cs.total_output_chars) if cs.total_output_chars > 0 else "--"
            lines.append(
                f"    {cs.command_name:<20} {cs.count:>5}  {tot_lat:>10}  {avg_lat:>8}  {out_str:>8}"
            )
        remaining = len(bb.command_stats) - top_n
        if remaining > 0:
            lines.append(f"    ... and {remaining} more")

    # Subagents
    if stats.subagent_count:
        lines.append(f"\n  Subagents: {stats.subagent_count}")
        for agent_type, count in stats.subagent_sessions.items():
            lines.append(f"    {agent_type}: {count}")

    # Time Breakdown
    if stats.time_breakdown:
        tbd = stats.time_breakdown
        lines.append(f"\n  Time Breakdown (active: {_format_duration(tbd.total_active_time_seconds)})")
        lines.append(
            f"    Model:      {_format_duration(tbd.total_model_time_seconds):>12}  "
            f"({tbd.model_time_percent:>5.1f}%)"
        )
        lines.append(
            f"    Tool:       {_format_duration(tbd.total_tool_time_seconds):>12}  "
            f"({tbd.tool_time_percent:>5.1f}%)"
        )
        lines.append(
            f"    User:       {_format_duration(tbd.total_user_time_seconds):>12}  "
            f"({tbd.user_time_percent:>5.1f}%)"
        )
        if tbd.total_inactive_time_seconds > 0:
            lines.append(
                f"    Inactive:   {_format_duration(tbd.total_inactive_time_seconds):>12}  "
                f"(gaps > {_format_duration(tbd.inactivity_threshold_seconds)})"
            )
        categories = [
            ("Model", tbd.model_time_percent),
            ("Tool", tbd.tool_time_percent),
            ("User", tbd.user_time_percent),
        ]
        bottleneck = max(categories, key=lambda x: x[1])
        lines.append(f"    Bottleneck: {bottleneck[0]} ({bottleneck[1]:.1f}% of active time)")
        lines.append(f"    Interactions: {tbd.user_interaction_count}  ({tbd.interactions_per_hour:.1f}/hour)")

    # Duration
    lines.append(f"\n  Duration:     {_format_duration(stats.session_duration_seconds)}")
    if stats.first_message_time:
        lines.append(f"  Start:        {stats.first_message_time.strftime('%Y-%m-%d %H:%M:%S')}")
    if stats.last_message_time:
        lines.append(f"  End:          {stats.last_message_time.strftime('%Y-%m-%d %H:%M:%S')}")
    if stats.compact_count > 0:
        lines.append(f"  Auto Compacts: {stats.compact_count}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# L3 — detailed (everything in L2 + extras)
# ---------------------------------------------------------------------------


def _format_detailed(stats: SessionStatistics, session_id: str) -> str:
    """L2 output plus all tools (no cap), all bash commands, compact events."""
    # Start with full standard output
    text = _format_standard(stats, session_id)
    extra: list[str] = []

    # If there were capped tools in L2 (>15), show the remainder
    if stats.tool_calls and len(stats.tool_calls) > 15:
        extra.append("\n  All Tool Calls (continued)")
        extra.append(f"    {'Tool':<28} {'Count':>5}  {'Avg Lat':>8}  {'Errors':>6}")
        extra.append(f"    {'---':<28} {'-----':>5}  {'--------':>8}  {'------':>6}")
        for tc in stats.tool_calls[15:]:
            lat_str = f"{tc.avg_latency_seconds:.2f}s" if tc.avg_latency_seconds > 0 else "--"
            err_str = str(tc.error_count) if tc.error_count > 0 else "--"
            display_name = tc.tool_name
            if tc.tool_name.startswith("mcp__"):
                parts = tc.tool_name.split("__")
                if len(parts) >= 3:
                    display_name = f"{parts[-1]}"
            extra.append(f"    {display_name:<28} {tc.count:>5}  {lat_str:>8}  {err_str:>6}")

    # Full bash command table (no cap)
    if stats.bash_breakdown and len(stats.bash_breakdown.command_stats) > 10:
        extra.append("\n  All Bash Commands (continued)")
        extra.append(f"    {'Command':<20} {'Count':>5}  {'Total Lat':>10}  {'Avg Lat':>8}  {'Output':>8}")
        extra.append(f"    {'---':<20} {'-----':>5}  {'----------':>10}  {'--------':>8}  {'------':>8}")
        for cs in stats.bash_breakdown.command_stats[10:]:
            tot_lat = _format_duration(cs.total_latency_seconds) if cs.total_latency_seconds > 0 else "--"
            avg_lat = f"{cs.avg_latency_seconds:.2f}s" if cs.avg_latency_seconds > 0 else "--"
            out_str = _format_chars(cs.total_output_chars) if cs.total_output_chars > 0 else "--"
            extra.append(
                f"    {cs.command_name:<20} {cs.count:>5}  {tot_lat:>10}  {avg_lat:>8}  {out_str:>8}"
            )

    # Compact events
    if stats.compact_events:
        extra.append(f"\n  Compact Events ({len(stats.compact_events)})")
        extra.append(f"    {'Timestamp':<28} {'Trigger':<20} {'Pre-Tokens':>10}")
        extra.append(f"    {'---':<28} {'---':<20} {'----------':>10}")
        for ce in stats.compact_events:
            ts_str = ce.timestamp[:19] if ce.timestamp else "--"
            extra.append(f"    {ts_str:<28} {ce.trigger:<20} {ce.pre_tokens:>10,}")

    if extra:
        return text.rstrip() + "\n" + "\n".join(extra) + "\n"
    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def format_session_stats(
    stats: SessionStatistics,
    session_id: str = "",
    level: OutputLevel = OutputLevel.STANDARD,
) -> str:
    """
    Format session statistics as human-readable text.

    Args:
        stats: Session statistics object.
        session_id: Session identifier (for display).
        level: Output verbosity level.

    Returns:
        Formatted string.
    """
    if level == OutputLevel.SUMMARY:
        return _format_summary(stats, session_id)
    if level == OutputLevel.DETAILED:
        return _format_detailed(stats, session_id)
    return _format_standard(stats, session_id)
