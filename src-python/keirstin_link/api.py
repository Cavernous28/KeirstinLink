"""FastAPI HTTP server."""

import hmac
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
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import DATA_DIR, DEVICE_TOKEN, MAX_VERSIONS, PORT, STATIC_DIR

# Cache-busting headers for static UI files so updates take effect immediately.
STATIC_HEADERS = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}

from .discovery import DiscoveryService, get_discovered_peers
from .folder_index import (
    DEFAULT_IGNORE_PATTERNS,
    _is_ignored,
    index_sync_folder,
    master_index_roots,
    rebuild_files_index,
)

from .settings_store import Settings, SettingsStore
from .store import DeviceStore, FileStore, PendingStore, SnapshotStore

from .models import ChangeStatus, DeviceInfo, FileEntry, ProposedChange, SyncRoot

# Shared discovery service instance, managed by main.py. Settings reloads can restart it.
_discovery_service: DiscoveryService | None = None


def _static_response(path: str) -> FileResponse:
    return FileResponse(str(path), headers=STATIC_HEADERS)


def _serve_index() -> Response:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace('href="styles.css"', 'href="styles.css?v=3"')
    html = html.replace('src="main.js"', 'src="main.js?v=3"')
    return Response(content=html, media_type="text/html", headers=STATIC_HEADERS)


def set_discovery_service(service: DiscoveryService | None) -> None:
    global _discovery_service
    _discovery_service = service


def restart_discovery() -> dict[str, Any]:
    """Restart the discovery service with current settings.

    Called after settings change so the advertised device name stays in sync.
    """
    global _discovery_service
    if _discovery_service is None:
        return {"restarted": False, "reason": "discovery service not running"}
    _discovery_service.stop()
    _discovery_service = DiscoveryService(port=PORT)
    _discovery_service.start()
    return {"restarted": True, "device_name": SettingsStore.load().device_name, "port": PORT}

app = FastAPI(title="KeirstinLink", version="0.1.0")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the web UI static files from the repo src/ directory.
# Explicit routes keep API endpoints reachable; root-relative paths in index.html match these.
app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")


@app.get("/styles.css")
def styles_css() -> FileResponse:
    return _static_response(str(STATIC_DIR / "styles.css"))


@app.get("/main.js")
def main_js() -> FileResponse:
    return _static_response(str(STATIC_DIR / "main.js"))


@app.get("/")
@app.get("/index.html")
def index() -> Response:
    return _serve_index()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_device_token(device: DeviceInfo, token: str | None) -> None:
    if not device.token:
        return
    if token is None:
        raise HTTPException(status_code=401, detail="Device token required")
    # Use constant-time comparison to avoid timing leaks
    if not hmac.compare_digest(device.token, token):
        raise HTTPException(status_code=403, detail="Invalid device token")


def _require_any_device_token(token: str) -> DeviceInfo:
    """Return the paired device whose token matches. Raise 401/403 if none matches."""
    if not token:
        raise HTTPException(status_code=401, detail="Device token required")
    for d in DeviceStore.list_devices():
        if d.token and hmac.compare_digest(d.token, token):
            return d
    raise HTTPException(status_code=403, detail="Invalid device token")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "KeirstinLink", "port": PORT}


@app.post("/android-crash")
def android_crash(trace: str = Form("")) -> dict[str, Any]:
    """Receive a crash stack trace from the Android client for debugging."""
    from datetime import datetime
    log_path = DATA_DIR / "android_crashes.log"
    entry = f"[{datetime.now(timezone.utc).isoformat()}]\n{trace}\n{'='*40}\n"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(entry)
    print(f"[android-crash] logged crash to {log_path}")
    return {"status": "logged"}


@app.get("/my-token")
def my_token() -> dict[str, Any]:
    """Return this device's pairing token. Only expose on localhost / trusted networks."""
    return {"token": DEVICE_TOKEN}


