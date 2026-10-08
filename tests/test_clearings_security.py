# SPDX-License-Identifier: MIT
# MIT License
#
# Copyright (c) 2026 The Hermit
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""Disposable loopback adversarial checks; no owner helper or browser state."""
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
spec = importlib.util.spec_from_file_location("clearings_local_security", ROOT / "tools" / "clearings_local.py")
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


class SecurityChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clearings-security-")
        self.bridge = local.Bridge(Path(self.temp.name) / "config")
        self.token = "fixture-token-known-only-to-this-test"
        self.launches = local.LaunchState()
        self.server = local.LocalServer(("127.0.0.1", 0),
                                        local.handler_for(self.bridge, self.token, 0, self.launches))
        self.port = self.server.server_port
        self.url = f"http://127.0.0.1:{self.port}"
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(3)
        self.temp.cleanup()

    def request(self, path, *, data=None, headers=None):
        request = urllib.request.Request(self.url + path, data=data,
                                         headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def session(self):
        return {"port": self.port, "token": self.token,
                "identity": local.program_identity(self.bridge)}

    def test_public_root_has_no_token_and_one_use_launch_is_required(self):
        status, page = self.request("/")
        self.assertEqual(status, 200)
        self.assertNotIn(self.token.encode(), page)
        self.assertNotIn(b"__CLEARINGS_LOCAL_TOKEN__", page)
        headers = {"Content-Type": "application/json", "Origin": self.url}
        self.assertEqual(self.request("/api/bootstrap", data=b'{"nonce":"guess"}', headers=headers)[0], 403)
        self.assertEqual(self.request("/api/handoff")[0], 403)
        self.assertTrue(local.verify_listener(self.session(), self.bridge, self.port))
        launch = local.authenticated_control(self.session(), "launch", self.port)
        nonce = launch["nonce"]
        self.assertRegex(nonce, r"^[A-Za-z0-9_-]{32,80}$")
        self.assertEqual(self.request("/api/bootstrap", data=json.dumps({"nonce": nonce}).encode(),
                                      headers={"Content-Type": "application/json"})[0], 403)
        status, body = self.request("/api/bootstrap", data=json.dumps({"nonce": nonce}).encode(), headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"token": self.token})
        self.assertEqual(self.request("/api/bootstrap", data=json.dumps({"nonce": nonce}).encode(), headers=headers)[0], 403)
        self.assertEqual(self.request("/api/handoff", headers={"X-Clearings-Token": self.token})[0], 200)

    def test_foreign_duplicate_authority_and_origin_are_refused(self):
        token = {"X-Clearings-Token": self.token}
        self.assertEqual(self.request("/", headers={"Host": "attacker.invalid"})[0], 403)
        self.assertEqual(self.request("/api/handoff", headers={**token, "Origin": "http://attacker.invalid"})[0], 403)
        self.assertEqual(self.request("/api/handoff", headers={**token, "Host": "attacker.invalid"})[0], 403)
        with socket.create_connection(("127.0.0.1", self.port), timeout=2) as client:
            client.sendall((f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
                            "Host: attacker.invalid\r\nConnection: close\r\n\r\n").encode())
            self.assertIn(b"403", client.recv(200).split(b"\r\n", 1)[0])
        status, _ = self.request("/api/control", data=b'{}', headers={"Content-Type": "application/json"})
        self.assertEqual(status, 403)

    def test_forged_listener_metadata_does_not_receive_secret(self):
        seen = []
        class Pretender(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_GET(self):
                seen.append((self.path, dict(self.headers)))
                raw = json.dumps(local.program_identity(bridge)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        bridge = self.bridge
        fake = ThreadingHTTPServer(("127.0.0.1", 0), Pretender)
        worker = threading.Thread(target=fake.serve_forever, daemon=True)
        worker.start()
        try:
            session = {"port": fake.server_port, "token": self.token,
                       "identity": local.program_identity(self.bridge)}
            with self.assertRaisesRegex(RuntimeError, "did not prove"):
                local.verify_listener(session, self.bridge, fake.server_port)
            self.assertEqual(len(seen), 1)
            self.assertNotIn("X-Clearings-Token", seen[0][1])
            self.assertIn("challenge=", seen[0][0])
        finally:
            fake.shutdown();fake.server_close();worker.join(3)

    def test_legacy_listener_fails_closed_without_sending_saved_token(self):
        local.atomic_json(self.bridge.root / "session.json",
                          {"port": self.port, "token": "old-plaintext-secret"})
        with self.assertRaisesRegex(RuntimeError, "Close the other program"):
            local.run_server(self.bridge, self.port, False, show_tray=False)
        with self.assertRaisesRegex(RuntimeError, "Close the earlier Clearings helper"):
            local.stop_server(self.bridge)
        self.assertEqual(local.load_json(self.bridge.root / "session.json")["token"], "old-plaintext-secret")

    def test_replay_and_expired_tickets_are_refused(self):
        stamp = int(time.monotonic() * 1000)
        self.assertTrue(self.launches.claim("a" * 43, stamp))
        self.assertFalse(self.launches.claim("a" * 43, stamp))
        self.launches.used["a" * 43] = time.monotonic() - 1
        self.assertFalse(self.launches.claim("a" * 43, stamp - 31000))
        with patch.object(local, "BOOTSTRAP_SECONDS", .01):
            nonce = self.launches.issue()
            time.sleep(.03)
            self.assertFalse(self.launches.redeem(nonce))

    def test_replay_cutoff_refuses_half_millisecond_expiry_edge(self):
        clock = [100.0]
        with patch.object(local.time, "monotonic", side_effect=lambda: clock[0]):
            self.assertTrue(self.launches.claim("boundary", 100000))
            clock[0] = 130.0005
            self.assertFalse(self.launches.claim("boundary", 100000))

    def test_busy_handlers_are_bounded_before_thread_creation(self):
        clients = []
        try:
            for _ in range(local.MAX_HANDLERS):
                client = socket.create_connection(("127.0.0.1", self.port), timeout=2)
                client.sendall(b"GET / HTTP/1.1\r\n")
                clients.append(client)
            deadline = time.monotonic() + 2
            while self.server.request_slots._value and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(self.server.request_slots._value, 0)
            with socket.create_connection(("127.0.0.1", self.port), timeout=2) as extra:
                extra.sendall(b"GET / HTTP/1.1\r\n")
                try:
                    self.assertIn(b"503", extra.recv(200).split(b"\r\n", 1)[0])
                except ConnectionAbortedError:
                    # Windows can abort a deliberately refused socket before
                    # the small 503 response reaches the client.
                    self.assertEqual(self.server.request_slots._value, 0)
        finally:
            for client in clients:
                client.close()


if __name__ == "__main__":
    unittest.main()
