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
"""Disposable size-boundary checks; no live Clearings home is opened."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "tools" / "clearings_local.py"
sys.path.insert(0, str(MODULE.parent))
spec = importlib.util.spec_from_file_location("clearings_local_size_repair", MODULE)
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


class HandoffSizeRepair(unittest.TestCase):
    def test_compact_fallback_preserves_entire_packet(self):
        packet = {"generation": 322, "snapshot": {"documents": [{"title": "Café ☺", "items": ["A", "B"]}]},
                  "proposals": [{"id": "pending", "actor": "Morrow", "base": {"text": "before"},
                                 "incoming": {"text": "after"}, "status": "pending"}],
                  "receipts": [{"id": "applied", "status": "applied"}]}
        pretty = (json.dumps(packet, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        compact = (json.dumps(packet, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        limit = (len(pretty) + len(compact)) // 2
        self.assertLess(len(compact), limit)
        self.assertGreater(len(pretty), limit)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clearings_handoff.json"
            with patch.object(local, "MAX_BYTES", limit):
                local.atomic_json(path, packet)
                self.assertEqual(local.load_json(path), packet)
            self.assertEqual(path.read_bytes(), compact)

    def test_truly_oversized_packet_leaves_prior_bytes_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clearings_handoff.json"
            original = b'{"generation":322,"proposals":[]}\n'
            path.write_bytes(original)
            oversized = {"generation": 323, "proposals": [{"incoming": "x" * 300}]}
            compact_size = len((json.dumps(oversized, ensure_ascii=False,
                                           separators=(",", ":")) + "\n").encode("utf-8"))
            with patch.object(local, "MAX_BYTES", compact_size - 1):
                with self.assertRaisesRegex(ValueError, "nothing was written"):
                    local.atomic_json(path, oversized)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_compact_storage_retains_identity_and_generation_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = local.Bridge(Path(directory) / "config")
            home = Path(directory) / "home"
            home.mkdir()
            bridge.set_home(str(home))
            workspace = {"format": "checklist-studio-workspace",
                         "index": {"libraryId": "fixture-library", "notes": "x" * 120},
                         "documents": []}
            first = {"format": "clearings-local-handoff", "schemaVersion": 1,
                     "libraryId": "fixture-library", "snapshot": None, "snapshotAt": None,
                     "generation": 0, "proposals": [], "receipts": []}
            pretty = len((json.dumps(first, ensure_ascii=False, indent=2) + "\n").encode())
            compact = len((json.dumps(first, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
            limit = (pretty + compact) // 2
            # Use compact encoding on the handoff while preserving the bridge's normal guards.
            with patch.object(local, "MAX_BYTES", limit):
                local.atomic_json(bridge.handoff_path(), first)
            with patch.object(local, "MAX_BYTES", 100_000):
                bridge.sync(workspace, 1, 0)
                before = bridge.handoff_path().read_bytes()
                with self.assertRaisesRegex(ValueError, "generation changed"):
                    bridge.sync(workspace, 2, 0)
                self.assertEqual(bridge.handoff_path().read_bytes(), before)
                other = json.loads(json.dumps(workspace))
                other["index"]["libraryId"] = "another-library"
                with self.assertRaisesRegex(ValueError, "another checklist library"):
                    bridge.sync(other, 2, 1)
                self.assertEqual(bridge.handoff_path().read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
