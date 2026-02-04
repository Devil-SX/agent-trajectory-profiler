"""
CLI entry point for running the FastAPI server.

Provides a command-line interface to start the API server with
configurable options.
"""

import sys
from pathlib import Path

import click
import uvicorn

from claude_vis.api.config import get_settings


@click.command()
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
    reload: bool,
    log_level: str | None,
) -> None:
    """
    Start the Claude Code Session Visualizer API server.

    This command starts a FastAPI server that provides REST endpoints
    for accessing and analyzing Claude Code session data.

    Examples:

        # Start server with default settings
        claude-vis serve

        # Start on custom host/port
        claude-vis serve --host 127.0.0.1 --port 8080

        # Use custom session directory
        claude-vis serve --path /path/to/sessions

        # Enable auto-reload for development
        claude-vis serve --reload

        # Set custom log level
        claude-vis serve --log-level debug
    """
    # Get settings
    settings = get_settings()

    # Override settings with CLI arguments
    if path is not None:
        # Update settings with custom path
        settings.session_path = path.expanduser().resolve()

    # Set host, port, and other configs
    server_host = host or settings.api_host
    server_port = port or settings.api_port
    server_reload = reload or settings.api_reload
    server_log_level = log_level or settings.log_level.lower()

    # Print startup information
    click.echo("=" * 60)
    click.echo("Claude Code Session Visualizer API")
    click.echo("=" * 60)
    click.echo(f"Session Path: {settings.session_path}")
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

    try:
        # Start uvicorn server
        uvicorn.run(
            "claude_vis.api.app:app",
            host=server_host,
            port=server_port,
            reload=server_reload,
            log_level=server_log_level,
            access_log=True,
        )
    except KeyboardInterrupt:
        click.echo("\nShutting down server...")
        sys.exit(0)
    except Exception as e:
        click.echo(f"Error starting server: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    serve()
