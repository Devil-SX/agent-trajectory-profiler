"""Main CLI entry point for Agent Trajectory Profiler."""

import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from agent_vis import __version__
from agent_vis.formatters.human import OutputLevel, format_session_stats
from agent_vis.parsers import SessionParseError, parse_session_directory, parse_session_file

if TYPE_CHECKING:
    from agent_vis.models import SessionStatistics


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


def _terminate_subprocess(
    process: subprocess.Popen | None,
    label: str,
    timeout_seconds: float = 8.0,
) -> None:
    """Terminate subprocess gracefully, then force-kill if needed."""
    if process is None or process.poll() is not None:
        return

    click.echo(f"Stopping {label}...")
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        click.echo(f"{label} did not stop in time. Killing it.", err=True)
        process.kill()
        process.wait(timeout=3.0)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _normalize_cli_date_range(
    start_date: str | None,
    end_date: str | None,
    *,
    default_last_days: int | None = None,
) -> tuple[str | None, str | None]:
    """Validate CLI date options and apply API-matching defaults."""
    if default_last_days is not None and not start_date and not end_date:
        end = date.today()
        start = end - timedelta(days=max(default_last_days - 1, 0))
        start_date = start.isoformat()
        end_date = end.isoformat()

    if start_date is not None and not _DATE_RE.match(start_date):
        raise ValueError(f"Invalid --start-date format: '{start_date}'. Expected YYYY-MM-DD.")
    if end_date is not None and not _DATE_RE.match(end_date):
        raise ValueError(f"Invalid --end-date format: '{end_date}'. Expected YYYY-MM-DD.")
    if start_date and end_date and start_date > end_date:
        raise ValueError("--start-date must be on or before --end-date.")

    return start_date, end_date


def _build_readonly_session_service(db_path: Path | None):
    """Create a SessionService wired to the current DB without startup sync side effects."""
    from agent_vis.api.config import get_settings
    from agent_vis.api.service import SessionService
    from agent_vis.db.connection import get_connection
    from agent_vis.db.repository import SessionRepository

    settings = get_settings()
    resolved_db_path = (db_path or settings.db_path).expanduser().resolve()
    service = SessionService(
        settings.session_path,
        codex_session_path=settings.codex_session_path,
        single_session=settings.single_session,
        db_path=resolved_db_path,
        inactivity_threshold=settings.inactivity_threshold,
        model_timeout_threshold=settings.model_timeout_threshold,
    )

    try:
        conn = get_connection(resolved_db_path, create=False)
    except Exception:
        return service

    service._conn = conn
    service._repo = SessionRepository(conn)
    return service


def _echo_json_payload(payload: Any) -> None:
    """Render a CLI payload as pretty JSON."""
    data = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    click.echo(json.dumps(data, indent=2))


def _run_readonly_service_command(
    db_path: Path | None,
    operation: Callable[[Any], Any],
) -> None:
    """Execute a read-only service call and print its JSON response."""
    service = _build_readonly_session_service(db_path)
    try:
        payload_or_awaitable = operation(service)
        payload = (
            asyncio.run(payload_or_awaitable)
            if asyncio.iscoroutine(payload_or_awaitable)
            else payload_or_awaitable
        )
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        if getattr(service, "_conn", None) is not None:
            service._conn.close()

    _echo_json_payload(payload)


def _run_analytics_command(
    db_path: Path | None,
    operation: Callable[[Any], Awaitable[Any]],
) -> None:
    """Execute an async analytics service call and print its JSON response."""
    _run_readonly_service_command(db_path, operation)


def _validate_numeric_range(
    minimum: int | float | None,
    maximum: int | float | None,
    *,
    min_label: str,
    max_label: str,
) -> None:
    """Validate a min/max CLI range pair."""
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError(f"{min_label} must be <= {max_label}")


