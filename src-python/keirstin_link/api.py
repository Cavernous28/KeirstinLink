"""FastAPI HTTP server."""

import hashlib
import json
import os
import shutil
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .config import DATA_DIR, MAX_VERSIONS, PORT
from .folder_index import index_sync_folder, rebuild_files_index
from .models import ChangeStatus, DeviceInfo, FileEntry, ProposedChange, SyncRoot
from .settings_store import Settings, SettingsStore
from .store import DeviceStore, FileStore, PendingStore, SnapshotStore

app = FastAPI(title="KeirstinLink", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "KeirstinLink", "port": PORT}


@app.get("/state")
def get_state() -> dict[str, Any]:
    """Return the current UI state: devices, pending approvals, registered files, settings."""
    settings = SettingsStore.load()
    return {
        "devices": [d.model_dump() for d in DeviceStore.list_devices()],
        "pending": [c.model_dump() for c in PendingStore.list_changes(status=ChangeStatus.PENDING)],
        "files": [f.model_dump() for f in FileStore.list_files()],
        "settings": settings.model_dump(),
    }


@app.get("/settings")
def get_settings() -> dict[str, Any]:
    return SettingsStore.load().model_dump()


@app.post("/settings")
def save_settings(
    device_name: str = Form(""),
    mode: str = Form("master"),
    sync_folder: str = Form(""),
    master_sync_folder: str = Form(""),
) -> dict[str, Any]:
    settings = SettingsStore.load()
    if device_name:
        settings.device_name = device_name
    if mode in ("master", "client"):
        settings.mode = mode
    if sync_folder:
        settings.sync_folder = sync_folder
        Path(sync_folder).mkdir(parents=True, exist_ok=True)
    if master_sync_folder:
        settings.master_sync_folder = master_sync_folder
        Path(master_sync_folder).mkdir(parents=True, exist_ok=True)
    SettingsStore.save(settings)
    return settings.model_dump()


def _hash_file(path: Path, block_size: int = 65536) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block_size):
            hasher.update(chunk)
    return hasher.hexdigest()


@app.get("/folder-index")
def folder_index() -> list[dict[str, Any]]:
    """Return the current contents of the sync folder with hashes."""
    return [e.model_dump() for e in index_sync_folder()]


@app.post("/scan-local")
async def scan_local(
    device_id: str = Form(...),
    remote_index_json: str = Form(""),
) -> dict[str, Any]:
    """Client: compare local sync folder against a remote master index and return a changeset to propose.

    If `remote_index_json` is provided, use it directly instead of fetching from the device.
    Only considers files under the device's configured `shared_folders`.
    """
    device = next((d for d in DeviceStore.list_devices() if d.id == device_id), None)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if remote_index_json:
        try:
            remote_index = json.loads(remote_index_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in remote_index_json")
    else:
        base_url = f"http://{device.host}:{device.port}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base_url}/folder-index")
                resp.raise_for_status()
                remote_index = resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Could not fetch folder index from {base_url}: {e}")

    remote_by_path = {e["relative_path"]: e for e in remote_index}
    default_root = SettingsStore.sync_folder_path()
    roots = _iter_sync_roots(device, default_root)
    allowed = _parse_shared_folders(device.shared_folders)
    changes = []

    for local_root, remote_prefix in roots:
        if not local_root.exists():
            continue
        for local_path in local_root.rglob("*"):
            if not local_path.is_file():
                continue
            try:
                stat = local_path.stat()
                rel_to_root = _normalize_rel_path(str(local_path.relative_to(local_root)))
                rel = _local_to_remote(rel_to_root, remote_prefix)
                # Legacy fallback filtering: if no explicit sync roots, honor shared_folders
                if not device.sync_roots and not _is_under_shared_folders(rel, allowed):
                    continue
                local_mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
                local_checksum = _hash_file(local_path)
                remote = remote_by_path.get(rel)
                if not remote:
                    changes.append({"relative_path": rel, "action": "create", "checksum": local_checksum, "size": stat.st_size, "modified": local_mtime})
                elif remote.get("checksum") != local_checksum:
                    changes.append({"relative_path": rel, "action": "update", "checksum": local_checksum, "size": stat.st_size, "modified": local_mtime})
            except (OSError, ValueError):
                continue

    return {"device_id": device_id, "changes": changes, "count": len(changes), "sync_roots": [r.model_dump() for r in device.sync_roots]}


def _parse_shared_folders(raw: list[str]) -> list[str]:
    """Normalize shared folder entries. Empty list or ['*'] means all folders."""
    cleaned = []
    for entry in raw:
        for part in entry.split(","):
            part = part.strip().replace("\\", "/").strip("/")
            if part:
                cleaned.append(part)
    if not cleaned or cleaned == ["*"]:
        return []
    return cleaned


