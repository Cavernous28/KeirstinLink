"""Runtime settings for KeirstinLink."""

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .config import DEFAULT_SYNC_FOLDER, SETTINGS_FILE


class SyncRoot(BaseModel):
    local_path: str
    remote_prefix: str = ""


class Settings(BaseModel):
    device_name: str = "KeirstinLink Device"
    mode: str = "master"  # "master" or "client"
    sync_folder: str = DEFAULT_SYNC_FOLDER
    master_sync_folder: str = DEFAULT_SYNC_FOLDER
    master_sync_roots: list[SyncRoot] = Field(default_factory=list)
    allow_sync_deletes: bool = False  # if False, sync only creates/updates; never proposes or applies deletes


class SettingsStore:
    @staticmethod
    def load() -> Settings:
        if not SETTINGS_FILE.exists():
            return Settings()
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return Settings(**data)
        except (json.JSONDecodeError, TypeError):
            return Settings()

    @staticmethod
    def save(settings: Settings) -> None:
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings.model_dump(), indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)

    @staticmethod
    def sync_folder_path() -> Path:
        settings = SettingsStore.load()
        path = Path(settings.sync_folder)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def master_folder_path() -> Path:
        settings = SettingsStore.load()
        path = Path(settings.master_sync_folder)
        path.mkdir(parents=True, exist_ok=True)
        return path
