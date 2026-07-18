"""Stub master bridge server for KeirstinLink.

This is intentionally minimal: it exposes a /callback endpoint and a health check.
The real orchestration logic will live here in later iterations.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from fastapi import FastAPI, Request
import uvicorn

from .config import get_config, master_url

app = FastAPI(title="KeirstinLink Master Bridge")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "mode": "master"}


@app.post("/callback")
async def callback(request: Request) -> dict:
    payload = await request.json()
    # TODO: validate PSK, persist result, notify master Hermes instance.
    print("[master] received callback:", json.dumps(payload, indent=2))
    return {"received": True, "task_id": payload.get("task_id")}


def main() -> None:
    parser = argparse.ArgumentParser(description="KeirstinLink master bridge")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=7788)
    args = parser.parse_args()

    cfg = get_config()
    url = master_url(cfg)
    print(f"[master] KeirstinLink master bridge starting at {url}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