@click.group()
@click.version_option(version=__version__, prog_name="agent-vis")
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
    import socket

    import uvicorn

    from agent_vis.api.config import get_settings

    def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
        """Check if a port is already in use."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return False
            except OSError:
                return True

    def find_available_port(
        start_port: int, host: str = "127.0.0.1", max_tries: int = 10
    ) -> int | None:
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
        os.environ["AGENT_VIS_SINGLE_SESSION"] = single_session

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
        click.echo(f"Warning: Session path does not exist: {settings.session_path}", err=True)
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
            "agent_vis.api.app:app",
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


@main.command()
@click.option(
    "--host",
    default=None,
    help="Backend host to bind to (default: 0.0.0.0)",
)
@click.option(
    "--port",
    default=None,
    type=int,
    help="Backend port to bind to (default: 8000)",
)
@click.option(
    "--path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Path to agent session directory (default: ~/.claude/projects/)",
)
@click.option(
    "--reload",
    is_flag=True,
    default=False,
    help="Enable backend auto-reload for development",
)
@click.option(
    "--log-level",
    default=None,
    type=click.Choice(["debug", "info", "warning", "error", "critical"], case_sensitive=False),
    help="Backend log level (default: info)",
)
@click.option(
    "--frontend-port",
    default=5173,
    type=int,
    help="Frontend dev server port (default: 5173)",
)
def dashboard(
    host: str | None,
    port: int | None,
    path: Path | None,
    reload: bool,
    log_level: str | None,
    frontend_port: int,
) -> None:
    """
    Start backend and frontend development servers together.

    Runs:
    - backend: uvicorn agent_vis.api.app:app
    - frontend: npm run dev (in frontend/)
    """
    from agent_vis.api.config import get_settings

    project_root = get_project_root()
    frontend_dir = project_root / "frontend"
    if not frontend_dir.exists():
        click.echo(
            f"Error: frontend directory not found at {frontend_dir}. Cannot start dashboard.",
            err=True,
        )
        sys.exit(1)

    npm_path = shutil.which("npm")
    if not npm_path:
        click.echo("Error: npm not found. Please install Node.js and npm first.", err=True)
        sys.exit(1)

    settings = get_settings()
    backend_host = host or settings.api_host
    backend_port = port or settings.api_port
    backend_reload = reload or settings.api_reload
    backend_log_level = (log_level or settings.log_level).lower()
    session_path = path.expanduser().resolve() if path is not None else settings.session_path

    backend_env = os.environ.copy()
    backend_env["AGENT_VIS_SESSION_PATH"] = str(session_path)
    backend_env["AGENT_VIS_API_HOST"] = backend_host
    backend_env["AGENT_VIS_API_PORT"] = str(backend_port)

    backend_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "agent_vis.api.app:app",
        "--host",
        backend_host,
        "--port",
        str(backend_port),
        "--log-level",
        backend_log_level,
    ]
    if backend_reload:
        backend_cmd.append("--reload")

    frontend_cmd = [
        npm_path,
        "run",
        "dev",
        "--",
        "--host",
        backend_host,
        "--port",
        str(frontend_port),
    ]

    click.echo("=" * 60)
    click.echo("Agent Trajectory Profiler Dashboard")
    click.echo("=" * 60)
    click.echo(f"Session Path:   {session_path}")
    click.echo(f"Backend URL:    http://{backend_host}:{backend_port}")
    click.echo(f"API Docs:       http://{backend_host}:{backend_port}/docs")
    click.echo(f"Frontend URL:   http://{backend_host}:{frontend_port}")
    click.echo(f"Backend Reload: {'Enabled' if backend_reload else 'Disabled'}")
    click.echo(f"Log Level:      {backend_log_level.upper()}")
    click.echo("=" * 60)
    click.echo("Starting dashboard... (Press Ctrl+C to stop)\n")

    backend_process: subprocess.Popen | None = None
    frontend_process: subprocess.Popen | None = None
    stop_requested = False

    def request_shutdown(signum: int, frame: object) -> None:
        """Set shutdown flag on termination signals."""
        del signum, frame
        nonlocal stop_requested
        stop_requested = True

    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)

    exit_code = 0
    try:
        backend_process = subprocess.Popen(backend_cmd, env=backend_env)
        frontend_process = subprocess.Popen(frontend_cmd, cwd=frontend_dir)

        while True:
            if stop_requested:
                break

            backend_code = backend_process.poll()
            frontend_code = frontend_process.poll()

            if backend_code is not None or frontend_code is not None:
                if backend_code is not None and backend_code != 0:
                    click.echo(f"Backend server exited with code {backend_code}.", err=True)
                if frontend_code is not None and frontend_code != 0:
                    click.echo(f"Frontend server exited with code {frontend_code}.", err=True)

                if backend_code is None or frontend_code is None:
                    click.echo("One process exited. Stopping the remaining process...")
                exit_code = backend_code or frontend_code or 0
                break

            time.sleep(0.2)

    except KeyboardInterrupt:
        stop_requested = True
    finally:
        _terminate_subprocess(frontend_process, "frontend dev server")
        _terminate_subprocess(backend_process, "backend API server")
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)

    if exit_code != 0:
        sys.exit(exit_code)


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
            sessions_list = [(s.metadata.session_id, s) for s in parsed_data.sessions]
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
            sessions_list = [(s.metadata.session_id, s) for s in parsed_data.sessions]
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
    help="SQLite database path (default: ~/.agent-vis/profiler.db)",
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
    from agent_vis.db.connection import get_connection
    from agent_vis.db.repository import SessionRepository
    from agent_vis.db.sync import SyncEngine
    from agent_vis.parsers.registry import get_parser

    default_path = Path.home() / ".claude" / "projects"
    if ecosystem == "codex":
        default_path = Path.home() / ".codex" / "sessions"
    scan_path = (path or default_path).expanduser().resolve()

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
    help="SQLite database path (default: ~/.agent-vis/profiler.db)",
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
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    default=False,
    help="Return API-shaped JSON for a single session statistics query",
)
def stats(
    session_id: str | None,
    level: str,
    sort_by: str,
    limit: int,
    db_path: Path | None,
    start_date: str | None,
    end_date: str | None,
    json_output: bool,
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

    from agent_vis.db.connection import get_connection
    from agent_vis.db.repository import SessionRepository

    # Validate date formats
    _date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    if start_date is not None and not _date_re.match(start_date):
        click.echo(
            f"Error: Invalid --start-date format: '{start_date}'. Expected YYYY-MM-DD.", err=True
        )
        sys.exit(1)
    if end_date is not None and not _date_re.match(end_date):
        click.echo(
            f"Error: Invalid --end-date format: '{end_date}'. Expected YYYY-MM-DD.", err=True
        )
        sys.exit(1)
    if start_date and end_date and start_date > end_date:
        click.echo("Error: --start-date must be on or before --end-date.", err=True)
        sys.exit(1)

    conn = get_connection(db_path, create=False)
    repo = SessionRepository(conn)
    output_level = OutputLevel(int(level))

    if json_output and not session_id:
        click.echo("Error: --json requires --session-id.", err=True)
        conn.close()
        sys.exit(1)

    if session_id:
        statistics = repo.get_statistics(session_id)
        if statistics is None:
            click.echo(f"Error: Session '{session_id}' not found in database.", err=True)
            click.echo("Run 'agent-vis sync' first to populate the database.", err=True)
            conn.close()
            sys.exit(1)
        if json_output:
            from agent_vis.api.models import SessionStatisticsResponse

            _echo_json_payload(
                SessionStatisticsResponse(session_id=session_id, statistics=statistics)
            )
        else:
            click.echo(format_session_stats(statistics, session_id, level=output_level))
    else:
        rows = repo.list_sessions(
            sort_by=sort_by,
            sort_order="DESC",
            limit=limit,
            start_date=start_date,
            end_date=end_date,
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
                from agent_vis.formatters.human import _format_duration, _format_tokens

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
    from agent_vis.prompts.analyze import build_analyze_prompt

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
        "claude",
        "-p",
        prompt,
        "--model",
        model,
        "--system-prompt",
        system_role,
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


@main.group()
def sessions() -> None:
    """Read-only session queries mirroring the REST API."""
    pass


@sessions.command("list")
@click.option("--page", type=click.IntRange(min=1), default=1, show_default=True)
@click.option(
    "--page-size",
    type=click.IntRange(min=1, max=200),
    default=50,
    show_default=True,
)
@click.option("--start-date", default=None, help="Filter sessions on/after this date (YYYY-MM-DD)")
@click.option("--end-date", default=None, help="Filter sessions on/before this date (YYYY-MM-DD)")
@click.option("--ecosystem", default=None, help="Filter by ecosystem (e.g. claude_code, codex)")
@click.option(
    "--bottleneck",
    type=click.Choice(["model", "tool", "user"], case_sensitive=False),
    default=None,
    help="Filter by bottleneck category.",
)
@click.option(
    "--sort-by",
    type=click.Choice(
        ["updated", "created", "tokens", "duration", "automation", "messages"], case_sensitive=False
    ),
    default="updated",
    show_default=True,
    help="Sort key for session list.",
)
@click.option(
    "--sort-direction",
    type=click.Choice(["asc", "desc"], case_sensitive=False),
    default="desc",
    show_default=True,
    help="Sort direction.",
)
@click.option("--min-tokens", type=click.IntRange(min=0), default=None)
@click.option("--max-tokens", type=click.IntRange(min=0), default=None)
@click.option("--min-messages", type=click.IntRange(min=0), default=None)
@click.option("--max-messages", type=click.IntRange(min=0), default=None)
@click.option("--min-automation", type=float, default=None)
@click.option("--max-automation", type=float, default=None)
@click.option(
    "--view",
    type=click.Choice(["logical", "physical"], case_sensitive=False),
    default="logical",
    show_default=True,
    help="Session view mode.",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=None,
    help="SQLite database path (default: ~/.agent-vis/profiler.db)",
)
def sessions_list(
    page: int,
    page_size: int,
    start_date: str | None,
    end_date: str | None,
    ecosystem: str | None,
    bottleneck: str | None,
    sort_by: str,
    sort_direction: str,
    min_tokens: int | None,
    max_tokens: int | None,
    min_messages: int | None,
    max_messages: int | None,
    min_automation: float | None,
    max_automation: float | None,
    view: str,
    db_path: Path | None,
) -> None:
    """Return session list data as API-shaped JSON."""
    from agent_vis.api.models import SessionListResponse

    try:
        start_date, end_date = _normalize_cli_date_range(start_date, end_date)
        _validate_numeric_range(
            min_tokens,
            max_tokens,
            min_label="min_tokens",
            max_label="max_tokens",
        )
        _validate_numeric_range(
            min_messages,
            max_messages,
            min_label="min_messages",
            max_label="max_messages",
        )
        _validate_numeric_range(
            min_automation,
            max_automation,
            min_label="min_automation",
            max_label="max_automation",
        )
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    ecosystem_filter = None if ecosystem in (None, "", "all") else ecosystem

    async def _operation(service: Any) -> Any:
        sessions_payload, total_count = await service.list_sessions(
            page,
            page_size,
            sort_by=sort_by,
            sort_order=sort_direction.upper(),
            start_date=start_date,
            end_date=end_date,
            ecosystem=ecosystem_filter,
            bottleneck=bottleneck,
            min_tokens=min_tokens,
            max_tokens=max_tokens,
            min_messages=min_messages,
            max_messages=max_messages,
            min_automation=min_automation,
            max_automation=max_automation,
            view_mode=view,
        )
        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 0
        return SessionListResponse(
            sessions=sessions_payload,
            count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    _run_readonly_service_command(db_path, _operation)


@sessions.command("get")
@click.argument("session_id")
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=None,
    help="SQLite database path (default: ~/.agent-vis/profiler.db)",
)
def sessions_get(session_id: str, db_path: Path | None) -> None:
    """Return session detail as API-shaped JSON."""
    from agent_vis.api.models import SessionDetailResponse

    async def _operation(service: Any) -> Any:
        session = await service.get_session(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' not found.")
        return SessionDetailResponse(session=session)

    _run_readonly_service_command(db_path, _operation)


@sessions.command("statistics")
@click.argument("session_id")
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=None,
    help="SQLite database path (default: ~/.agent-vis/profiler.db)",
)
def sessions_statistics(session_id: str, db_path: Path | None) -> None:
    """Return session statistics as API-shaped JSON."""
    from agent_vis.api.models import SessionStatisticsResponse

    async def _operation(service: Any) -> Any:
        statistics = await service.get_session_statistics(session_id)
        if statistics is None:
            raise ValueError(f"Session '{session_id}' not found.")
        return SessionStatisticsResponse(session_id=session_id, statistics=statistics)

    _run_readonly_service_command(db_path, _operation)


@main.command("sync-status")
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=None,
    help="SQLite database path (default: ~/.agent-vis/profiler.db)",
)
def sync_status(db_path: Path | None) -> None:
    """Return sync status as API-shaped JSON."""
    from agent_vis.api.models import SyncStatusResponse

    def _operation(service: Any) -> Any:
        return SyncStatusResponse(**service.get_sync_status())

    _run_readonly_service_command(db_path, _operation)


@main.command()
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=None,
    help="SQLite database path (default: ~/.agent-vis/profiler.db)",
)
def capabilities(db_path: Path | None) -> None:
    """Return registered capability manifests as JSON."""
    from agent_vis.api.models import CapabilityListResponse

    def _operation(service: Any) -> Any:
        return CapabilityListResponse(capabilities=service.get_capabilities())

    _run_readonly_service_command(db_path, _operation)


@main.command("frontend-preferences")
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=None,
    help="SQLite database path (default: ~/.agent-vis/profiler.db)",
)
def frontend_preferences(db_path: Path | None) -> None:
    """Return persisted frontend preferences as JSON."""

    def _operation(service: Any) -> Any:
        return service.get_frontend_preferences()

    _run_readonly_service_command(db_path, _operation)


@main.group()
def analytics() -> None:
    """Read-only analytics queries mirroring the REST API."""
    pass


@analytics.command("overview")
@click.option(
    "--start-date",
    default=None,
    help="Range start date (YYYY-MM-DD)",
)
@click.option(
    "--end-date",
    default=None,
    help="Range end date (YYYY-MM-DD)",
)
@click.option(
    "--ecosystem",
    default=None,
    help="Optional source filter (e.g. claude_code, codex)",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=None,
    help="SQLite database path (default: ~/.agent-vis/profiler.db)",
)
def analytics_overview(
    start_date: str | None,
    end_date: str | None,
    ecosystem: str | None,
    db_path: Path | None,
) -> None:
    """Return cross-session overview metrics as JSON."""
    try:
        start_date, end_date = _normalize_cli_date_range(start_date, end_date, default_last_days=7)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    async def _operation(service: Any) -> Any:
        return await service.get_analytics_overview(start_date, end_date, ecosystem=ecosystem)

    _run_analytics_command(db_path, _operation)


@analytics.command("distributions")
@click.option(
    "--dimension",
    type=click.Choice(
        [
            "bottleneck",
            "project",
            "branch",
            "automation_band",
            "tool",
            "session_token_share",
        ],
        case_sensitive=False,
    ),
    default="bottleneck",
    show_default=True,
    help="Distribution dimension to aggregate.",
)
@click.option(
    "--start-date",
    default=None,
    help="Range start date (YYYY-MM-DD)",
)
@click.option(
    "--end-date",
    default=None,
    help="Range end date (YYYY-MM-DD)",
)
@click.option(
    "--ecosystem",
    default=None,
    help="Optional source filter (e.g. claude_code, codex)",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=None,
    help="SQLite database path (default: ~/.agent-vis/profiler.db)",
)
def analytics_distributions(
    dimension: str,
    start_date: str | None,
    end_date: str | None,
    ecosystem: str | None,
    db_path: Path | None,
) -> None:
    """Return analytics distributions as JSON."""
    try:
        start_date, end_date = _normalize_cli_date_range(start_date, end_date, default_last_days=7)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    async def _operation(service: Any) -> Any:
        return await service.get_analytics_distribution(
            dimension,
            start_date,
            end_date,
            ecosystem=ecosystem,
        )

    _run_analytics_command(db_path, _operation)


@analytics.command("timeseries")
@click.option(
    "--interval",
    type=click.Choice(["day", "week"], case_sensitive=False),
    default="day",
    show_default=True,
    help="Aggregation interval.",
)
@click.option(
    "--start-date",
    default=None,
    help="Range start date (YYYY-MM-DD)",
)
@click.option(
    "--end-date",
    default=None,
    help="Range end date (YYYY-MM-DD)",
)
@click.option(
    "--ecosystem",
    default=None,
    help="Optional source filter (e.g. claude_code, codex)",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=None,
    help="SQLite database path (default: ~/.agent-vis/profiler.db)",
)
def analytics_timeseries(
    interval: str,
    start_date: str | None,
    end_date: str | None,
    ecosystem: str | None,
    db_path: Path | None,
) -> None:
    """Return analytics time-series aggregates as JSON."""
    try:
        start_date, end_date = _normalize_cli_date_range(start_date, end_date, default_last_days=7)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    async def _operation(service: Any) -> Any:
        return await service.get_analytics_timeseries(
            start_date,
            end_date,
            interval,
            ecosystem=ecosystem,
        )

    _run_analytics_command(db_path, _operation)


@analytics.command("project-comparison")
@click.option(
    "--start-date",
    default=None,
    help="Range start date (YYYY-MM-DD)",
)
@click.option(
    "--end-date",
    default=None,
    help="Range end date (YYYY-MM-DD)",
)
@click.option(
    "--limit",
    type=click.IntRange(min=1, max=50),
    default=10,
    show_default=True,
    help="Maximum projects to return.",
)
@click.option(
    "--ecosystem",
    default=None,
    help="Optional source filter (e.g. claude_code, codex)",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=None,
    help="SQLite database path (default: ~/.agent-vis/profiler.db)",
)
def analytics_project_comparison(
    start_date: str | None,
    end_date: str | None,
    limit: int,
    ecosystem: str | None,
    db_path: Path | None,
) -> None:
    """Return project-level comparison metrics as JSON."""
    try:
        start_date, end_date = _normalize_cli_date_range(start_date, end_date, default_last_days=7)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    async def _operation(service: Any) -> Any:
        return await service.get_project_comparison(
            start_date,
            end_date,
            limit,
            ecosystem=ecosystem,
        )

    _run_analytics_command(db_path, _operation)


@analytics.command("project-swimlane")
@click.option(
    "--interval",
    type=click.Choice(["day", "week"], case_sensitive=False),
    default="day",
    show_default=True,
    help="Aggregation interval.",
)
@click.option(
    "--start-date",
    default=None,
    help="Range start date (YYYY-MM-DD)",
)
@click.option(
    "--end-date",
    default=None,
    help="Range end date (YYYY-MM-DD)",
)
@click.option(
    "--project-limit",
    type=click.IntRange(min=1, max=50),
    default=12,
    show_default=True,
    help="Maximum projects to include in the swimlane.",
)
@click.option(
    "--ecosystem",
    default=None,
    help="Optional source filter (e.g. claude_code, codex)",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=None,
    help="SQLite database path (default: ~/.agent-vis/profiler.db)",
)
def analytics_project_swimlane(
    interval: str,
    start_date: str | None,
    end_date: str | None,
    project_limit: int,
    ecosystem: str | None,
    db_path: Path | None,
) -> None:
    """Return project swimlane points as JSON."""
    try:
        start_date, end_date = _normalize_cli_date_range(start_date, end_date, default_last_days=7)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    async def _operation(service: Any) -> Any:
        return await service.get_project_swimlane(
            start_date,
            end_date,
            interval,
            project_limit,
            ecosystem=ecosystem,
        )

    _run_analytics_command(db_path, _operation)


@main.group()
def report() -> None:
    """Reporting commands (incremental summaries)."""
    pass


@report.command("telegram")
@click.option(
    "--config-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Telegram config path (default: ~/.agent-vis/config/telegram.toml)",
)
@click.option(
    "--state-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Report state path (default: ~/.agent-vis/state/report-state.json)",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=None,
    help="SQLite database path (default: ~/.agent-vis/profiler.db)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Generate report and print result without sending to Telegram",
)
@click.option(
    "--window",
    type=click.Choice(["auto", "1d", "3d", "7d", "14d", "30d", "90d", "all"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="Report window mode: auto uses incremental checkpoint; others use manual lookback.",
)
@click.option(
    "--days",
    type=click.IntRange(min=1),
    default=None,
    help="Custom manual lookback days. Overrides --window when set.",
)
@click.option(
    "--style",
    type=click.Choice(["advanced", "compact"], case_sensitive=False),
    default=None,
    help="Report style override (defaults to telegram.report.style).",
)
@click.option(
    "--format",
    "report_format",
    type=click.Choice(["markdownv2", "html", "plain"], case_sensitive=False),
    default=None,
    help="Telegram rich-text format override (defaults to telegram.report.format).",
)
@click.option(
    "--detail-level",
    type=click.Choice(["low", "medium", "high"], case_sensitive=False),
    default=None,
    help="Detail granularity override (defaults to telegram.report.detail_level).",
)
@click.option(
    "--split-mode",
    type=click.Choice(["auto", "single"], case_sensitive=False),
    default=None,
    help="Message split policy override (defaults to telegram.report.split_mode).",
)
@click.option(
    "--max-message-chars",
    type=click.IntRange(min=512, max=4096),
    default=None,
    help="Message length limit override (defaults to telegram.report.max_message_chars).",
)
@click.option(
    "--send-details/--no-send-details",
    default=None,
    help="Whether to send detail sections (defaults to telegram.report.send_details).",
)
def report_telegram(
    config_path: Path | None,
    state_path: Path | None,
    db_path: Path | None,
    dry_run: bool,
    window: str,
    days: int | None,
    style: str | None,
    report_format: str | None,
    detail_level: str | None,
    split_mode: str | None,
    max_message_chars: int | None,
    send_details: bool | None,
) -> None:
    """Send incremental summary report to Telegram Bot chat."""
    from agent_vis.reporting.telegram import (
        DEFAULT_CONFIG_PATH,
        DEFAULT_STATE_PATH,
        run_telegram_incremental_report,
    )

    resolved_config_path = config_path or DEFAULT_CONFIG_PATH
    resolved_state_path = state_path or DEFAULT_STATE_PATH

    try:
        result = run_telegram_incremental_report(
            config_path=resolved_config_path,
            state_path=resolved_state_path,
            db_path=db_path,
            dry_run=dry_run,
            window=window,
            days=days,
            style=style,
            report_format=report_format,
            detail_level=detail_level,
            split_mode=split_mode,
            max_message_chars=max_message_chars,
            send_details=send_details,
        )
    except Exception as exc:
        click.echo(f"Telegram report failed: {exc}", err=True)
        click.echo(f"Config: {resolved_config_path}", err=True)
        click.echo(f"State:  {resolved_state_path}", err=True)
        sys.exit(1)

    click.echo("=" * 60)
    click.echo("Telegram Incremental Report")
    click.echo("=" * 60)
    click.echo(f"Status:         {result.status}")
    click.echo(f"Target chat:    {result.chat_id}")
    click.echo(f"Render format:  {result.render_format}")
    click.echo(f"Window mode:    {result.window_mode}")
    click.echo(f"Window start:   {result.window_start or 'initial-sync'}")
    click.echo(f"Window end:     {result.window_end}")
    click.echo(f"State updated:  {'yes' if result.state_updated else 'no'}")
    click.echo(f"Messages sent:  {result.message_count}")
    click.echo(f"Truncated:      {'yes' if result.truncated else 'no'}")
    click.echo(
        "Sections:       " + ", ".join(result.sections_sent)
        if result.sections_sent
        else "Sections:       (none)"
    )
    click.echo(f"New sessions:   {result.summary.session_count}")
    click.echo(f"Tool errors:    {result.summary.total_tool_errors}")
    click.echo(
        "Sources:        "
        + ", ".join(f"{k}={v}" for k, v in sorted(result.summary.source_counts.items()))
        if result.summary.source_counts
        else "Sources:        (none)"
    )
    click.echo(
        "Bottlenecks:    "
        + ", ".join(f"{k}={v}" for k, v in sorted(result.summary.bottleneck_counts.items()))
        if result.summary.bottleneck_counts
        else "Bottlenecks:    (none)"
    )
    click.echo("=" * 60)


if __name__ == "__main__":
    main()
