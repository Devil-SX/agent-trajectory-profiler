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
