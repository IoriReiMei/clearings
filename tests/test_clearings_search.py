# SPDX-License-Identifier: MIT
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from clearings_local import Bridge
MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None
if MCP_AVAILABLE:
    from clearings_mcp import build_server, matched_passage, item_path_index, path_from_index
    from mcp import Client


@unittest.skipUnless(MCP_AVAILABLE, "Optional MCP SDK is not installed")
class SearchChecks(unittest.IsolatedAsyncioTestCase):
    def test_unicode_match_and_bounded_excerpt(self):
        text = "Before " * 100 + "Straße" + " after" * 100
        passage = matched_passage(text, "strasse")
        self.assertIn("Straße", passage)
        self.assertLessEqual(len(passage), 160)
        self.assertTrue(passage.startswith("…") and passage.endswith("…"))
        self.assertIsNone(matched_passage(text, "missing"))

    def test_deep_path_index_keeps_single_predecessors(self):
        count = 3000
        doc = {"model": {"roots": ["n0"], "items": [{"id": f"n{n}", "requires": [f"n{n+1}"] if n+1<count else []} for n in range(count)]}}
        index, shared = item_path_index(doc)
        self.assertEqual(len(index), count)
        self.assertTrue(all(value is None or isinstance(value, str) for value in index.values()))
        self.assertEqual(len(path_from_index(index, "n2999")), count)
        self.assertFalse(shared)

    async def test_sdk_search_names_actual_field_and_builds_only_matched_outline(self):
        with tempfile.TemporaryDirectory(prefix="clearings-search-") as directory:
            bridge = Bridge(Path(directory) / "config")
            doc = json.loads((ROOT / "examples/generic/program_overview.json").read_text(encoding="utf-8"))
            item = doc["model"]["items"][-1]
            item["review"] = "Prefix " * 80 + "SPECIAL PASSAGE" + " suffix" * 80
            other = copy.deepcopy(doc)
            other["documentId"] = "other-fictional-checklist"
            other["model"]["items"][-1].pop("review")
            ws = {"format": "checklist-studio-workspace", "index": {"libraryId": "search-fixture",
                  "entries": [{"id": d["documentId"], "file": d["documentId"] + ".json"} for d in [other, doc]]},
                  "documents": [other, doc]}
            bridge.sync(ws, 1)
            async with Client(build_server(bridge, "Reader")) as client:
                with patch("clearings_mcp.item_path_index", wraps=item_path_index) as index:
                    result = await client.call_tool("clearings_search_items", {"query": "special passage"})
                    value = result.structured_content
                    if value is None:
                        value = json.loads(result.content[0].text)
                    value = value.get("result", value)
                    self.assertEqual(index.call_count, 1)
                    self.assertEqual(value["results"][0]["match"]["field"], "review")
                    self.assertIn("SPECIAL PASSAGE", value["results"][0]["match"]["excerpt"])
                    self.assertTrue(value["notAProposalBase"])


if __name__ == "__main__":
    unittest.main()
