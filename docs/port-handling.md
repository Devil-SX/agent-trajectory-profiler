# Port Handling Guide

## Overview

Both backend and frontend servers now gracefully handle port conflicts instead of crashing.

---

## Backend Server (FastAPI)

### Behavior

**Default Port**: 8000

**When port 8000 is occupied**:
- ✅ Automatically tries ports 8001, 8002, ..., 8009
- ✅ Prints warning message with new port
- ✅ Server starts successfully on alternative port

**When custom port is specified**:
```bash
claude-vis serve --port 8080
```
- ❌ Fails with clear error if port 8080 is occupied
- ✅ Does NOT auto-switch (user made explicit choice)

### Examples

**Scenario 1: Default port occupied**
```bash
$ claude-vis serve --reload
Warning: Default port 8000 is already in use.
Using alternative port: 8001

============================================================
Claude Code Session Visualizer
============================================================
Server URL:   http://0.0.0.0:8001
API Docs:     http://0.0.0.0:8001/docs
Reload Mode:  Enabled
============================================================
```

**Scenario 2: Custom port occupied**
```bash
$ claude-vis serve --port 8000
Error: Port 8000 is already in use.
Please specify a different port with --port option.
```

**Scenario 3: Custom port available**
```bash
$ claude-vis serve --port 8080
============================================================
Claude Code Session Visualizer
============================================================
Server URL:   http://0.0.0.0:8080
API Docs:     http://0.0.0.0:8080/docs
============================================================
```

---

## Frontend Server (Vite)

### Behavior

**Default Port**: 5173

**When port 5173 is occupied**:
- ✅ Automatically tries 5174, 5175, 5176, etc.
- ✅ Prints message showing actual port used
- ✅ Updates local dev server URL automatically

**Vite built-in behavior** (`strictPort: false`):
```
$ npm run dev
Port 5173 is in use, trying another one...
VITE v5.0.0  ready in 500 ms

➜  Local:   http://localhost:5174/
➜  Network: http://192.168.1.100:5174/
```

---

## Configuration

### Backend (main.py)

Port detection logic:
```python
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
```

### Frontend (vite.config.ts)

```typescript
export default defineConfig({
  server: {
    port: 5173,
    strictPort: false, // Allow auto port selection
    host: true,
  },
})
```

---

## VS Code Tasks

Updated tasks handle port conflicts automatically:

```json
{
  "label": "Start Dev Server",
  "command": "uv run claude-vis serve --reload",
  // Will auto-find available port if 8000 is taken
}
```

---

## Testing Port Handling

### Manual Test

**Terminal 1**: Start first instance
```bash
claude-vis serve --reload
# Uses port 8000
```

**Terminal 2**: Start second instance
```bash
claude-vis serve --reload
# Auto-switches to port 8001
```

**Terminal 3**: Try custom port
```bash
claude-vis serve --port 8000
# Fails with clear error message
```

### Automated Test

```python
import socket

def test_port_conflict():
    # Occupy port 8000
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('127.0.0.1', 8000))
    server.listen(1)

    # Try to start claude-vis serve (should use 8001)
    # ...

    server.close()
```

---

## Troubleshooting

### Problem: "Could not find an available port"

**Cause**: Ports 8000-8009 all occupied

**Solution**:
```bash
# Check what's using ports
lsof -i :8000-8009

# Kill processes if needed
kill -9 <PID>

# Or use a custom port range
claude-vis serve --port 9000
```

### Problem: Frontend shows wrong backend URL

**Cause**: Backend auto-switched to different port

**Solution**:
1. Check backend startup message for actual port
2. Update frontend `.env` if needed:
   ```bash
   echo "VITE_API_BASE_URL=http://localhost:8001" > frontend/.env.local
   ```
3. Restart frontend dev server

### Problem: Want to force specific ports

**Solution**: Use explicit port flags
```bash
# Backend on specific port (fails if taken)
claude-vis serve --port 8080

# Frontend on specific port (fails if taken)
cd frontend && npm run dev -- --port 5000 --strictPort
```

---

## Best Practices

1. **Development**: Let auto-detection work (don't specify --port)
2. **Production**: Use explicit ports with monitoring
3. **CI/CD**: Use specific ports to avoid conflicts
4. **Multiple instances**: First instance gets default, others auto-adjust

---

## Implementation Details

### Changes Made

**Files Modified**:
- `claude_vis/cli/main.py` - Added port detection logic
- `frontend/vite.config.ts` - Enabled automatic port selection
- `CLAUDE.md` - Updated documentation
- `docs/port-handling.md` - This guide

**Functions Added**:
- `is_port_in_use()` - Check if port is occupied
- `find_available_port()` - Find next available port

**Behavior**:
- Default ports try auto-fallback (8001, 8002, ...)
- Custom ports fail fast with clear error
- Maximum 10 port attempts before giving up

---

## Future Enhancements

Potential improvements:
- [ ] Add `--auto-port` flag to always find free port
- [ ] Save preferred port to config file
- [ ] Show all running instances with `claude-vis list`
- [ ] Auto-detect and connect frontend to backend port
- [ ] Support port ranges: `--port-range 8000-8100`
