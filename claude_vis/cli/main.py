"""Main CLI entry point for Claude Code Session Visualizer."""

import click


@click.group()
@click.version_option(version="0.1.0", prog_name="claude-vis")
def main() -> None:
    """Claude Code Session Visualizer CLI."""
    pass


if __name__ == "__main__":
    main()
