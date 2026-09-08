#!/usr/bin/env bash
set -e

# Determine script and project directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Detect Python executable (.venv preferred)
if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo "Error: Python 3 is required but was not found." >&2
    exit 1
fi

# Ensure static frontend assets exist
STATIC_INDEX="$SCRIPT_DIR/agy_cockpit/backend/static/index.html"
if [ ! -f "$STATIC_INDEX" ]; then
    echo "Static frontend assets not found. Building frontend..."
    if command -v npm &>/dev/null; then
        (cd "$SCRIPT_DIR/agy_cockpit/frontend" && npm run build)
    else
        echo "Warning: npm not found. Frontend static assets may be missing." >&2
    fi
fi

# Set default workspace if not provided in arguments
HAS_WORKSPACE=false
for arg in "$@"; do
    if [[ "$arg" == "-w" || "$arg" == "--workspace" || "$arg" == --workspace=* ]]; then
        HAS_WORKSPACE=true
        break
    fi
done

ARGS=()
if [ "$HAS_WORKSPACE" = false ]; then
    DEFAULT_WS="${WORKSPACE:-$SCRIPT_DIR}"
    ARGS+=("--workspace" "$DEFAULT_WS")
fi

# Support PORT and HOST environment variables if not passed in flags
HAS_PORT=false
HAS_HOST=false
for arg in "$@"; do
    if [[ "$arg" == "-p" || "$arg" == "--port" || "$arg" == --port=* ]]; then
        HAS_PORT=true
    fi
    if [[ "$arg" == "--host" || "$arg" == --host=* ]]; then
        HAS_HOST=true
    fi
done

if [ "$HAS_PORT" = false ] && [ -n "$PORT" ]; then
    ARGS+=("--port" "$PORT")
fi

if [ "$HAS_HOST" = false ] && [ -n "$HOST" ]; then
    ARGS+=("--host" "$HOST")
fi

if [ -n "$TOKEN" ]; then
    ARGS+=("--token" "$TOKEN")
fi

# Run the Cockpit CLI with configured arguments
exec "$PYTHON" -m agy_cockpit.cli "${ARGS[@]}" "$@"
