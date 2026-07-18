# KeirstinLink Python Backend

Lightweight FastAPI backend for KeirstinLink file sync / device coordination.

## Endpoints

- `GET /health` — service health
- `GET /files` — index of tracked files
- `POST /pull` — download a file by URI / id
- `POST /propose` — propose a change to a file
- `POST /approve` — approve a pending change
- `POST /reject` — reject a pending change
- `GET /versions/{file_id}` — version snapshots (last 3 kept)
- `GET /devices` — registered LAN devices

## Run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m keirstin_link.main
```

## Discovery

- UDP broadcast listener on port `37100`
- Optional mDNS advertisement on `_keirstinlink._tcp.local.`
