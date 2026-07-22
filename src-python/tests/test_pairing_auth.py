"""Test device-token pairing and authenticated sync operations."""
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

# Make sure we can import the package under test
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def find_free_port():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class PairingAuthTest(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kl_test_"))
        self.master_data = self.tmp / "master_data"
        self.client_data = self.tmp / "client_data"
        self.master_data.mkdir()
        self.client_data.mkdir()

        self.master_port = find_free_port()
        self.client_port = find_free_port()

        env_common = os.environ.copy()
        env_common["KL_DATA_DIR"] = str(self.tmp / "data")
        env_common["KL_MAX_VERSIONS"] = "3"
        # Run master in client mode is wrong; master is master. We just need two HTTP endpoints
        # on the same machine for the test. We'll start the app once and hit it as both sides.
        env_common["KL_PORT"] = str(self.master_port)

        self.master_root = Path(__file__).resolve().parent.parent
        self.proc = Popen(
            [sys.executable, "-m", "keirstin_link.main"],
            cwd=str(self.master_root),
            env=env_common,
            stdout=PIPE,
            stderr=PIPE,
        )
        self.base = f"http://127.0.0.1:{self.master_port}"
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                r = httpx.get(f"{self.base}/health", timeout=0.5)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.2)
        else:
            self._kill()
            self.fail("backend did not start")

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

    def _post_form(self, path, data):
        return httpx.post(f"{self.base}{path}", data=data, timeout=10)

    def test_pairing_blocks_unauthenticated_index(self):
        # Register a client device without token initially
        r = self._post_form("/devices", {
            "id": "test-client",
            "name": "Test Client",
            "host": "127.0.0.1",
            "port": "3711",
            "capabilities": "mobile",
        })
        self.assertEqual(r.status_code, 200, r.text)

        # After setting a token on the device, unauthenticated index is rejected
        # We'll simulate the master receiving a /pair call: client sends its token.
        client_token = "client-secret-token-123"
        r = self._post_form("/pair", {"device_id": "test-client", "token": client_token})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("master_token", r.json())
        master_token = r.json()["master_token"]
        self.assertTrue(master_token)

        # Now /folder-index without token should fail (device exists and has token)
        r = httpx.get(f"{self.base}/folder-index", params={"device_id": "test-client"}, timeout=5)
        self.assertEqual(r.status_code, 401, r.text)

        # With wrong token should fail
        r = httpx.get(f"{self.base}/folder-index", params={"device_id": "test-client", "token": "wrong"}, timeout=5)
        self.assertEqual(r.status_code, 403, r.text)

        # With correct token succeeds
        r = httpx.get(f"{self.base}/folder-index", params={"device_id": "test-client", "token": client_token}, timeout=5)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsInstance(r.json(), list)

        # /my-token is callable locally
        r = httpx.get(f"{self.base}/my-token", timeout=5)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["token"], master_token)


if __name__ == "__main__":
    import unittest
    unittest.main()
