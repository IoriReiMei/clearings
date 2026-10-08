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
"""Disposable controls for the explicit, lossless resolved-history archive."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "clearings_local.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("clearings_local_archive_control", SCRIPT)
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


class ResolvedArchive(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        home = root / "home"
        home.mkdir()
        bridge = local.Bridge(root / "config")
        bridge.set_home(str(home))
        packet = {
            "format": "clearings-local-handoff", "schemaVersion": 1,
            "libraryId": "archive-fixture", "generation": 17,
            "snapshotAt": "fixed", "snapshot": {"format": "checklist-studio-workspace",
                                             "index": {"libraryId": "archive-fixture"},
                                             "documents": [], "unknownSnapshot": [1, 2]},
            "proposals": [
                {"id": "applied", "documentId": "list", "status": "applied",
                 "base": {"large": "a" * 500}, "incoming": {"large": "b" * 500},
                 "unknownProposal": {"keep": True}},
                {"id": "signed-pending", "documentId": "list", "status": "pending",
                 "commit": {"id": "signature", "author": "Morrow"},
                 "base": {"older": 1}, "incoming": {"newer": 2}},
                {"id": "dismissed", "documentId": "list", "status": "dismissed",
                 "base": {"old": 1}, "incoming": {"new": 2}},
                {"id": "future", "documentId": "list", "status": "future-status",
                 "unknownProposal": "preserve"}],
            "receipts": [{"proposalId": "applied", "status": "applied"}],
            "unknownTopLevel": {"mustSurvive": ["x", "y"]}}
        local.atomic_json(bridge.handoff_path(), packet)
        return bridge, packet

    def test_preview_then_archive_preserves_full_preimage_and_active_work(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, before = self.fixture(directory)
            path = bridge.handoff_path()
            original = path.read_bytes()
            preview = bridge.archive_resolved(dry_run=True)
            self.assertFalse(preview["changed"])
            self.assertEqual(preview["archived"], 2)
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse((bridge.home() / "archives").exists())

            receipt = bridge.archive_resolved()
            self.assertTrue(receipt["changed"])
            self.assertLess(receipt["activeCompactBytes"], len(original))
            self.assertEqual(receipt["archive"], preview["archive"])
            archive = bridge.home() / receipt["archive"]["file"]
            self.assertEqual(archive.read_bytes(), original)

            self.assertEqual(receipt["archive"]["sha256"],
                             hashlib.sha256(original).hexdigest())
            self.assertEqual(receipt["archive"]["bytes"], len(original))
            active = bridge.read()
            self.assertEqual(active["generation"], before["generation"])
            self.assertEqual(active["libraryId"], before["libraryId"])
            self.assertEqual(active["snapshot"], before["snapshot"])
            self.assertEqual(active["receipts"], before["receipts"])
            self.assertEqual(active["unknownTopLevel"], before["unknownTopLevel"])
            self.assertEqual([p["id"] for p in active["proposals"]],
                             ["signed-pending", "future"])
            self.assertEqual(active["proposals"][0], before["proposals"][1])
            self.assertEqual(active["proposals"][1], before["proposals"][3])
            self.assertEqual(active["resolvedProposalArchives"], [receipt["archive"]])
            self.assertEqual([p["id"] for p in bridge.browser_handoff()["proposals"]
                              if p["status"] == "pending"], ["signed-pending"])
            compact_bytes = path.read_bytes()
            self.assertEqual(bridge.archive_resolved()["changed"], False)
            self.assertEqual(path.read_bytes(), compact_bytes)
            self.assertEqual(archive.read_bytes(), original)

    def test_later_explicit_archive_keeps_earlier_reference_traversable(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, _ = self.fixture(directory)
            first = bridge.archive_resolved()["archive"]
            active = bridge.read()
            active["proposals"][0]["status"] = "applied"
            local.atomic_json(bridge.handoff_path(), active)
            second = bridge.archive_resolved()["archive"]
            self.assertNotEqual(first["sha256"], second["sha256"])
            self.assertEqual(bridge.read()["resolvedProposalArchives"], [first, second])
            older = json.loads((bridge.home() / first["file"]).read_text(encoding="utf-8"))
            newer = json.loads((bridge.home() / second["file"]).read_text(encoding="utf-8"))
            self.assertEqual([p["id"] for p in older["proposals"][:2]],
                             ["applied", "signed-pending"])
            self.assertEqual(newer["resolvedProposalArchives"], [first])

    def test_interruption_after_archive_is_recoverable_without_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, _ = self.fixture(directory)
            path = bridge.handoff_path()
            original = path.read_bytes()
            expected_archive = bridge.home() / bridge.archive_resolved(True)["archive"]["file"]
            with patch.object(local, "atomic_json", side_effect=RuntimeError("replacement stopped")):
                with self.assertRaisesRegex(RuntimeError, "replacement stopped"):
                    bridge.archive_resolved()
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(expected_archive.read_bytes(), original)
            self.assertTrue(bridge.archive_resolved()["changed"])
            self.assertEqual(expected_archive.read_bytes(), original)
            self.assertEqual(len(list((bridge.home() / "archives").iterdir())), 1)

    def test_interruption_before_archive_publication_leaves_active_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, _ = self.fixture(directory)
            path = bridge.handoff_path()
            original = path.read_bytes()
            archive = bridge.home() / bridge.archive_resolved(True)["archive"]["file"]
            with patch.object(local.os, "replace", side_effect=RuntimeError("publication stopped")):
                with self.assertRaisesRegex(RuntimeError, "publication stopped"):
                    bridge.archive_resolved()
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(archive.exists())
            self.assertEqual(len(list(archive.parent.glob("*.part"))), 1)
            self.assertTrue(bridge.archive_resolved()["changed"])
            self.assertEqual(archive.read_bytes(), original)

    def test_corrupt_preexisting_archive_refuses_active_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, _ = self.fixture(directory)
            path = bridge.handoff_path()
            original = path.read_bytes()
            archive = bridge.home() / bridge.archive_resolved(True)["archive"]["file"]
            archive.parent.mkdir()
            archive.write_bytes(b"not the handoff")
            with self.assertRaisesRegex(ValueError, "Archive verification failed"):
                bridge.archive_resolved()
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(archive.read_bytes(), b"not the handoff")

    def test_cli_dry_run_uses_only_disposable_config(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, _ = self.fixture(directory)
            original = bridge.handoff_path().read_bytes()
            result = subprocess.run([sys.executable, "-B", str(SCRIPT),
                                     "--config-dir", str(bridge.root),
                                     "archive-resolved", "--dry-run"],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["archived"], 2)
            self.assertEqual(bridge.handoff_path().read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
