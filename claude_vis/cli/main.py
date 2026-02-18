"""Main CLI entry point for Claude Code Session Visualizer."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import click

from claude_vis.parsers import SessionParseError, parse_session_directory, parse_session_file


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent


def check_and_build_frontend() -> bool:
    """
    Check if frontend is built, build if necessary.

    Returns:
        True if frontend is ready, False otherwise
    """
    project_root = get_project_root()
    frontend_dir = project_root / "frontend"
    dist_dir = frontend_dir / "dist"
    index_file = dist_dir / "index.html"

    # Check if frontend directory exists
    if not frontend_dir.exists():
        click.echo("Warning: Frontend directory not found.", err=True)
        return False

    # Check if already built
    if index_file.exists():
        return True

    click.echo("Frontend not built. Building automatically...")

    # Check if npm is available
    npm_path = shutil.which("npm")
    if not npm_path:
        click.echo("Error: npm not found. Please install Node.js to build frontend.", err=True)
        return False

    # Check if node_modules exists, install dependencies if not
    node_modules = frontend_dir / "node_modules"
    if not node_modules.exists():
        click.echo("Installing frontend dependencies...")
        try:
            subprocess.run(
                ["npm", "install"],
                cwd=frontend_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            click.echo("✓ Dependencies installed.")
        except subprocess.CalledProcessError as e:
            click.echo(f"Error installing dependencies: {e.stderr}", err=True)
            return False

    # Build frontend
    click.echo("Building frontend...")
    try:
        subprocess.run(
            ["npm", "run", "build"],
            cwd=frontend_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        click.echo("✓ Frontend built successfully.")
        return True
    except subprocess.CalledProcessError as e:
        click.echo(f"Error building frontend: {e.stderr}", err=True)
        return False


@click.group()
@click.version_option(version="0.3.0", prog_name="claude-vis")
def main() -> None:
    """Claude Code Session Visualizer CLI."""
    pass


@main.command()
@click.option(
    "--host",
    default=None,
    help="Host to bind to (default: 0.0.0.0)",
)
@click.option(
    "--port",
    default=None,
    type=int,
    help="Port to bind to (default: 8000)",
)
@click.option(
    "--path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Path to Claude session directory (default: ~/.claude/projects/)",
)
@click.option(
    "--single-session",
    type=str,
    default=None,
    help="Load only a specific session by ID",
)
@click.option(
    "--reload",
    is_flag=True,
    default=False,
    help="Enable auto-reload for development",
)
@click.option(
    "--log-level",
    default=None,
    type=click.Choice(["debug", "info", "warning", "error", "critical"], case_sensitive=False),
    help="Log level (default: info)",
)
def serve(
    host: str | None,
    port: int | None,
    path: Path | None,
    single_session: str | None,
    reload: bool,
    log_level: str | None,
) -> None:
    """
    Start the Claude Code Session Visualizer API server.

    This command starts a FastAPI server that provides REST endpoints
    for accessing and analyzing Claude Code session data. The server
    also serves the frontend static files in production mode.

    Frontend is automatically built if not already built.

    Examples:

        # Start server with default settings
        claude-vis serve

        # Start on custom host/port
        claude-vis serve --host 127.0.0.1 --port 8080

        # Use custom session directory
        claude-vis serve --path /path/to/sessions

        # Load only a specific session
        claude-vis serve --single-session abc123

        # Enable auto-reload for development (hot reload)
        claude-vis serve --reload

        # Set custom log level
        claude-vis serve --log-level debug
    """
    # Import here to avoid loading uvicorn when not needed
    import os
    import signal

    import uvicorn

    from claude_vis.api.config import get_settings

    # Auto-check and build frontend if needed
    if not check_and_build_frontend():
        click.echo("Warning: Frontend not available. API will still start.", err=True)
        click.echo("Visit http://localhost:8000/docs for API documentation.", err=True)
        click.echo()

    # Get settings
    settings = get_settings()

    # Override settings with CLI arguments
    if path is not None:
        # Update settings with custom path
        settings.session_path = path.expanduser().resolve()

    # Handle single session mode via environment variable
    if single_session is not None:
        os.environ["CLAUDE_VIS_SINGLE_SESSION"] = single_session

    # Set host, port, and other configs
    server_host = host or settings.api_host
    server_port = port or settings.api_port
    server_reload = reload or settings.api_reload
    server_log_level = log_level or settings.log_level.lower()

    # Print startup information
    click.echo("=" * 60)
    click.echo("Claude Code Session Visualizer")
    click.echo("=" * 60)
    click.echo(f"Session Path: {settings.session_path}")
    if single_session:
        click.echo(f"Single Session: {single_session}")
    click.echo(f"Server URL:   http://{server_host}:{server_port}")
    click.echo(f"API Docs:     http://{server_host}:{server_port}/docs")
    click.echo(f"Reload Mode:  {'Enabled' if server_reload else 'Disabled'}")
    click.echo(f"Log Level:    {server_log_level.upper()}")
    click.echo("=" * 60)
    click.echo()

    # Verify session path exists
    if not settings.session_path.exists():
        click.echo(
            f"Warning: Session path does not exist: {settings.session_path}", err=True
        )
        click.echo("The API will start but no sessions will be available.", err=True)
        click.echo()

    # Setup signal handlers for graceful shutdown
    def handle_shutdown_signal(signum: int, frame: object) -> None:
        """Handle shutdown signals gracefully."""
        click.echo("\n\nReceived shutdown signal, stopping server...")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)

    try:
        # Start uvicorn server
        click.echo("Starting server... (Press Ctrl+C to stop)\n")
        uvicorn.run(
            "claude_vis.api.app:app",
            host=server_host,
            port=server_port,
            reload=server_reload,
            log_level=server_log_level,
            access_log=True,
        )
    except KeyboardInterrupt:
        click.echo("\n\nGracefully shutting down server...")
        sys.exit(0)
    except Exception as e:
        click.echo(f"\nError starting server: {e}", err=True)
        sys.exit(1)


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


def _print_session_stats(stats: "SessionStatistics", session_id: str = "") -> None:
    """Print human-readable statistics for a single session."""
    from claude_vis.models import SessionStatistics  # noqa: F811

    header = f"Session: {session_id}" if session_id else "Session Statistics"
    click.echo(f"\n{'=' * 60}")
    click.echo(f"  {header}")
    click.echo(f"{'=' * 60}")

    # Messages
    click.echo(f"\n  Messages")
    click.echo(f"    Total:      {stats.message_count}")
    click.echo(f"    User:       {stats.user_message_count}")
    click.echo(f"    Assistant:  {stats.assistant_message_count}")
    if stats.system_message_count:
        click.echo(f"    System:     {stats.system_message_count}")

    # Tokens (with percentages)
    click.echo(f"\n  Tokens")
    click.echo(f"    Total:       {stats.total_tokens:,}")
    tb = stats.token_breakdown
    inp_pct = f"  ({tb.input_percent:.1f}%)" if tb else ""
    out_pct = f"  ({tb.output_percent:.1f}%)" if tb else ""
    click.echo(f"    Input:       {stats.total_input_tokens:,}{inp_pct}")
    click.echo(f"    Output:      {stats.total_output_tokens:,}{out_pct}")
    if stats.cache_read_tokens:
        cr_pct = f"  ({tb.cache_read_percent:.1f}%)" if tb else ""
        click.echo(f"    Cache Read:  {stats.cache_read_tokens:,}{cr_pct}")
    if stats.cache_creation_tokens:
        cc_pct = f"  ({tb.cache_creation_percent:.1f}%)" if tb else ""
        click.echo(f"    Cache Write: {stats.cache_creation_tokens:,}{cc_pct}")

    # Tools (with avg latency column)
    if stats.tool_calls:
        click.echo(f"\n  Tool Calls ({stats.total_tool_calls} total)")
        click.echo(f"    {'Tool':<28} {'Count':>5}  {'Avg Lat':>8}  {'Errors':>6}")
        click.echo(f"    {'---':<28} {'-----':>5}  {'--------':>8}  {'------':>6}")
        for tc in stats.tool_calls[:15]:
            lat_str = f"{tc.avg_latency_seconds:.2f}s" if tc.avg_latency_seconds > 0 else "--"
            err_str = str(tc.error_count) if tc.error_count > 0 else "--"
            # Shorten MCP tool names: "mcp__server__method" -> "method (group)"
            display_name = tc.tool_name
            if tc.tool_name.startswith("mcp__"):
                parts = tc.tool_name.split("__")
                if len(parts) >= 3:
                    display_name = f"{parts[-1]}"
            click.echo(f"    {display_name:<28} {tc.count:>5}  {lat_str:>8}  {err_str:>6}")
        if len(stats.tool_calls) > 15:
            click.echo(f"    ... and {len(stats.tool_calls) - 15} more tools")

    # Tool Groups (only show groups with multiple tools, e.g. MCP servers)
    if stats.tool_groups:
        multi_tool_groups = [g for g in stats.tool_groups if g.tool_count > 1]
        if multi_tool_groups:
            click.echo(f"\n  Tool Groups (MCP)")
            click.echo(f"    {'Group':<28} {'Count':>5}  {'Avg Lat':>8}  {'Errors':>6}  {'Tools':>5}")
            click.echo(f"    {'---':<28} {'-----':>5}  {'--------':>8}  {'------':>6}  {'-----':>5}")
            for g in multi_tool_groups:
                lat_str = f"{g.avg_latency_seconds:.2f}s" if g.avg_latency_seconds > 0 else "--"
                err_str = str(g.error_count) if g.error_count > 0 else "--"
                click.echo(f"    {g.group_name:<28} {g.count:>5}  {lat_str:>8}  {err_str:>6}  {g.tool_count:>5}")

    # Bash Breakdown
    if stats.bash_breakdown:
        bb = stats.bash_breakdown
        click.echo(f"\n  Bash Breakdown ({bb.total_calls} calls, {bb.total_sub_commands} sub-commands, avg {bb.avg_commands_per_call}/call)")

        # Commands/call distribution — compact single line
        dist_parts = []
        for n in sorted(bb.commands_per_call_distribution.keys()):
            if n <= 3:
                dist_parts.append(f"{n}: {bb.commands_per_call_distribution[n]}")
            else:
                # Aggregate 4+
                break
        # Sum counts for 4+
        four_plus = sum(
            cnt for n, cnt in bb.commands_per_call_distribution.items() if n >= 4
        )
        if four_plus:
            dist_parts.append(f"4+: {four_plus}")
        click.echo(f"    Commands/Call    {', '.join(dist_parts)}")

        # Top commands table with latency and output
        top_n = 10
        click.echo(f"    {'Command':<20} {'Count':>5}  {'Total Lat':>10}  {'Avg Lat':>8}  {'Output':>8}")
        click.echo(f"    {'---':<20} {'-----':>5}  {'----------':>10}  {'--------':>8}  {'------':>8}")
        for cs in bb.command_stats[:top_n]:
            tot_lat = _format_duration(cs.total_latency_seconds) if cs.total_latency_seconds > 0 else "--"
            avg_lat = f"{cs.avg_latency_seconds:.2f}s" if cs.avg_latency_seconds > 0 else "--"
            out_str = _format_chars(cs.total_output_chars) if cs.total_output_chars > 0 else "--"
            click.echo(f"    {cs.command_name:<20} {cs.count:>5}  {tot_lat:>10}  {avg_lat:>8}  {out_str:>8}")
        remaining = len(bb.command_stats) - top_n
        if remaining > 0:
            click.echo(f"    ... and {remaining} more")

    # Subagents
    if stats.subagent_count:
        click.echo(f"\n  Subagents: {stats.subagent_count}")
        for agent_type, count in stats.subagent_sessions.items():
            click.echo(f"    {agent_type}: {count}")

    # Time Breakdown
    if stats.time_breakdown:
        tbd = stats.time_breakdown
        click.echo(f"\n  Time Breakdown (active: {_format_duration(tbd.total_active_time_seconds)})")
        click.echo(f"    Model:      {_format_duration(tbd.total_model_time_seconds):>12}  ({tbd.model_time_percent:>5.1f}%)")
        click.echo(f"    Tool:       {_format_duration(tbd.total_tool_time_seconds):>12}  ({tbd.tool_time_percent:>5.1f}%)")
        click.echo(f"    User:       {_format_duration(tbd.total_user_time_seconds):>12}  ({tbd.user_time_percent:>5.1f}%)")
        if tbd.total_inactive_time_seconds > 0:
            click.echo(f"    Inactive:   {_format_duration(tbd.total_inactive_time_seconds):>12}  (gaps > {_format_duration(tbd.inactivity_threshold_seconds)})")
        # Identify bottleneck
        categories = [
            ("Model", tbd.model_time_percent),
            ("Tool", tbd.tool_time_percent),
            ("User", tbd.user_time_percent),
        ]
        bottleneck = max(categories, key=lambda x: x[1])
        click.echo(f"    Bottleneck: {bottleneck[0]} ({bottleneck[1]:.1f}% of active time)")
        click.echo(f"    Interactions: {tbd.user_interaction_count}  ({tbd.interactions_per_hour:.1f}/hour)")

    # Duration
    click.echo(f"\n  Duration:     {_format_duration(stats.session_duration_seconds)}")
    if stats.first_message_time:
        click.echo(f"  Start:        {stats.first_message_time.strftime('%Y-%m-%d %H:%M:%S')}")
    if stats.last_message_time:
        click.echo(f"  End:          {stats.last_message_time.strftime('%Y-%m-%d %H:%M:%S')}")
    if stats.compact_count > 0:
        click.echo(f"  Auto Compacts: {stats.compact_count}")

    click.echo()


@main.command()
@click.option(
    "--file",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    default=None,
    help="Parse a single .jsonl session file",
)
@click.option(
    "--session",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Parse all session files in a directory",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output file path for JSON output (default: stdout)",
)
@click.option(
    "--compact",
    is_flag=True,
    default=False,
    help="Compact JSON output without indentation (default is pretty-printed)",
)
@click.option(
    "--human",
    is_flag=True,
    default=False,
    help="Display only statistics in human-readable format (no JSON)",
)
def parse(
    file: Path | None,
    session: Path | None,
    output: Path | None,
    compact: bool,
    human: bool,
) -> None:
    """
    Parse Claude Code session data and output JSON.

    Three modes of operation:

    \b
      --file <path.jsonl>   Parse a single .jsonl file
      --session <dir>       Parse all .jsonl files in a directory
      (default)             Parse all sessions under ~/.claude/projects/

    Examples:

    \b
        # Human-readable statistics
        claude-vis parse --file session.jsonl --human

    \b
        # Parse a single file (pretty JSON by default)
        claude-vis parse --file session.jsonl

    \b
        # Parse a session directory
        claude-vis parse --session ./my-project-sessions/

    \b
        # Compact JSON for piping
        claude-vis parse --compact | jq .
    """
    if file and session:
        click.echo("Error: --file and --session are mutually exclusive.", err=True)
        sys.exit(1)

    try:
        sessions_list: list[tuple[str, object]] = []  # (session_id, session_obj)

        if file:
            # Mode 1: single file
            file = file.expanduser().resolve()
            click.echo(f"Parsing file: {file}", err=True)
            session_obj = parse_session_file(file)
            sessions_list = [(session_obj.metadata.session_id, session_obj)]
            json_data = session_obj.model_dump(mode="json")
            click.echo(
                f"Successfully parsed 1 session ({session_obj.statistics.message_count} messages)",
                err=True,
            )
        elif session:
            # Mode 2: session directory
            session = session.expanduser().resolve()
            click.echo(f"Parsing session directory: {session}", err=True)
            parsed_data = parse_session_directory(session)
            sessions_list = [
                (s.metadata.session_id, s) for s in parsed_data.sessions
            ]
            json_data = parsed_data.model_dump(mode="json")
            click.echo(
                f"Successfully parsed {parsed_data.session_count} sessions "
                f"({parsed_data.total_messages} messages)",
                err=True,
            )
        else:
            # Mode 3: default user directory
            path = Path.home() / ".claude" / "projects"
            path = path.expanduser().resolve()
            click.echo(f"Parsing sessions from: {path}", err=True)
            parsed_data = parse_session_directory(path)
            sessions_list = [
                (s.metadata.session_id, s) for s in parsed_data.sessions
            ]
            json_data = parsed_data.model_dump(mode="json")
            click.echo(
                f"Successfully parsed {parsed_data.session_count} sessions "
                f"({parsed_data.total_messages} messages)",
                err=True,
            )

        # --human: print statistics only
        if human:
            for sid, s in sessions_list:
                _print_session_stats(s.statistics, sid)  # type: ignore[union-attr]
            return

        # Output JSON (pretty by default, --compact for minified)
        indent = None if compact else 2

        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            with open(output, "w", encoding="utf-8") as f:
                json.dump(json_data, f, indent=indent)
            click.echo(f"Output written to: {output}", err=True)
        else:
            json.dump(json_data, sys.stdout, indent=indent)
            if not compact:
                click.echo()

    except SessionParseError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
