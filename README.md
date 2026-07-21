# KeirstinLink

A lightweight, LAN-first file sync and transfer tool for Android, Windows, and Linux.

## What it is

- **LAN-first sync**: Devices discover each other on the local network and transfer files directly.
- **Master/slave safety model**: One master device is the source of truth. Clients pull automatically but can only *propose* changes; the master must approve them.
- **Version snapshots**: Master keeps the last N versions of files for rollback.
- **Cross-platform UI**: Tauri v2 shell with a Python FastAPI backend.

## Repository layout

```
KeirstinLink/
├── README.md                 # This file
├── DESIGN.md                 # Architecture and safety rules
├── .env.example              # Environment variables
├── start.bat                 # Windows quick start (launches backend)
├── start-backend.bat         # Windows backend launcher
├── start.sh                  # POSIX backend launcher
├── src/                      # Tauri frontend (HTML/JS/CSS)
├── src-tauri/                # Tauri Rust shell
└── src-python/               # FastAPI backend
    └── keirstin_link/
        ├── main.py           # Uvicorn entry point
        ├── api.py            # REST endpoints
        ├── config.py         # Settings
        ├── discovery.py      # UDP + mDNS discovery
        ├── models.py         # Pydantic models
        └── store.py          # JSON file stores
```

## Quick start

### 1. Configure

```bash
cp .env.example .env
# Edit .env if you want to change port or data directory.
```

### 2. Install Python dependencies

```bash
cd src-python
pip install -r requirements.txt
```

### 3. Start the backend

**Windows:**
```bat
cd KeirstinLink
start.bat
```

**POSIX / git-bash:**
```bash
./start.sh
```

### 4. Start the Tauri UI (development)

```bash
npm install
cd src-tauri
cargo tauri dev
```

## Current status

The backend runs and exposes a working REST API. The frontend shell renders the device list and pending approvals. The Rust shell now auto-starts the Python backend in development.

**Still to implement:**
- Real folder/file sync engine (delta by hash/mtime, pull from master, propose changes).
- Android client.
- Remote Hermes bridge mode (deferred until sync is solid).

## Design and safety

See [DESIGN.md](DESIGN.md).

## License

MIT (placeholder — update when the project matures).
