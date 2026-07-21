"""Shared configuration helpers for KeirstinLink."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]


def _find_env_file() -> Path | None:
    """Locate the nearest .env file relative to this file."""
    here = Path(__file__).resolve().parent.parent
    candidates = [here / ".env", Path.cwd() / ".env"]
    for cand in candidates:
        if cand.exists():
            return cand
    return None


def load_env() -> None:
    """Load environment variables from .env if python-dotenv is available."""
    if load_dotenv is None:
        return
    env_file = _find_env_file()
    if env_file:
        load_dotenv(env_file)


def get_config() -> dict[str, str]:
    """Return a safe subset of KeirstinLink configuration values."""
    load_env()
    return {
        "master_host": os.getenv("KL_MASTER_HOST", "localhost"),
        "master_port": os.getenv("KL_MASTER_PORT", "7788"),
        "bridge_psk": os.getenv("KL_BRIDGE_PSK", ""),
        "hermes_bin": os.getenv("HERMES_BIN", "hermes"),
    }


def master_url(config: dict[str, str] | None = None) -> str:
    """Build the default master bridge URL."""
    cfg = config or get_config()
    return f"http://{cfg['master_host']}:{cfg['master_port']}"
