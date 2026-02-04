"""Main CLI entry point for Claude Code Session Visualizer."""

import json
import sys
from pathlib import Path

import click

from claude_vis.parsers import SessionParseError, parse_session_directory


@click.group()
@click.version_option(version="0.1.0", prog_name="claude-vis")
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


@main.command()
@click.option(
    "--path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Path to Claude session directory (default: ~/.claude/projects/)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output file path for JSON output (default: stdout)",
)
@click.option(
    "--pretty",
    is_flag=True,
    default=False,
    help="Pretty-print JSON output with indentation",
)
def parse(path: Path | None, output: Path | None, pretty: bool) -> None:
    """
    Parse Claude Code session files from a directory.

    Reads all .jsonl session files in the specified directory and outputs
    structured data in JSON format. By default, uses ~/.claude/projects/
    as the session directory.

    Examples:

        # Parse sessions from default directory
        claude-vis parse

        # Parse from custom directory
        claude-vis parse --path /path/to/sessions

        # Save output to file
        claude-vis parse --output sessions.json

        # Pretty-print output
        claude-vis parse --pretty
    """
    # Resolve default path
    if path is None:
        path = Path.home() / ".claude" / "projects"

    # Expand path
    path = path.expanduser().resolve()

    click.echo(f"Parsing sessions from: {path}", err=True)

    try:
        # Parse session directory
        parsed_data = parse_session_directory(path)

        click.echo(
            f"Successfully parsed {parsed_data.session_count} sessions "
            f"({parsed_data.total_messages} messages)",
            err=True,
        )

        # Convert to JSON
        json_data = parsed_data.model_dump(mode="json")

        # Determine output format
        indent = 2 if pretty else None

        # Write output
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            with open(output, "w", encoding="utf-8") as f:
                json.dump(json_data, f, indent=indent)
            click.echo(f"Output written to: {output}", err=True)
        else:
            # Output to stdout
            json.dump(json_data, sys.stdout, indent=indent)
            if pretty:
                click.echo()  # Add newline for pretty output

    except SessionParseError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
