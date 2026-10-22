# SPDX-License-Identifier: MIT
# Copyright (c) 2026 The Hermit. See ../LICENSE.
"""Agent workflows against disposable fictional workspaces, never a running helper."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from clearings_local import Bridge, RuntimeBridge, HelperUpdating
from clearings_agent import AgentWorkspace, SessionCache, failure


class AgentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='clearings-agent-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.bridge = Bridge(Path(self.temp.name) / 'config')
        self.doc = json.loads((ROOT / 'examples/generic/program_overview.json').read_text(encoding='utf-8'))
        self.ws = {'format': 'checklist-studio-workspace', 'schemaVersion': 1,
                   'futureField': {'preserve': True},
                   'index': {'libraryId': 'agent-fixture', 'defaultChecklist': self.doc['documentId'],
                             'entries': [{'id': self.doc['documentId'], 'file': 'fixture.json'}]},
                   'documents': [self.doc]}
        self.bridge.sync(self.ws, 1)
        self.runtime = RuntimeBridge(self.bridge)
        self.api = AgentWorkspace(self.runtime, 'CA1', True)
        self.cid = self.doc['documentId']

    def change(self, key, changes, request='test-edit', revision=None):
        revision = revision or self.api.read_item(self.cid, key)['revision']
        return self.runtime.propose_item_edits(self.cid,
            [{'item_id': key, 'expected_revision': revision, 'changes': changes}], 'CA1', '', request)

    def commit_change(self, key, changes, request='test-edit'):
        receipt = self.change(key, changes, request)
        self.api.commit(receipt['proposalId'])
        return receipt

    def assign(self, key, actor='CA1'):
        return self.commit_change(key, {'assignment': {'id': 'assignment-' + key, 'assignee': actor,
                                  'role': 'assistant', 'status': 'pending', 'note': ''}}, 'assign-' + key)

    def test_reads_health_and_prepare_do_not_write(self):
        before = self.bridge.handoff_path().read_bytes()
        item = self.api.read_item(self.cid, 'purpose')
        self.assertEqual(item['item']['detail'], self.doc['model']['items'][1]['detail'])
        self.assertEqual(item['ancestors'][0]['itemId'], 'shape')
        status = self.api.status()
        self.assertTrue(status['readReady'])
        self.assertEqual(status['writeReadiness'], 'eligible')
        self.assertFalse(status['writeProbePerformed'])
        self.api.briefing()
        self.api.prepare_handoff(self.cid, ['purpose'], 'Goal', 'Read it', 'Ask the owner')
        self.assertEqual(before, self.bridge.handoff_path().read_bytes())

    def test_focused_edit_preserves_every_unrelated_field_and_deduplicates_after_commit(self):
        read = self.api.read_item(self.cid, 'purpose')
        revision = read['revision']
        draft = self.change('purpose', {'response': 'Please review the fixture'}, revision=revision)
        self.assertIn('response', [c['field'] for c in self.api.preview(draft['proposalId'])['changes']])
        receipt = self.api.commit(draft['proposalId'])
        self.assertEqual(receipt['delivery'], 'committed-awaiting-browser')
        self.assertFalse(receipt['humanReviewConfirmed'])
        self.assertEqual(receipt['commit'], self.api.commit(draft['proposalId'])['commit'])
        retry = self.change('purpose', {'response': 'Please review the fixture'}, revision=revision)
        self.assertEqual(draft['proposalId'], retry['proposalId'])
        self.assertTrue(retry['alreadyProposed'])
        latest = self.api.read_item(self.cid, 'purpose')
        self.assertEqual(read['item']['detail'], latest['item']['detail'])
        self.assertTrue(latest['item']['needsReview'])
        self.assertFalse(latest['completed'])
        self.assertEqual(latest['attribution']['response']['actor'], 'CA1')
        self.assertEqual(self.bridge.refresh_for_ai()['effectiveWorkspace']['futureField'], {'preserve': True})
        self.assertEqual(self.bridge.read()['snapshot'], self.ws)

    def test_unrelated_edit_does_not_invalidate_item_but_target_and_parent_changes_do(self):
        revision = self.api.read_item(self.cid, 'purpose')['revision']
        self.commit_change('boundaries', {'detail': 'Unrelated'}, 'unrelated')
        self.change('purpose', {'detail': 'Fresh edit'}, 'fresh', revision)
        self.commit_change('purpose', {'response': 'Concurrent response'}, 'concurrent')
        with self.assertRaisesRegex(ValueError, 'STALE_ITEM'):
            self.change('purpose', {'detail': 'Stale'}, 'stale', revision)
        revision = self.api.read_item(self.cid, 'purpose')['revision']
        self.commit_change('shape', {'completed': True}, 'close')
        with self.assertRaisesRegex(ValueError, 'STALE_ITEM'):
            self.change('purpose', {'detail': 'Stale scope'}, 'stale-scope', revision)

    def test_batch_failure_is_atomic_and_commit_rechecks_new_conflicts(self):
        a = self.api.read_item(self.cid, 'purpose')
        b = self.api.read_item(self.cid, 'boundaries')
        before = self.bridge.handoff_path().read_bytes()
        with self.assertRaisesRegex(ValueError, 'STALE_ITEM'):
            self.runtime.propose_item_edits(self.cid, [
                {'item_id': 'purpose', 'expected_revision': a['revision'], 'changes': {'detail': 'Do not stage'}},
                {'item_id': 'boundaries', 'expected_revision': '0' * 64, 'changes': {'detail': 'Stale'}}], 'CA1', '', 'atomic')
        self.assertEqual(before, self.bridge.handoff_path().read_bytes())
        first = self.change('purpose', {'detail': 'First'}, 'first')
        self.commit_change('purpose', {'detail': 'Second'}, 'second')
        self.assertFalse(self.api.preview(first['proposalId'])['readyToCommitAtRead'])
        with self.assertRaisesRegex(ValueError, 'Commit conflicts'):
            self.api.commit(first['proposalId'])

    def test_closed_scope_permits_discussion_not_task_rewrite(self):
        self.commit_change('shape', {'completed': True}, 'close')
        self.assertTrue(self.api.read_item(self.cid, 'purpose')['closedScope'])
        with self.assertRaisesRegex(ValueError, 'CONFLICT'):
            self.change('purpose', {'detail': 'Rewrite a closed task'}, 'rewrite')
        self.commit_change('purpose', {'response': 'Discussion remains possible'}, 'discussion')

    def test_invalid_field_types_request_reuse_and_noop_do_not_stage(self):
        revision = self.api.read_item(self.cid, 'purpose')['revision']
        for change in ({'id': 'replacement'}, {'completed': 1}, {'text': None}, {'needsReview': 'yes'}, {}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.change('purpose', change, 'invalid', revision)
        self.change('purpose', {'detail': 'A'}, 'same', revision)
        with self.assertRaisesRegex(ValueError, 'already used'):
            self.change('purpose', {'detail': 'B'}, 'same', revision)
        with self.assertRaisesRegex(ValueError, 'NO_CHANGE'):
            self.change('purpose', {'detail': self.doc['model']['items'][1]['detail']}, 'noop', revision)

    def test_briefing_pages_are_stable_and_checkpoint_only_on_final_page(self):
        self.assign('purpose')
        self.assign('boundaries')
        first = self.api.briefing(limit=1)
        self.assertEqual(len(first['items']), 1)
        self.assertIsNone(first['checkpoint'])
        self.assertIsNotNone(first['nextCursor'])
        self.commit_change('purpose', {'detail': 'Changed during pagination'}, 'during')
        second = self.api.briefing(cursor=first['nextCursor'], limit=1)
        self.assertEqual(len(second['items']), 1)
        self.assertIsNone(second['nextCursor'])
        self.assertNotEqual(first['items'][0]['itemId'], second['items'][0]['itemId'])
        since = self.api.briefing(since=second['checkpoint'])
        self.assertEqual([i['itemId'] for i in since['items']], ['purpose'])
        self.assertEqual(self.api.briefing(since=since['checkpoint'])['items'], [])
        with self.assertRaises(ValueError):
            self.api.briefing(for_actor='Someone else', cursor=first['nextCursor'])

    def test_briefing_reports_completed_and_reassigned_tasks_once(self):
        self.assign('purpose')
        initial = self.api.briefing()
        self.commit_change('purpose', {'completed': True}, 'finish')
        changed = self.api.briefing(since=initial['checkpoint'])
        self.assertTrue(changed['items'][0]['completed'])
        self.assertEqual(self.api.briefing(since=changed['checkpoint'])['items'], [])

    def test_review_attention_excludes_own_response_and_foreign_assignment(self):
        self.commit_change('purpose', {'response': 'My question'}, 'own')
        self.assertEqual(self.api.briefing()['items'], [])
        reader = AgentWorkspace(self.runtime, 'Human fixture')
        self.assertEqual(reader.briefing()['items'][0]['itemId'], 'purpose')
        self.assign('purpose', 'Different AI')
        self.assertEqual(reader.briefing()['items'], [])

    def test_cache_expiry_bounds_and_scope_rejection(self):
        clock = [0]
        cache = SessionCache(clock=lambda: clock[0], max_bytes=500)
        token = cache.put('checkpoint', {'some': 'context'})
        with self.assertRaises(ValueError):
            cache.get(token, 'handoff')
        clock[0] = 1800
        with self.assertRaisesRegex(ValueError, 'EXPIRED'):
            cache.get(token, 'checkpoint')
        with self.assertRaisesRegex(ValueError, 'limit'):
            cache.put('handoff', {'x': 'x' * 600})
        token = self.api.briefing()['checkpoint']
        with self.assertRaisesRegex(ValueError, 'different'):
            self.api.briefing(for_actor='Other', since=token)

    def test_nested_context_survives_commit_and_reconnect_without_touching_response(self):
        before = self.api.read_item(self.cid, 'purpose')
        prepared = self.api.prepare_handoff(self.cid, ['purpose'], 'Understand the task',
                    'Read current requirements', 'Ask one question', evidence='No execution yet',
                    parent_item_id='purpose', recipient='Next AI')
        self.assertFalse(prepared['saved'])
        draft = self.api.propose_handoff(prepared['handoffToken'], 'handoff')
        self.api.commit(draft['proposalId'])
        again = self.api.propose_handoff(prepared['handoffToken'], 'handoff')
        self.assertEqual(again['proposalId'], draft['proposalId'])
        restarted = AgentWorkspace(self.runtime, 'Next AI')
        task = restarted.read_item(self.cid, 'purpose')
        self.assertIn(prepared['contextItemId'], task['item']['requires'])
        self.assertEqual(task['item']['detail'], before['item']['detail'])
        self.assertNotIn('response', task['item'])
        context = restarted.read_item(self.cid, prepared['contextItemId'])
        self.assertFalse(context['completed'])
        self.assertIn('No execution yet', context['item']['detail'])
        self.assertEqual(context['item']['assignment']['status'], 'pending')
        self.assertEqual(restarted.briefing()['items'][0]['itemId'], prepared['contextItemId'])
        with self.assertRaisesRegex(ValueError, 'EXPIRED'):
            restarted.propose_handoff(prepared['handoffToken'], 'new-session')

    def test_handoff_refuses_missing_source_and_closed_parent(self):
        for key in ('missing',):
            with self.assertRaisesRegex(ValueError, 'NOT_FOUND'):
                self.api.prepare_handoff(self.cid, [key], 'Goal', 'Progress', 'Next')
        self.commit_change('shape', {'completed': True}, 'close')
        with self.assertRaisesRegex(ValueError, 'closed'):
            self.api.prepare_handoff(self.cid, ['purpose'], 'Goal', 'Progress', 'Next', parent_item_id='purpose')
        self.assertFalse(self.api.prepare_handoff(self.cid, ['purpose'], 'Goal', 'Progress', 'Next')['saved'])

    def test_health_and_receipt_remain_honest_when_followup_reads_fail(self):
        draft = self.change('purpose', {'response': 'Receipt test'})
        with patch.object(self.api, 'snapshot', side_effect=ValueError('Reconnect this MCP client to load the updated helper host')):
            status = self.api.status()
            self.assertFalse(status['readReady'])
            self.assertEqual(status['problem']['code'], 'RECONNECT_REQUIRED')
            receipt = self.api.commit(draft['proposalId'])
            self.assertEqual(receipt['delivery'], 'unknown')
            self.assertEqual(receipt['commit']['author'], 'CA1')
        self.assertEqual(self.api.read_item(self.cid, 'purpose')['item']['response'], 'Receipt test')
        with patch.object(self.api, 'preview', side_effect=OSError('private path')):
            result = self.api.draft_receipt(draft)
            self.assertEqual(result['proposalId'], draft['proposalId'])
            self.assertNotIn('private path', str(result))

    def test_preview_pagination_and_completion_are_explicit(self):
        draft = self.change('purpose', {'detail': 'x' * 1000, 'text': 'New title', 'completed': True})
        page = self.api.preview(draft['proposalId'], limit=1)
        self.assertIsNotNone(page['nextOffset'])
        all_changes = self.api.preview(draft['proposalId'])['changes']
        self.assertIn('completed', [c['field'] for c in all_changes])
        self.assertTrue(next(c for c in all_changes if c['field'] == 'detail')['after']['truncated'])

    def test_write_pause_protects_new_entrypoint_and_returns_retry_guidance(self):
        revision = self.api.read_item(self.cid, 'purpose')['revision']
        self.runtime.busy.set()
        with self.assertRaises(HelperUpdating) as raised:
            self.change('purpose', {'response': 'Paused'}, 'pause', revision)
        error = failure(raised.exception)
        self.assertTrue(error['retryable'])
        self.assertEqual(error['retryAfterMs'], 1000)
        self.assertEqual(self.api.status()['writeReadiness'], 'paused')

    def test_prepared_context_cannot_cross_library_and_large_reads_are_explicit(self):
        prepared = self.api.prepare_handoff(self.cid, ['purpose'], 'Goal', 'Progress', 'Next')
        data = self.api.cache.get(prepared['handoffToken'], 'handoff')
        data['libraryId'] = 'a-different-library'
        token = self.api.cache.put('handoff', data)
        before = self.bridge.handoff_path().read_bytes()
        with self.assertRaisesRegex(ValueError, 'different library'):
            self.api.propose_handoff(token, 'wrong-library')
        self.assertEqual(before, self.bridge.handoff_path().read_bytes())
        base = self.bridge.read_checklist(self.cid)['effectiveDocument']
        incoming = copy.deepcopy(base)
        incoming['model']['items'][1]['detail'] = '\U0001f332' * 100000
        draft = self.bridge.propose(base, incoming, 'CA1')
        self.bridge.commit_proposal(draft['proposalId'], 'CA1')
        with self.assertRaisesRegex(ValueError, '256 KiB'):
            self.api.read_item(self.cid, 'purpose')

    def test_incorporated_receipt_does_not_claim_human_review(self):
        draft = self.commit_change('purpose', {'response': 'Saved discussion'})
        effective = self.bridge.refresh_for_ai()['effectiveWorkspace']
        self.bridge.sync(effective, 2)
        self.bridge.mark(draft['proposalId'], 'applied', 'Synthetic browser incorporation', 'Human fixture')
        receipt = self.api.commit(draft['proposalId'])
        self.assertEqual(receipt['delivery'], 'incorporated-by-browser')
        self.assertFalse(receipt['humanReviewConfirmed'])


if __name__ == '__main__':
    unittest.main()
