// SPDX-License-Identifier: MIT
// MIT License
//
// Copyright (c) 2026 The Hermit
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.
'use strict';
// Exercise the actual browser handoff functions against disposable stubs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const appRoot = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(appRoot, fs.existsSync(path.join(appRoot,'LC_CHECKLIST.html')) ? 'LC_CHECKLIST.html' : 'index.html'), 'utf8');
function block(start, end) {
  const a = html.indexOf(start), b = html.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, `missing handoff source block ${start}`);
  return html.slice(a, b);
}
const syncSource = block('let localSyncQueue=Promise.resolve();', 'function proposalPlan(');
const newSource = block('async function commitLocalNewProposal(', 'let refreshInert=[];');
const commitSource = block('async function commitLocalProposal(', 'async function refreshLocal(');
const refreshSource = block('async function refreshLocal(', 'function readStore(');
const clone = x => JSON.parse(JSON.stringify(x));

async function testPreservesOriginalSyncError() {
  let calls = 0;
  const box = {Promise, localBridgeToken: 'fixture', localSyncBlocked: false,
    localError: '', localKnownGeneration: 1, clone, updateSaveStatus() {}, toast() {},
    async localRequest() {calls++; throw Error('Handoff exceeds 16 MB; nothing was written');}};
  vm.createContext(box);
  vm.runInContext(syncSource + '\nthis.api={performLocalSync,localSync};', box);
  assert.equal(await box.api.performLocalSync({}, 2), false);
  assert.equal(box.localSyncBlocked, true);
  assert.equal(box.localError, 'Handoff exceeds 16 MB; nothing was written');
  assert.equal(await box.api.performLocalSync({}, 2), false);
  assert.equal(calls, 1, 'a later autosave cannot silently retry a blocked handoff');
  assert.equal(box.localError, 'Handoff exceeds 16 MB; nothing was written');
}

function fixture() {
  const old = {documentId: 'one', title: 'Original', description: '', subtitle: '', footer: '',
    model: {items: []}, state: {}};
  const next = {...clone(old), title: 'Changed'};
  const proposal = {id: 'p1', kind: 'edit', documentId: 'one', actor: 'Morrow',
    createdAt: '2026-10-01T00:00:00Z', incoming: next};
  const second = {...proposal, id: 'p2'};
  let saves = 0, marks = 0, syncs = 0;
  const box = {Promise, Blob, Date, MAX_BYTES: 16*1024*1024, localBridgeToken: 'fixture',
    localSyncBlocked: false, localError: '', localKnownGeneration: 1,
    localBusy: false, lastRefreshAt: 0, started: true, browserConflict: false, browserDB: {},
    browserSaving: false, dirty: false, pendingDraft: null, baseGeneration: 1,
    browserSavedAt: '', firstDirtyAt: 0, revision: 0, workspace: {index: {activity: []}, documents: [old]},
    localPending: [proposal, second], refreshClearArmed: false, clone,
    getDoc(id) {return box.workspace.documents.find(d => d.documentId === id);},
    preferences() {return {clearOnRefreshPress: false, displayName: 'Hermit'};},
    validateDocument: x => x, validateWorkspace: x => x, preserveAttribution() {},
    pruneDocumentLinks() {}, stampAttribution() {}, uid: () => 'activity',
    refreshIndexes() {}, render() {}, renderLibrary() {}, updateSaveStatus() {}, toast() {},
    setRefreshBusy(value) {box.localBusy = value;},
    async loadLocalPending() {return box.localPending;},
    proposalPlan() {return {merged: next, unresolved: [], applied: true};},
    async commitBrowserSnapshot() {saves++;},
    async localSync() {syncs++; box.localSyncBlocked = true;
      box.localError = 'Handoff exceeds 16 MB; nothing was written'; return false;},
    async localRequest() {marks++; return {};},
    validateIncomingChecklist: p => p.incoming,
  };
  vm.createContext(box);
  vm.runInContext(newSource + '\n' + commitSource + '\n' + refreshSource +
    '\nthis.api={commitLocalNewProposal,commitLocalProposal,refreshLocal};', box);
  return {box, proposal, counts: () => ({saves, marks, syncs})};
}

async function testRefreshStopsAfterFailedSync() {
  const {box, counts} = fixture();
  await box.api.refreshLocal();
  assert.deepEqual(counts(), {saves: 1, marks: 0, syncs: 1});
  assert.equal(box.workspace.documents[0].title, 'Changed', 'first edit stays browser-saved');
  assert.equal(box.localPending.length, 2, 'both proposals remain pending');
  assert.equal(box.localError, 'Handoff exceeds 16 MB; nothing was written');
  assert.equal(box.localSyncBlocked, true);
  box.lastRefreshAt = 0; // Bypass the click cooldown to exercise the blocked guard.
  await box.api.refreshLocal();
  assert.deepEqual(counts(), {saves: 1, marks: 0, syncs: 1}, 'blocked refresh cannot apply another proposal');
}

async function testNewChecklistStopsAfterFailedSync() {
  const {box, counts} = fixture();
  const newDoc = {documentId: 'new', title: 'New', archived: false,
    model: {items: [{id: 'i1'}]}, state: {}};
  box.localPending = [{id: 'new-proposal', kind: 'create', documentId: 'new',
    actor: 'Morrow', createdAt: '2026-10-01T00:00:00Z', commit: {author: 'Morrow'}, incoming: newDoc}];
  box.workspace.index.schemaVersion = 4;
  box.workspace.index.entries = [{id: 'one', file: 'checklist-one.json'}];
  box.workspace.index.defaultChecklist = 'one';
  await box.api.refreshLocal();
  assert.deepEqual(counts(), {saves: 1, marks: 0, syncs: 1});
  assert.equal(box.workspace.documents.length, 2, 'new list stays browser-saved');
  assert.equal(box.localPending[0].id, 'new-proposal', 'receipt remains pending');
  assert.equal(box.localError, 'Handoff exceeds 16 MB; nothing was written');
}

(async () => {
  await testPreservesOriginalSyncError(); console.log('PASS original sync error survives later autosave');
  await testRefreshStopsAfterFailedSync(); console.log('PASS Refresh stops after failed sync');
  await testNewChecklistStopsAfterFailedSync(); console.log('PASS new-list Refresh stops after failed sync');
})().catch(error => {console.error(error); process.exitCode = 1;});
