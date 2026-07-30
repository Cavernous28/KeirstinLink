"""Configuration for KeirstinLink backend."""

import json
import os
import socket
import sys
from pathlib import Path

HOST = os.getenv("KL_HOST", "0.0.0.0")
PORT = int(os.getenv("KL_PORT", "3710"))

# Production data directory: per-user local app data, not relative to source tree.
default_data_dir = Path.home() / "AppData" / "Local" / "KeirstinLink" / "data"
if sys.platform != "win32":
    default_data_dir = Path.home() / ".local" / "share" / "KeirstinLink" / "data"

DATA_DIR = Path(os.getenv("KL_DATA_DIR", str(default_data_dir)))
MAX_VERSIONS = int(os.getenv("KL_MAX_VERSIONS", "3"))
UDP_DISCOVERY_PORT = int(os.getenv("KL_UDP_PORT", "37100"))
UDP_BUFFER = int(os.getenv("KL_UDP_BUFFER", "8192"))
MDNS_SERVICE_NAME = os.getenv("KL_MDNS_NAME", "KeirstinLink")
MDNS_SERVICE_TYPE = "_keirstinlink._tcp.local."

DATA_DIR.mkdir(parents=True, exist_ok=True)

FILES_INDEX = DATA_DIR / "files_index.json"
PENDING_DIR = DATA_DIR / "pending"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
DEVICE_REGISTRY = DATA_DIR / "devices.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
TOKEN_FILE = DATA_DIR / "device_token.json"
INSTALL_ID_FILE = DATA_DIR / "install_id.json"
PID_FILE = DATA_DIR / "keirstinlink.pid"

PENDING_DIR.mkdir(parents=True, exist_ok=True)
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

# Static web UI directory. In a packaged install this is next to src-python; in dev it's the repo src/.
REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(os.getenv("KL_STATIC_DIR", str(REPO_ROOT / "src")))


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


def load_or_create_install_id() -> str:
    if INSTALL_ID_FILE.exists():
        try:
            data = json.loads(INSTALL_ID_FILE.read_text(encoding="utf-8"))
            install_id = data.get("install_id", "")
            if install_id:
                return install_id
        except (json.JSONDecodeError, OSError):
            pass
    import secrets
    install_id = secrets.token_urlsafe(16)
    INSTALL_ID_FILE.write_text(json.dumps({"install_id": install_id}), encoding="utf-8")
    return install_id


DEVICE_TOKEN = os.getenv("KL_DEVICE_TOKEN") or load_or_create_device_token()
INSTALL_ID = load_or_create_install_id()

DEFAULT_SYNC_FOLDER = str(Path.home() / "KeirstinLinkSync")