def _is_under_shared_folders(rel_path: str, folders: list[str]) -> bool:
    """Return True if rel_path is inside one of the configured shared folders (or if no folders configured)."""
    if not folders:
        return True
    for folder in folders:
        if rel_path == folder or rel_path.startswith(folder + "/"):
            return True
    return False


def _parse_sync_roots(raw: list[dict[str, str]]) -> list[SyncRoot]:
    """Parse sync roots from JSON/dict form."""
    roots = []
    for item in raw:
        if isinstance(item, SyncRoot):
            roots.append(item)
            continue
        if not isinstance(item, dict):
            continue
        local = item.get("local_path", "").strip()
        remote = item.get("remote_prefix", "").strip().replace("\\", "/").strip("/")
        if local:
            roots.append(SyncRoot(local_path=local, remote_prefix=remote))
    return roots


def _normalize_rel_path(rel: str) -> str:
    """Normalize a relative path to forward slashes, no leading/trailing slashes."""
    return rel.replace("\\", "/").strip("/")


def _iter_sync_roots(device: DeviceInfo, default_root: Path) -> list[tuple[Path, str]]:
    """Return list of (local_root_path, remote_prefix) to scan for this device.

    If the device has sync_roots, use those. Otherwise fall back to the default sync folder
    with the remote_prefix derived from shared_folders logic (empty prefix = whole folder).
    """
    if device.sync_roots:
        return [(Path(r.local_path), _normalize_rel_path(r.remote_prefix)) for r in device.sync_roots]
    # Legacy fallback: one root at the global sync folder, no remote prefix; filter by shared_folders later
    return [(default_root, "")]


def _local_to_remote(rel_to_root: str, remote_prefix: str) -> str:
    """Combine a path relative to a local root with the remote prefix."""
    rel_to_root = _normalize_rel_path(rel_to_root)
    if remote_prefix:
        return f"{remote_prefix}/{rel_to_root}" if rel_to_root else remote_prefix
    return rel_to_root


def _find_sync_root_for_remote(remote_path: str, roots: list[tuple[Path, str]]) -> tuple[Optional[Path], str]:
    """Find the local root whose remote_prefix matches the start of remote_path.

    Returns (local_root, remainder_relative_to_local_root). If no match, returns (None, remote_path).
    """
    remote_path = _normalize_rel_path(remote_path)
    # Prefer longest prefix match
    best: tuple[Optional[Path], str] = (None, remote_path)
    best_len = -1
    for local_root, prefix in roots:
        if not prefix:
            if best_len < 0:
                best = (local_root, remote_path)
                best_len = 0
            continue
        prefix_norm = _normalize_rel_path(prefix)
        if remote_path == prefix_norm:
            return (local_root, "")
        if remote_path.startswith(prefix_norm + "/"):
            if len(prefix_norm) > best_len:
                best = (local_root, remote_path[len(prefix_norm) + 1:])
                best_len = len(prefix_norm)
    return best


@app.post("/folder-index/rebuild")
def rebuild_index() -> dict[str, Any]:
    """Rebuild the stored file index from the sync folder."""
    entries = rebuild_files_index()
    return {"count": len(entries), "files": [e.model_dump() for e in entries]}


