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
"""Disposable aggregate-handoff capacity checks; no owner home is opened."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import test_clearings_handoff_size_repair as fixtures

local = fixtures.local


class AggregateHandoffCapacity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clearings-capacity-")
        root = Path(self.temp.name)
        home = root / "home"
        home.mkdir()
        self.bridge = local.Bridge(root / "config")
        self.bridge.set_home(str(home))
        self.path = self.bridge.handoff_path()

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def proposal(identifier, status, size=100):
        return {"id": identifier, "documentId": "fixture-list", "status": status,
                "base": {"text": "A" * size}, "incoming": {"text": "B" * size},
                "unknownProposal": {"actor": "Morrow", "keep": [1, 2]}}

    def test_aggregate_handoff_crosses_generic_limit_without_loss(self):
        self.assertEqual(local.MAX_BYTES, 16 * 1024 * 1024)
        self.assertEqual(local.MAX_HANDOFF_BYTES, 64 * 1024 * 1024)
        with patch.object(local, "MAX_BYTES", 512), patch.object(local, "MAX_HANDOFF_BYTES", 8192):
            proposals = [self.proposal(str(i), "pending", 250) for i in range(4)]
            def edit(packet):
                packet.update(libraryId="fixture-lib", generation=7,
                              proposals=proposals, unknownTopLevel={"preserve": True})
                return True
            self.bridge.change(edit)
            original = self.path.read_bytes()
            self.assertGreater(len(original), local.MAX_BYTES)
            self.assertLess(len(original), local.MAX_HANDOFF_BYTES)
            saved = self.bridge.read()
            self.assertEqual(saved["proposals"], proposals)
            self.assertEqual(saved["unknownTopLevel"], {"preserve": True})
            self.assertEqual(saved["generation"], 7)
            self.assertEqual(self.path.read_bytes(), original)

    def test_handoff_cap_refuses_atomically_and_generic_cap_stays_small(self):
        self.bridge.change(lambda packet: packet.update(libraryId="fixture-lib") or True)
        original = self.path.read_bytes()
        with patch.object(local, "MAX_BYTES", 512), patch.object(local, "MAX_HANDOFF_BYTES", 3000):
            with self.assertRaisesRegex(ValueError, "Handoff exceeds 3000 bytes; nothing was written"):
                self.bridge.change(lambda packet: packet.update(
                    proposals=[self.proposal("too-large", "pending", 2000)]) or True)
            self.assertEqual(self.path.read_bytes(), original)
            incoming = Path(self.temp.name) / "incoming.json"
            incoming.write_bytes(b'{"payload":"' + b"x" * 513 + b'"}')
            with self.assertRaisesRegex(ValueError, "exceeds 512 bytes"):
                local.load_json(incoming)
            with self.assertRaisesRegex(ValueError, "nothing was written"):
                local.atomic_json(incoming, {"payload": "y" * 513})
            self.assertEqual(incoming.read_bytes(), b'{"payload":"' + b"x" * 513 + b'"}')

    def test_incoming_http_keeps_its_document_and_control_limits(self):
        token = "fixture-token"
        server = local.LocalServer(("127.0.0.1", 0),
                                   local.handler_for(self.bridge, token, 0, local.LaunchState()))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        original = self.bridge.read()
        try:
            with patch.object(local, "MAX_BYTES", 512):
                for endpoint, body, headers in (
                    ("sync", b"x" * 513, {"X-Clearings-Token": token}),
                    ("control", b"x" * 4097, {}),
                ):
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/api/{endpoint}",
                        data=body, headers={"Content-Type": "application/json", **headers})
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(request, timeout=3)
                    self.assertEqual(caught.exception.code, 413)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(3)
        self.assertEqual(self.bridge.read(), original)

    def test_real_size_handoff_is_readable_and_archives_exact_preimage(self):
        packet = self.bridge.read()
        packet.update(libraryId="fixture-lib", generation=7,
                      snapshot={"format": "checklist-studio-workspace",
                                "index": {"libraryId": "fixture-lib"}, "documents": []},
                      proposals=[self.proposal("resolved", "applied"),
                                 self.proposal("pending", "pending")],
                      unknownTopLevel={"large": "q" * (local.MAX_BYTES + 1024)})
        local.atomic_json(self.path, packet, max_bytes=local.MAX_HANDOFF_BYTES, compact=True)
        original = self.path.read_bytes()
        self.assertGreater(len(original), local.MAX_BYTES)
        self.assertLess(len(original), local.MAX_HANDOFF_BYTES)
        self.assertEqual(self.bridge.read(), packet)
        preview = self.bridge.archive_resolved(dry_run=True)
        self.assertEqual(preview["archived"], 1)
        self.assertEqual(self.path.read_bytes(), original)
        receipt = self.bridge.archive_resolved()
        archive = self.bridge.home() / receipt["archive"]["file"]
        self.assertEqual(archive.read_bytes(), original)
        self.assertEqual(receipt["archive"]["sha256"], hashlib.sha256(original).hexdigest())
        active = self.bridge.read()
        self.assertEqual([p["id"] for p in active["proposals"]], ["pending"])
        self.assertEqual(active["proposals"][0], packet["proposals"][1])
        self.assertEqual(active["unknownTopLevel"], packet["unknownTopLevel"])
        self.assertEqual(active["generation"], 7)
        self.assertEqual(active["resolvedProposalArchives"], [receipt["archive"]])
        self.assertGreater(len(self.path.read_bytes()), local.MAX_BYTES)
        before = self.path.read_bytes()
        workspace = packet["snapshot"]
        with self.assertRaisesRegex(ValueError, "generation changed"):
            self.bridge.sync(workspace, 8, 6)
        changed_library = json.loads(json.dumps(workspace))
        changed_library["index"]["libraryId"] = "other-lib"
        with self.assertRaisesRegex(ValueError, "another checklist library"):
            self.bridge.sync(changed_library, 8, 7)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
