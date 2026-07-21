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

PENDING_DIR.mkdir(parents=True, exist_ok=True)
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SYNC_FOLDER = str(Path.home() / "KeirstinLinkSync")
