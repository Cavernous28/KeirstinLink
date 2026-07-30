"""Folder indexing and hash utilities."""

import fnmatch
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from .config import FILES_INDEX
from .models import FileEntry
from .settings_store import SettingsStore


DEFAULT_IGNORE_PATTERNS = [
    ".git",
    ".gitignore",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".cache",
    ".tmp",
    "*.tmp",
    "*.log",
    ".DS_Store",
    "Thumbs.db",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    "*.pyc",
    "*.pyo",
    "dist",
    "build",
    "target",
]


def _is_ignored(path: Path, root: Path, patterns: list[str]) -> bool:
    """Return True if any part of path matches an ignore pattern."""
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        return False
    lower_parts = [p.lower() for p in rel_parts]
    for part in lower_parts:
        for pattern in patterns:
            if fnmatch.fnmatch(part, pattern.lower()):
                return True
    return False


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


def index_sync_folder(hash_files: bool = True) -> list[FolderIndexEntry]:
    root = SettingsStore.master_folder_path()
    entries = []
    for p in root.rglob("*"):
        if p.is_file() and not _is_ignored(p, root, DEFAULT_IGNORE_PATTERNS):
            try:
                stat = p.stat()
                rel = str(p.relative_to(root)).replace("\\", "/")
                entries.append(
                    FolderIndexEntry(
                        relative_path=rel,
                        name=p.name,
                        size=stat.st_size,
                        modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                        checksum=_hash_file(p) if hash_files else None,
                    )
                )
            except (OSError, ValueError):
                continue
    return sorted(entries, key=lambda e: e.relative_path)


def rebuild_files_index() -> list[FileEntry]:
    root = SettingsStore.sync_folder_path()
    entries = []
    for idx, p in enumerate(root.rglob("*")):
        if p.is_file() and not _is_ignored(p, root, DEFAULT_IGNORE_PATTERNS):
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
