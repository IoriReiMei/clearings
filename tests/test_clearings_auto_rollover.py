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

"""Disposable checks for pressure rollover of exact resolved-handoff history."""
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_clearings_handoff_size_repair as fixtures

local = fixtures.local


def encoded(packet):
    return (json.dumps(packet, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


class AutomaticResolvedRollover(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clearings-rollover-",
                                                dir=Path(__file__).parent)
        root = Path(self.temp.name)
        home = root / "home"
        home.mkdir()
        self.bridge = local.Bridge(root / "config")
        self.bridge.set_home(str(home))
        self.path = self.bridge.handoff_path()
        packet = self.bridge.read()
        packet.update(libraryId="fixture-library", generation=41,
                      snapshot={"index": {"libraryId": "fixture-library"},
                                "documents": [], "futureSnapshot": [1, 2]},
                      proposals=[
                          {"id": "old", "status": "applied", "documentId": "list",
                           "base": {"text": "A" * 500},
                           "incoming": {"text": "B" * 500},
                           "unknownProposal": {"keep": True}},
                          {"id": "pending", "status": "pending", "documentId": "list",
                           "base": {"text": "C" * 50},
                           "incoming": {"text": "D" * 50},
                           "commit": {"author": "Linden"}}],
                      receipts=[{"proposalId": "old", "status": "applied"}],
                      futureTopLevel={"keep": [3, 4]})
        local.atomic_json(self.path, packet, compact=True)
        self.original = self.path.read_bytes()
        self.before = packet

    def tearDown(self):
        self.temp.cleanup()

    def cap(self):
        return patch.object(local, "MAX_HANDOFF_BYTES", len(self.original) + 1)

    def archive(self):
        descriptor = self.bridge.read()["resolvedProposalArchives"][-1]
        archive = self.bridge.home() / descriptor["file"]
        self.assertEqual(archive.read_bytes(), self.original)
        self.assertEqual(descriptor["sha256"], hashlib.sha256(self.original).hexdigest())
        self.assertEqual(descriptor["bytes"], len(self.original))
        return descriptor

    def test_pressure_rollover_keeps_pending_unknowns_receipts_and_generation(self):
        new = {"id": "new", "status": "pending", "documentId": "other",
               "incoming": {"text": "new" * 12}, "unknownProposal": [5]}
        with self.cap():
            self.bridge.change(lambda packet: packet["proposals"].append(new) or True)
        active = self.bridge.read()
        self.assertEqual([p["id"] for p in active["proposals"]], ["pending", "new"])
        self.assertEqual(active["proposals"], [self.before["proposals"][1], new])
        self.assertEqual(active["snapshot"], self.before["snapshot"])
        self.assertEqual(active["receipts"], self.before["receipts"])
        self.assertEqual(active["futureTopLevel"], self.before["futureTopLevel"])
        self.assertEqual(active["generation"], 41)
        self.assertEqual(self.archive()["resolvedProposalIds"], ["old"])

    def test_newly_resolved_entry_is_not_removed_by_same_edit(self):
        def edit(packet):
            packet["proposals"][1]["status"] = "applied"
            packet["receipts"].append({"proposalId": "pending", "status": "applied",
                                       "summary": "A" * 100})
            return True
        with self.cap():
            self.bridge.change(edit)
        self.assertEqual([p["id"] for p in self.bridge.read()["proposals"]], ["pending"])
        self.assertEqual(self.archive()["resolvedProposalIds"], ["old"])

    def test_nonarchivable_oversize_edit_leaves_everything_intact(self):
        # Even removing every old terminal proposal would not make this fit.
        with self.cap(), self.assertRaisesRegex(ValueError, "after archiving resolved history"):
            self.bridge.change(lambda packet: packet.update(
                futureTopLevel={"huge": "Q" * 4000}) or True)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse((self.bridge.home() / "archives").exists())

    def test_only_pending_history_cannot_be_evicted(self):
        only_pending = copy.deepcopy(self.before)
        only_pending["proposals"] = [only_pending["proposals"][1]]
        local.atomic_json(self.path, only_pending, compact=True)
        original = self.path.read_bytes()
        with patch.object(local, "MAX_HANDOFF_BYTES", len(original) + 1):
            with self.assertRaisesRegex(ValueError, "nothing was written"):
                self.bridge.change(lambda packet: packet.update(
                    futureTopLevel={"huge": "Q" * 1000}) or True)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse((self.bridge.home() / "archives").exists())

    def test_failed_active_replace_is_recoverable_without_duplicate(self):
        new = {"id": "new", "status": "pending", "documentId": "other",
               "incoming": {"text": "new" * 12}}
        with self.cap():
            with patch.object(local, "atomic_json", side_effect=RuntimeError("replace stopped")):
                with self.assertRaisesRegex(RuntimeError, "replace stopped"):
                    self.bridge.change(lambda packet: packet["proposals"].append(new) or True)
            self.assertEqual(self.path.read_bytes(), self.original)
            self.assertEqual(len(list((self.bridge.home() / "archives").glob("*.json"))), 1)
            self.bridge.change(lambda packet: packet["proposals"].append(new) or True)
        self.assertEqual(len(list((self.bridge.home() / "archives").glob("*.json"))), 1)
        self.assertEqual(self.archive()["resolvedProposalIds"], ["old"])

    def test_corrupt_existing_archive_refuses_active_replacement(self):
        digest = hashlib.sha256(self.original).hexdigest()
        archive = self.bridge.home() / "archives" / ("clearings-resolved-" + digest + ".json")
        archive.parent.mkdir()
        archive.write_bytes(b"corrupt")
        with self.cap(), self.assertRaisesRegex(ValueError, "Archive verification failed"):
            self.bridge.change(lambda packet: packet["proposals"].append(
                {"id": "new", "status": "pending", "incoming": {"x": "Q" * 50}}) or True)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(archive.read_bytes(), b"corrupt")

    def test_changed_old_terminal_entry_is_not_removed(self):
        def edit(packet):
            packet["proposals"][0]["unknownProposal"]["keep"] = "changed"
            packet["proposals"].append({"id": "new", "status": "pending",
                                         "documentId": "other", "incoming": {"x": 1}})
            return True
        with self.cap(), self.assertRaisesRegex(ValueError, "nothing was written"):
            self.bridge.change(edit)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse((self.bridge.home() / "archives").exists())

    def test_edit_cannot_drop_pending_or_existing_archive_index(self):
        def drop_pending(packet):
            packet["proposals"] = [p for p in packet["proposals"]
                                   if p["id"] != "pending"]
            packet["futureTopLevel"] = {"huge": "Q" * 2000}
            return True
        with self.cap(), self.assertRaisesRegex(ValueError, "history changed unexpectedly"):
            self.bridge.change(drop_pending)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse((self.bridge.home() / "archives").exists())

    def test_two_locked_edits_keep_both_new_pending_entries(self):
        def add(identifier):
            def edit(packet):
                packet["proposals"].append({"id": identifier, "status": "pending",
                                             "documentId": identifier,
                                             "incoming": {"x": "Q" * 30}})
                return True
            return self.bridge.change(edit)
        with self.cap(), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(add, identifier) for identifier in ("one", "two")]
            for future in futures:
                self.assertTrue(future.result(timeout=10))
        active = self.bridge.read()
        self.assertEqual({p["id"] for p in active["proposals"]},
                         {"pending", "one", "two"})
        self.assertEqual(self.archive()["resolvedProposalIds"], ["old"])


class ActualCollaborationRollover(unittest.TestCase):
    def test_propose_commit_effective_read_and_sync_after_pressure(self):
        example = (Path(__file__).resolve().parents[1] / "examples" / "generic" /
                   "program_overview.json")
        document = json.loads(example.read_text(encoding="utf-8"))
        list_id = document["documentId"]
        workspace = {"format": "checklist-studio-workspace", "schemaVersion": 1,
                     "index": {"libraryId": "fixture-library", "defaultChecklist": list_id,
                               "entries": [{"id": list_id,
                                            "file": f"checklist-{list_id}.json"}]},
                     "documents": [document]}
        with tempfile.TemporaryDirectory(prefix="clearings-api-rollover-",
                                         dir=Path(__file__).parent) as folder:
            root = Path(folder)
            home = root / "home"
            home.mkdir()
            bridge = local.Bridge(root / "config")
            bridge.set_home(str(home))
            bridge.sync(workspace, 1)
            first = copy.deepcopy(document)
            first["title"] = "First assistant's completed title"
            old_id = bridge.propose(document, first, "Morrow")["proposalId"]
            bridge.commit_proposal(old_id, "Morrow")
            browser_copy = copy.deepcopy(workspace)
            browser_copy["documents"][0] = first
            bridge.sync(browser_copy, 2, 1)
            bridge.mark(old_id, "applied", "Browser accepted first title", "Hermit")
            old_bytes = bridge.handoff_path().read_bytes()

            current = bridge.read_checklist(list_id)["effectiveDocument"]
            second = copy.deepcopy(current)
            second["description"] = "A later signed assistant edit"
            with patch.object(local, "MAX_HANDOFF_BYTES", len(old_bytes) + 1000):
                new_id = bridge.propose(current, second, "Linden")["proposalId"]
                commit = bridge.commit_proposal(new_id, "Linden")["commit"]
                readback = bridge.read_checklist(list_id)
                self.assertEqual(readback["effectiveDocument"]["description"],
                                 second["description"])
                self.assertEqual(readback["committedAwaitingBrowser"][0]["proposalId"], new_id)
                self.assertEqual(commit["author"], "Linden")
                bridge.sync(browser_copy, 3, 2)
            active = bridge.read()
            self.assertEqual(active["generation"], 3)
            self.assertEqual([p["id"] for p in active["proposals"]], [new_id])
            self.assertEqual(active["proposals"][0]["commit"], commit)
            self.assertEqual(active["receipts"][-1]["proposalId"], old_id)
            descriptor = active["resolvedProposalArchives"][0]
            self.assertEqual(descriptor["resolvedProposalIds"], [old_id])
            self.assertEqual((home / descriptor["file"]).read_bytes(), old_bytes)


if __name__ == "__main__":
    unittest.main()
