."""Basic API smoke tests."""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from keirstin_link.api import app
from keirstin_link.config import DATA_DIR


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("keirstin_link.config.DATA_DIR", tmp_path)
    monkeypatch.setattr("keirstin_link.store.FILES_INDEX", tmp_path / "files_index.json")
    monkeypatch.setattr("keirstin_link.store.PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr("keirstin_link.store.SNAPSHOTS_DIR", tmp_path / "snapshots")
    monkeypatch.setattr("keirstin_link.store.DEVICE_REGISTRY", tmp_path / "devices.json")
    monkeypatch.setattr("keirstin_link.api.DATA_DIR", tmp_path)
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_files_empty(client):
    r = client.get("/files")
    assert r.status_code == 200
    assert r.json() == []


def test_register_and_pull(tmp_path, client):
    src = tmp_path / "hello.txt"
    src.write_text("world")

    r = client.post("/files/register", data={"id": "f1", "name": "hello.txt", "path": str(src), "size": 5})
    assert r.status_code == 200
    assert r.json()["id"] == "f1"

    r = client.post("/pull", data={"uri": str(src), "file_id": "f1"})
    assert r.status_code == 200
    assert r.json()["file"]["size"] == 5


def test_propose_approve_flow(client):
    r = client.post("/files/register", data={"id": "f2", "name": "x.txt", "path": "/tmp/x.txt", "size": 0})
    assert r.status_code == 200
    r = client.post("/propose", data={"file_id": "f2", "payload": '{"note": "edit"}'})
    assert r.status_code == 200
    change_id = r.json()["id"]

    r = client.post("/approve", data={"change_id": change_id})
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    r = client.get("/versions/f2")
    assert r.status_code == 200
    assert len(r.json()["versions"]) >= 1


def test_devices_empty(client):
    r = client.get("/devices")
    assert r.status_code == 200
    assert r.json() == []
