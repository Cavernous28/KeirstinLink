"""Folder indexing and hash utilities."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from .config import FILES_INDEX
from .models import FileEntry
from .settings_store import SettingsStore


class FolderIndexEntry(BaseModel):
    relative_path: str
    name: str
    size: int
    modified: str
    checksum: Optional[str] = None


def _hash_file(path: Path, block_size: int = 65536) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def index_sync_folder() -> list[FolderIndexEntry]:
    root = SettingsStore.master_folder_path()
    entries = []
    for p in root.rglob("*"):
        if p.is_file():
            try:
                stat = p.stat()
                rel = str(p.relative_to(root)).replace("\\", "/")
                entries.append(
                    FolderIndexEntry(
                        relative_path=rel,
                        name=p.name,
                        size=stat.st_size,
                        modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                        checksum=_hash_file(p),
                    )
                )
            except (OSError, ValueError):
                continue
    return sorted(entries, key=lambda e: e.relative_path)


def rebuild_files_index() -> list[FileEntry]:
    root = SettingsStore.sync_folder_path()
    entries = []
    for idx, p in enumerate(root.rglob("*")):
        if p.is_file():
            try:
                stat = p.stat()
                rel = str(p.relative_to(root)).replace("\\", "/")
                entry = FileEntry(
                    id=f"file-{idx}",
                    name=p.name,
                    path=str(p),
                    size=stat.st_size,
                    modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                    checksum=_hash_file(p),
                    tags=[rel],
                )
                entries.append(entry)
            except (OSError, ValueError):
                continue
    data = {"files": [e.model_dump() for e in entries]}
    tmp = FILES_INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(FILES_INDEX)
    return entries
