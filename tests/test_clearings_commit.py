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
"""Cross-check the AI handoff merge against Clearings' browser merge."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from clearings_commit import merge_documents, validate_document  # noqa: E402


class CommitMergeChecks(unittest.TestCase):
    def setUp(self):
        self.base = json.loads((ROOT / "examples/generic/program_overview.json").read_text(encoding="utf-8"))

    def test_reference_links_reject_browser_trim_bypasses(self):
        for href in (" javascript:alert(1)", "\tjavascript:alert(1)",
                     " //attacker.example/path", "\ufeffjavascript:alert(1)",
                     "https://example.test/\n"):
            with self.subTest(href=repr(href)):
                candidate = copy.deepcopy(self.base)
                candidate["references"] = [{"title": "Unsafe", "href": href}]
                with self.assertRaisesRegex(ValueError, "Unsafe checklist reference"):
                    validate_document(candidate)
        for href in ("https://example.test/path", "docs/notes with spaces.html"):
            with self.subTest(href=href):
                candidate = copy.deepcopy(self.base)
                candidate["references"] = [{"title": "Safe", "href": href}]
                validate_document(candidate)

    @staticmethod
    def item(document, key):
        return next(x for x in document["model"]["items"] if x["id"] == key)

    def compare_browser(self, base, current, incoming):
        if not shutil.which("node"):
            self.skipTest("Node is needed for the independent browser-merge comparison")
        script = ("const fs=require('node:fs');"
                  "const {mergeChecklistDocuments}=require('./tools/merge.cjs');"
                  "const x=JSON.parse(fs.readFileSync(0,'utf8'));"
                  "const y=mergeChecklistDocuments(x.base,x.current,x.incoming);"
                  "process.stdout.write(JSON.stringify({merged:y.merged,conflicts:y.unresolved.map(c=>c.key)}));")
        result = subprocess.run(["node", "-e", script], input=json.dumps({"base": base, "current": current,
                               "incoming": incoming}), text=True, capture_output=True, check=True, cwd=ROOT)
        browser = json.loads(result.stdout)
        helper = merge_documents(base, current, incoming)
        self.assertEqual(helper["conflicts"], sorted(browser["conflicts"]))
        if not helper["conflicts"]:
            self.assertEqual(helper["merged"], browser["merged"])

    def test_independent_item_fields(self):
        base = self.base
        current = copy.deepcopy(base)
        incoming = copy.deepcopy(base)
        self.item(current, "purpose")["detail"] = "Human detail"
        self.item(incoming, "boundaries")["text"] = "AI title"
        self.compare_browser(base, current, incoming)

    def test_same_field_conflict(self):
        base = self.base
        current = copy.deepcopy(base)
        incoming = copy.deepcopy(base)
        self.item(current, "purpose")["text"] = "Human title"
        self.item(incoming, "purpose")["text"] = "AI title"
        self.compare_browser(base, current, incoming)

    def test_completion_vs_changed_meaning_conflict(self):
        base = self.base
        current = copy.deepcopy(base)
        incoming = copy.deepcopy(base)
        self.item(current, "purpose")["detail"] = "A failed check"
        incoming["state"]["purpose"] = True
        self.compare_browser(base, current, incoming)

    def test_append_children_and_new_item(self):
        base = self.base
        current = copy.deepcopy(base)
        incoming = copy.deepcopy(base)
        one = {"id": "human-child", "order": 100, "parents": [], "label": "", "tags": [],
               "text": "Human child", "detail": "", "requires": []}
        two = {**one, "id": "ai-child", "text": "AI child"}
        current["model"]["items"].append(one)
        incoming["model"]["items"].append(two)
        self.item(current, "shape")["requires"].append("human-child")
        self.item(incoming, "shape")["requires"].append("ai-child")
        self.compare_browser(base, current, incoming)

    def test_move_conflict(self):
        base = self.base
        current = copy.deepcopy(base)
        incoming = copy.deepcopy(base)
        one = {"id": "human-child", "order": 100, "parents": [], "label": "", "tags": [],
               "text": "Human child", "detail": "", "requires": []}
        current["model"]["items"].append(one)
        self.item(current, "shape")["requires"].append("human-child")
        self.item(incoming, "shape")["requires"].remove("purpose")
        self.item(incoming, "make")["requires"].append("purpose")
        self.compare_browser(base, current, incoming)

    def test_titles_and_completion_have_matching_conflicts(self):
        changed=copy.deepcopy(self.base);self.item(changed,'purpose')['text']='New requirement'
        done=copy.deepcopy(self.base);done['state']['purpose']=True
        self.compare_browser(self.base,changed,done)
        self.compare_browser(self.base,done,changed)

    def test_deletion_refuses_every_concurrent_change_and_replays(self):
        incoming=copy.deepcopy(self.base)
        incoming['model']['items']=[i for i in incoming['model']['items'] if i['id']!='purpose']
        self.item(incoming,'shape')['requires'].remove('purpose')
        incoming['state'].pop('purpose',None)
        self.compare_browser(self.base,self.base,incoming)
        merged=merge_documents(self.base,self.base,incoming)['merged']
        self.compare_browser(self.base,merged,incoming)
        for kind in ['text','completion','new-link']:
            current=copy.deepcopy(self.base)
            if kind=='text':self.item(current,'boundaries')['text']='Concurrent unrelated edit'
            elif kind=='completion':current['state']['purpose']=True
            else:self.item(current,'make')['requires'].append('purpose')
            self.compare_browser(self.base,current,incoming)
            self.assertEqual(merge_documents(self.base,current,incoming)['conflicts'],['document:deletion-stale'])

    def test_closed_scope_partial_replay(self):
        base=copy.deepcopy(self.base)
        incoming=copy.deepcopy(base);self.item(incoming,'shape')['requires'].reverse();self.item(incoming,'shape')['detail']='New heading description';incoming['state']['shape']=True
        current=copy.deepcopy(base);self.item(current,'shape')['requires'].reverse();current['state']['shape']=True
        self.compare_browser(base,current,incoming)
        self.assertFalse(any(key.endswith(':locked') for key in merge_documents(base,current,incoming)['conflicts']))


    def test_mixed_deletion_cannot_bypass_closed_scope(self):
        base=copy.deepcopy(self.base);base['state']['make']=True
        incoming=copy.deepcopy(base);incoming['model']['items']=[i for i in incoming['model']['items'] if i['id']!='purpose'];self.item(incoming,'shape')['requires'].remove('purpose');incoming['state'].pop('purpose',None)
        child=self.item(base,'make')['requires'][0]
        one=copy.deepcopy(incoming);one['state'][child]=True
        two=copy.deepcopy(incoming);new=copy.deepcopy(self.item(two,child));new['id']='extra';two['model']['items'].append(new);self.item(two,'make')['requires'].append('extra')
        for changed in [one,two]:
            self.compare_browser(base,base,changed)
            self.assertEqual(merge_documents(base,base,changed)['conflicts'],['document:deletion-locked'])

    def test_missing_item_completion_conflicts(self):
        current=copy.deepcopy(self.base);current['model']['items']=[i for i in current['model']['items'] if i['id']!='purpose'];self.item(current,'shape')['requires'].remove('purpose');current['state'].pop('purpose',None)
        incoming=copy.deepcopy(self.base);incoming['state']['purpose']=True
        self.compare_browser(self.base,current,incoming)
        self.assertIn('item:purpose:missing',merge_documents(self.base,current,incoming)['conflicts'])

    def test_invalid_cycle_is_rejected_before_commit(self):
        bad = copy.deepcopy(self.base)
        self.item(bad, "purpose")["requires"].append("shape")
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate_document(bad)


if __name__ == "__main__":
    unittest.main()
