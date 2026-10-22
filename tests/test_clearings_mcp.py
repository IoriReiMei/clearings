# SPDX-License-Identifier: MIT
"""Official-SDK stdio checks against a fresh synthetic Clearings home only."""
from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None
if MCP_AVAILABLE:
    from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from clearings_local import Bridge  # noqa: E402
if MCP_AVAILABLE:
    from clearings_mcp import GUIDE_TOPICS, ToolError, existing_bridge, read_guide  # noqa: E402


def payload(result):
    if result.is_error:
        raise AssertionError("Unexpected MCP tool error: " + repr(result.content))
    value = result.structured_content
    if value is None:
        if len(result.content) != 1 or result.content[0].type != "text":
            raise AssertionError("Unexpected MCP tool result: " + repr(result))
        value = json.loads(result.content[0].text)
    return value.get("result", value) if isinstance(value, dict) else value


@unittest.skipUnless(MCP_AVAILABLE,
                     "Optional MCP SDK absent; install tools/requirements-mcp.txt to run MCP checks")
class ClearingsMcpStdioTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clearings-mcp-")
        base = Path(self.temp.name)
        self.config = base / "config"
        self.home = base / "home"
        self.home.mkdir()
        self.bridge = Bridge(self.config)
        self.bridge.set_home(str(self.home))
        self.document = json.loads((ROOT / "examples/generic/program_overview.json").read_text(encoding="utf-8"))
        self.workspace = {"format": "checklist-studio-workspace", "schemaVersion": 1,
                          "futureWorkspaceField": {"preserve": "untouched"},
                          "index": {"libraryId": "synthetic-mcp-library",
                                    "defaultChecklist": self.document["documentId"],
                                    "entries": [{"id": self.document["documentId"],
                                                 "file": f"checklist-{self.document['documentId']}.json"}],
                                    "futureIndexField": {"preserve": "untouched"}},
                          "documents": [self.document]}
        self.bridge.sync(self.workspace, 1)

    def tearDown(self):
        self.temp.cleanup()

    def client(self, actor: str, write: bool = False):
        args = ["-B", str(ROOT / "tools/clearings_mcp.py"),
                "--config-dir", str(self.config), "--home", str(self.home), "--actor", actor]
        if write:
            args.append("--write")
        return Client(StdioServerParameters(command=sys.executable, args=args,
                                            env=dict(os.environ), cwd=ROOT))

    async def test_read_only_discovery_and_existing_config_precheck(self):
        absent = Path(self.temp.name) / "absent"
        with self.assertRaisesRegex(ValueError, "existing Clearings config"):
            existing_bridge(str(absent), str(self.home))
        self.assertFalse(absent.exists())
        other_home = Path(self.temp.name) / "other-home"
        other_home.mkdir()
        with self.assertRaisesRegex(ValueError, "differs from"):
            existing_bridge(str(self.config), str(other_home))
        before = self.bridge.handoff_path().read_bytes()
        async with self.client("Reader") as client:
            tools = await client.list_tools()
            self.assertEqual({tool.name for tool in tools.tools},
                             {"clearings_list_checklists", "clearings_read_checklist",
                              "clearings_search_items", "clearings_get_guide", "clearings_get_status",
                              "clearings_read_item", "clearings_get_briefing", "clearings_preview_proposal",
                              "clearings_prepare_handoff"})
            listed = payload(await client.call_tool("clearings_list_checklists"))
            self.assertEqual(listed["checklists"][0]["id"], self.document["documentId"])
            read = payload(await client.call_tool("clearings_read_checklist",
                                                  {"checklist_id": self.document["documentId"],
                                                   "branch_id": "shape"}))
            self.assertTrue(read["partial"])
            self.assertTrue(read["branch"]["notAProposalBase"])
            self.assertTrue(read["readOnly"])
        self.assertEqual(self.bridge.handoff_path().read_bytes(), before)

    async def test_bundled_guide_topics_and_read_only_capabilities(self):
        before = self.bridge.handoff_path().read_bytes()
        async with self.client("Guide Reader") as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            guide_tool = tools["clearings_get_guide"]
            self.assertTrue(guide_tool.annotations.read_only_hint)
            self.assertFalse(guide_tool.annotations.open_world_hint)
            self.assertEqual(set(guide_tool.input_schema["properties"]["topic"]["enum"]),
                             set(GUIDE_TOPICS))
            start = payload(await client.call_tool("clearings_get_guide"))
            self.assertEqual(start["topic"], "start")
            self.assertEqual(start["actor"], "Guide Reader")
            self.assertFalse(start["writeEnabled"])
            self.assertEqual({item["id"] for item in start["topics"]}, set(GUIDE_TOPICS))
            self.assertNotIn("effectiveDocument", start)
            self.assertNotIn("synthetic-mcp-library", json.dumps(start))
            self.assertLess(len(start["text"]), 4000)
            for topic, title in GUIDE_TOPICS.items():
                result = payload(await client.call_tool("clearings_get_guide", {"topic": topic}))
                source = (ROOT / result["source"]).read_text(encoding="utf-8")
                self.assertIn(result["text"], source)
                self.assertEqual(result["title"], title)
                if topic != "reference":
                    self.assertTrue(result["text"].startswith("## " + title + "\n"))
                    self.assertEqual(result["text"].count("\n## "), 0)
                self.assertLessEqual(len(result["text"].encode("utf-8")), 65536)
            for invalid in ("../config/settings.json", "unknown", "", "START"):
                self.assertTrue((await client.call_tool("clearings_get_guide", {"topic": invalid})).is_error)
        self.assertEqual(self.bridge.handoff_path().read_bytes(), before)

    def test_incomplete_bundled_guidance_fails_without_reading_other_files(self):
        fixture = Path(self.temp.name) / "guide-only"
        fixture.mkdir()
        with patch("clearings_mcp.SOURCE_ROOT", fixture):
            with self.assertRaisesRegex(ToolError, "Choose a guide topic"):
                read_guide("../config/settings.json")
            for malformed in (None, b"", b"# Wrong heading", b"\xff", b"x" * 65537):
                if malformed is not None:
                    (fixture / "AI_START_HERE.md").write_bytes(malformed)
                with self.assertRaisesRegex(ToolError, "Bundled Clearings guide is unavailable"):
                    read_guide("start")

    async def test_effective_only_and_bounded_search_on_synthetic_checklists(self):
        active = copy.deepcopy(self.document)
        active["state"]["purpose"] = True
        next(item for item in active["model"]["items"] if item["id"] == "purpose")["response"] = "One special response"
        active["model"]["items"][1]["detail"] = "A " + "specific " * 100
        next(item for item in active["model"]["items"] if item["id"] == "make")["requires"].append("purpose")
        next(item for item in active["model"]["items"] if item["id"] == "purpose")["requires"].append("grandchild")
        active["model"]["items"].append({"id": "grandchild", "order": 101, "parents": [],
                                         "label": "", "tags": [], "text": "Descendant target",
                                         "detail": "One direct parent, two root paths.",
                                         "requires": []})
        archived = copy.deepcopy(self.document)
        archived["documentId"] = "archived-synthetic"
        archived["title"] = "Old synthetic list"
        archived["archived"] = True
        archived["model"]["items"][1]["text"] = "Archival special target"
        workspace = copy.deepcopy(self.workspace)
        workspace["documents"] = [active, archived]
        workspace["index"]["entries"].append(
            {"id": archived["documentId"], "file": "checklist-archived-synthetic.json"})
        self.bridge.sync(workspace, 2)
        before = self.bridge.handoff_path().read_bytes()
        async with self.client("Reader") as client:
            full = payload(await client.call_tool("clearings_read_checklist",
                                                  {"checklist_id": active["documentId"]}))
            compact = payload(await client.call_tool("clearings_read_checklist",
                                                     {"checklist_id": active["documentId"],
                                                      "effective_only": True}))
            self.assertEqual(compact["effectiveDocument"], full["effectiveDocument"])
            self.assertNotIn("savedDocument", compact)
            self.assertNotIn("pendingUnapplied", compact)
            self.assertFalse(compact["partial"])
            self.assertLess(len(json.dumps(compact)), len(json.dumps(full)))
            rejected = await client.call_tool("clearings_read_checklist",
                                              {"checklist_id": active["documentId"],
                                               "branch_id": "shape", "effective_only": True})
            self.assertTrue(rejected.is_error)
            self.assertIn("full checklist", repr(rejected.content))
            found = payload(await client.call_tool("clearings_search_items",
                                                   {"query": "specific", "limit": 1}))
            self.assertTrue(found["notAProposalBase"])
            self.assertTrue(found["hasMore"] is False)
            self.assertEqual(found["results"][0]["pathIds"], ["shape", "purpose"])
            self.assertTrue(found["results"][0]["sharedParentPaths"])
            self.assertTrue(found["results"][0]["completed"])
            self.assertLessEqual(len(found["results"][0]["detail"]), 160)
            self.assertEqual(found["results"][0]["response"], "One special response")
            by_response = payload(await client.call_tool("clearings_search_items", {"query": "special response"}))
            self.assertEqual(by_response["results"][0]["itemId"], "purpose")
            self.assertEqual(next(i for i in full["effectiveDocument"]["model"]["items"] if i["id"] == "purpose")["response"], "One special response")
            branch = payload(await client.call_tool("clearings_read_checklist", {"checklist_id": active["documentId"], "branch_id": "purpose"}))
            self.assertEqual(next(i for i in branch["branch"]["items"] if i["id"] == "purpose")["response"], "One special response")
            descendant = payload(await client.call_tool("clearings_search_items",
                                                        {"query": "Descendant target"}))
            self.assertEqual(descendant["results"][0]["pathIds"],
                             ["shape", "purpose", "grandchild"])
            self.assertTrue(descendant["results"][0]["sharedParentPaths"])
            hidden = payload(await client.call_tool("clearings_search_items",
                                                    {"query": "Archival special"}))
            self.assertEqual(hidden["results"], [])
            shown = payload(await client.call_tool("clearings_search_items",
                                                   {"query": "Archival special",
                                                    "include_archived": True}))
            self.assertEqual(shown["results"][0]["checklistId"], archived["documentId"])
            limited = payload(await client.call_tool("clearings_search_items",
                                                     {"query": "the", "limit": 1}))
            self.assertEqual(len(limited["results"]), 1)
            self.assertTrue(limited["hasMore"])
            for args in ({"query": " "}, {"query": "specific", "limit": 0},
                         {"query": "specific", "limit": 51}):
                self.assertTrue((await client.call_tool("clearings_search_items", args)).is_error)
        self.assertEqual(self.bridge.handoff_path().read_bytes(), before)

    async def test_list_reports_expected_bridge_rejection_for_malformed_synthetic_handoff(self):
        malformed = self.bridge.read()
        malformed["format"] = "malformed-synthetic-handoff"
        self.bridge.handoff_path().write_text(json.dumps(malformed), encoding="utf-8")
        before = self.bridge.handoff_path().read_bytes()
        async with self.client("Reader") as client:
            guide = payload(await client.call_tool("clearings_get_guide", {"topic": "recovery"}))
            self.assertIn("Do not delete or overwrite", guide["text"])
            rejected = await client.call_tool("clearings_list_checklists")
            self.assertTrue(rejected.is_error)
            self.assertIn("Unrecognized handoff file; it was not changed", repr(rejected.content))
            self.assertNotIn("No browser-saved workspace yet", repr(rejected.content))
        self.assertEqual(self.bridge.handoff_path().read_bytes(), before)

    async def test_focused_tools_schema_receipts_and_context_over_stdio(self):
        cid = self.document['documentId']
        async with self.client('CA1', write=True) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            schema = json.dumps(tools['clearings_propose_item_edits'].input_schema)
            self.assertIn('expected_revision', schema)
            self.assertIn('mcpAcknowledgement', schema)
            self.assertIn('additionalProperties', schema)
            status = payload(await client.call_tool('clearings_get_status'))
            self.assertTrue(status['readReady'])
            self.assertTrue(status['writeToolsExposed'])
            read = payload(await client.call_tool('clearings_read_item', {'checklist_id': cid, 'item_id': 'purpose'}))
            args = {'checklist_id': cid, 'request_id': 'focused-stdio', 'edits': [
                {'item_id': 'purpose', 'expected_revision': read['revision'], 'changes': {'response': 'Please review.'}}]}
            draft = payload(await client.call_tool('clearings_propose_item_edits', args))
            self.assertTrue(draft['preview']['readyToCommitAtRead'])
            self.assertIn('needsReview', [c['field'] for c in draft['preview']['changes']])
            receipt = payload(await client.call_tool('clearings_commit_proposal', {'proposal_id': draft['proposalId']}))
            self.assertEqual(receipt['delivery'], 'committed-awaiting-browser')
            retry = payload(await client.call_tool('clearings_propose_item_edits', args))
            self.assertEqual(retry['proposalId'], draft['proposalId'])
            stale = copy.deepcopy(args)
            stale['request_id'] = 'stale-stdio'
            stale['edits'][0]['changes'] = {'detail': 'Stale rewrite'}
            rejected = await client.call_tool('clearings_propose_item_edits', stale)
            self.assertTrue(rejected.is_error)
            self.assertIn('STALE_ITEM', repr(rejected.content))
            for changes in ({'completed': 'yes'}, {'unknown': 'ignored?'}, {'text': None}):
                invalid = copy.deepcopy(stale)
                invalid['edits'][0]['changes'] = changes
                self.assertTrue((await client.call_tool('clearings_propose_item_edits', invalid)).is_error)
            prepared = payload(await client.call_tool('clearings_prepare_handoff', {
                'checklist_id': cid, 'item_ids': ['purpose'], 'parent_item_id': 'purpose',
                'goal': 'Continue fixture', 'progress': 'Read and asked a question', 'next_step': 'Wait for an answer',
                'recipient': 'Next AI'}))
            self.assertFalse(prepared['saved'])
            handoff = payload(await client.call_tool('clearings_propose_handoff', {
                'handoff_token': prepared['handoffToken'], 'request_id': 'handoff-stdio'}))
            payload(await client.call_tool('clearings_commit_proposal', {'proposal_id': handoff['proposalId']}))
        async with self.client('Next AI') as reader:
            briefing = payload(await reader.call_tool('clearings_get_briefing'))
            self.assertIn(prepared['contextItemId'], [i['itemId'] for i in briefing['items']])
            context = payload(await reader.call_tool('clearings_read_item', {
                'checklist_id': cid, 'item_id': prepared['contextItemId']}))
            self.assertIn('Wait for an answer', context['item']['detail'])
            self.assertEqual(context['item']['assignment']['status'], 'pending')
            self.assertTrue((await reader.call_tool('clearings_propose_handoff', {
                'handoff_token': prepared['handoffToken'], 'request_id': 'not-exposed'})).is_error)

    async def test_status_works_during_workspace_read_failure(self):
        malformed = self.bridge.read()
        malformed['format'] = 'synthetic-invalid'
        self.bridge.handoff_path().write_text(json.dumps(malformed), encoding='utf-8')
        before = self.bridge.handoff_path().read_bytes()
        async with self.client('Reader') as client:
            status = payload(await client.call_tool('clearings_get_status'))
            self.assertFalse(status['readReady'])
            self.assertEqual(status['writeReadiness'], 'unavailable')
            self.assertIn('problem', status)
            self.assertTrue((await client.call_tool('clearings_list_checklists')).is_error)
        self.assertEqual(before, self.bridge.handoff_path().read_bytes())

    async def test_two_declared_actors_task_handoff_new_list_and_conflict(self):
        async with self.client("Linden", write=True) as a:
            tools = {tool.name: tool for tool in (await a.list_tools()).tools}
            self.assertEqual(len(tools), 15)
            guide = payload(await a.call_tool("clearings_get_guide", {"topic": "collaboration"}))
            self.assertTrue(guide["writeEnabled"])
            self.assertEqual(guide["actor"], "Linden")
            self.assertTrue(tools["clearings_commit_proposal"].annotations.destructive_hint)
            self.assertTrue(tools["clearings_withdraw_proposal"].annotations.destructive_hint)
            read = payload(await a.call_tool("clearings_read_checklist",
                                             {"checklist_id": self.document["documentId"]}))
            base = read["effectiveDocument"]
            incoming = copy.deepcopy(base)
            task = {"id": "mcp-synthetic-task", "order": 100, "parents": [],
                    "label": "", "tags": [], "text": "Check the synthetic handoff",
                    "detail": "A directly actionable test task.", "requires": []}
            incoming["model"]["items"].append(task)
            next(item for item in incoming["model"]["items"] if item["id"] == "shape")["requires"].append(task["id"])
            draft = payload(await a.call_tool("clearings_propose_existing",
                                              {"base": base, "incoming": incoming,
                                               "note": "Synthetic first actor task"}))
            async with self.client("Morrow", write=True) as other:
                refused = await other.call_tool("clearings_withdraw_proposal",
                                                {"proposal_id": draft["proposalId"],
                                                 "reason": "Attempt to withdraw another actor's draft"})
                self.assertTrue(refused.is_error)
                self.assertIn("Withdraw only your own", repr(refused.content))
            signed = payload(await a.call_tool("clearings_commit_proposal",
                                               {"proposal_id": draft["proposalId"]}))
            self.assertEqual(signed["commit"]["author"], "Linden")
        async with self.client("Morrow", write=True) as b:
            read = payload(await b.call_tool("clearings_read_checklist",
                                             {"checklist_id": self.document["documentId"]}))
            self.assertFalse(read["partial"])
            base = read["effectiveDocument"]
            self.assertIn(task["id"], {item["id"] for item in base["model"]["items"]})
            incoming = copy.deepcopy(base)
            incoming["state"][task["id"]] = True
            draft = payload(await b.call_tool("clearings_propose_existing",
                                               {"base": base, "incoming": incoming}))
            signed = payload(await b.call_tool("clearings_commit_proposal",
                                                {"proposal_id": draft["proposalId"]}))
            self.assertEqual(signed["commit"]["author"], "Morrow")
            new = copy.deepcopy(self.document)
            new["documentId"] = "mcp-synthetic-new"
            new["title"] = "Synthetic new list"
            new["state"] = {item["id"]: False for item in new["model"]["items"]}
            created = payload(await b.call_tool("clearings_propose_new", {"incoming": new}))
            payload(await b.call_tool("clearings_commit_proposal",
                                      {"proposal_id": created["proposalId"]}))
            latest = payload(await b.call_tool("clearings_list_checklists"))
            self.assertEqual({x["id"] for x in latest["checklists"]},
                             {self.document["documentId"], "mcp-synthetic-new"})
            stale = payload(await b.call_tool("clearings_read_checklist",
                                              {"checklist_id": self.document["documentId"]}))
            stale_base = stale["effectiveDocument"]
        async with self.client("Linden", write=True) as a:
            current = payload(await a.call_tool("clearings_read_checklist",
                                                {"checklist_id": self.document["documentId"]}))
            changed = copy.deepcopy(current["effectiveDocument"])
            next(item for item in changed["model"]["items"] if item["id"] == "purpose")["text"] = "Linden changed this"
            draft = payload(await a.call_tool("clearings_propose_existing",
                                              {"base": current["effectiveDocument"],
                                               "incoming": changed}))
            payload(await a.call_tool("clearings_commit_proposal",
                                      {"proposal_id": draft["proposalId"]}))
        async with self.client("Morrow", write=True) as b:
            conflicting = copy.deepcopy(stale_base)
            next(item for item in conflicting["model"]["items"] if item["id"] == "purpose")["text"] = "Morrow changed this differently"
            draft = payload(await b.call_tool("clearings_propose_existing",
                                               {"base": stale_base, "incoming": conflicting}))
            rejected = await b.call_tool("clearings_commit_proposal",
                                         {"proposal_id": draft["proposalId"]})
            self.assertTrue(rejected.is_error)
            self.assertIn("Commit conflicts", repr(rejected.content))
            withdrawn = payload(await b.call_tool("clearings_withdraw_proposal",
                                                  {"proposal_id": draft["proposalId"],
                                                   "reason": "Conflicted synthetic draft"}))
            self.assertEqual(withdrawn["actor"], "Morrow")
            final = payload(await b.call_tool("clearings_read_checklist",
                                             {"checklist_id": self.document["documentId"]}))
            self.assertTrue(final["effectiveDocument"]["state"][task["id"]])
            compact = payload(await b.call_tool("clearings_read_checklist",
                                               {"checklist_id": self.document["documentId"],
                                                "effective_only": True}))
            self.assertEqual(compact["effectiveDocument"], final["effectiveDocument"])
            self.assertEqual(final["effectiveDocument"]["attribution"][task["id"]]["completed"]["actor"], "Morrow")
            listed = payload(await b.call_tool("clearings_list_checklists"))
            self.assertEqual(len(listed["committedAwaitingBrowser"]), 4)
        effective = self.bridge.refresh_for_ai()["effectiveWorkspace"]
        self.assertEqual(effective["futureWorkspaceField"], self.workspace["futureWorkspaceField"])
        self.assertEqual(effective["index"]["futureIndexField"],
                         self.workspace["index"]["futureIndexField"])
        self.assertEqual(self.bridge.read()["snapshot"], self.workspace)


if __name__ == "__main__":
    unittest.main()
