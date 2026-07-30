#!/bin/bash
# One-click launcher for KeirstinLink on Linux
# Starts the Python backend if not running, then opens the web UI in the default browser.

set -e

REPO_DIR="${KEIRSTINLINK_DIR:-$HOME/KeirstinLink}"
VENV_DIR="$REPO_DIR/src-python/.venv"
DATA_DIR="$HOME/.local/share/KeirstinLink"
HOST="127.0.0.1"
PORT="3710"
URL="http://${HOST}:${PORT}"

mkdir -p "$DATA_DIR"

# Check if backend is already responding
if curl -fs "$URL/health" > /dev/null 2>&1; then
    echo "KeirstinLink backend already running at $URL"
else
    echo "Starting KeirstinLink backend..."
    cd "$REPO_DIR/src-python"

    # Create venv and install deps if missing
    if [ ! -d "$VENV_DIR" ]; then
        echo "Creating Python virtual environment..."
        python3 -m venv "$VENV_DIR"
        "$VENV_DIR/bin/pip" install --upgrade pip
        "$VENV_DIR/bin/pip" install -r requirements.txt
    fi

    nohup "$VENV_DIR/bin/python3" -m keirstin_link.main --host "$HOST" --port "$PORT" > "$DATA_DIR/backend.log" 2>&1 &

    # Wait for backend to come up
    for i in {1..30}; do
        if curl -fs "$URL/health" > /dev/null 2>&1; then
            echo "Backend ready."
            break
        fi
        sleep 0.5
    done
fi

# Open browser
echo "Opening KeirstinLink in browser: $URL"
if command -v xdg-open &> /dev/null; then
    xdg-open "$URL"
elif command -v kde-open &> /dev/null; then
    kde-open "$URL"
else
    echo "No browser opener found. Open this URL manually: $URL"
fi
