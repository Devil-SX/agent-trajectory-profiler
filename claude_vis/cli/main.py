"""Main CLI entry point for Agent Trajectory Profiler."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from claude_vis.formatters.human import OutputLevel, format_session_stats
from claude_vis.parsers import SessionParseError, parse_session_directory, parse_session_file

if TYPE_CHECKING:
    from claude_vis.models import SessionStatistics


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
@click.version_option(version="0.5.0", prog_name="agent-vis")
def main() -> None:
    """Agent Trajectory Profiler CLI."""
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
    help="Path to agent session directory (default: ~/.claude/projects/)",
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
    Start the Agent Trajectory Profiler API server.

    This command starts a FastAPI server that provides REST endpoints
    for accessing and analyzing agent session data. The server
    also serves the frontend static files in production mode.

    Frontend is automatically built if not already built.

    Examples:

        # Start server with default settings
        agent-vis serve

        # Start on custom host/port
        agent-vis serve --host 127.0.0.1 --port 8080

        # Use custom session directory
        agent-vis serve --path /path/to/sessions

        # Load only a specific session
        agent-vis serve --single-session abc123

        # Enable auto-reload for development (hot reload)
        agent-vis serve --reload

        # Set custom log level
        agent-vis serve --log-level debug
    """
    # Import here to avoid loading uvicorn when not needed
    import os
    import signal
    import socket

    import uvicorn

    from claude_vis.api.config import get_settings

    def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
        """Check if a port is already in use."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return False
            except OSError:
                return True

    def find_available_port(start_port: int, host: str = "127.0.0.1", max_tries: int = 10) -> int | None:
        """Find an available port starting from start_port."""
        for port in range(start_port, start_port + max_tries):
            if not is_port_in_use(port, host):
                return port
        return None

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
    requested_port = port or settings.api_port
    server_reload = reload or settings.api_reload
    server_log_level = log_level or settings.log_level.lower()

    # Check if requested port is in use
    if is_port_in_use(requested_port, server_host):
        if port is not None:
            # User explicitly specified a port, don't auto-change it
            click.echo(f"Error: Port {requested_port} is already in use.", err=True)
            click.echo("Please specify a different port with --port option.", err=True)
            sys.exit(1)
        else:
            # Try to find an alternative port
            click.echo(f"Warning: Default port {requested_port} is already in use.", err=True)
            alternative_port = find_available_port(requested_port + 1, server_host)
            if alternative_port is None:
                click.echo("Error: Could not find an available port.", err=True)
                click.echo("Please stop other services or specify a custom port.", err=True)
                sys.exit(1)
            click.echo(f"Using alternative port: {alternative_port}", err=True)
            click.echo()
            server_port = alternative_port
    else:
        server_port = requested_port

    # Print startup information
    click.echo("=" * 60)
    click.echo("Agent Trajectory Profiler")
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


def _format_session_stats(stats: "SessionStatistics", session_id: str = "") -> str:
    """Format human-readable statistics for a single session as a string."""
    return format_session_stats(stats, session_id, level=OutputLevel.STANDARD)


def _print_session_stats(stats: "SessionStatistics", session_id: str = "") -> None:
    """Print human-readable statistics for a single session."""
    click.echo(format_session_stats(stats, session_id, level=OutputLevel.STANDARD))


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
@click.option(
    "--level",
    type=click.Choice(["1", "2", "3"], case_sensitive=False),
    default="2",
    help="Output detail level for --human: 1=summary, 2=standard, 3=detailed",
)
@click.option(
    "--inactivity-threshold",
    type=float,
    default=None,
    help="Seconds of gap to classify as inactive (default: 1800)",
)
@click.option(
    "--model-timeout",
    type=float,
    default=None,
    help="Seconds of model inference gap to count as timeout (default: 600)",
)
def parse(
    file: Path | None,
    session: Path | None,
    output: Path | None,
    compact: bool,
    human: bool,
    level: str,
    inactivity_threshold: float | None,
    model_timeout: float | None,
) -> None:
    """
    Parse agent trajectory session data and output JSON.

    Three modes of operation:

    \b
      --file <path.jsonl>   Parse a single .jsonl file
      --session <dir>       Parse all .jsonl files in a directory
      (default)             Parse all sessions under ~/.claude/projects/

    Examples:

    \b
        # Human-readable statistics
        agent-vis parse --file session.jsonl --human

    \b
        # Parse a single file (pretty JSON by default)
        agent-vis parse --file session.jsonl

    \b
        # Parse a session directory
        agent-vis parse --session ./my-project-sessions/

    \b
        # Compact JSON for piping
        agent-vis parse --compact | jq .
    """
    if file and session:
        click.echo("Error: --file and --session are mutually exclusive.", err=True)
        sys.exit(1)

    # Build keyword args for threshold params
    parse_kwargs: dict[str, float] = {}
    if inactivity_threshold is not None:
        parse_kwargs["inactivity_threshold"] = inactivity_threshold
    if model_timeout is not None:
        parse_kwargs["model_timeout_threshold"] = model_timeout

    try:
        sessions_list: list[tuple[str, object]] = []  # (session_id, session_obj)

        if file:
            # Mode 1: single file
            file = file.expanduser().resolve()
            click.echo(f"Parsing file: {file}", err=True)
            session_obj = parse_session_file(file, **parse_kwargs)
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
            parsed_data = parse_session_directory(session, **parse_kwargs)
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
            parsed_data = parse_session_directory(path, **parse_kwargs)
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
            output_level = OutputLevel(int(level))
            for sid, s in sessions_list:
                click.echo(format_session_stats(s.statistics, sid, level=output_level))  # type: ignore[union-attr]
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


@main.command()
@click.option(
    "--path",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Directory to scan (default: ~/.claude/projects/)",
)
@click.option(
    "--ecosystem",
    default="claude_code",
    help="Parser ecosystem (default: claude_code)",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Force full re-parse of all files",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=None,
    help="SQLite database path (default: ~/.claude-vis/profiler.db)",
)
@click.option(
    "--inactivity-threshold",
    type=float,
    default=None,
    help="Seconds of gap to classify as inactive (default: 1800)",
)
@click.option(
    "--model-timeout",
    type=float,
    default=None,
    help="Seconds of model inference gap to count as timeout (default: 600)",
)
def sync(
    path: Path | None,
    ecosystem: str,
    force: bool,
    db_path: Path | None,
    inactivity_threshold: float | None,
    model_timeout: float | None,
) -> None:
    """
    Incrementally scan and parse agent trajectory files into the database.

    Compares file modification times against the DB to skip unchanged files.

    Examples:

    \b
        # Sync default directory
        agent-vis sync

    \b
        # Sync a specific directory
        agent-vis sync --path ~/.claude/projects/my-project/

    \b
        # Force re-parse everything
        agent-vis sync --force
    """
    from claude_vis.db.connection import get_connection
    from claude_vis.db.repository import SessionRepository
    from claude_vis.db.sync import SyncEngine
    from claude_vis.parsers.registry import get_parser

    scan_path = (path or Path.home() / ".claude" / "projects").expanduser().resolve()

    try:
        parser = get_parser(ecosystem)
    except KeyError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Apply threshold overrides if provided
    if inactivity_threshold is not None:
        parser.inactivity_threshold = inactivity_threshold  # type: ignore[attr-defined]
    if model_timeout is not None:
        parser.model_timeout_threshold = model_timeout  # type: ignore[attr-defined]

    conn = get_connection(db_path)
    repo = SessionRepository(conn)
    engine = SyncEngine(repo, parser)

    click.echo(f"Scanning: {scan_path}", err=True)
    result = engine.sync(scan_path, force=force)
    conn.close()

    click.echo(
        f"Sync complete: {result.parsed} parsed, {result.skipped} skipped, "
        f"{len(result.errors)} errors",
        err=True,
    )
    for err in result.errors[:10]:
        click.echo(f"  - {err}", err=True)


@main.command()
@click.option(
    "--session-id",
    default=None,
    help="Show statistics for a specific session",
)
@click.option(
    "--level",
    type=click.Choice(["1", "2", "3"], case_sensitive=False),
    default="2",
    help="Output detail level: 1=summary, 2=standard, 3=detailed",
)
@click.option(
    "--sort-by",
    type=click.Choice(
        ["created_at", "parsed_at", "total_tokens", "duration_seconds"],
        case_sensitive=False,
    ),
    default="created_at",
    help="Sort sessions by field (default: created_at)",
)
@click.option(
    "--limit",
    type=int,
    default=20,
    help="Maximum number of sessions to show (default: 20)",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=None,
    help="SQLite database path (default: ~/.claude-vis/profiler.db)",
)
@click.option(
    "--start-date",
    default=None,
    help="Filter sessions created on or after this date (YYYY-MM-DD)",
)
@click.option(
    "--end-date",
    default=None,
    help="Filter sessions created on or before this date (YYYY-MM-DD)",
)
def stats(
    session_id: str | None,
    level: str,
    sort_by: str,
    limit: int,
    db_path: Path | None,
    start_date: str | None,
    end_date: str | None,
) -> None:
    """
    Query session statistics from the database.

    Run 'agent-vis sync' first to populate the database.

    Examples:

    \b
        # List all sessions (summary)
        agent-vis stats --level 1

    \b
        # Detailed stats for one session
        agent-vis stats --session-id abc123 --level 3

    \b
        # Sort by token usage
        agent-vis stats --sort-by total_tokens --limit 10

    \b
        # Filter by date range
        agent-vis stats --start-date 2026-02-01 --end-date 2026-02-25
    """
    import re

    from claude_vis.db.connection import get_connection
    from claude_vis.db.repository import SessionRepository

    # Validate date formats
    _date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    if start_date is not None and not _date_re.match(start_date):
        click.echo(f"Error: Invalid --start-date format: '{start_date}'. Expected YYYY-MM-DD.", err=True)
        sys.exit(1)
    if end_date is not None and not _date_re.match(end_date):
        click.echo(f"Error: Invalid --end-date format: '{end_date}'. Expected YYYY-MM-DD.", err=True)
        sys.exit(1)
    if start_date and end_date and start_date > end_date:
        click.echo("Error: --start-date must be on or before --end-date.", err=True)
        sys.exit(1)

    conn = get_connection(db_path, create=False)
    repo = SessionRepository(conn)
    output_level = OutputLevel(int(level))

    if session_id:
        statistics = repo.get_statistics(session_id)
        if statistics is None:
            click.echo(f"Error: Session '{session_id}' not found in database.", err=True)
            click.echo("Run 'agent-vis sync' first to populate the database.", err=True)
            conn.close()
            sys.exit(1)
        click.echo(format_session_stats(statistics, session_id, level=output_level))
    else:
        rows = repo.list_sessions(
            sort_by=sort_by, sort_order="DESC", limit=limit,
            start_date=start_date, end_date=end_date,
        )
        if not rows:
            if start_date or end_date:
                click.echo("No sessions found for the specified date range.", err=True)
            else:
                click.echo("No sessions in database. Run 'agent-vis sync' first.", err=True)
            conn.close()
            sys.exit(1)

        for row in rows:
            sid = row["session_id"]
            if output_level == OutputLevel.SUMMARY:
                # Build a one-liner from the DB summary columns
                from claude_vis.formatters.human import _format_duration, _format_tokens

                dur = _format_duration(row["duration_seconds"])
                tok = _format_tokens(row["total_tokens"] or 0)
                bn = row["bottleneck"] or "--"
                ar = f"{row['automation_ratio']:.0f}:1" if row["automation_ratio"] else "--"
                click.echo(f"{sid} | {dur} | {tok} tok | Bottleneck: {bn} | Auto: {ar}")
            else:
                statistics = repo.get_statistics(sid)
                if statistics:
                    click.echo(format_session_stats(statistics, sid, level=output_level))

    conn.close()


@main.command()
@click.option(
    "--file",
    required=True,
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    help="Path to a .jsonl session file",
)
@click.option(
    "--model",
    default="sonnet",
    help="Claude model name (default: sonnet)",
)
@click.option(
    "--lang",
    type=click.Choice(["en", "cn"], case_sensitive=False),
    default="en",
    help="Report language (default: en)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output path for analysis report (default: output/<session_id>_analysis.md)",
)
def analyze(
    file: Path,
    model: str,
    lang: str,
    output: Path | None,
) -> None:
    """
    Invoke Claude to produce an AI-powered analysis of a session trajectory.

    Parses the JSONL file, computes statistics, then calls `claude -p` headless
    to generate an actionable Markdown report with bottleneck analysis,
    automation degree rating, and improvement recommendations.

    Examples:

    \b
        # English analysis with default model
        agent-vis analyze --file session.jsonl

    \b
        # Chinese analysis with specific model
        agent-vis analyze --file session.jsonl --lang cn --model sonnet

    \b
        # Custom output path
        agent-vis analyze --file session.jsonl -o report.md
    """
    from claude_vis.prompts.analyze import build_analyze_prompt

    file = file.expanduser().resolve()

    # 1. Parse session
    click.echo(f"Parsing file: {file}", err=True)
    try:
        session_obj = parse_session_file(file)
    except SessionParseError as e:
        click.echo(f"Error parsing session: {e}", err=True)
        sys.exit(1)

    session_id = session_obj.metadata.session_id
    stats_text = _format_session_stats(session_obj.statistics, session_id)

    # 2. Build prompt
    prompt, system_role = build_analyze_prompt(
        stats_text=stats_text,
        jsonl_file_path=str(file),
        session_id=session_id,
        lang=lang,
    )

    # 3. Check claude CLI exists
    if not shutil.which("claude"):
        click.echo(
            "Error: 'claude' CLI not found in PATH. "
            "Install Claude Code: https://docs.anthropic.com/en/docs/claude-code",
            err=True,
        )
        sys.exit(1)

    # 4. Determine output path
    if output is None:
        output = get_project_root() / "output" / f"{session_id}_analysis.md"
    output.parent.mkdir(parents=True, exist_ok=True)

    # 5. Invoke claude headless
    click.echo(f"Invoking Claude ({model}) for analysis...", err=True)
    env = os.environ.copy()
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)

    cmd = [
        "claude", "-p", prompt,
        "--model", model,
        "--system-prompt", system_role,
        "--dangerously-skip-permissions",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            env=env,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        click.echo("Error: Claude analysis timed out after 10 minutes.", err=True)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        click.echo(f"Error: Claude process failed (exit code {e.returncode}).", err=True)
        if e.stderr:
            click.echo(e.stderr[:500], err=True)
        sys.exit(1)

    report = result.stdout.strip()
    if not report:
        click.echo("Error: Claude returned empty output.", err=True)
        sys.exit(1)

    # 6. Write report
    output.write_text(report, encoding="utf-8")
    click.echo(f"Analysis report written to: {output}", err=True)


if __name__ == "__main__":
    main()
