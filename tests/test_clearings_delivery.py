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
"""Delivery regressions use fictional work and disposable local helpers only."""
import copy
import json
import io
import os
import socket
import threading
import time
import unittest
from unittest.mock import patch
import test_clearings_local as fixtures
from clearings_commit import merge_documents, stamp_attribution, validate_document

local = fixtures.local


class DeliveryChecks(unittest.TestCase):
    setUp = fixtures.BridgeChecks.setUp
    tearDown = fixtures.BridgeChecks.tearDown

    def test_two_assistants_edit_new_list_without_browser(self):
        self.bridge.sync(self.workspace, 1)
        new = copy.deepcopy(self.document)
        new['documentId'] = 'shared-delivery'
        new['state'] = {}
        proposal = self.bridge.propose_new(new, 'Morrow')['proposalId']
        self.bridge.commit_proposal(proposal, 'Morrow')
        base = self.bridge.read_checklist(new['documentId'])['effectiveDocument']
        incoming = copy.deepcopy(base)
        key = incoming['model']['items'][-1]['id']
        incoming['state'][key] = True
        p = self.bridge.propose(base, incoming, 'Linden')['proposalId']
        commit = self.bridge.commit_proposal(p, 'Linden')['commit']
        result = self.bridge.read_checklist(new['documentId'])
        self.assertIsNone(result['savedDocument'])
        self.assertEqual(result['effectiveDocument']['attribution'][key]['created']['actor'], 'Morrow')
        self.assertEqual(result['effectiveDocument']['attribution'][key]['completed']['actor'], 'Linden')
        self.assertEqual(result['effectiveDocument']['attribution'][key]['completed']['at'], commit['at'])

    def test_retention_never_drops_pending(self):
        pending = {'id':'keep','status':'pending'}
        proposals = [pending] + [{'id':str(n),'status':'applied'} for n in range(180)]
        kept = local.retain_proposals(proposals)
        self.assertEqual(kept[0], pending)
        self.assertEqual(len(kept),151)

    def test_withdraw_is_attributed_and_preserves_proposal(self):
        self.bridge.sync(self.workspace,1)
        incoming=copy.deepcopy(self.document);incoming['title']='Ready for review'
        p=self.bridge.propose(self.document,incoming,'Morrow')['proposalId']
        with self.assertRaisesRegex(ValueError,'own proposal'):
            self.bridge.withdraw(p,'Linden','not mine')
        self.bridge.withdraw(p,'Morrow','Superseded by a fresh read')
        saved=self.bridge.read()
        self.assertEqual(saved['proposals'][0]['status'],'dismissed')
        self.assertEqual(saved['receipts'][-1]['actor'],'Morrow')

    def test_completion_conflicts_with_changed_title_both_directions(self):
        base=copy.deepcopy(self.document);key=base['model']['items'][-1]['id']
        changed=copy.deepcopy(base);changed['model']['items'][-1]['text']='A materially different task'
        completed=copy.deepcopy(base);completed['state'][key]=True
        for current,incoming in [(changed,completed),(completed,changed)]:
            self.assertTrue(merge_documents(base,current,incoming)['conflicts'])

    def test_raw_handoff_cannot_edit_below_closed_parent(self):
        base=copy.deepcopy(self.document)
        parent=next(i for i in base['model']['items'] if i['requires']);key=parent['requires'][0]
        current=copy.deepcopy(base);current['state'][parent['id']]=True
        incoming=copy.deepcopy(base);next(i for i in incoming['model']['items'] if i['id']==key)['text']='Forbidden implicit reopen'
        self.assertIn('item:'+key+':locked',merge_documents(base,current,incoming)['conflicts'])

    def test_durable_attribution_survives_edit_and_plain_export(self):
        d=copy.deepcopy(self.document);d['state']={};key=d['model']['items'][-1]['id']
        created={'actor':'Morrow','role':'assistant','at':'2026-09-29T00:00:00Z','commitId':'one'}
        completed={'actor':'Linden','role':'assistant','at':'2026-09-29T01:00:00Z','commitId':'two'}
        stamp_attribution(d,None,created)
        before=copy.deepcopy(d);d['state'][key]=True;stamp_attribution(d,before,completed)
        before=copy.deepcopy(d);d['model']['items'][-1]['detail']='More context';stamp_attribution(d,before,created)
        restored=validate_document(json.loads(json.dumps(d)))
        self.assertEqual(restored['attribution'][key],{'created':created,'completed':completed})
        before=copy.deepcopy(d);d['state'][key]=False;stamp_attribution(d,before,created)
        self.assertNotIn('completed',d['attribution'][key])

    def test_existing_completion_is_not_reattributed(self):
        d=copy.deepcopy(self.document);key=d['model']['items'][-1]['id'];d['state'][key]=True
        human={'actor':'Hermit','role':'human','at':'2026-09-29T00:00:00Z'}
        d['attribution']={key:{'completed':human}}
        stamp_attribution(d,copy.deepcopy(d),{'actor':'Morrow','role':'assistant','at':'2026-09-29T01:00:00Z'})
        self.assertEqual(d['attribution'][key]['completed'],human)

    def test_deletion_and_next_assistant_edit_without_browser(self):
        self.bridge.sync(self.workspace,1)
        base=copy.deepcopy(self.document);incoming=copy.deepcopy(base)
        key=next(i['id'] for i in base['model']['items'] if not i['requires'])
        incoming['model']['items']=[i for i in incoming['model']['items'] if i['id']!=key]
        for i in incoming['model']['items']:i['requires']=[child for child in i['requires'] if child!=key]
        incoming['model']['roots']=[root for root in incoming['model']['roots'] if root!=key]
        incoming['state'].pop(key,None)
        p=self.bridge.propose(base,incoming,'Morrow')['proposalId'];self.bridge.commit_proposal(p,'Morrow')
        next_base=self.bridge.read_checklist(base['documentId'])['effectiveDocument']
        self.assertNotIn(key,{i['id'] for i in next_base['model']['items']})
        edited=copy.deepcopy(next_base);edited['title']='Continue after removal'
        p=self.bridge.propose(next_base,edited,'Linden')['proposalId'];self.bridge.commit_proposal(p,'Linden')
        self.assertEqual(self.bridge.read_checklist(base['documentId'])['effectiveDocument']['title'],edited['title'])

    def test_shutdown_refuses_other_installation_before_contact(self):
        session = {"port": 12345, "token": "fixture-token", "pid": os.getpid(),
                   "identity": local.program_identity(self.bridge)}
        with patch.object(local, "_dpapi", side_effect=lambda data, protect: data[::-1]):
            local.write_private_session(self.bridge.root / "session.json", session)
            with patch.object(local, "verify_listener") as verify:
                with self.assertRaisesRegex(RuntimeError, "different Clearings installation"):
                    local.stop_server(self.bridge, installation=str(self.bridge.root / "other.exe"))
                verify.assert_not_called()

    def test_legacy_shutdown_never_sends_plaintext_or_terminates_process(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0));port = probe.getsockname()[1]
        local.atomic_json(self.bridge.root / "session.json",
                          {"port": port, "token": "legacy-fixture", "pid": os.getpid()})
        with patch.object(local, "_listener_present", return_value=True), patch.object(local, "stop_legacy_windows_process") as legacy:
            with self.assertRaisesRegex(RuntimeError, "Close the earlier Clearings helper"):
                local.stop_server(self.bridge, installation=str(local.PROGRAM))
            legacy.assert_not_called()
        with patch.object(local, "_listener_present", return_value=False):
            self.assertFalse(local.stop_server(self.bridge))

    def test_release_helper_stops_without_touching_workspace(self):
        self.bridge.sync(self.workspace, 1)
        packet = copy.deepcopy(self.bridge.read())
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0));port = probe.getsockname()[1]
        errors = []
        def serve():
            try:
                local.run_server(self.bridge, port, False, show_tray=False)
            except Exception as exc:
                errors.append(exc)
        with patch.object(local, "CHANNEL", "release"), patch.object(local, "_dpapi", side_effect=lambda data, protect: data[::-1]):
            worker = threading.Thread(target=serve, daemon=True);worker.start()
            deadline = time.monotonic() + 10
            ready = False
            try:
                while time.monotonic() < deadline and not errors:
                    if (self.bridge.root / "session.json").exists():
                        session = local.load_private_session(self.bridge.root / "session.json")
                        try:
                            ready = local.verify_listener(session, self.bridge, port)
                            if ready:break
                        except (OSError, RuntimeError, ValueError):pass
                    time.sleep(.02)
                self.assertTrue(ready, repr(errors))
                with self.assertRaisesRegex(RuntimeError, "different Clearings installation"):
                    local.stop_server(self.bridge, installation=str(self.bridge.root / "not-this.exe"))
                self.assertTrue(worker.is_alive())
                self.assertTrue(local.stop_server(self.bridge))
            finally:
                if worker.is_alive() and (self.bridge.root / "session.json").exists():
                    try:local.stop_server(self.bridge)
                    except (OSError, RuntimeError):pass
                worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
        self.assertEqual(self.bridge.read(), packet)

    def test_shutdown_delivers_acknowledgement_before_server_exits(self):
        handler=local.handler_for(self.bridge,'fixture-token',0)
        entered=threading.Event();release=threading.Event();stopping=threading.Event()
        original_send=handler.send
        def delayed_send(request,*args,**kwargs):
            entered.set();release.wait(3)
            return original_send(request,*args,**kwargs)
        handler.send=delayed_send
        server=local.LocalServer(('127.0.0.1',0),handler)
        original_shutdown=server.shutdown
        def shutdown():
            stopping.set();original_shutdown()
        server.shutdown=shutdown
        worker=threading.Thread(target=lambda:server.serve_forever(poll_interval=.01),daemon=True)
        result=[];errors=[]
        def request_stop():
            try:
                req=local.urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/shutdown',data=b'{}',headers={'X-Clearings-Token':'fixture-token','Content-Type':'application/json'})
                with local.urllib.request.urlopen(req,timeout=5) as response:result.append(json.load(response))
            except Exception as exc:errors.append(exc)
        worker.start();client=threading.Thread(target=request_stop,daemon=True);client.start()
        try:
            self.assertTrue(entered.wait(3))
            self.assertFalse(stopping.wait(.2),'Server exited while its acknowledgement was still pending')
        finally:
            release.set();client.join(5)
            if not stopping.wait(1):server.shutdown()
            worker.join(3);server.server_close()
        self.assertEqual(errors,[])
        self.assertEqual(result,[{'stopping':True}])
        self.assertFalse(worker.is_alive())


if __name__=='__main__':unittest.main()
