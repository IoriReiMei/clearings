# SPDX-License-Identifier: MIT
"""Fictional-data regression checks for review, recovery and helper handover."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import clearings_local as local
from clearings_commit import stamp_attribution, validate_document, merge_documents


class CoordinationChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clearings-coordination-")
        self.root = Path(self.temp.name)
        self.bridge = local.Bridge(self.root / "config")
        self.doc = json.loads((ROOT / "examples/generic/program_overview.json").read_text(encoding="utf-8"))
        self.item_id = self.doc["model"]["items"][-1]["id"]
        self.ws = {"format": "checklist-studio-workspace", "schemaVersion": 1,
                   "index": {"libraryId": "coordination-fixture", "defaultChecklist": self.doc["documentId"],
                             "entries": [{"id": self.doc["documentId"], "file": "checklist.json"}]},
                   "documents": [self.doc]}
        self.stamp = {"actor": "Human fixture", "role": "human", "at": "2026-10-21T10:00:00Z"}

    def tearDown(self):
        self.temp.cleanup()

    def item(self, doc):
        return next(i for i in doc["model"]["items"] if i["id"] == self.item_id)

    def test_response_review_and_last_field_author(self):
        first = copy.deepcopy(self.doc)
        self.item(first)["response"] = "Please review the result."
        stamp_attribution(first, self.doc, self.stamp)
        self.assertTrue(self.item(first)["needsReview"])
        self.assertEqual(self.item(first)["detail"], self.item(self.doc)["detail"])
        second = copy.deepcopy(first)
        self.item(second)["review"] = "Reviewed with a qualification."
        ai = {**self.stamp, "actor": "AI fixture", "role": "assistant"}
        stamp_attribution(second, first, ai)
        self.assertFalse(self.item(second)["needsReview"])
        self.assertEqual(second["attribution"][self.item_id]["response"]["actor"], "Human fixture")
        self.assertEqual(second["attribution"][self.item_id]["review"]["actor"], "AI fixture")
        validate_document(second)

    def test_review_of_stale_response_conflicts(self):
        base = copy.deepcopy(self.doc)
        self.item(base).update(response="Earlier question", needsReview=True)
        current, incoming = copy.deepcopy(base), copy.deepcopy(base)
        self.item(current)["response"] = "A different question"
        self.item(incoming).update(review="Answer to the earlier question", needsReview=False)
        self.assertIn("item:" + self.item_id + ":review-response", merge_documents(base, current, incoming)["conflicts"])

    def test_independent_description_and_response_merge(self):
        current, incoming = copy.deepcopy(self.doc), copy.deepcopy(self.doc)
        self.item(current)["detail"] = "Human description"
        self.item(incoming)["response"] = "AI question"
        result = merge_documents(self.doc, current, incoming)
        self.assertFalse(result["conflicts"])
        self.assertEqual(self.item(result["merged"])["detail"], "Human description")
        self.assertEqual(self.item(result["merged"])["response"], "AI question")

    def test_assignment_accept_reassign_complete_and_reopen_receipts(self):
        old = copy.deepcopy(self.doc)
        for assignment, done in [
            ({"id": "assign-1", "assignee": "Ada", "role": "human", "status": "pending", "note": "Question"}, False),
            ({"id": "assign-1", "assignee": "Ada", "role": "human", "status": "accepted", "note": "Accepted"}, False),
            ({"id": "assign-2", "assignee": "Birch", "role": "assistant", "status": "pending", "note": "Reassigned"}, False),
            ({"id": "assign-2", "assignee": "Birch", "role": "assistant", "status": "accepted", "note": "Accepted"}, True),
            ({"id": "assign-2", "assignee": "Birch", "role": "assistant", "status": "accepted", "note": "Accepted"}, False),
        ]:
            new = copy.deepcopy(old)
            self.item(new)["assignment"] = assignment
            new["state"][self.item_id] = done
            stamp_attribution(new, old, self.stamp)
            validate_document(new)
            old = new
        events = old["attribution"][self.item_id]["assignmentHistory"]
        self.assertEqual([e["status"] for e in events], ["pending", "accepted", "superseded", "pending", "completed", "accepted"])

    def test_optional_fields_remain_optional_and_future_fields_refused(self):
        before = copy.deepcopy(self.doc)
        validate_document(self.doc)
        self.assertEqual(self.doc, before)
        bad = copy.deepcopy(self.doc)
        self.item(bad)["review"] = 42
        with self.assertRaises(ValueError):
            validate_document(bad)

    def save_draft(self):
        record = {"format": "clearings-browser-record", "version": 1, "generation": 1,
                  "savedAt": self.stamp["at"], "workspace": self.ws,
                  "draft": {"context": {"mode": "response", "docId": self.doc["documentId"], "id": self.item_id},
                            "fields": [["response", "An unfinished question"]], "baseKey": "fixture"}}
        self.bridge.sync(self.ws, 1, 0, record)
        return record

    def test_backup_contains_draft_version_and_signed_history_without_session(self):
        record = self.save_draft()
        incoming = copy.deepcopy(self.doc)
        self.item(incoming)["response"] = "Signed AI response"
        proposal = self.bridge.propose(self.doc, incoming, "Fixture AI", request_id="retry-one")
        signed = self.bridge.commit_proposal(proposal["proposalId"], "Fixture AI")
        self.bridge.backup_workspace()
        backup = self.bridge._read_recovery_bundle(self.bridge.recovery_directory() / "latest.json")
        self.assertEqual(backup["appVersion"], local.VERSION)
        self.assertEqual(backup["handoff"]["browserDraft"]["draft"], record["draft"])
        self.assertEqual(backup["handoff"]["proposals"][0]["commit"], signed["commit"])
        self.assertNotIn("token", backup)
        self.assertEqual(self.bridge.recovery_record()["record"], record)

    def test_missing_handoff_recovers_but_existing_file_wins(self):
        self.save_draft()
        self.bridge.backup_workspace()
        prior = self.bridge.handoff_path().read_bytes()
        self.bridge.handoff_path().unlink()  # Only this test's disposable home.
        self.assertTrue(self.bridge.restore_missing_handoff())
        self.assertEqual(self.bridge.handoff_path().read_bytes(), prior)
        self.bridge.handoff_path().write_text("damaged fixture", encoding="utf-8")
        self.assertFalse(self.bridge.restore_missing_handoff())
        self.assertEqual(self.bridge.handoff_path().read_text(), "damaged fixture")

    def test_previous_good_backup_survives_bad_latest(self):
        self.save_draft()
        self.bridge.backup_workspace()
        self.bridge.backup_workspace()
        (self.bridge.recovery_directory() / "latest.json").write_text("broken", encoding="utf-8")
        self.bridge.handoff_path().unlink()
        self.assertTrue(self.bridge.restore_missing_handoff())
        self.assertEqual(self.bridge.recovery_record()["record"]["draft"]["fields"][0][1], "An unfinished question")

    def test_archive_recovery_and_retry_after_archiving(self):
        self.save_draft()
        incoming = copy.deepcopy(self.doc)
        self.item(incoming)["text"] = "Changed once"
        request = self.bridge.propose(self.doc, incoming, "Fixture AI", request_id="request-1")
        commit = self.bridge.commit_proposal(request["proposalId"], "Fixture AI")
        self.bridge.mark(request["proposalId"], "applied", "Fixture receipt", "Human fixture")
        self.bridge.archive_resolved()
        self.bridge.backup_workspace()
        packet = self.bridge.read()
        archive = self.bridge.home() / packet["resolvedProposalArchives"][0]["file"]
        original = archive.read_bytes()
        archive.unlink()
        self.bridge.handoff_path().unlink()
        self.assertTrue(self.bridge.restore_missing_handoff())
        self.assertEqual(archive.read_bytes(), original)
        again = self.bridge.propose(self.doc, incoming, "Fixture AI", request_id="request-1")
        self.assertEqual(again["proposalId"], request["proposalId"])
        self.assertEqual(self.bridge.commit_proposal(again["proposalId"], "Fixture AI")["commit"], commit["commit"])
        self.assertFalse(self.bridge.read()["proposals"])
        self.item(incoming)["text"] = "Different payload"
        with self.assertRaisesRegex(ValueError, "different content"):
            self.bridge.propose(self.doc, incoming, "Fixture AI", request_id="request-1")

    def test_shutdown_backup_failure_keeps_writes_available(self):
        self.save_draft()
        with patch.object(self.bridge, "backup_workspace", side_effect=OSError("Fixture disk failure")):
            with self.assertRaises(OSError):
                self.bridge.prepare_shutdown()
        self.bridge.sync(self.ws, 2)
        self.assertFalse(self.bridge.maintenance_path.exists())

    def test_shutdown_drains_and_blocks_cross_process_writers(self):
        self.save_draft()
        self.bridge.prepare_shutdown()
        second = local.Bridge(self.bridge.root)
        with self.assertRaises(local.HelperUpdating):
            second.sync(self.ws, 2)
        self.assertEqual(second.read()["generation"], 1)
        self.bridge.end_maintenance()
        second.sync(self.ws, 2)

    def test_compact_http_record_keeps_the_same_draft(self):
        full = self.save_draft()
        compact = {key: value for key, value in full.items() if key != "workspace"}
        self.bridge.sync(self.ws, 1, 1, compact)
        self.assertEqual(self.bridge.recovery_record()["record"], full)

    def test_backup_waits_for_an_active_writer(self):
        self.save_draft()
        entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
        errors = []
        def edit(packet):
            entered.set()
            if not release.wait(4):
                raise RuntimeError("Fixture timeout")
            packet["fixtureLastWrite"] = "finished"
            return True
        def write():
            try:
                local.Bridge(self.bridge.root).change(edit)
            except BaseException as error:
                errors.append(error)
        def stop():
            try:
                self.bridge.prepare_shutdown()
                stopped.set()
            except BaseException as error:
                errors.append(error)
        writer = threading.Thread(target=write)
        shutdown = threading.Thread(target=stop)
        writer.start()
        self.assertTrue(entered.wait(4))
        shutdown.start()
        try:
            self.assertFalse(stopped.wait(.1))
        finally:
            release.set()
            writer.join(5)
            shutdown.join(5)
        self.assertFalse(errors)
        self.assertTrue(stopped.is_set())
        bundle = self.bridge._read_recovery_bundle(self.bridge.recovery_directory() / "latest.json")
        self.assertEqual(bundle["handoff"]["fixtureLastWrite"], "finished")
        self.bridge.end_maintenance()


class RuntimeChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clearings-runtime-")
        self.root = Path(self.temp.name)
        (self.root / "tools").mkdir()
        for name in ("clearings_local.py", "clearings_commit.py", "clearings_tray.py"):
            shutil.copy2(ROOT / "tools" / name, self.root / "tools" / name)
        shutil.copy2(ROOT / ("LC_CHECKLIST.html" if (ROOT / "LC_CHECKLIST.html").exists() else "index.html"),
                     self.root / "LC_CHECKLIST.html")
        spec = importlib.util.spec_from_file_location("fixture_runtime", self.root / "tools/clearings_local.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.bridge = self.module.Bridge(self.root / "config")
        self.runtime = self.module.RuntimeBridge(self.bridge)
        self.client = self.module.RuntimeBridge(self.module.Bridge(self.bridge.root))
        self.identities = []
        self.runtime.on_identity = self.identities.append
        self.ws = {"format": "checklist-studio-workspace", "index": {"libraryId": "runtime-fixture"}, "documents": []}
        self.bridge.sync(self.ws, 1)

    def tearDown(self):
        self.temp.cleanup()

    def change_engine(self):
        path = self.root / "tools/clearings_local.py"
        text = path.read_text(encoding="utf-8")
        text = text.replace("    def recovery_record(self):", "    def fixture_engine(self):\n        return 'new engine'\n\n    def recovery_record(self):")
        path.write_text(text, encoding="utf-8")

    def test_apply_preserves_data_and_other_clients_follow_approved_engine(self):
        before = self.bridge.handoff_path().read_bytes()
        self.change_engine()
        self.assertEqual(self.runtime.source_status()["status"], "ready")
        self.runtime.apply_source_update()
        self.assertEqual(self.runtime.fixture_engine(), "new engine")
        self.assertEqual(self.client.read()["generation"], 1)
        self.assertEqual(self.client.fixture_engine(), "new engine")
        self.assertEqual(self.bridge.handoff_path().read_bytes(), before)
        self.assertEqual(self.runtime.source_status()["status"], "current")
        self.assertEqual(len(self.identities), 1)
        with self.assertRaises(self.module.HelperUpdating):
            self.bridge.sync(self.ws, 2)
        self.client.sync(self.ws, 2)

    def test_host_change_requires_normal_restart(self):
        path = self.root / "tools/clearings_local.py"
        path.write_text(path.read_text(encoding="utf-8").replace("REQUEST_DEADLINE = 10.0", "REQUEST_DEADLINE = 11.0"), encoding="utf-8")
        self.assertEqual(self.runtime.source_status()["status"], "restart-required")
        with self.assertRaises(ValueError):
            self.runtime.apply_source_update()
        self.assertEqual(self.runtime.read()["generation"], 1)

    def test_invalid_candidate_keeps_old_engine_and_clears_pause(self):
        path = self.root / "tools/clearings_commit.py"
        with path.open("a", encoding="utf-8") as output:
            output.write("\nthis is invalid python !!!\n")
        with self.assertRaises(SyntaxError):
            self.runtime.apply_source_update()
        self.runtime.sync(self.ws, 2)
        self.assertFalse(self.bridge.maintenance_path.exists())
        self.assertFalse(self.identities)

    def test_new_writes_receive_retry_while_engine_switches(self):
        entered, release = threading.Event(), threading.Event()
        self.change_engine()
        def pause(identity):
            entered.set()
            if not release.wait(4):
                raise RuntimeError("Fixture timeout")
        self.runtime.on_identity = pause
        errors = []
        def apply():
            try:
                self.runtime.apply_source_update()
            except BaseException as error:
                errors.append(error)
        worker = threading.Thread(target=apply)
        worker.start()
        try:
            self.assertTrue(entered.wait(4))
            with self.assertRaises(self.module.HelperUpdating):
                self.runtime.sync(self.ws, 2)
            with self.assertRaises(self.module.HelperUpdating):
                self.client.sync(self.ws, 2)
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(errors)
        self.client.sync(self.ws, 2)

    def test_http_update_keeps_listener_and_authentication(self):
        token = "fictional-token-for-this-isolated-test"
        server = self.module.LocalServer(("127.0.0.1", 0), self.module.handler_for(self.runtime, token, 0))
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        address = f"http://127.0.0.1:{server.server_port}/api/"
        def request(path, data=None, authorize=True):
            headers = {"Content-Type": "application/json"}
            if authorize:
                headers["X-Clearings-Token"] = token
            req = urllib.request.Request(address + path, data=None if data is None else json.dumps(data).encode(), headers=headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                return json.load(response)
        try:
            self.change_engine()
            with self.assertRaises(urllib.error.HTTPError) as error:
                request("apply-source-update", {}, authorize=False)
            self.assertEqual(error.exception.code, 403)
            self.assertEqual(request("source-update")["status"], "ready")
            request("apply-source-update", {})
            self.assertEqual(request("source-update")["status"], "current")
            self.assertEqual(request("state")["generation"], 1)
            self.runtime.current.begin_maintenance()
            try:
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request("sync", {"workspace": self.ws, "generation": 2})
                self.assertEqual(error.exception.code, 503)
                retry = json.load(error.exception)
                self.assertEqual(retry["code"], "CLEARINGS_UPDATING")
                self.assertTrue(retry["retryable"])
            finally:
                self.runtime.current.end_maintenance()
            challenge = "a" * 40
            proof = request("identity-proof?challenge=" + challenge, authorize=False)["proof"]
            self.assertEqual(proof, self.module.control_mac(token, "identity", challenge,
                             self.module.program_identity(self.runtime), server.server_port))
        finally:
            server.shutdown()
            thread.join(5)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