@app.get("/files/download")
def download_file(path: str) -> StreamingResponse:
    """Download a file from the master sync folder by relative path."""
    root = SettingsStore.master_folder_path()
    target = (root / path).resolve()
    # Security: refuse to serve anything outside the sync folder.
    if not str(target).startswith(str(root.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    def iter_file():
        with target.open("rb") as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(iter_file(), media_type="application/octet-stream", headers={"Content-Disposition": f"attachment; filename=\"{target.name}\""})


@app.post("/pull")
async def pull_device(device_id: str = Form(...), remote_index_json: str = Form("")) -> dict[str, Any]:
    """Client: pull all missing or changed files from a remote master device.

    If `remote_index_json` is provided, use it directly instead of fetching from the device.
    """
    device = next((d for d in DeviceStore.list_devices() if d.id == device_id), None)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if remote_index_json:
        try:
            remote_index = json.loads(remote_index_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in remote_index_json")
    else:
        base_url = f"http://{device.host}:{device.port}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base_url}/folder-index")
                resp.raise_for_status()
                remote_index = resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Could not fetch folder index from {base_url}: {e}")

    local_default = SettingsStore.sync_folder_path()
    roots = _iter_sync_roots(device, local_default)
    pulled = []
    skipped = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for remote_entry in remote_index:
            remote_path = remote_entry["relative_path"]
            local_root, rel_to_root = _find_sync_root_for_remote(remote_path, roots)
            if local_root is None:
                continue

            local_path = (local_root / rel_to_root).resolve()
            local_path.parent.mkdir(parents=True, exist_ok=True)

            need_download = True
            if local_path.is_file():
                local_mtime = datetime.fromtimestamp(local_path.stat().st_mtime, tz=timezone.utc).isoformat()
                if local_mtime == remote_entry["modified"] and local_path.stat().st_size == remote_entry["size"]:
                    need_download = False

            if need_download:
                try:
                    safe_rel = remote_path.replace("\\", "/")
                    resp = await client.get(f"{base_url}/files/download?path={urllib.parse.quote(safe_rel)}")
                    resp.raise_for_status()
                    local_path.write_bytes(resp.content)
                    remote_mtime = datetime.fromisoformat(remote_entry["modified"])
                    os.utime(local_path, (remote_mtime.timestamp(), remote_mtime.timestamp()))
                    pulled.append(remote_path)
                except Exception as e:
                    raise HTTPException(status_code=502, detail=f"Failed to pull {remote_path}: {e}")
            else:
                skipped.append(remote_path)

    # Rebuild our local index after pull
    rebuild_files_index()
    return {"pulled": pulled, "skipped": skipped, "count": len(pulled)}


@app.post("/propose-files")
async def propose_files(
    device_id: str = Form(...),
    changes_json: str = Form(...),
) -> dict[str, Any]:
    """Client: propose a batch of local file changes to a remote master device."""
    device = next((d for d in DeviceStore.list_devices() if d.id == device_id), None)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        changes = json.loads(changes_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in changes_json")

    local_default = SettingsStore.sync_folder_path()
    roots = _iter_sync_roots(device, local_default)
    base_url = f"http://{device.host}:{device.port}"

    proposed = []
    source_device = SettingsStore.load().device_name or device.id

    async with httpx.AsyncClient(timeout=30.0) as client:
        for change in changes:
            rel_path = change.get("relative_path", "")
            action = change.get("action", "")
            if not rel_path or action not in ("create", "update"):
                continue

            local_root, rel_to_root = _find_sync_root_for_remote(rel_path, roots)
            if local_root is None:
                proposed.append({"relative_path": rel_path, "error": "No sync root covers this path"})
                continue

            local_path = (local_root / rel_to_root).resolve()
            if not local_path.is_file():
                proposed.append({"relative_path": rel_path, "error": "Local file not found"})
                continue

            change_id = str(uuid4())
            files = {
                "relative_path": (None, rel_path),
                "action": (None, action),
                "source_device": (None, source_device),
                "change_id": (None, change_id),
                "file": (local_path.name, local_path.read_bytes(), "application/octet-stream"),
            }
            try:
                resp = await client.post(f"{base_url}/receive-proposal", files=files)
                resp.raise_for_status()
                proposed.append(resp.json())
            except Exception as e:
                proposed.append({"relative_path": rel_path, "error": str(e)})

    return {"proposed": proposed, "count": len(proposed)}


@app.post("/receive-proposal")
def receive_proposal(
    relative_path: str = Form(...),
    action: str = Form(...),
    source_device: str = Form(""),
    change_id: str = Form(""),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Master: receive a single file proposal from a client and queue it for approval."""
    master_root = SettingsStore.master_folder_path()
    target_path = (master_root / relative_path).resolve()

    # Security: refuse paths outside master folder
    if not str(target_path).startswith(str(master_root.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    source_name = source_device or None
    # Dedupe: if a pending change for the same relative_path + source already exists, return it
    for existing in PendingStore.list_changes(status=ChangeStatus.PENDING):
        if existing.relative_path == relative_path and existing.source_device == source_name:
            return existing.model_dump()

    if not change_id:
        change_id = str(uuid4())

    pending_dir = DATA_DIR / "pending_files" / change_id
    pending_dir.mkdir(parents=True, exist_ok=True)
    upload_dest = pending_dir / target_path.name
    with upload_dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    file_id = f"file-{relative_path.replace('/', '-').replace(' ', '_')}"
    change = ProposedChange(
        id=change_id,
        file_id=file_id,
        source_device=source_name,
        relative_path=relative_path,
        action=action,
        payload={
            "relative_path": relative_path,
            "action": action,
            "uploaded_filename": str(upload_dest),
            "target_filename": str(target_path),
            "original_exists": target_path.exists(),
        },
    )
    PendingStore.save_change(change)

    # Mirror to registered file entry for UI consistency
    entry = FileEntry(
        id=file_id,
        name=target_path.name,
        path=str(target_path),
        size=upload_dest.stat().st_size,
        modified=_now(),
        checksum=_hash_file(upload_dest),
        tags=[relative_path],
        source_device=source_name,
    )
    FileStore.upsert_file(entry)

    return change.model_dump()


@app.post("/approve")
def approve_change(change_id: str = Form(...)) -> dict[str, Any]:
    change = PendingStore.set_status(change_id, ChangeStatus.APPROVED)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")

    _apply_approved_change(change)
    return change.model_dump()


def _apply_approved_change(change: ProposedChange) -> None:
    """Copy pending file to master target, snapshot existing file, update index."""
    payload = change.payload or {}
    target_filename = payload.get("target_filename")
    uploaded_filename = payload.get("uploaded_filename")
    relative_path = payload.get("relative_path") or change.relative_path

    if target_filename and uploaded_filename:
        target = Path(target_filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        source = Path(uploaded_filename)
        if source.exists():
            # Snapshot existing file before overwrite
            if target.exists():
                SnapshotStore.create(change.file_id, source_path=target, note=f"pre-approve {change.id}")
            shutil.copy2(source, target)
            # Update file entry
            entry = FileEntry(
                id=change.file_id,
                name=target.name,
                path=str(target),
                size=target.stat().st_size,
                modified=_now(),
                checksum=_hash_file(target),
                tags=[relative_path] if relative_path else [],
                source_device=change.source_device,
            )
            FileStore.upsert_file(entry)


@app.post("/approve-all")
def approve_all_changes() -> dict[str, Any]:
    """Approve every currently pending change."""
    pending = PendingStore.list_changes(status=ChangeStatus.PENDING)
    approved = []
    failed = []
    for change in pending:
        try:
            updated = PendingStore.set_status(change.id, ChangeStatus.APPROVED)
            if updated:
                _apply_approved_change(updated)
                approved.append(change.id)
        except Exception as e:
            failed.append({"id": change.id, "error": str(e)})
    return {"approved": approved, "failed": failed, "count": len(approved)}


@app.post("/reject")
def reject_change(change_id: str = Form(...)) -> dict[str, Any]:
    change = PendingStore.set_status(change_id, ChangeStatus.REJECTED)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")

    payload = change.payload or {}
    uploaded_filename = payload.get("uploaded_filename")
    if uploaded_filename:
        upload_path = Path(uploaded_filename)
        if upload_path.exists():
            upload_path.unlink()
        pending_dir = DATA_DIR / "pending_files" / change_id
        if pending_dir.exists():
            shutil.rmtree(pending_dir)

    PendingStore.remove_change(change_id)
    return change.model_dump()


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


@app.post("/devices")
def register_device(
    id: str = Form(...),
    name: str = Form(...),
    host: str = Form("127.0.0.1"),
    port: int = Form(3710),
    capabilities: str = Form(""),
    shared_folders: str = Form(""),
    sync_roots_json: str = Form(""),
) -> dict[str, Any]:
    roots = []
    if sync_roots_json:
        try:
            roots = _parse_sync_roots(json.loads(sync_roots_json))
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in sync_roots_json")
    device = DeviceInfo(
        id=id,
        name=name,
        host=host,
        port=port,
        capabilities=[c.strip() for c in capabilities.split(",") if c.strip()],
        shared_folders=[f.strip().replace("\\", "/").strip("/") for f in shared_folders.split(",") if f.strip()],
        sync_roots=roots,
    )
    DeviceStore.upsert_device(device)
    return device.model_dump()


@app.put("/devices/{device_id}")
def update_device(
    device_id: str,
    name: str = Form(""),
    host: str = Form(""),
    port: int = Form(0),
    capabilities: str = Form(""),
    shared_folders: str = Form(""),
    sync_roots_json: str = Form(""),
) -> dict[str, Any]:
    device = next((d for d in DeviceStore.list_devices() if d.id == device_id), None)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if name:
        device.name = name
    if host:
        device.host = host
    if port > 0:
        device.port = port
    if capabilities:
        device.capabilities = [c.strip() for c in capabilities.split(",") if c.strip()]
    if shared_folders:
        device.shared_folders = [f.strip().replace("\\", "/").strip("/") for f in shared_folders.split(",") if f.strip()]
    if sync_roots_json:
        try:
            device.sync_roots = _parse_sync_roots(json.loads(sync_roots_json))
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in sync_roots_json")
    DeviceStore.upsert_device(device)
    return device.model_dump()


@app.delete("/devices/{device_id}")
def delete_device(device_id: str) -> JSONResponse:
    DeviceStore.remove_device(device_id)
    return JSONResponse(content={"deleted": device_id})
