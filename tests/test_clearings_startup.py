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
"""Bind-first startup regressions using only disposable config and ports."""
import base64
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

import test_clearings_security as fixtures

local = fixtures.local


class StartupChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clearings-startup-")
        self.bridge = local.Bridge(Path(self.temp.name) / "config")
        self.session_path = self.bridge.root / "session.json"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]

    def tearDown(self):
        self.temp.cleanup()

    def write_legacy(self, raw):
        self.session_path.write_bytes(raw)
        if local.os.name != "nt":
            self.session_path.chmod(0o600)

    def saved_backup(self):
        backups = list(self.bridge.root.glob("session-recovery-*.json"))
        self.assertEqual(len(backups), 1)
        envelope = json.loads(backups[0].read_text(encoding="ascii"))
        self.assertEqual(envelope["format"], "clearings-session-recovery-v1")
        payload = base64.b64decode(envelope["payload"], validate=True)
        return payload[::-1] if local.os.name == "nt" else payload

    def test_free_port_replaces_stale_legacy_only_after_retained_bind(self):
        original = b'{"port":8765,"token":"fixture-legacy","pid":101}\n'
        self.write_legacy(original)
        save_session = local.write_private_session
        def save_while_bound(path, session):
            with socket.socket() as competitor:
                with self.assertRaises(OSError):
                    competitor.bind(("127.0.0.1", self.port))
            return save_session(path, session)
        with patch.object(local, "_dpapi", side_effect=lambda data, protect: data[::-1]), \
                patch.object(local, "_listener_present", side_effect=AssertionError("pre-bind probe")), \
                patch.object(local, "write_private_session", side_effect=save_while_bound), \
                patch.object(local.LocalServer, "serve_forever", return_value=None):
            local.run_server(self.bridge, self.port, False, show_tray=False)
            session = local.load_private_session(self.session_path)
        self.assertEqual(session["port"], self.port)
        self.assertEqual(session["identity"], local.program_identity(self.bridge))
        self.assertEqual(self.saved_backup(), original)

    def test_free_port_replaces_stale_protected_with_recoverable_backup(self):
        former = {"port": self.port, "token": "fixture-stale", "identity": local.program_identity(self.bridge)}
        with patch.object(local, "_dpapi", side_effect=lambda data, protect: data[::-1]):
            local.write_private_session(self.session_path, former)
            original = self.session_path.read_bytes()
            with patch.object(local, "_listener_present", side_effect=AssertionError("pre-bind probe")), \
                    patch.object(local.LocalServer, "serve_forever", return_value=None):
                local.run_server(self.bridge, self.port, False, show_tray=False)
            self.assertNotEqual(local.load_private_session(self.session_path)["token"], former["token"])
        self.assertEqual(self.saved_backup(), original)

    def test_occupied_unknown_port_never_replaces_session_or_opens_browser(self):
        original = b'{"port":8765,"token":"fixture-legacy"}\n'
        self.write_legacy(original)
        with socket.socket() as occupant:
            occupant.bind(("127.0.0.1", self.port))
            occupant.listen()
            with patch.object(local.webbrowser, "open") as browser:
                with self.assertRaisesRegex(RuntimeError, "Close the other program"):
                    local.run_server(self.bridge, self.port, True, show_tray=False)
                browser.assert_not_called()
        self.assertEqual(self.session_path.read_bytes(), original)
        self.assertEqual(list(self.bridge.root.glob("session-recovery-*.json")), [])

    def test_matching_protected_incumbent_is_reused_only_after_authentication(self):
        session = {"port": self.port, "token": "fixture-incumbent",
                   "identity": local.program_identity(self.bridge)}
        with patch.object(local, "_dpapi", side_effect=lambda data, protect: data[::-1]):
            local.write_private_session(self.session_path, session)
            original = self.session_path.read_bytes()
            with socket.socket() as occupant:
                occupant.bind(("127.0.0.1", self.port))
                occupant.listen()
                with patch.object(local, "verify_listener", return_value=True) as verify:
                    local.run_server(self.bridge, self.port, False, show_tray=False)
                    verify.assert_called_once()
        self.assertEqual(self.session_path.read_bytes(), original)
        self.assertEqual(list(self.bridge.root.glob("session-recovery-*.json")), [])

    def test_uncertain_incumbent_does_not_replace_or_reuse_session(self):
        session = {"port": self.port, "token": "fixture-incumbent",
                   "identity": local.program_identity(self.bridge)}
        with patch.object(local, "_dpapi", side_effect=lambda data, protect: data[::-1]):
            local.write_private_session(self.session_path, session)
            original = self.session_path.read_bytes()
            with patch.object(local, "LocalServer", side_effect=OSError("fixture bind denial")), \
                    patch.object(local, "verify_listener", side_effect=TimeoutError("fixture timeout")), \
                    patch.object(local.webbrowser, "open") as browser:
                with self.assertRaises(TimeoutError):
                    local.run_server(self.bridge, self.port, True, show_tray=False)
                browser.assert_not_called()
        self.assertEqual(self.session_path.read_bytes(), original)
        self.assertEqual(list(self.bridge.root.glob("session-recovery-*.json")), [])

    def test_failed_start_restores_exact_legacy_session_and_closes_socket(self):
        original = b'{"port":8765,"token":"fixture-legacy"}\n'
        self.write_legacy(original)
        with patch.object(local, "_dpapi", side_effect=lambda data, protect: data[::-1]), \
                patch.object(local.webbrowser, "open", side_effect=RuntimeError("fixture browser failure")):
            with self.assertRaisesRegex(RuntimeError, "fixture browser failure"):
                local.run_server(self.bridge, self.port, True, show_tray=False)
        self.assertEqual(self.session_path.read_bytes(), original)
        self.assertEqual(self.saved_backup(), original)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", self.port))

    def test_oversized_session_is_refused_before_bind_or_replacement(self):
        self.session_path.write_bytes(b"x" * (local.MAX_BYTES + 1))
        with patch.object(local, "LocalServer") as server:
            with self.assertRaisesRegex(RuntimeError, "too large to preserve"):
                local.run_server(self.bridge, self.port, False, show_tray=False)
            server.assert_not_called()
        self.assertEqual(self.session_path.stat().st_size, local.MAX_BYTES + 1)
        self.assertEqual(list(self.bridge.root.glob("session-recovery-*.json")), [])

    def test_session_change_during_bind_is_not_overwritten(self):
        self.write_legacy(b'{"port":8765,"token":"first"}\n')
        changed = b'{"port":8765,"token":"second"}\n'
        make_server = local.LocalServer
        def change_then_bind(*args, **kwargs):
            self.write_legacy(changed)
            return make_server(*args, **kwargs)
        with patch.object(local, "LocalServer", side_effect=change_then_bind):
            with self.assertRaisesRegex(RuntimeError, "changed during startup"):
                local.run_server(self.bridge, self.port, False, show_tray=False)
        self.assertEqual(self.session_path.read_bytes(), changed)
        self.assertEqual(list(self.bridge.root.glob("session-recovery-*.json")), [])
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", self.port))


if __name__ == "__main__":
    unittest.main()
