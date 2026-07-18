#!/usr/bin/env bash
# KeirstinLink POSIX launcher
# Usage: ./start.sh [master|slave <task>]

set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
    echo "[KeirstinLink] .env not found. Copy .env.example to .env and fill it in."
    exit 1
fi

# shellcheck source=/dev/null
source .env

MODE=${1:-master}

if [[ "$MODE" == "master" ]]; then
    echo "[KeirstinLink] Starting master bridge on ${KL_MASTER_HOST}:${KL_MASTER_PORT}"
    python -m src.master --host "${KL_MASTER_HOST}" --port "${KL_MASTER_PORT}"
elif [[ "$MODE" == "slave" ]]; then
    TASK=${2:-}
    if [[ -z "$TASK" ]]; then
        echo "[KeirstinLink] Usage: ./start.sh slave <task_json_or_task_id>"
        exit 1
    fi
    echo "[KeirstinLink] Starting slave with task: $TASK"
    python -m src.slave --task "$TASK" --callback-url "http://${KL_MASTER_HOST}:${KL_MASTER_PORT}/callback"
else
    echo "[KeirstinLink] Unknown mode: $MODE. Use 'master' or 'slave'."
    exit 1
fi
