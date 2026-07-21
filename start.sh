#!/usr/bin/env bash
# KeirstinLink POSIX backend launcher
# Usage: ./start.sh

set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
    echo "[KeirstinLink] .env not found. Copy .env.example to .env and fill it in."
    exit 1
fi

# shellcheck source=/dev/null
source .env

echo "[KeirstinLink] Starting backend on ${KL_HOST}:${KL_PORT}"
cd src-python
python -m keirstin_link.main --host "${KL_HOST}" --port "${KL_PORT}"
