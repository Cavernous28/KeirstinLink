"""FastAPI HTTP server."""

import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from .config import DATA_DIR, MAX_VERSIONS, PORT
from .models import ChangeStatus, FileEntry, ProposedChange
from .store import DeviceStore, FileStore, PendingStore, SnapshotStore

app = FastAPI(title="KeirstinLink", version="0.1.0")


def _now() -> datetime:
    return datetime.now(timezone.utc)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "KeirstinLink", "port": PORT}


@app.get("/files")
def list_files() -> list[dict[str, Any]]:
    return [f.model_dump() for f in FileStore.list_files()]


@app.post("/files/register")
def register_file(
    id: str = Form(...),
    name: str = Form(...),
    path: str = Form(...),
    size: int = Form(0),
    tags: str = Form(""),
) -> dict[str, Any]:
    entry = FileEntry(
        id=id,
        name=name,
        path=path,
        size=size,
        modified=_now(),
        tags=[t.strip() for t in tags.split(",") if t.strip()],
    )
    FileStore.upsert_file(entry)
    return entry.model_dump()


@app.post("/pull")
def pull_file(uri: str = Form(...), file_id: str = Form(...)) -> dict[str, Any]:
    """Skeleton pull: expects a local path URI for demo."""
    source = Path(uri)
    if not source.exists():
        raise HTTPException(status_code=404, detail="Source not found")

    dest_dir = DATA_DIR / "files"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / (file_id or source.name)
    shutil.copy2(source, dest)

    entry = FileEntry(
        id=file_id or str(uuid4()),
        name=source.name,
        path=str(dest),
        size=dest.stat().st_size,
        modified=_now(),
    )
    FileStore.upsert_file(entry)
    SnapshotStore.create(entry.id, source_path=dest, note="pulled")
    return {"file": entry.model_dump(), "snapshot_count": len(SnapshotStore.list_for_file(entry.id))}


@app.post("/propose")
def propose_change(
    file_id: str = Form(...),
    payload: str = Form("{}"),
    source_device: str = Form(""),
    upload: UploadFile = File(None),
) -> dict[str, Any]:
    file_entry = FileStore.get_file(file_id)
    if not file_entry:
        raise HTTPException(status_code=404, detail="File not registered")

    change_id = str(uuid4())
    data = {"raw_payload": json.loads(payload), "uploaded_filename": None}
    if upload:
        change_dir = DATA_DIR / "pending_files" / change_id
        change_dir.mkdir(parents=True, exist_ok=True)
        dest = change_dir / (upload.filename or "upload")
        with dest.open("wb") as f:
            shutil.copyfileobj(upload.file, f)
        data["uploaded_filename"] = str(dest)

    change = ProposedChange(
        id=change_id,
        file_id=file_id,
        source_device=source_device or None,
        payload=data,
    )
    PendingStore.save_change(change)
    return change.model_dump()


@app.post("/approve")
def approve_change(change_id: str = Form(...)) -> dict[str, Any]:
    change = PendingStore.set_status(change_id, ChangeStatus.APPROVED)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")

    file_entry = FileStore.get_file(change.file_id)
    source = None
    if file_entry:
        source = Path(file_entry.path) if Path(file_entry.path).exists() else None
    if change.payload.get("uploaded_filename"):
        upload_path = Path(change.payload["uploaded_filename"])
        if upload_path.exists():
            source = upload_path
    if source and source.exists():
        SnapshotStore.create(change.file_id, source_path=source, note=f"approved {change_id}")
    return change.model_dump()


@app.post("/reject")
def reject_change(change_id: str = Form(...)) -> dict[str, Any]:
    change = PendingStore.set_status(change_id, ChangeStatus.REJECTED)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change.model_dump()


@app.get("/pending")
def list_pending() -> list[dict[str, Any]]:
    return [c.model_dump() for c in PendingStore.list_changes(status=ChangeStatus.PENDING)]


@app.get("/versions/{file_id}")
def list_versions(file_id: str) -> dict[str, Any]:
    return {"file_id": file_id, "versions": [v.model_dump() for v in SnapshotStore.list_for_file(file_id)]}


@app.get("/versions/{file_id}/download/{snapshot_id}")
def download_version(file_id: str, snapshot_id: str) -> FileResponse:
    snap_dir = SnapshotStore._snapshot_dir(file_id)
    candidates = list(snap_dir.glob(f"{snapshot_id}-*"))
    if not candidates:
        raise HTTPException(status_code=404, detail="Snapshot file not found")
    return FileResponse(candidates[0], media_type="application/octet-stream")


@app.get("/devices")
def list_devices() -> list[dict[str, Any]]:
    return [d.model_dump() for d in DeviceStore.list_devices()]


@app.delete("/devices/{device_id}")
def delete_device(device_id: str) -> JSONResponse:
    DeviceStore.remove_device(device_id)
    return JSONResponse(content={"deleted": device_id})
