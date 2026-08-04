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

# Static web UI directory. Resolution order:
# 1. Explicit KL_STATIC_DIR env var.
# 2. PyInstaller onefile extraction dir (sys._MEIPASS) where src/ is bundled.
# 3. Installed dir next to the frozen .exe (e.g. C:\Program Files\KeirstinLink).
# 4. Dev repo layout: repo/src/.
def _resolve_static_dir() -> Path:
    if os.getenv("KL_STATIC_DIR"):
        return Path(os.getenv("KL_STATIC_DIR"))

    if getattr(sys, "frozen", False):
        # PyInstaller onefile: _MEIPASS is the temp extraction dir.
        meipass = Path(getattr(sys, "_MEIPASS", ""))
        if meipass and (meipass / "src" / "index.html").exists():
            return meipass / "src"
        # onefile companion dir (fallback): installed dir containing the .exe
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "src" / "index.html").exists():
            return exe_dir / "src"

    # Dev layout: this file is under src-python/keirstin_link/, repo root is two parents up.
    return Path(__file__).resolve().parents[2] / "src"

STATIC_DIR = _resolve_static_dir()


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
