"""Configuration for KeirstinLink backend."""

import json
import os
from pathlib import Path

HOST = os.getenv("KL_HOST", "0.0.0.0")
PORT = int(os.getenv("KL_PORT", "3710"))
DATA_DIR = Path(os.getenv("KL_DATA_DIR", str(Path(__file__).resolve().parent.parent / "data")))
MAX_VERSIONS = int(os.getenv("KL_MAX_VERSIONS", "3"))
UDP_DISCOVERY_PORT = int(os.getenv("KL_UDP_PORT", "37100"))
MDNS_SERVICE_NAME = os.getenv("KL_MDNS_NAME", "KeirstinLink")
MDNS_SERVICE_TYPE = "_keirstinlink._tcp.local."

DATA_DIR.mkdir(parents=True, exist_ok=True)

FILES_INDEX = DATA_DIR / "files_index.json"
PENDING_DIR = DATA_DIR / "pending"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
DEVICE_REGISTRY = DATA_DIR / "devices.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
TOKEN_FILE = DATA_DIR / "device_token.json"

PENDING_DIR.mkdir(parents=True, exist_ok=True)
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def load_or_create_device_token() -> str:
    if TOKEN_FILE.exists():
        try:
            data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            token = data.get("token", "")
            if token:
                return token
        except (json.JSONDecodeError, OSError):
            pass
    import secrets
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(json.dumps({"token": token}), encoding="utf-8")
    return token


DEVICE_TOKEN = os.getenv("KL_DEVICE_TOKEN") or load_or_create_device_token()

DEFAULT_SYNC_FOLDER = str(Path.home() / "KeirstinLinkSync")
