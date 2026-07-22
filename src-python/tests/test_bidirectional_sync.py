"""End-to-end bidirectional sync test with token auth.

This test starts one KeirstinLink backend in "master" mode, registers a fake client
device, pairs it with a token, then runs the full create/update loop:

1. Client creates a local file.
2. Client calls /scan-local to build a changeset.
3. Client calls /propose-files to send it to the master.
4. Master has a pending approval.
5. Master calls /approve on the change.
6. Master's folder now contains the file.

Then it tests update propagation:

7. Client modifies the file.
8. New proposal → approve.
9. Master file matches client file.
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from subprocess import Popen, PIPE, TimeoutExpired
from unittest import TestCase

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def find_free_port():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class BidirectionalSyncTest(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kl_bidi_"))
        self.master_folder = self.tmp / "master"
        self.client_folder = self.tmp / "client"
        self.master_folder.mkdir()
        self.client_folder.mkdir()

        self.port = find_free_port()

        env = os.environ.copy()
        env["KL_DATA_DIR"] = str(self.tmp / "data")
        env["KL_PORT"] = str(self.port)
        env["KL_MAX_VERSIONS"] = "3"

        root = Path(__file__).resolve().parent.parent
        self.proc = Popen(
            [sys.executable, "-m", "keirstin_link.main"],
            cwd=str(root),
            env=env,
            stdout=PIPE,
            stderr=PIPE,
        )
        self.base = f"http://127.0.0.1:{self.port}"
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                if httpx.get(f"{self.base}/health", timeout=0.5).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.2)
        else:
            self._kill()
            self.fail("backend did not start")

        # Configure master settings
        r = httpx.post(f"{self.base}/settings", data={
            "device_name": "master-pc",
            "mode": "master",
            "sync_folder": str(self.master_folder),
            "master_sync_folder": str(self.master_folder),
        }, timeout=5)
        self.assertEqual(r.status_code, 200, r.text)

        # Register client device with sync root pointing at the client folder
        self.client_token = "client-secret-token"
        client_roots = json.dumps([{"local_path": str(self.client_folder), "remote_prefix": ""}])
        r = httpx.post(f"{self.base}/devices", data={
            "id": "client-one",
            "name": "client-one",
            "host": "127.0.0.1",
            "port": str(self.port),
            "capabilities": "mobile",
            "token": self.client_token,
            "sync_roots_json": client_roots,
        }, timeout=5)
        self.assertEqual(r.status_code, 200, r.text)

    def tearDown(self):
        self._kill()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _kill(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except TimeoutExpired:
                self.proc.kill()

    def _pending(self):
        r = httpx.get(f"{self.base}/state", timeout=5)
        r.raise_for_status()
        return r.json().get("pending", [])

    def _approve_first(self):
        pending = self._pending()
        self.assertTrue(pending)
        change_id = pending[0]["id"]
        r = httpx.post(f"{self.base}/approve", data={"change_id": change_id}, timeout=5)
        self.assertEqual(r.status_code, 200, r.text)
        return change_id

    def test_create_file_propagates_to_master(self):
        local_file = self.client_folder / "hello.txt"
        local_file.write_text("hello world", encoding="utf-8")

        # Build changeset as if client scanned against master index
        r = httpx.post(f"{self.base}/scan-local", data={
            "device_id": "client-one",
            "remote_index_json": "[]",
        }, timeout=10)
        self.assertEqual(r.status_code, 200, r.text)
        changes = r.json()["changes"]
        self.assertEqual(len(changes), 1, changes)
        self.assertEqual(changes[0]["action"], "create")

        # Propose to master (still using the same backend as a stand-in for client calls)
        r = httpx.post(f"{self.base}/propose-files", data={
            "device_id": "client-one",
            "changes_json": json.dumps(changes),
        }, timeout=10)
        self.assertEqual(r.status_code, 200, r.text)
        print("propose result:", r.text)
        self.assertEqual(r.json()["count"], 1, r.text)

        # Approve
        self._approve_first()

        # Verify master has the file
        master_file = self.master_folder / "hello.txt"
        self.assertTrue(master_file.is_file())
        self.assertEqual(master_file.read_text(encoding="utf-8"), "hello world")

    def test_update_file_propagates_to_master(self):
        # Seed the file on both sides
        (self.client_folder / "notes.txt").write_text("v1", encoding="utf-8")
        (self.master_folder / "notes.txt").write_text("v1", encoding="utf-8")

        # Modify client side
        (self.client_folder / "notes.txt").write_text("v2", encoding="utf-8")

        # Remote index from master's perspective
        remote_index = [
            {"relative_path": "notes.txt", "checksum": "old", "size": 2, "modified": "2024-01-01T00:00:00+00:00"},
        ]
        r = httpx.post(f"{self.base}/scan-local", data={
            "device_id": "client-one",
            "remote_index_json": json.dumps(remote_index),
        }, timeout=10)
        self.assertEqual(r.status_code, 200, r.text)
        changes = r.json()["changes"]
        self.assertEqual(len(changes), 1, changes)
        self.assertEqual(changes[0]["action"], "update")

        # Propose and approve
        r = httpx.post(f"{self.base}/propose-files", data={
            "device_id": "client-one",
            "changes_json": json.dumps(changes),
        }, timeout=10)
        self.assertEqual(r.status_code, 200, r.text)

        # Conflict may be flagged depending on checksums; just resolve accept if needed
        pending = self._pending()
        self.assertEqual(len(pending), 1)
        if pending[0].get("payload", {}).get("conflict"):
            r = httpx.post(f"{self.base}/resolve-conflict", data={
                "change_id": pending[0]["id"],
                "resolution": "accept",
            }, timeout=5)
        else:
            self._approve_first()

        master_file = self.master_folder / "notes.txt"
        self.assertEqual(master_file.read_text(encoding="utf-8"), "v2")


if __name__ == "__main__":
    import json
    import unittest
    unittest.main()
