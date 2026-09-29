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
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

MODULE = Path(__file__).resolve().parent.parent / "tools" / "clearings_local.py"
sys.path.insert(0, str(MODULE.parent))
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
                          "index": {"libraryId": "test-library", "defaultChecklist": self.document["documentId"],
                                    "entries": [{"id": self.document["documentId"],
                                                 "file": f"checklist-{self.document['documentId']}.json"}]},
                          "documents": [self.document]}

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

    def test_new_checklist_is_unique_pending_and_unchecked(self):
        self.bridge.sync(self.workspace, 1)
        new = json.loads(json.dumps(self.document))
        new["documentId"] = "new-review-list"
        new["title"] = "A new review list"
        new["state"] = {}
        before = self.bridge.read()
        checked = json.loads(json.dumps(new))
        checked["state"][checked["model"]["items"][0]["id"]] = True
        with self.assertRaisesRegex(ValueError, "unchecked"):
            self.bridge.propose_new(checked, "Assistant tester")
        self.assertEqual(self.bridge.read(), before)
        result = self.bridge.propose_new(new, "Assistant tester")
        self.assertEqual(self.bridge.read()["proposals"][-1]["kind"], "create")
        with self.assertRaisesRegex(ValueError, "pending proposal"):
            self.bridge.propose_new(new, "Other assistant")
        self.assertEqual(self.bridge.read()["snapshot"], self.workspace)
        self.bridge.mark(result["proposalId"], "dismissed", "Cancelled in review", "Human tester")
        self.workspace["documents"].append(new)
        self.bridge.sync(self.workspace, 2)
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.bridge.propose_new(new, "Other assistant")

    def test_ai_refresh_includes_other_assistant_pending_without_applying(self):
        self.bridge.sync(self.workspace, 1)
        incoming = json.loads(json.dumps(self.document))
        incoming["title"] = "Pending title"
        self.bridge.propose(self.document, incoming, "Morrow")
        before = self.bridge.handoff_path().read_bytes()
        refreshed = self.bridge.refresh_for_ai()
        self.assertEqual(refreshed["generation"], 1)
        self.assertEqual(refreshed["savedWorkspace"]["documents"][0]["title"], self.document["title"])
        self.assertEqual(refreshed["pendingUnapplied"][0]["incoming"]["title"], "Pending title")
        self.assertTrue(refreshed["readOnly"])
        self.assertEqual(self.bridge.handoff_path().read_bytes(), before)

    def test_committed_completion_is_visible_to_ai_before_browser_refresh(self):
        self.bridge.sync(self.workspace, 1)
        item_id = self.document["model"]["items"][0]["id"]
        incoming = json.loads(json.dumps(self.document))
        incoming["state"][item_id] = True
        proposal_id = self.bridge.propose(self.document, incoming, "Linden")["proposalId"]
        self.assertFalse(self.bridge.read_checklist(self.document["documentId"])
                         ["effectiveDocument"]["state"].get(item_id, False))
        committed = self.bridge.commit_completions(proposal_id, "Linden")
        self.assertEqual(committed["itemIds"], [item_id])
        self.assertTrue(self.bridge.commit_completions(proposal_id, "Linden")["alreadyCommitted"])
        before_read = self.bridge.handoff_path().read_bytes()
        result = self.bridge.read_checklist(self.document["documentId"])
        self.assertTrue(result["effectiveDocument"]["state"][item_id])
        self.assertFalse(result["savedDocument"]["state"].get(item_id, False))
        self.assertEqual(result["committedAwaitingBrowser"][0]["actor"], "Linden")
        self.assertTrue(self.bridge.read_checklist(self.document["documentId"], item_id)
                        ["branch"]["state"][item_id])
        self.assertTrue(self.bridge.refresh_for_ai()["effectiveWorkspace"]["documents"][0]
                        ["state"][item_id])
        self.assertEqual(self.bridge.read()["proposals"][0]["status"], "pending")
        self.assertEqual(self.bridge.handoff_path().read_bytes(), before_read)

        # A browser update can still apply the original proposal and blue activity.
        self.bridge.sync({**self.workspace, "documents": [incoming]}, 2)
        self.bridge.mark(proposal_id, "applied", "Displayed", "Hermit")
        settled = self.bridge.read_checklist(self.document["documentId"])
        self.assertTrue(settled["savedDocument"]["state"][item_id])
        self.assertEqual(settled["committedAwaitingBrowser"], [])

    def test_only_pure_checkmark_proposals_can_be_committed(self):
        self.bridge.sync(self.workspace, 1)
        mixed = json.loads(json.dumps(self.document))
        item_id = mixed["model"]["items"][0]["id"]
        mixed["state"][item_id] = True
        mixed["title"] = "Also rename"
        mixed_id = self.bridge.propose(self.document, mixed, "Linden")["proposalId"]
        before = self.bridge.handoff_path().read_bytes()
        with self.assertRaisesRegex(ValueError, "also changes"):
            self.bridge.commit_completions(mixed_id, "Linden")
        self.assertEqual(self.bridge.handoff_path().read_bytes(), before)

        incoming = json.loads(json.dumps(self.document))
        incoming["state"][item_id] = True
        proposal_id = self.bridge.propose(self.document, incoming, "Linden")["proposalId"]
        changed_saved = json.loads(json.dumps(self.workspace))
        changed_saved["documents"][0]["state"][item_id] = True
        self.bridge.sync(changed_saved, 2)
        with self.assertRaisesRegex(ValueError, "no new shared change"):
            self.bridge.commit_completions(proposal_id, "Linden")

    def test_full_and_partial_reads_preserve_context_and_handoff(self):
        doc = json.loads(json.dumps(self.document))
        ids = [item["id"] for item in doc["model"]["items"]]
        self.assertGreaterEqual(len(ids), 3)
        # Construct a small shared branch independent of the example's hierarchy.
        a, b, c = ids[:3]
        doc["model"]["roots"] = [a, b]
        for item in doc["model"]["items"]:
            item["requires"] = []
        doc["model"]["items"] = doc["model"]["items"][:3]
        doc["model"]["items"][0]["requires"] = [c]
        doc["model"]["items"][1]["requires"] = [c]
        doc["state"] = {c: True}
        self.workspace["documents"] = [doc]
        self.bridge.sync(self.workspace, 1)
        self.bridge.propose(doc, json.loads(json.dumps(doc)), "Other AI")
        before = self.bridge.handoff_path().read_bytes()
        full = self.bridge.read_checklist(doc["documentId"])
        self.assertFalse(full["partial"])
        self.assertEqual(full["savedDocument"], doc)
        branch = self.bridge.read_checklist(doc["documentId"], c)
        self.assertTrue(branch["partial"])
        self.assertTrue(branch["branch"]["notAProposalBase"])
        self.assertEqual(branch["branch"]["descendantIds"], [c])
        self.assertEqual(set(branch["branch"]["ancestorAndSharedParentIds"]), {a, b})
        self.assertEqual(set(branch["branch"]["incomingLinks"][c]), {a, b})
        self.assertTrue(branch["branch"]["state"][c])
        self.assertEqual(len(branch["pendingUnapplied"]), 1)
        with self.assertRaisesRegex(ValueError, "Unknown branch"):
            self.bridge.read_checklist(doc["documentId"], "absent")
        with self.assertRaisesRegex(ValueError, "Unknown checklist ID"):
            self.bridge.read_checklist("absent")
        self.assertEqual(self.bridge.handoff_path().read_bytes(), before)

    def test_two_assistants_commit_independent_edits_without_browser_refresh(self):
        self.bridge.sync(self.workspace, 1)
        ids = [item["id"] for item in self.document["model"]["items"][:2]]
        self.assertEqual(len(ids), 2)
        first = json.loads(json.dumps(self.document))
        second = json.loads(json.dumps(self.document))
        first["model"]["items"][0]["detail"] = "Linden detail"
        second["model"]["items"][1]["text"] = "Morrow title"
        one = self.bridge.propose(self.document, first, "Linden")["proposalId"]
        two = self.bridge.propose(self.document, second, "Morrow")["proposalId"]
        self.assertTrue(all(p["requiresCommit"] for p in self.bridge.read()["proposals"]))
        self.assertEqual(self.bridge.browser_handoff()["proposals"], [])
        self.assertEqual(self.bridge.refresh_for_ai()["effectiveWorkspace"]["documents"][0], self.document)
        signed_one = self.bridge.commit_proposal(one, "Linden")
        signed_two = self.bridge.commit_proposal(two, "Morrow")
        self.assertEqual(len(self.bridge.browser_handoff()["proposals"]), 2)
        self.assertEqual(signed_one["commit"]["author"], "Linden")
        self.assertEqual(signed_two["commit"]["author"], "Morrow")
        self.assertEqual(self.bridge.commit_proposal(two, "Morrow")["commit"], signed_two["commit"])
        with self.assertRaisesRegex(ValueError, "another author"):
            self.bridge.commit_proposal(two, "Linden")
        effective = self.bridge.read_checklist(self.document["documentId"])
        by_id = {item["id"]: item for item in effective["effectiveDocument"]["model"]["items"]}
        self.assertEqual(by_id[ids[0]]["detail"], "Linden detail")
        self.assertEqual(by_id[ids[1]]["text"], "Morrow title")
        self.assertEqual(effective["savedDocument"], self.document)
        self.assertEqual([x["actor"] for x in effective["committedAwaitingBrowser"]], ["Linden", "Morrow"])

    def test_legacy_drafts_can_be_signed_in_order_without_browser_refresh(self):
        self.bridge.sync(self.workspace, 1)
        first = json.loads(json.dumps(self.document))
        first["model"]["items"][0]["text"] = "Morrow heading"
        second = json.loads(json.dumps(first))
        second["model"]["items"][1]["detail"] = "Linden detail"
        one = self.bridge.propose(self.document, first, "Morrow")["proposalId"]
        two = self.bridge.propose(first, second, "Linden")["proposalId"]

        def make_legacy(packet):
            for proposal in packet["proposals"]:
                proposal.pop("requiresCommit", None)
            return True
        self.bridge.change(make_legacy)

        with self.assertRaisesRegex(ValueError, "older unsigned proposal"):
            self.bridge.commit_proposal(two, "Linden")
        self.assertEqual(self.bridge.commit_proposal(one, "Morrow")["commit"]["author"], "Morrow")
        self.assertEqual(self.bridge.commit_proposal(two, "Linden")["commit"]["author"], "Linden")
        effective = self.bridge.read_checklist(self.document["documentId"])
        items = effective["effectiveDocument"]["model"]["items"]
        self.assertEqual(items[0]["text"], "Morrow heading")
        self.assertEqual(items[1]["detail"], "Linden detail")
        self.assertEqual(effective["savedDocument"], self.document)

    def test_same_field_conflict_stays_unsigned_and_does_not_overwrite(self):
        self.bridge.sync(self.workspace, 1)
        first = json.loads(json.dumps(self.document))
        second = json.loads(json.dumps(self.document))
        first["model"]["items"][0]["text"] = "Linden title"
        second["model"]["items"][0]["text"] = "Morrow title"
        one = self.bridge.propose(self.document, first, "Linden")["proposalId"]
        two = self.bridge.propose(self.document, second, "Morrow")["proposalId"]
        self.bridge.commit_proposal(one, "Linden")
        with self.assertRaisesRegex(ValueError, "item:.*:text"):
            self.bridge.commit_proposal(two, "Morrow")
        effective = self.bridge.read_checklist(self.document["documentId"])
        self.assertEqual(effective["effectiveDocument"]["model"]["items"][0]["text"], "Linden title")
        self.assertIsNone(self.bridge.read()["proposals"][1].get("commit"))

    def test_browser_conflict_holds_only_its_checklist(self):
        second_doc = json.loads(json.dumps(self.document))
        second_doc["documentId"] = "second-list"
        self.workspace["documents"].append(second_doc)
        self.workspace["index"]["entries"].append({"id": "second-list", "file": "checklist-second-list.json"})
        self.bridge.sync(self.workspace, 1)
        incoming = json.loads(json.dumps(self.document))
        incoming["model"]["items"][0]["text"] = "Linden title"
        first_id = self.bridge.propose(self.document, incoming, "Linden")["proposalId"]
        self.bridge.commit_proposal(first_id, "Linden")
        human_copy = json.loads(json.dumps(self.workspace))
        human_copy["documents"][0]["model"]["items"][0]["text"] = "Human title"
        self.bridge.sync(human_copy, 2)
        self.assertEqual(self.bridge.refresh_for_ai()["committedConflicts"][0]["proposalId"], first_id)
        other = json.loads(json.dumps(second_doc))
        other["model"]["items"][1]["detail"] = "Morrow independent detail"
        other_id = self.bridge.propose(second_doc, other, "Morrow")["proposalId"]
        self.assertEqual(self.bridge.commit_proposal(other_id, "Morrow")["commit"]["author"], "Morrow")
        effective = self.bridge.read_checklist("second-list")
        self.assertEqual(effective["effectiveDocument"]["model"]["items"][1]["detail"],
                         "Morrow independent detail")

    def test_committed_new_list_is_visible_to_ai_before_browser_preview(self):
        self.bridge.sync(self.workspace, 1)
        new = json.loads(json.dumps(self.document))
        new["documentId"] = "shared-new-list"
        new["title"] = "Shared new list"
        new["state"] = {}
        proposal = self.bridge.propose_new(new, "Morrow")["proposalId"]
        self.assertIsNone(next((d for d in self.bridge.refresh_for_ai()["effectiveWorkspace"]["documents"]
                                if d["documentId"] == new["documentId"]), None))
        self.bridge.commit_proposal(proposal, "Morrow")
        effective = self.bridge.read_checklist(new["documentId"])
        self.assertIsNone(effective["savedDocument"])
        self.assertEqual({k: v for k, v in effective["effectiveDocument"].items() if k != "attribution"}, new)
        self.assertEqual(effective["effectiveDocument"]["attribution"][new["model"]["items"][0]["id"]]["created"]["actor"], "Morrow")
        self.assertEqual(effective["committedAwaitingBrowser"][0]["actor"], "Morrow")
        displayed = json.loads(json.dumps(new))
        displayed["updatedAt"] = "2026-09-29T12:00:00Z"
        self.workspace["documents"].append(displayed)
        self.workspace["index"]["entries"].append({"id": new["documentId"],
                                                    "file": f"checklist-{new['documentId']}.json"})
        self.bridge.sync(self.workspace, 2)
        self.assertEqual(self.bridge.read_checklist(new["documentId"])["committedConflicts"], [])
        self.bridge.mark(proposal, "applied", "Displayed", "Hermit")
        self.assertEqual(self.bridge.read_checklist(new["documentId"])["committedAwaitingBrowser"], [])

    def test_read_only_cli_exposes_saved_and_pending_separately(self):
        self.bridge.sync(self.workspace, 1)
        incoming = json.loads(json.dumps(self.document))
        incoming["title"] = "Other AI suggestion"
        self.bridge.propose(self.document, incoming, "Other AI")
        before = self.bridge.handoff_path().read_bytes()
        common = [sys.executable, "-B", str(MODULE), "--config-dir", str(self.bridge.root)]
        refreshed = subprocess.run(common + ["refresh"], capture_output=True, text=True, check=True)
        payload = json.loads(refreshed.stdout)
        self.assertEqual(payload["savedWorkspace"]["documents"][0]["title"], self.document["title"])
        self.assertEqual(payload["pendingUnapplied"][0]["incoming"]["title"], "Other AI suggestion")
        read = subprocess.run(common + ["read", "--checklist", self.document["documentId"],
                                        "--branch", self.document["model"]["roots"][0]],
                              capture_output=True, text=True, check=True)
        self.assertTrue(json.loads(read.stdout)["partial"])
        self.assertEqual(self.bridge.handoff_path().read_bytes(), before)

    def test_malformed_removal_is_refused_without_changing_handoff(self):
        self.bridge.sync(self.workspace, 1)
        before = self.bridge.read()
        incoming = json.loads(json.dumps(self.document))
        incoming["model"]["items"] = incoming["model"]["items"][1:]
        with self.assertRaisesRegex(ValueError, "Missing root item"):
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
        shutil.copyfile(MODULE.with_name("clearings_commit.py"), alternate / "tools" / "clearings_commit.py")
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
            response["value"] = {**identity, "program": "another-installation"}
            with self.assertRaisesRegex(RuntimeError, "Another Clearings copy or version"):
                local.run_server(bridge, port, False)
            self.assertEqual(local.load_json(bridge.root / "session.json")["token"], "fixture-token")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_changed_working_helper_restarts_its_own_old_server(self):
        identity = {**local.program_identity(self.bridge), "helperSha256": "old-code"}

        class OldHandler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                if self.path != "/api/identity" or self.headers.get("X-Clearings-Token") != "fixture-token":
                    self.send_error(404)
                    return
                raw = json.dumps(identity).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                if self.path != "/api/shutdown" or self.headers.get("X-Clearings-Token") != "fixture-token":
                    self.send_error(404)
                    return
                raw = b'{"stopping": true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                def stop():
                    self.server.shutdown()
                    self.server.server_close()
                threading.Thread(target=stop, daemon=True).start()

        old_server = ThreadingHTTPServer(("127.0.0.1", 0), OldHandler)
        port = old_server.server_address[1]
        old_thread = threading.Thread(target=old_server.serve_forever, daemon=True)
        old_thread.start()
        local.atomic_json(self.bridge.root / "session.json",
                          {"port": port, "token": "fixture-token"})
        failures = []
        worker = threading.Thread(target=lambda: self._serve_and_capture(port, failures), daemon=True)
        try:
            worker.start()
            for _ in range(50):
                session = local.load_json(self.bridge.root / "session.json")
                if session["token"] != "fixture-token":
                    break
                time.sleep(0.1)
            self.assertNotEqual(session["token"], "fixture-token", failures)
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/identity",
                                         headers={"X-Clearings-Token": session["token"]})
            with urllib.request.urlopen(req, timeout=2) as response:
                self.assertEqual(json.load(response), local.program_identity(self.bridge))
        finally:
            session = local.load_json(self.bridge.root / "session.json")
            if session["token"] != "fixture-token":
                req = urllib.request.Request(f"http://127.0.0.1:{port}/api/shutdown", data=b"{}",
                    headers={"X-Clearings-Token": session["token"], "Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=2) as response:
                    self.assertEqual(json.load(response), {"stopping": True})
            else:
                old_server.shutdown()
            old_server.server_close()
            old_thread.join(timeout=2)
            worker.join(timeout=2)
        self.assertFalse(failures)
        self.assertFalse(worker.is_alive())

    def _serve_and_capture(self, port, failures):
        try:
            local.run_server(self.bridge, port, False)
        except Exception as exc:
            failures.append(exc)

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
