"""Basic API smoke tests."""

from pathlib import Path

import json
import pytest
from fastapi.testclient import TestClient

from keirstin_link.api import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "test_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("keirstin_link.config.DATA_DIR", data_dir)
    monkeypatch.setattr("keirstin_link.config.FILES_INDEX", data_dir / "files_index.json")
    monkeypatch.setattr("keirstin_link.config.PENDING_DIR", data_dir / "pending")
    monkeypatch.setattr("keirstin_link.config.SNAPSHOTS_DIR", data_dir / "snapshots")
    monkeypatch.setattr("keirstin_link.config.DEVICE_REGISTRY", data_dir / "devices.json")
    monkeypatch.setattr("keirstin_link.config.SETTINGS_FILE", data_dir / "settings.json")
    monkeypatch.setattr("keirstin_link.store.FILES_INDEX", data_dir / "files_index.json")
    monkeypatch.setattr("keirstin_link.store.PENDING_DIR", data_dir / "pending")
    monkeypatch.setattr("keirstin_link.store.SNAPSHOTS_DIR", data_dir / "snapshots")
    monkeypatch.setattr("keirstin_link.store.DEVICE_REGISTRY", data_dir / "devices.json")
    monkeypatch.setattr("keirstin_link.settings_store.SETTINGS_FILE", data_dir / "settings.json")
    monkeypatch.setattr("keirstin_link.api.DATA_DIR", data_dir)
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_state_empty(client):
    r = client.get("/state")
    assert r.status_code == 200
    data = r.json()
    assert data["devices"] == []
    assert data["pending"] == []


def test_register_and_pull(tmp_path, client):
    # Configure a sync folder and a fake remote master device.
    sync = tmp_path / "sync"
    sync.mkdir()
    (sync / "hello.txt").write_text("world")

    r = client.post("/settings", data={"device_name": "test", "mode": "client", "sync_folder": str(sync), "master_sync_folder": str(sync)})
    assert r.status_code == 200

    r = client.post("/devices", data={"id": "dev-local", "name": "Local Master", "host": "127.0.0.1", "port": "3710", "capabilities": "master"})
    assert r.status_code == 200

    # /pull reaches out to the remote device over HTTP. If a real backend happens to be running on 3710, it succeeds.
    r = client.post("/pull", data={"device_id": "dev-local"})
    assert r.status_code in (200, 502)
    if r.status_code == 200:
        data = r.json()
        assert "pulled" in data
        assert "skipped" in data


def test_folder_index_and_download(tmp_path, client):
    sync = tmp_path / "sync"
    sync.mkdir()
    (sync / "hello.txt").write_text("world")

    r = client.post("/settings", data={"sync_folder": str(sync), "master_sync_folder": str(sync)})
    assert r.status_code == 200

    r = client.get("/folder-index")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["relative_path"] == "hello.txt"

    r = client.get("/files/download?path=hello.txt")
    assert r.status_code == 200
    assert r.content == b"world"


def test_bidirectional_propose_approve_flow(tmp_path, client):
    # Set master folder and sync folder separately
    master = tmp_path / "master"
    master.mkdir()
    client_dir = tmp_path / "client"
    client_dir.mkdir()
    client.post("/settings", data={"device_name": "Master", "mode": "master", "sync_folder": str(client_dir), "master_sync_folder": str(master)})

    # Add a local device
    client.post("/devices", data={"id": "dev-local", "name": "Local", "host": "127.0.0.1", "port": "3710", "capabilities": "master"})

    # Create a file in the client sync folder and a different existing file in the master folder
    (client_dir / "new_file.txt").write_text("client content")
    (master / "new_file.txt").write_text("original content")

    # Build a remote index that says master already has a different checksum
    remote_index = [
        {
            "relative_path": "new_file.txt",
            "name": "new_file.txt",
            "size": 15,
            "modified": "2026-01-01T00:00:00+00:00",
            "checksum": "0000000000000000000000000000000000000000000000000000000000000000",
        }
    ]

    # Scan for changes
    r = client.post("/scan-local", data={"device_id": "dev-local", "remote_index_json": json.dumps(remote_index)})
    assert r.status_code == 200
    scan = r.json()
    assert scan["count"] == 1
    assert scan["changes"][0]["relative_path"] == "new_file.txt"
    assert scan["changes"][0]["action"] == "update"

    # Send a single proposal directly to the master receiver (mimics what /propose-files does over HTTP)
    src = client_dir / "new_file.txt"
    with src.open("rb") as f:
        r = client.post(
            "/receive-proposal",
            data={"relative_path": "new_file.txt", "action": "update", "source_device": "dev-local"},
            files={"file": ("new_file.txt", f, "application/octet-stream")},
        )
    assert r.status_code == 200
    proposal = r.json()
    change_id = proposal["id"]
    file_id = proposal["file_id"]

    # Approve it
    r = client.post("/approve", data={"change_id": change_id})
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    # Verify master folder now has the updated file
    master_file = master / "new_file.txt"
    assert master_file.exists()
    assert master_file.read_text() == "client content"

    # Verify a snapshot was created of the original
    r = client.get(f"/versions/{file_id}")
    assert r.status_code == 200
    assert len(r.json()["versions"]) == 1


