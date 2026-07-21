"""Stub slave worker for KeirstinLink.

This is intentionally minimal: it parses a task payload, simulates execution,
and posts a result back to the master callback URL.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

from .config import get_config


def run_task(task: dict) -> dict:
    """Placeholder task runner. Real implementation will invoke Hermes or local tools."""
    return {
        "task_id": task.get("task_id"),
        "status": "success",
        "summary": "Stub slave execution completed.",
        "artifacts": [],
        "logs": "noop",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="KeirstinLink slave worker")
    parser.add_argument("--task", required=True, help="Task JSON string or path to JSON file")
    parser.add_argument("--callback-url", required=True, help="Master callback URL")
    args = parser.parse_args()

    cfg = get_config()

    raw = args.task
    if Path(raw).exists():
        task = json.loads(Path(raw).read_text())
    else:
        task = json.loads(raw)

    print(f"[slave] Running task {task.get('task_id')}")
    result = run_task(task)

    response = httpx.post(args.callback_url, json=result, timeout=30.0)
    print(f"[slave] Callback response: {response.status_code} {response.text}")


if __name__ == "__main__":
    main()
