"""Pydantic models."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class ChangeStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class FileEntry(BaseModel):
    id: str
    name: str
    path: str
    size: int = 0
    modified: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    checksum: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class VersionSnapshot(BaseModel):
    id: str
    file_id: str
    created: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    checksum: Optional[str] = None
    note: Optional[str] = None


class ProposedFileChange(BaseModel):
    relative_path: str
    action: str  # "create" | "update" | "delete"
    checksum: Optional[str] = None
    size: int = 0
    modified: str = ""


class ProposedChange(BaseModel):
    id: str
    file_id: str
    status: ChangeStatus = ChangeStatus.PENDING
    created: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)
    source_device: Optional[str] = None
    relative_path: Optional[str] = None
    action: Optional[str] = None  # convenience from payload


class DeviceInfo(BaseModel):
    id: str
    name: str
    host: str
    port: int
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    capabilities: list[str] = Field(default_factory=list)
