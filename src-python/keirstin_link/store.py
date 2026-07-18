"""Simple JSON file stores."""

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .config import DATA_DIR, DEVICE_REGISTRY, FILES_INDEX, MAX_VERSIONS, PENDING_DIR, SNAPSHOTS_DIR
from .models import ChangeStatus, DeviceInfo, FileEntry, ProposedChange, VersionSnapshot


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


class FileStore:
    @staticmethod
    def list_files() -> list[FileEntry]:
        data = _read_json(FILES_INDEX, {"files": []})
        return [FileEntry(**f) for f in data.get("files", [])]

    @staticmethod
    def get_file(file_id: str) -> Optional[FileEntry]:
        for f in FileStore.list_files():
            if f.id == file_id:
                return f
        return None

    @staticmethod
    def upsert_file(entry: FileEntry) -> None:
        files = FileStore.list_files()
        updated = False
        for i, f in enumerate(files):
            if f.id == entry.id:
                files[i] = entry
                updated = True
                break
        if not updated:
            files.append(entry)
        _write_json(FILES_INDEX, {"files": [f.model_dump() for f in files]})


class SnapshotStore:
    @staticmethod
    def _snapshot_dir(file_id: str) -> Path:
        return SNAPSHOTS_DIR / file_id

    @staticmethod
    def create(file_id: str, source_path: Optional[Path] = None, note: Optional[str] = None) -> VersionSnapshot:
        snap_dir = SnapshotStore._snapshot_dir(file_id)
        snap_dir.mkdir(parents=True, exist_ok=True)

        snap_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        snap = VersionSnapshot(id=snap_id, file_id=file_id, note=note)

        meta_path = snap_dir / f"{snap_id}.json"
        _write_json(meta_path, snap.model_dump())

        if source_path and source_path.exists():
            dest = snap_dir / f"{snap_id}-{source_path.name}"
            shutil.copy2(source_path, dest)

        SnapshotStore._prune(file_id)
        return snap

    @staticmethod
    def list_for_file(file_id: str) -> list[VersionSnapshot]:
        snap_dir = SnapshotStore._snapshot_dir(file_id)
        if not snap_dir.exists():
            return []
        snaps = []
        for p in sorted(snap_dir.glob("*.json")):
            try:
                snaps.append(VersionSnapshot(**_read_json(p, {})))
            except Exception:
                continue
        return snaps

    @staticmethod
    def _prune(file_id: str) -> None:
        snaps = SnapshotStore.list_for_file(file_id)
        if len(snaps) <= MAX_VERSIONS:
            return
        for old in snaps[:-MAX_VERSIONS]:
            meta = SnapshotStore._snapshot_dir(file_id) / f"{old.id}.json"
            if meta.exists():
                meta.unlink()
            for data in SnapshotStore._snapshot_dir(file_id).glob(f"{old.id}-*"):
                if data.is_file():
                    data.unlink()


class PendingStore:
    @staticmethod
    def _pending_path(change_id: str) -> Path:
        return PENDING_DIR / f"{change_id}.json"

    @staticmethod
    def list_changes(status: Optional[ChangeStatus] = None) -> list[ProposedChange]:
        changes = []
        for p in PENDING_DIR.glob("*.json"):
            try:
                changes.append(ProposedChange(**_read_json(p, {})))
            except Exception:
                continue
        if status:
            changes = [c for c in changes if c.status == status]
        return sorted(changes, key=lambda c: c.created)

    @staticmethod
    def get_change(change_id: str) -> Optional[ProposedChange]:
        path = PendingStore._pending_path(change_id)
        if not path.exists():
            return None
        try:
            return ProposedChange(**_read_json(path, {}))
        except Exception:
            return None

    @staticmethod
    def save_change(change: ProposedChange) -> None:
        PendingStore._pending_path(change.id).parent.mkdir(parents=True, exist_ok=True)
        _write_json(PendingStore._pending_path(change.id), change.model_dump())

    @staticmethod
    def set_status(change_id: str, status: ChangeStatus) -> Optional[ProposedChange]:
        change = PendingStore.get_change(change_id)
        if not change:
            return None
        change.status = status
        PendingStore.save_change(change)
        return change


class DeviceStore:
    @staticmethod
    def list_devices() -> list[DeviceInfo]:
        data = _read_json(DEVICE_REGISTRY, {"devices": []})
        return [DeviceInfo(**d) for d in data.get("devices", [])]

    @staticmethod
    def upsert_device(device: DeviceInfo) -> None:
        devices = DeviceStore.list_devices()
        updated = False
        for i, d in enumerate(devices):
            if d.id == device.id:
                devices[i] = device
                updated = True
                break
        if not updated:
            devices.append(device)
        _write_json(DEVICE_REGISTRY, {"devices": [d.model_dump() for d in devices]})

    @staticmethod
    def remove_device(device_id: str) -> None:
        devices = [d for d in DeviceStore.list_devices() if d.id != device_id]
        _write_json(DEVICE_REGISTRY, {"devices": [d.model_dump() for d in devices]})
