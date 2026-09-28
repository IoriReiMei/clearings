# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Disposable local-helper checks; never touch an owner's browser profile."""
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest

MODULE = Path(__file__).resolve().parent.parent / "tools" / "clearings_local.py"
spec = importlib.util.spec_from_file_location("clearings_local", MODULE)
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


class BridgeChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.bridge = local.Bridge(root / "config")
        self.home = root / "home"
        self.home.mkdir()
        self.bridge.set_home(str(self.home))
        self.document = json.loads((MODULE.parent.parent / "examples" / "generic" /
                                    "program_overview.json").read_text(encoding="utf-8"))
        self.workspace = {"format": "checklist-studio-workspace", "schemaVersion": 1,
                          "index": {"libraryId": "test-library"}, "documents": [self.document]}

    def tearDown(self):
        self.temp.cleanup()

    def test_snapshot_proposal_receipt_and_no_retrograde_sync(self):
        self.bridge.sync(self.workspace, 1)
        incoming = json.loads(json.dumps(self.document))
        incoming["model"]["items"][0]["text"] = "New title"
        result = self.bridge.propose(self.document, incoming, "Assistant tester")
        packet = self.bridge.read()
        self.assertEqual(packet["proposals"][0]["id"], result["proposalId"])
        self.assertEqual(packet["snapshot"]["index"]["libraryId"], "test-library")
        self.bridge.sync(self.workspace, 2)
        with self.assertRaisesRegex(ValueError, "older generation"):
            self.bridge.sync(self.workspace, 1)
        self.bridge.mark(result["proposalId"], "applied", "One title changed", "Human tester")
        self.assertEqual(self.bridge.read()["receipts"][-1]["status"], "applied")

    def test_pending_work_prevents_home_switch_and_source_is_preserved(self):
        self.bridge.sync(self.workspace, 1)
        result = self.bridge.propose(self.document, self.document, "Assistant tester")
        other = Path(self.temp.name) / "other"
        other.mkdir()
        with self.assertRaisesRegex(ValueError, "pending"):
            self.bridge.set_home(str(other))
        self.assertEqual(self.bridge.read()["proposals"][0]["status"], "pending")
        self.bridge.mark(result["proposalId"], "dismissed", "Practice only", "Human tester")
        self.assertEqual(self.bridge.set_home(str(other)), str(other.resolve()))

    def test_removal_proposal_is_refused_without_changing_handoff(self):
        self.bridge.sync(self.workspace, 1)
        before = self.bridge.read()
        incoming = json.loads(json.dumps(self.document))
        incoming["model"]["items"] = incoming["model"]["items"][1:]
        with self.assertRaisesRegex(ValueError, "Removing existing items"):
            self.bridge.propose(self.document, incoming, "Assistant tester")
        self.assertEqual(self.bridge.read(), before)

    def test_equal_generation_cannot_replace_different_browser_content(self):
        self.bridge.sync(self.workspace, 1)
        before = self.bridge.read()
        divergent = json.loads(json.dumps(self.workspace))
        divergent["documents"][0]["title"] = "A different browser title"
        with self.assertRaisesRegex(ValueError, "different content"):
            self.bridge.sync(divergent, 1)
        self.assertEqual(self.bridge.read(), before)

    def test_stale_browser_expectation_cannot_replace_newer_handoff(self):
        self.bridge.sync(self.workspace, 1, 0)
        self.bridge.sync(self.workspace, 2, 1)
        before = self.bridge.read()
        with self.assertRaisesRegex(ValueError, "generation changed"):
            self.bridge.sync(self.workspace, 3, 1)
        self.assertEqual(self.bridge.read(), before)

    def test_public_copy_uses_a_separate_stable_origin(self):
        expected = ("release", 18765) if local.APP.name == "index.html" else ("working", 8765)
        self.assertEqual((local.CHANNEL, local.PORT), expected)
        alternate = Path(self.temp.name) / "alternate"
        (alternate / "tools").mkdir(parents=True)
        shutil.copyfile(MODULE, alternate / "tools" / "clearings_local.py")
        alternate_app = "LC_CHECKLIST.html" if expected[0] == "release" else "index.html"
        (alternate / alternate_app).write_text("alternate test page", encoding="utf-8")
        spec = importlib.util.spec_from_file_location("clearings_alternate_test", alternate / "tools" / "clearings_local.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        other = ("working", 8765) if expected[0] == "release" else ("release", 18765)
        self.assertEqual((module.CHANNEL, module.PORT), other)
        self.assertEqual(module.APP.resolve(), (alternate / alternate_app).resolve())

    def test_only_the_same_installed_program_may_be_reused(self):
        bridge = self.bridge
        identity = local.program_identity(bridge)
        response = {"value": identity}

        class IdentityHandler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(response["value"]).encode("utf-8"))

        server = ThreadingHTTPServer(("127.0.0.1", 0), IdentityHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            local.atomic_json(bridge.root / "session.json", {"port": port, "token": "fixture-token"})
            local.run_server(bridge, port, False)
            response["value"] = {**identity, "appSha256": "another-version"}
            with self.assertRaisesRegex(RuntimeError, "Another Clearings copy or version"):
                local.run_server(bridge, port, False)
            self.assertEqual(local.load_json(bridge.root / "session.json")["token"], "fixture-token")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_occupied_port_without_matching_session_is_not_silently_reused(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        try:
            with self.assertRaisesRegex(RuntimeError, "cannot use 127.0.0.1"):
                local.run_server(self.bridge, server.server_address[1], False)
            self.assertFalse((self.bridge.root / "session.json").exists())
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
