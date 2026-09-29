# SPDX-License-Identifier: MPL-2.0
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

    def test_shutdown_rejects_untrusted_identity_before_request(self):
        local.atomic_json(self.bridge.root/'session.json',{'port':12345,'token':'fixture','pid':os.getpid()})
        for field in ['program','config','channel']:
            identity=local.program_identity(self.bridge);identity[field]='another'
            with patch.object(local.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(identity).encode())) as request, patch.object(local,'stop_legacy_windows_process') as legacy:
                with self.assertRaisesRegex(RuntimeError,'different Clearings'):local.stop_server(self.bridge,installation=str(local.PROGRAM))
                self.assertEqual(request.call_count,1);legacy.assert_not_called()

    def test_legacy_shutdown_fallback_is_explicit_and_release_only(self):
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        local.atomic_json(self.bridge.root/'session.json',{'port':port,'token':'fixture','pid':os.getpid()})
        for channel,explicit,allowed in [('working',True,False),('release',False,False),('release',True,True)]:
            with patch.object(local,'CHANNEL',channel):
                identity=local.program_identity(self.bridge)
                absent=local.urllib.error.HTTPError('fixture',404,'No route',{},None)
                with patch.object(local.urllib.request,'urlopen',side_effect=[io.BytesIO(json.dumps(identity).encode()),absent]), patch.object(local,'stop_legacy_windows_process') as legacy:
                    if allowed:
                        self.assertTrue(local.stop_server(self.bridge,installation=str(local.PROGRAM)))
                        legacy.assert_called_once_with(os.getpid(),str(local.PROGRAM))
                    else:
                        with self.assertRaises(local.urllib.error.HTTPError):local.stop_server(self.bridge,installation=str(local.PROGRAM) if explicit else None)
                        legacy.assert_not_called()

    def test_release_helper_stops_without_touching_workspace(self):
        self.bridge.sync(self.workspace,1)
        packet=copy.deepcopy(self.bridge.read())
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        errors=[]
        def serve():
            try:local.run_server(self.bridge,port,False)
            except Exception as exc:errors.append(exc)
        with patch.object(local,'CHANNEL','release'), patch.object(socket,'getfqdn',side_effect=AssertionError('Loopback must not depend on DNS')):
            worker=threading.Thread(target=serve,daemon=True);worker.start()
            deadline=time.monotonic()+10
            ready=False
            try:
                while time.monotonic()<deadline and not errors:
                    if (self.bridge.root/'session.json').exists():
                        session=local.load_json(self.bridge.root/'session.json')
                        request=local.urllib.request.Request(f'http://127.0.0.1:{port}/api/identity',headers={'X-Clearings-Token':session['token']})
                        try:
                            with local.urllib.request.urlopen(request,timeout=.5) as response:
                                ready=json.load(response)==local.program_identity(self.bridge)
                            if ready:break
                        except (OSError,ValueError):pass
                    time.sleep(.02)
                self.assertTrue(ready,repr(errors))
                with self.assertRaisesRegex(RuntimeError,'different Clearings'):
                    local.stop_server(self.bridge,installation=str(self.bridge.root/'not-this.exe'))
                self.assertTrue(worker.is_alive())
                self.assertTrue(local.stop_server(self.bridge))
            finally:
                if worker.is_alive() and (self.bridge.root/'session.json').exists():
                    try:local.stop_server(self.bridge)
                    except (OSError,RuntimeError):pass
                worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors,[])
        self.assertEqual(self.bridge.read(),packet)


if __name__=='__main__':unittest.main()