@app.post("/pair")
def pair_device(
    request: Request,
    device_id: str = Form(...),
    token: str = Form(...),
    name: str = Form(""),
    host: str = Form(""),
    port: int = Form(3710),
    capabilities: str = Form(""),
) -> dict[str, Any]:
    """Pair with a remote device by storing its token.

    Called by a client toward the master: the client says "I am device_id and here is my token".
    The master stores the token and replies with its own token so the client can authenticate back.
    If the device does not yet exist on the master, it is created using the supplied metadata.
    """
    device = next((d for d in DeviceStore.list_devices() if d.id == device_id), None)
    if not device:
        # Auto-create the device record from the client's self-registration data
        caps = [c.strip() for c in capabilities.split(",") if c.strip()] or ["mobile"]
        device = DeviceInfo(
            id=device_id,
            name=name or device_id,
            host=host or (request.client.host if request.client else "127.0.0.1"),
            port=port,
            capabilities=caps,
            token=token,
            last_seen=_now(),
            sync_roots=[],
            shared_folders=["*"],
        )
    else:
        device.token = token
        device.last_seen = _now()
    if host:
        device.host = host
    if port:
        device.port = port
    if name:
        device.name = name
    if request.client and request.client.host:
        device.host = request.client.host
    DeviceStore.upsert_device(device)
    return {"master_token": DEVICE_TOKEN}


@app.get("/state")
def get_state() -> dict[str, Any]:
    """Return the current UI state: devices, pending approvals, registered files, settings."""
    settings = SettingsStore.load()
    return {
        "devices": [d.model_dump() for d in DeviceStore.list_devices()],
        "pending": [c.model_dump() for c in PendingStore.list_changes(status=ChangeStatus.PENDING)],
        "files": [f.model_dump() for f in FileStore.list_files()],
        "settings": settings.model_dump(),
        "discovered": get_discovered_peers(),
    }


@app.get("/discovered")
def list_discovered() -> dict[str, Any]:
    """Return recently discovered LAN peers."""
    return {"discovered": get_discovered_peers()}


@app.get("/settings")
def get_settings() -> dict[str, Any]:
    return SettingsStore.load().model_dump()


@app.post("/settings")
def save_settings(
    device_name: str = Form(""),
    mode: str = Form("master"),
    sync_folder: str = Form(""),
    master_sync_folder: str = Form(""),
    master_sync_roots_json: str = Form(""),
    allow_sync_deletes: str = Form(""),
    restart_discovery_flag: str = Form("true"),
) -> dict[str, Any]:
    settings = SettingsStore.load()
    name_changed = False
    if device_name:
        name_changed = settings.device_name != device_name
        settings.device_name = device_name
    if mode in ("master", "client"):
        settings.mode = mode
    if sync_folder:
        settings.sync_folder = sync_folder
        Path(sync_folder).mkdir(parents=True, exist_ok=True)
    if master_sync_folder:
        settings.master_sync_folder = master_sync_folder
        Path(master_sync_folder).mkdir(parents=True, exist_ok=True)
    if master_sync_roots_json:
        try:
            raw_roots = json.loads(master_sync_roots_json)
            settings.master_sync_roots = [SyncRoot(**r) for r in raw_roots]
        except (json.JSONDecodeError, TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid master_sync_roots_json")
    if allow_sync_deletes:
        settings.allow_sync_deletes = allow_sync_deletes.lower() in {"1", "true", "yes"}
    SettingsStore.save(settings)
    result = settings.model_dump()
    if name_changed and restart_discovery_flag.lower() not in {"false", "0", "no"}:
        result["discovery"] = restart_discovery()
    return result


@app.post("/discovery/restart")
def discovery_restart() -> dict[str, Any]:
    return restart_discovery()


def _hash_file(path: Path, block_size: int = 65536) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block_size):
            hasher.update(chunk)
    return hasher.hexdigest()