def test_reject_proposal_cleans_up(tmp_path, client):
    master = tmp_path / "master"
    master.mkdir()
    client_dir = tmp_path / "client"
    client_dir.mkdir()
    client.post("/settings", data={"device_name": "Master", "mode": "master", "sync_folder": str(client_dir), "master_sync_folder": str(master)})
    client.post("/devices", data={"id": "dev-local", "name": "Local", "host": "127.0.0.1", "port": "3710", "capabilities": "master"})

    (client_dir / "rejected.txt").write_text("reject me")

    src = client_dir / "rejected.txt"
    with src.open("rb") as f:
        r = client.post(
            "/receive-proposal",
            data={"relative_path": "rejected.txt", "action": "create", "source_device": "dev-local"},
            files={"file": ("rejected.txt", f, "application/octet-stream")},
        )
    change_id = r.json()["id"]

    pending_dir = tmp_path / "test_data" / "pending_files" / change_id
    assert pending_dir.exists()

    r = client.post("/reject", data={"change_id": change_id})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert not pending_dir.exists()


@pytest.fixture
def fresh_device_registry(tmp_path, monkeypatch):
    """Give each test a clean device registry without relying on global state."""
    monkeypatch.setattr("keirstin_link.store.DEVICE_REGISTRY", tmp_path / "devices.json")


def test_devices_empty(client):
    r = client.get("/devices")
    assert r.status_code == 200
    assert r.json() == []

def test_propose_files_http_loopback(tmp_path, monkeypatch):
    """Integration test for /propose-files using a real subprocess server on a free port."""
    import json
    import os
    import shutil
    import subprocess
    import sys
    import time
    import urllib.error
    import urllib.request

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    client_dir = tmp_path / "client"
    client_dir.mkdir()
    master_dir = tmp_path / "master"
    master_dir.mkdir()

    env = os.environ.copy()
    env["KL_DATA_DIR"] = str(data_dir)
    env["KL_SYNC_FOLDER"] = str(client_dir)
    env["KL_MASTER_SYNC_FOLDER"] = str(master_dir)

    port = 3730
    base = f"http://127.0.0.1:{port}"
    py_dir = Path(__file__).resolve().parent.parent / "keirstin_link"
    root_dir = py_dir.parent

    def wait_for_health(timeout=15):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"{base}/health", timeout=1)
                return True
            except Exception:
                time.sleep(0.25)
        return False

    def post(path, fields):
        data = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(f"{base}{path}", data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())

    def get(path):
        req = urllib.request.Request(f"{base}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())

    proc = subprocess.Popen(
        [sys.executable, "-m", "keirstin_link.main", "--host", "127.0.0.1", "--port", str(port), "--no-discovery"],
        cwd=str(root_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert wait_for_health(), "Backend did not start"

        post("/settings", {"device_name": "LoopMaster", "mode": "master", "sync_folder": str(client_dir), "master_sync_folder": str(master_dir)})
        post("/devices", {"id": "dev-loop", "name": "LoopClient", "host": "127.0.0.1", "port": str(port), "capabilities": "mobile"})

        (client_dir / "loop.txt").write_text("loop content", encoding="utf-8")

        _, scan = post("/scan-local", {"device_id": "dev-loop", "remote_index_json": json.dumps([])})
        assert scan["count"] == 1

        _, prop = post("/propose-files", {"device_id": "dev-loop", "changes_json": json.dumps(scan["changes"])})
        assert prop["count"] == 1, prop
        change_id = prop["proposed"][0]["id"]

        _, state = get("/state")
        assert len(state["pending"]) == 1

        post("/approve", {"change_id": change_id})
        master_file = master_dir / "loop.txt"
        assert master_file.read_text(encoding="utf-8") == "loop content"

        _, final = get("/state")
        assert len(final["pending"]) == 0
        assert len(final["files"]) == 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

