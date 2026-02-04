# Claude Code Session Visualizer

A comprehensive web application to visualize and analyze Claude Code sessions with CLI tools for parsing session data and an interactive frontend for detailed visualization, statistics, and analytics.

![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)

## 🌟 Features

- **Session Parsing**: Parse Claude Code session data from `.jsonl` files
- **Interactive Dashboard**: Web-based visualization with responsive design
- **Detailed Analytics**: Comprehensive session statistics and metrics
- **REST API**: FastAPI-powered backend with auto-generated documentation
- **CLI Tools**: Command-line interface for batch processing and server management
- **Real-time Updates**: Live session data updates in development mode
- **Mobile Responsive**: Optimized for desktop, tablet, and mobile devices

## 📋 Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Usage](#cli-usage)
- [Web UI Guide](#web-ui-guide)
- [API Documentation](#api-documentation)
- [Architecture](#architecture)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

## 🔧 Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.10 or higher**: Check with `python --version` or `python3 --version`
- **UV**: Fast Python package installer and resolver ([installation guide](https://github.com/astral-sh/uv))
- **Node.js 18+** (for frontend development): Check with `node --version`
- **Git**: For version control

## 📦 Installation

### Step 1: Install UV

If you don't have UV installed, install it using one of the following methods:

```bash
# macOS and Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# With pip (alternative)
pip install uv
```

Verify installation:
```bash
uv --version
```

### Step 2: Clone the Repository

```bash
git clone https://github.com/yourusername/claude-code-sessin-vis.git
cd claude-code-sessin-vis
```

### Step 3: Install Dependencies

```bash
# Install Python dependencies (creates .venv automatically)
uv sync --dev

# Install frontend dependencies (optional, for development)
cd frontend
npm install
cd ..
```

This will:
- Create a virtual environment in `.venv/`
- Install all project dependencies
- Install development tools (pytest, playwright, black, mypy, ruff)
- Generate a `uv.lock` file for reproducible builds

### Step 4: Activate Virtual Environment

```bash
# macOS and Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

## 🚀 Quick Start

### Option 1: Run with Built Frontend (Production Mode)

```bash
# Build the frontend first
cd frontend
npm run build
cd ..

# Start the server (serves both API and frontend)
claude-vis serve
```

Open your browser to `http://localhost:8000`

### Option 2: Development Mode (Separate Frontend)

Terminal 1 - Backend:
```bash
claude-vis serve --reload --log-level debug
```

Terminal 2 - Frontend:
```bash
cd frontend
npm run dev
```

- Backend API: `http://localhost:8000`
- Frontend Dev Server: `http://localhost:5173`
- API Documentation: `http://localhost:8000/docs`

## 💻 CLI Usage

The `claude-vis` CLI provides two main commands: `serve` and `parse`.

### Command: `serve`

Start the API server with the web interface.

```bash
# Basic usage (uses default ~/.claude/projects/)
claude-vis serve

# Custom host and port
claude-vis serve --host 127.0.0.1 --port 8080

# Custom session directory
claude-vis serve --path /path/to/claude/sessions

# Load a single specific session
claude-vis serve --single-session abc123def456

# Development mode with auto-reload
claude-vis serve --reload --log-level debug

# Production mode
claude-vis serve --host 0.0.0.0 --port 8000 --log-level info
```

**Options:**
- `--host TEXT`: Host to bind to (default: `0.0.0.0`)
- `--port INTEGER`: Port to bind to (default: `8000`)
- `--path PATH`: Path to Claude session directory (default: `~/.claude/projects/`)
- `--single-session TEXT`: Load only a specific session by ID
- `--reload`: Enable auto-reload for development
- `--log-level [debug|info|warning|error|critical]`: Set log level (default: `info`)

**Example Output:**
```
============================================================
Claude Code Session Visualizer
============================================================
Session Path: /home/user/.claude/projects
Server URL:   http://0.0.0.0:8000
API Docs:     http://0.0.0.0:8000/docs
Reload Mode:  Disabled
Log Level:    INFO
============================================================

Starting server... (Press Ctrl+C to stop)
```

### Command: `parse`

Parse Claude Code session files and output JSON data.

```bash
# Parse from default directory to stdout
claude-vis parse

# Parse from custom directory
claude-vis parse --path /path/to/sessions

# Save to file
claude-vis parse --output sessions.json

# Pretty-print output
claude-vis parse --pretty

# Combine options
claude-vis parse --path ~/sessions --output data.json --pretty
```

**Options:**
- `--path PATH`: Path to Claude session directory (default: `~/.claude/projects/`)
- `--output PATH`, `-o PATH`: Output file path (default: stdout)
- `--pretty`: Pretty-print JSON with indentation

**Example Output:**
```
Parsing sessions from: /home/user/.claude/projects
Successfully parsed 15 sessions (342 messages)
Output written to: sessions.json
```

### Getting Help

```bash
# General help
claude-vis --help

# Command-specific help
claude-vis serve --help
claude-vis parse --help

# Version information
claude-vis --version
```

## 🖥️ Web UI Guide

### Home Page

The home page displays a list of all available Claude Code sessions:

- **Session Cards**: Each session shows:
  - Session ID (truncated)
  - Creation date and time
  - Message count
  - Subagent count
  - Duration

- **Sorting**: Click column headers to sort sessions
- **Search**: Use the search bar to filter sessions
- **Click to View**: Click any session card to view details

### Session Detail View

The detail view provides comprehensive information about a specific session:

#### 1. Overview Panel
- Session ID (full)
- Creation timestamp
- Total messages
- Subagent count
- Session duration

#### 2. Messages Timeline
- Chronological list of all messages
- User messages (displayed on the right)
- Assistant messages (displayed on the left)
- Message timestamps
- Character counts

#### 3. Subagent Information
- List of all subagents used in the session
- Subagent types and IDs
- Status indicators
- Execution details

#### 4. Statistics Dashboard

**Message Statistics:**
- Total message count
- User vs Assistant message breakdown
- Average message length
- Message frequency over time

**Token Usage (if available):**
- Total tokens used
- Input vs Output tokens
- Token usage by message

**Tool Usage:**
- Most frequently used tools
- Tool execution counts
- Success/failure rates

**Timeline Visualization:**
- Interactive timeline chart
- Message activity heatmap
- Session duration breakdown

**Performance Metrics:**
- Average response time
- Peak usage periods
- Session efficiency score

### Navigation

- **Back Button**: Return to session list
- **Breadcrumbs**: Navigate between pages
- **Mobile Menu**: Hamburger menu on mobile devices
- **Responsive Layout**: Optimized for all screen sizes

### Tips for Best Experience

1. **Use Chrome or Firefox** for best compatibility
2. **Enable JavaScript** - required for interactive features
3. **Desktop View** - Best for detailed analytics
4. **Mobile View** - Optimized for quick session browsing

## 📚 API Documentation

The API is built with FastAPI and provides comprehensive RESTful endpoints.

### Base URL

```
http://localhost:8000
```

### Interactive API Documentation

- **Swagger UI**: `http://localhost:8000/docs` - Interactive API explorer
- **ReDoc**: `http://localhost:8000/redoc` - Clean API documentation

### Endpoints

#### 1. Root Endpoint

```http
GET /
```

Returns API information.

**Response:**
```json
{
  "name": "Claude Code Session Visualizer API",
  "version": "0.1.0",
  "docs": "/docs",
  "health": "/health"
}
```

#### 2. Health Check

```http
GET /health
```

Check API health and status.

**Response:**
```json
{
  "status": "healthy",
  "session_path": "/home/user/.claude/projects",
  "sessions_loaded": 15
}
```

#### 3. List Sessions

```http
GET /api/sessions
```

Get a list of all available sessions.

**Response:**
```json
{
  "sessions": [
    {
      "session_id": "abc123def456",
      "created_at": "2024-02-04T10:30:00Z",
      "message_count": 25,
      "subagent_count": 3,
      "duration_seconds": 1800
    }
  ],
  "count": 15
}
```

#### 4. Get Session Details

```http
GET /api/sessions/{session_id}
```

Get complete details for a specific session.

**Parameters:**
- `session_id` (path): Session identifier

**Response:**
```json
{
  "session": {
    "session_id": "abc123def456",
    "created_at": "2024-02-04T10:30:00Z",
    "messages": [
      {
        "message_id": "msg_001",
        "role": "user",
        "content": "Hello, can you help me?",
        "timestamp": "2024-02-04T10:30:05Z"
      }
    ],
    "subagents": [
      {
        "agent_id": "agent_001",
        "type": "code_analyzer",
        "status": "completed"
      }
    ],
    "metadata": {
      "message_count": 25,
      "subagent_count": 3
    }
  }
}
```

#### 5. Get Session Statistics

```http
GET /api/sessions/{session_id}/statistics
```

Get computed analytics and statistics for a session.

**Parameters:**
- `session_id` (path): Session identifier

**Response:**
```json
{
  "session_id": "abc123def456",
  "statistics": {
    "message_stats": {
      "total_messages": 25,
      "user_messages": 12,
      "assistant_messages": 13,
      "avg_message_length": 156.4
    },
    "tool_usage": {
      "total_tool_calls": 45,
      "unique_tools": 8,
      "most_used_tool": "read_file"
    },
    "timing": {
      "session_duration": 1800,
      "avg_response_time": 2.3,
      "first_message": "2024-02-04T10:30:05Z",
      "last_message": "2024-02-04T11:00:05Z"
    }
  }
}
```

### Error Responses

All endpoints may return error responses in this format:

```json
{
  "error": "Error type",
  "detail": "Detailed error message",
  "status_code": 404
}
```

**Common Status Codes:**
- `200 OK`: Success
- `404 Not Found`: Resource not found
- `500 Internal Server Error`: Server error
- `503 Service Unavailable`: Service not initialized

### CORS Configuration

The API supports CORS for local development:
- Allowed origins: `http://localhost:5173`, `http://localhost:8000`
- Allows all methods and headers
- Supports credentials

## 🏗️ Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Claude Code Session Visualizer           │
└─────────────────────────────────────────────────────────────┘

┌──────────────┐         ┌──────────────┐         ┌──────────┐
│   Frontend   │────────▶│   FastAPI    │────────▶│  Parser  │
│   (React)    │◀────────│   Backend    │◀────────│  Engine  │
└──────────────┘         └──────────────┘         └──────────┘
      │                         │                       │
      │                         │                       │
      ▼                         ▼                       ▼
┌──────────────┐         ┌──────────────┐         ┌──────────┐
│  Recharts    │         │   Pydantic   │         │  .jsonl  │
│   Charts     │         │   Models     │         │  Files   │
└──────────────┘         └──────────────┘         └──────────┘
```

### Component Architecture

#### Backend (Python)

```
claude_vis/
├── api/
│   ├── app.py           # FastAPI application
│   ├── config.py        # Configuration management
│   ├── models.py        # API response models
│   └── service.py       # Business logic
├── cli/
│   └── main.py          # CLI commands
├── parsers/
│   ├── parser.py        # Session file parser
│   └── statistics.py    # Analytics computation
└── models.py            # Domain models
```

**Key Components:**

1. **Parser Engine**: Reads `.jsonl` session files and converts to structured data
2. **Statistics Engine**: Computes analytics from raw session data
3. **API Service**: Manages session data and provides business logic
4. **FastAPI Application**: REST API with automatic documentation

#### Frontend (React + TypeScript)

```
frontend/src/
├── components/
│   ├── SessionList.tsx     # Session list view
│   ├── SessionDetail.tsx   # Detail view
│   ├── Statistics.tsx      # Analytics dashboard
│   └── charts/             # Chart components
├── services/
│   └── api.ts              # API client
├── types/
│   └── index.ts            # TypeScript definitions
└── App.tsx                 # Root component
```

**Key Technologies:**

- **React 19**: UI framework
- **TypeScript**: Type safety
- **Recharts**: Data visualization
- **TailwindCSS 4**: Styling
- **Vite**: Build tool

### Data Flow

1. **Session Files** → Parser reads `.jsonl` files
2. **Structured Data** → Converted to Pydantic models
3. **API Layer** → FastAPI exposes REST endpoints
4. **Frontend** → React fetches data and renders UI
5. **Analytics** → Statistics computed on-demand

### Session File Format

Claude Code sessions are stored as `.jsonl` (JSON Lines) files where each line is a valid JSON object representing a message or event:

```jsonl
{"type": "message", "role": "user", "content": "...", "timestamp": "..."}
{"type": "message", "role": "assistant", "content": "...", "timestamp": "..."}
{"type": "subagent", "agent_id": "...", "status": "...", "result": "..."}
```

## 🔨 Development

### Setting Up Development Environment

1. **Clone and install dependencies:**
```bash
git clone <repository-url>
cd claude-code-sessin-vis
uv sync --dev
```

2. **Install frontend dependencies:**
```bash
cd frontend
npm install
```

3. **Install Playwright browsers (for E2E tests):**
```bash
cd frontend
npx playwright install
```

### Development Workflow

#### Backend Development

```bash
# Activate virtual environment
source .venv/bin/activate

# Run server with auto-reload
claude-vis serve --reload --log-level debug

# Run tests
uv run pytest

# Type checking
uv run mypy .

# Linting
uv run ruff check .

# Format code
uv run black .
```

#### Frontend Development

```bash
cd frontend

# Start dev server
npm run dev

# Run type checking
npm run type-check

# Run linting
npm run lint

# Format code
npm run format

# Run E2E tests
npm run test:e2e

# Run E2E tests with UI
npm run test:e2e:ui
```

### Code Quality Tools

#### Python

- **Black**: Code formatter (line length: 100)
- **Ruff**: Fast linter and formatter
- **mypy**: Static type checker (strict mode)
- **pytest**: Testing framework

#### Frontend

- **Prettier**: Code formatter
- **ESLint**: Linter with TypeScript support
- **TypeScript**: Static type checking
- **Playwright**: E2E testing

### Running Tests

```bash
# Backend tests
uv run pytest -v

# Frontend E2E tests
cd frontend
npm run test:e2e

# Frontend E2E tests with UI mode
npm run test:e2e:ui
```

### Adding Dependencies

```bash
# Python dependency
uv add <package-name>

# Python dev dependency
uv add --dev <package-name>

# Frontend dependency
cd frontend
npm install <package-name>

# Frontend dev dependency
npm install --save-dev <package-name>
```

### Building for Production

```bash
# Build frontend
cd frontend
npm run build

# The built files will be in frontend/dist/
# The API server will automatically serve them
```

### Environment Variables

Create a `.env` file in the project root:

```env
# API Configuration
CLAUDE_VIS_API_HOST=0.0.0.0
CLAUDE_VIS_API_PORT=8000
CLAUDE_VIS_SESSION_PATH=/path/to/sessions
CLAUDE_VIS_LOG_LEVEL=info

# Single session mode (optional)
CLAUDE_VIS_SINGLE_SESSION=abc123def456

# CORS origins (comma-separated)
CLAUDE_VIS_CORS_ORIGINS=http://localhost:5173,http://localhost:8000
```

## 🐛 Troubleshooting

### Common Issues

#### Issue: `ModuleNotFoundError: No module named 'claude_vis'`

**Solution:**
```bash
# Make sure you're in the project root
cd claude-code-sessin-vis

# Reinstall dependencies
uv sync --dev

# Activate virtual environment
source .venv/bin/activate  # macOS/Linux
.venv\Scripts\activate     # Windows
```

#### Issue: `Session path does not exist`

**Solution:**
```bash
# Check if the default path exists
ls ~/.claude/projects/

# Or specify a custom path
claude-vis serve --path /path/to/your/sessions
```

#### Issue: `Port already in use`

**Solution:**
```bash
# Use a different port
claude-vis serve --port 8080

# Or kill the process using the port (Linux/macOS)
lsof -ti:8000 | xargs kill -9

# Or kill the process using the port (Windows)
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

#### Issue: Frontend build fails

**Solution:**
```bash
cd frontend

# Clean node_modules and reinstall
rm -rf node_modules package-lock.json
npm install

# Try building again
npm run build
```

#### Issue: API returns 503 Service Unavailable

**Cause:** Service not properly initialized or session path is invalid.

**Solution:**
1. Check server logs for initialization errors
2. Verify session path exists and is readable
3. Restart the server with `--reload` flag

#### Issue: CORS errors in browser

**Solution:**
```bash
# For development, start both servers:
# Terminal 1
claude-vis serve --reload

# Terminal 2
cd frontend && npm run dev

# Access via the frontend dev server URL (usually http://localhost:5173)
```

#### Issue: E2E tests fail

**Solution:**
```bash
cd frontend

# Install/update Playwright browsers
npx playwright install

# Run tests in debug mode
npm run test:e2e:debug
```

### Debug Mode

Enable verbose logging:

```bash
# Backend
claude-vis serve --log-level debug --reload

# Frontend (check browser console)
# Open DevTools (F12) and check Console and Network tabs
```

### Getting Help

1. **Check logs**: Review server output and browser console
2. **Verify installation**: Run `uv sync --dev` and `npm install`
3. **Check version**: Ensure Python 3.10+ and Node 18+
4. **Review API docs**: Visit `http://localhost:8000/docs`
5. **GitHub Issues**: Report bugs at [repository issues page]

## 🤝 Contributing

We welcome contributions! Please follow these guidelines:

### Getting Started

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and linting
5. Commit your changes (`git commit -m 'feat: add amazing feature'`)
6. Push to your branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

### Commit Message Convention

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
feat: add new feature
fix: fix bug in parser
docs: update README
style: format code with black
refactor: restructure API service
test: add tests for statistics
chore: update dependencies
```

### Code Style

- **Python**: Follow PEP 8, use Black for formatting (100 char line length)
- **TypeScript**: Follow provided ESLint config, use Prettier
- **Commits**: Use conventional commits format
- **Tests**: Add tests for new features

### Pull Request Process

1. Ensure all tests pass (`pytest` and `npm run test:e2e`)
2. Update documentation if needed
3. Add tests for new functionality
4. Follow the code style guidelines
5. Provide a clear description of changes
6. Link related issues

### Development Setup

See the [Development](#development) section for detailed setup instructions.

### Reporting Bugs

Open an issue with:
- Clear description of the problem
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Python version, etc.)
- Relevant logs or screenshots

### Feature Requests

Open an issue with:
- Clear description of the feature
- Use case and benefits
- Proposed implementation (if any)

## 📄 License

This project is licensed under the MIT License.

```
MIT License

Copyright (c) 2024 Claude Code Session Visualizer Team

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

See [LICENSE](LICENSE) file for full details.

---

## 📞 Support

- **Documentation**: This README and `/docs` endpoint
- **Issues**: [GitHub Issues](https://github.com/yourusername/claude-code-sessin-vis/issues)
- **API Docs**: `http://localhost:8000/docs`

---

**Made with ❤️ by the Claude Code Session Visualizer Team**