@app.get("/folder-index")
def folder_index(
    device_id: str = "",
    token: str = "",
    quick: str = "",
) -> list[dict[str, Any]]:
    """Return the current contents of the sync folder with hashes.

    Use `quick=1` to skip SHA-256 hashing and return only size + mtime.
    """
    if device_id:
        device = next((d for d in DeviceStore.list_devices() if d.id == device_id), None)
        if device:
            _require_device_token(device, token or None)
    hash_files = quick not in ("1", "true", "yes")
    roots = master_index_roots()
    return [e.model_dump() for e in index_sync_folder(hash_files=hash_files, roots=roots)]


@app.post("/scan-local")
async def scan_local(
    device_id: str = Form(...),
    remote_index_json: str = Form(""),
    quick: str = Form("1"),
) -> dict[str, Any]:
    """Client: compare local sync folder against a remote master index and return a changeset to propose.

    If `remote_index_json` is provided, use it directly instead of fetching from the device.
    Detects create, update, and delete operations. Use `quick=1` (default) to skip expensive
    SHA-256 hashing when size and mtime match; set `quick=0` to force checksum verification.
    """
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id required")
    quick_mode = quick not in ("0", "false", "no")
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
            async with httpx.AsyncClient(timeout=30.0 if quick_mode else 120.0) as client:
                params = {"quick": "1" if quick_mode else "0"}
                if device.token:
                    params["device_id"] = device.id
                    params["token"] = DEVICE_TOKEN
                resp = await client.get(f"{base_url}/folder-index", params=params)
                resp.raise_for_status()
                remote_index = resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Could not fetch folder index from {base_url}: {e}")

    remote_by_path = {e["relative_path"]: e for e in remote_index}
    default_root = SettingsStore.sync_folder_path()
    roots = _iter_sync_roots(device, default_root)
    allowed = _parse_shared_folders(device.shared_folders)
    changes = []
    local_rels: set[str] = set()

    for local_root, remote_prefix in roots:
        if not local_root.exists():
            continue
        for local_path in local_root.rglob("*"):
            if not local_path.is_file():
                continue
            if _is_ignored(local_path, local_root, DEFAULT_IGNORE_PATTERNS):
                continue
            try:
                stat = local_path.stat()
                rel_to_root = _normalize_rel_path(str(local_path.relative_to(local_root)))
                rel = _local_to_remote(rel_to_root, remote_prefix)
                if not device.sync_roots and not _is_under_shared_folders(rel, allowed):
                    continue
                local_rels.add(rel)
                local_mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
                remote = remote_by_path.get(rel)
                if not remote:
                    changes.append({"relative_path": rel, "action": "create", "checksum": None, "size": stat.st_size, "modified": local_mtime})
                else:
                    remote_mtime = remote.get("modified", "")
                    remote_size = remote.get("size")
                    if remote_size != stat.st_size or remote_mtime != local_mtime:
                        local_checksum = None if quick_mode else _hash_file(local_path)
                        changes.append({"relative_path": rel, "action": "update", "checksum": local_checksum, "size": stat.st_size, "modified": local_mtime})
            except (OSError, ValueError):
                continue

    # Detect deletions: files present on master but missing locally
    settings = SettingsStore.load()
    if getattr(settings, "allow_sync_deletes", False):
        for rel in remote_by_path:
            if not device.sync_roots and not _is_under_shared_folders(rel, allowed):
                continue
            if rel not in local_rels:
                changes.append({"relative_path": rel, "action": "delete"})
    else:
        # Safe mode: never propose deleting files from the master
        pass

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
def download_file(
    path: str,
    request: Request,
    device_id: str = "",
    token: str = "",
) -> Response:
    """Download a file from the master sync folder by relative path.

    Supports Range requests for chunked/resumable transfers.
    """
    root = SettingsStore.master_folder_path()
    target = (root / path).resolve()
    # Security: refuse to serve anything outside the sync folder.
    if not str(target).startswith(str(root.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    if device_id:
        device = next((d for d in DeviceStore.list_devices() if d.id == device_id), None)
        if device:
            _require_device_token(device, token or None)

    file_size = target.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        try:
            # Expect "bytes=start-end" (inclusive)
            unit, ranges = range_header.strip().split("=")
            if unit != "bytes":
                raise ValueError("Only bytes ranges supported")
            start_str, end_str = ranges.split("-")
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1
            if start >= file_size or end >= file_size or start > end:
                raise ValueError("Invalid range")
            length = end - start + 1
            with target.open("rb") as f:
                f.seek(start)
                data = f.read(length)
            headers = {
                "Content-Disposition": f"attachment; filename=\"{target.name}\"",
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
            }
            return Response(content=data, status_code=206, headers=headers, media_type="application/octet-stream")
        except Exception:
            raise HTTPException(status_code=416, detail="Range not satisfiable")

    def iter_file():
        with target.open("rb") as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(
        iter_file(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename=\"{target.name}\"",
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
        },
    )




CHUNK_SIZE = 1024 * 1024  # 1 MiB


@app.post("/files/upload-chunk")
def upload_chunk(
    relative_path: str = Form(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
    device_id: str = Form(""),
    token: str = Form(""),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Receive a single chunk of a file upload. Assemble once all chunks arrive."""
    master_root = SettingsStore.master_folder_path()
    target_path = (master_root / relative_path).resolve()
    if not str(target_path).startswith(str(master_root.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    if device_id:
        device = next((d for d in DeviceStore.list_devices() if d.id == device_id), None)
        if device:
            _require_device_token(device, token or None)
        elif token:
            # Caller supplied a token but no matching device id; still authenticate by token.
            _require_any_device_token(token)

    chunk_dir = DATA_DIR / "upload_chunks" / relative_path.replace("/", "-").replace("\\", "-")
    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunk_file = chunk_dir / f"chunk-{chunk_index:04d}"
    with chunk_file.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    received = sorted(chunk_dir.glob("chunk-*"))
    if len(received) == total_chunks:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with target_path.open("wb") as out:
            for cf in received:
                with cf.open("rb") as f:
                    shutil.copyfileobj(f, out)
        shutil.rmtree(chunk_dir)
        return {
            "relative_path": relative_path,
            "assembled": True,
            "size": target_path.stat().st_size,
            "checksum": _hash_file(target_path),
        }

    return {
        "relative_path": relative_path,
        "assembled": False,
        "chunk_index": chunk_index,
        "received": len(received),
        "total_chunks": total_chunks,
    }
@app.post("/pull")
async def pull_device(device_id: str = Form(...), remote_index_json: str = Form("")) -> dict[str, Any]:
    """Client: pull all missing or changed files from a remote master device.

    If `remote_index_json` is provided, use it directly instead of fetching from the device.
    """
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id required")
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
                params = {}
                if device.token:
                    params["device_id"] = device.id
                    params["token"] = DEVICE_TOKEN
                resp = await client.get(f"{base_url}/folder-index", params=params)
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
                    download_params = {"path": safe_rel}
                    if device.token:
                        download_params["device_id"] = device.id
                        download_params["token"] = DEVICE_TOKEN
                    resp = await client.get(f"{base_url}/files/download", params=download_params)
                    resp.raise_for_status()
                    total_size = int(resp.headers.get("content-length", str(len(resp.content))))

                    with local_path.open("wb") as out:
                        out.write(resp.content)
                        offset = len(resp.content)
                        while offset < total_size:
                            end = min(offset + CHUNK_SIZE - 1, total_size - 1)
                            headers = {"Range": f"bytes={offset}-{end}"}
                            chunk_resp = await client.get(
                                f"{base_url}/files/download",
                                params=download_params,
                                headers=headers,
                            )
                            chunk_resp.raise_for_status()
                            out.write(chunk_resp.content)
                            offset += len(chunk_resp.content)

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
    """Client: propose a batch of local file changes to a remote master device.

    Large create/update proposals are uploaded in chunks to avoid loading whole files into memory.
    """
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id required")
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
            if not rel_path or action not in ("create", "update", "delete"):
                continue

            if action == "delete":
                change_id = str(uuid4())
                try:
                    data = {
                        "relative_path": rel_path,
                        "action": action,
                        "source_device": source_device,
                        "change_id": change_id,
                    }
                    if device.token:
                        data["device_id"] = device.id
                        data["token"] = DEVICE_TOKEN
                    resp = await client.post(f"{base_url}/receive-proposal", data=data)
                    resp.raise_for_status()
                    proposed.append(resp.json())
                except Exception as e:
                    proposed.append({"relative_path": rel_path, "error": str(e)})
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
            try:
                # Upload file in chunks, then submit the proposal metadata
                total_size = local_path.stat().st_size
                total_chunks = max(1, (total_size + CHUNK_SIZE - 1) // CHUNK_SIZE)
                with local_path.open("rb") as f:
                    for idx in range(total_chunks):
                        chunk = f.read(CHUNK_SIZE)
                        files = {
                            "relative_path": (None, rel_path),
                            "chunk_index": (None, str(idx)),
                            "total_chunks": (None, str(total_chunks)),
                            "file": (local_path.name, chunk, "application/octet-stream"),
                        }
                        chunk_fields = {
                            "relative_path": (None, rel_path),
                            "chunk_index": (None, str(idx)),
                            "total_chunks": (None, str(total_chunks)),
                            "device_id": (None, source_device),
                        }
                        if device.token:
                            chunk_fields["device_id"] = (None, device.id)
                            chunk_fields["token"] = (None, DEVICE_TOKEN)
                        chunk_fields["file"] = (local_path.name, chunk, "application/octet-stream")
                        resp = await client.post(f"{base_url}/files/upload-chunk", files=chunk_fields)
                        resp.raise_for_status()

                files = {
                    "relative_path": (None, rel_path),
                    "action": (None, action),
                    "source_device": (None, source_device),
                    "change_id": (None, change_id),
                    "assembled": (None, "true"),
                }
                if device.token:
                    files["device_id"] = (None, device.id)
                    files["token"] = (None, DEVICE_TOKEN)
                files["file"] = (local_path.name, b"", "application/octet-stream")
                resp = await client.post(f"{base_url}/receive-proposal", files=files)
                resp.raise_for_status()
                proposed.append(resp.json())
            except Exception as e:
                proposed.append({"relative_path": rel_path, "error": str(e)})

    return {"proposed": proposed, "count": len(proposed)}


def _resolve_source_device_name(source_device: str, token: str, request: Request) -> str:
    """Return the friendliest name for the device sending this proposal.

    If the supplied token matches a paired device, use that device's registered name.
    Otherwise use the provided source_device name. Fallback to the request IP if nothing else.
    """
    if source_device:
        device = next((d for d in DeviceStore.list_devices() if d.id == source_device), None)
        if device and token:
            try:
                _require_device_token(device, token)
                return device.name or device.id
            except HTTPException:
                pass
    # Try matching by token alone (proposals sent from a paired device sometimes send name, sometimes id)
    if token:
        for d in DeviceStore.list_devices():
            if d.token and hmac.compare_digest(d.token, token):
                return d.name or d.id
    # Accept the caller-provided name if given
    if source_device:
        return source_device
    # Last resort: remote IP
    client = request.client
    return client.host if client and client.host else "unknown device"


@app.post("/receive-proposal")
def receive_proposal(
    request: Request,
    relative_path: str = Form(...),
    action: str = Form(...),
    source_device: str = Form(""),
    change_id: str = Form(""),
    assembled: bool = Form(False),
    token: str = Form(""),
    file: UploadFile = File(None),
) -> dict[str, Any]:
    """Master: receive a single file proposal from a client and queue it for approval.

    For create/update, either upload the full file here or upload chunks first and set assembled=True.
    """
    master_root = SettingsStore.master_folder_path()
    target_path = (master_root / relative_path).resolve()

    # Security: refuse paths outside master folder
    if not str(target_path).startswith(str(master_root.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    source_name = _resolve_source_device_name(source_device, token, request)

    # Safe sync: reject delete proposals unless explicitly allowed
    settings = SettingsStore.load()
    if action == "delete" and not getattr(settings, "allow_sync_deletes", False):
        raise HTTPException(status_code=403, detail="Delete actions are disabled. Enable allow_sync_deletes in settings to permit deletes.")

    # Dedupe: if a pending change for the same relative_path + source already exists, return it
    for existing in PendingStore.list_changes(status=ChangeStatus.PENDING):
        if existing.relative_path == relative_path and existing.source_device == source_name:
            return existing.model_dump()

    if not change_id:
        change_id = str(uuid4())

    # If the device is already paired, the caller must supply its token.
    device = next((d for d in DeviceStore.list_devices() if d.id == source_name), None)
    if device:
        _require_device_token(device, token or None)

    upload_dest: Path | None = None
    proposed_checksum: str | None = None
    if action in ("create", "update"):
        if assembled and target_path.exists():
            # File was pre-assembled via /files/upload-chunk; use it directly
            upload_dest = target_path
            proposed_checksum = _hash_file(upload_dest)
        else:
            if file is None:
                raise HTTPException(status_code=400, detail="File upload required for create/update")
            pending_dir = DATA_DIR / "pending_files" / change_id
            pending_dir.mkdir(parents=True, exist_ok=True)
            upload_dest = pending_dir / target_path.name
            with upload_dest.open("wb") as f:
                shutil.copyfileobj(file.file, f)
            proposed_checksum = _hash_file(upload_dest)

    file_id = f"file-{relative_path.replace('/', '-').replace(' ', '_')}"

    # Conflict detection: for updates, if master file exists and has a different checksum, flag it.
    conflict = False
    current_checksum: str | None = None
    current_size = 0
    if action == "update" and target_path.exists():
        current_checksum = _hash_file(target_path)
        current_size = target_path.stat().st_size
        if proposed_checksum and proposed_checksum != current_checksum:
            conflict = True
    if action == "delete" and target_path.exists():
        current_size = target_path.stat().st_size

    incoming_size = upload_dest.stat().st_size if upload_dest and upload_dest.exists() else 0

    change = ProposedChange(
        id=change_id,
        file_id=file_id,
        source_device=source_name,
        relative_path=relative_path,
        action=action,
        payload={
            "relative_path": relative_path,
            "action": action,
            "size": incoming_size,
            "original_size": current_size,
            "uploaded_filename": str(upload_dest) if upload_dest else None,
            "target_filename": str(target_path),
            "original_exists": target_path.exists(),
            "conflict": conflict,
            "current_checksum": current_checksum,
            "proposed_checksum": proposed_checksum,
        },
    )
    PendingStore.save_change(change)

    if upload_dest:
        entry = FileEntry(
            id=file_id,
            name=target_path.name,
            path=str(target_path),
            size=upload_dest.stat().st_size,
            modified=_now(),
            checksum=proposed_checksum,
            tags=[relative_path],
            source_device=source_name,
        )
        FileStore.upsert_file(entry)

    return change.model_dump()


@app.post("/approve")
def approve_change(change_id: str = Form(...)) -> dict[str, Any]:
    change = PendingStore.get_change(change_id)
    if not change:
        # Idempotent: already processed changes are a no-op.
        return {"id": change_id, "status": "missing", "note": "Change already processed or removed"}
    settings = SettingsStore.load()
    if change.action == "delete" and not getattr(settings, "allow_sync_deletes", False):
        raise HTTPException(status_code=403, detail="Delete actions are disabled")
    updated = PendingStore.set_status(change_id, ChangeStatus.APPROVED)
    if updated:
        _apply_approved_change(updated)
    return updated.model_dump() if updated else {"id": change_id, "status": "already_processed"}


@app.post("/resolve-conflict")
def resolve_conflict(
    change_id: str = Form(...),
    resolution: str = Form(...),
) -> dict[str, Any]:
    """Resolve a conflicted proposal: 'accept' (incoming), 'keep' (master), or 'reject'."""
    change = PendingStore.get_change(change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")

    payload = change.payload or {}
    if not payload.get("conflict"):
        raise HTTPException(status_code=400, detail="Change is not in conflict")

    if resolution not in ("accept", "keep", "reject"):
        raise HTTPException(status_code=400, detail="Resolution must be accept, keep, or reject")

    if resolution == "reject":
        return reject_change(change_id)

    if resolution == "accept":
        change.status = ChangeStatus.APPROVED
        PendingStore.save_change(change)
        _apply_approved_change(change)
        return change.model_dump()

    # resolution == "keep": reject the proposal, leaving master file untouched
    return reject_change(change_id)


def _apply_approved_change(change: ProposedChange) -> None:
    """Apply an approved change: copy pending file, delete target, snapshot before changes, update index."""
    payload = change.payload or {}
    target_filename = payload.get("target_filename")
    uploaded_filename = payload.get("uploaded_filename")
    relative_path = payload.get("relative_path") or change.relative_path

    if not target_filename:
        return

    target = Path(target_filename)
    if not str(target).startswith(str(SettingsStore.master_folder_path().resolve())):
        raise ValueError("Access denied")

    file_id = change.file_id

    if change.action == "delete":
        if target.exists():
            SnapshotStore.create(file_id, source_path=target, note=f"pre-delete {change.id}")
            target.unlink()
            # Remove parent dirs if empty
            try:
                target.parent.rmdir()
            except OSError:
                pass
        FileStore.upsert_file(FileEntry(
            id=file_id,
            name=target.name,
            path=str(target),
            size=0,
            modified=_now(),
            checksum=None,
            tags=[relative_path] if relative_path else [],
            source_device=change.source_device,
        ))
        return

    if uploaded_filename:
        target.parent.mkdir(parents=True, exist_ok=True)
        source = Path(uploaded_filename)
        if source.exists():
            if source.resolve() != target.resolve():
                if target.exists():
                    SnapshotStore.create(file_id, source_path=target, note=f"pre-approve {change.id}")
                shutil.copy2(source, target)
            entry = FileEntry(
                id=file_id,
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
            settings = SettingsStore.load()
            if change.action == "delete" and not getattr(settings, "allow_sync_deletes", False):
                failed.append({"id": change.id, "error": "Delete actions are disabled"})
                continue
            updated = PendingStore.set_status(change.id, ChangeStatus.APPROVED)
            if updated:
                _apply_approved_change(updated)
                approved.append(change.id)
        except Exception as e:
            failed.append({"id": change.id, "error": str(e)})
    return {"approved": approved, "failed": failed, "count": len(approved)}


@app.post("/reject")
def reject_change(change_id: str = Form(...)) -> dict[str, Any]:
    change = PendingStore.get_change(change_id)
    if not change:
        return {"id": change_id, "status": "missing", "note": "Change already processed or removed"}
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
    token: str = Form(""),
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
        token=token or None,
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
    token: str = Form(""),
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
    if token:
        device.token = token
    DeviceStore.upsert_device(device)
    return device.model_dump()


@app.delete("/devices/{device_id}")
def delete_device(device_id: str) -> JSONResponse:
    DeviceStore.remove_device(device_id)
    return JSONResponse(content={"deleted": device_id})
