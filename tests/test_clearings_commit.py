# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
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
