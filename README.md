# Claude Code Session Visualizer

A web application to visualize and analyze Claude Code sessions with CLI tools for parsing session data and a frontend for interactive visualization with detailed statistics and analytics.

## Features

- Parse Claude Code session data from various sources
- Interactive web-based visualization dashboard
- Detailed session statistics and analytics
- CLI tools for batch processing and analysis

## Prerequisites

- Python 3.10 or higher
- [UV](https://github.com/astral-sh/uv) - Fast Python package installer and resolver

## Installation

### Installing UV

If you don't have UV installed, install it using one of the following methods:

```bash
# macOS and Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# With pip
pip install uv
```

### Setting Up the Project

1. Clone the repository:
```bash
git clone <repository-url>
cd claude-code-sessin-vis
```

2. Initialize the UV environment and install dependencies:
```bash
uv sync --dev
```

This command will:
- Create a virtual environment in `.venv/`
- Install all project dependencies
- Install development dependencies (pytest, playwright, black, mypy, ruff)
- Generate a `uv.lock` file for dependency locking

3. Activate the virtual environment:
```bash
# macOS and Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

## Development

### Running the Application

```bash
# Using UV
uv run claude-vis --help

# Or with activated virtual environment
claude-vis --help
```

### Code Quality Tools

The project uses several tools to maintain code quality:

```bash
# Format code with Black
uv run black .

# Lint code with Ruff
uv run ruff check .

# Type check with mypy
uv run mypy .

# Run tests
uv run pytest
```

### Adding Dependencies

To add new dependencies:

```bash
# Production dependency
uv add <package-name>

# Development dependency
uv add --dev <package-name>
```

## Project Structure

```
claude-code-sessin-vis/
├── claude_vis/          # Main application package
│   ├── cli/            # CLI tools
│   ├── api/            # FastAPI backend
│   └── parsers/        # Session data parsers
├── tests/              # Test suite
├── pyproject.toml      # Project configuration
├── uv.lock            # Locked dependencies
└── README.md          # This file
```

## License

MIT
