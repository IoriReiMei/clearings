// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {validateWorkspace,progressStats,PREFERENCE_DEFAULTS}=require('../tools/contract.cjs');
const root=path.join(__dirname,'..');
const index=JSON.parse(fs.readFileSync(path.join(root,'examples/generic/checklist_index.json')));
const base={format:'checklist-studio-workspace',schemaVersion:1,index,documents:index.entries.map(e=>JSON.parse(fs.readFileSync(path.join(root,'examples/generic',e.file))))};
const clone=x=>JSON.parse(JSON.stringify(x));let count=0;
const v3Defaults=Object.fromEntries(Object.entries(PREFERENCE_DEFAULTS).filter(([key])=>!['openTopChecklist','displayName','showFooterProgress','showFooterTrack','clearOnRefreshPress'].includes(key)));
const test=(n,fn)=>{fn();console.log('PASS '+n);count++;};
test('version-1 index imports without changing source',()=>{assert.deepEqual(clone(validateWorkspace(base)),base);});
test('version-2 preferences validate without changing documents',()=>{const w=clone(base);w.index.schemaVersion=2;w.index.preferences={library:true,tracked:true,map:true,theme:'system',showProgress:true,progressFormat:'percent',rollup:true,autosave:true,saveDelay:1000,motion:'system'};const checked=clone(validateWorkspace(w));assert.deepEqual(checked.documents,base.documents);});
test('version-3 preferences validate new progress choices',()=>{const w=clone(base);w.index.schemaVersion=3;w.index.preferences={...v3Defaults};const checked=clone(validateWorkspace(w));assert.equal(checked.index.preferences.groupProgress,'children');assert.equal(checked.index.preferences.progressVisual,'bar');});
test('version-4 records startup choice, display name and bounded activity',()=>{const w=clone(base);w.index.schemaVersion=4;w.index.preferences={...PREFERENCE_DEFAULTS,displayName:'Human tester'};w.index.activity=[{id:'a1',at:'2026-09-27T12:00:00Z',actor:'Assistant tester',role:'assistant',action:'updated',checklistId:'example-overview',itemId:'purpose',approvedBy:'Human tester',highlight:true,unread:true}];assert.deepEqual(clone(validateWorkspace(w)),w);});
test('version-3 cannot silently adopt version-4 preferences',()=>{const w=clone(base);w.index.schemaVersion=3;w.index.preferences={...v3Defaults,openTopChecklist:true};assert.throws(()=>validateWorkspace(w));});
test('bottom controls default off and require the current preference schema',()=>{assert.equal(PREFERENCE_DEFAULTS.showFooterProgress,false);assert.equal(PREFERENCE_DEFAULTS.showFooterTrack,false);for(const key of ['showFooterProgress','showFooterTrack']){const old=clone(base);old.index.schemaVersion=3;old.index.preferences={...v3Defaults,[key]:true};assert.throws(()=>validateWorkspace(old));const bad=clone(base);bad.index.schemaVersion=4;bad.index.preferences={...PREFERENCE_DEFAULTS,[key]:'yes'};bad.index.activity=[];assert.throws(()=>validateWorkspace(bad));}});
test('activity cannot point to a missing item or claim an unknown role',()=>{const w=clone(base);w.index.schemaVersion=4;w.index.preferences={...PREFERENCE_DEFAULTS};w.index.activity=[{id:'a1',at:'2026-09-27T12:00:00Z',actor:'Second assistant',role:'assistant',action:'new',checklistId:'example-overview',itemId:'purpose',approvedBy:'Human tester',highlight:true,unread:true}];for(const changes of [{itemId:'missing'},{role:'unknown'}]){const bad=clone(w);Object.assign(bad.index.activity[0],changes);assert.throws(()=>validateWorkspace(bad));}});
test('version-2 index refuses version-3 progress preferences',()=>{for(const key of ['groupProgress','progressVisual']){const w=clone(base);w.index.schemaVersion=2;w.index.preferences[key]=PREFERENCE_DEFAULTS[key];assert.throws(()=>validateWorkspace(w));}});
test('unknown preference refuses instead of silently dropping it',()=>{const w=clone(base);w.index.schemaVersion=2;w.index.preferences.unknown=1;assert.throws(()=>validateWorkspace(w));});
test('old index cannot silently adopt new settings without version change',()=>{const w=clone(base);w.index.preferences.rollup=true;assert.throws(()=>validateWorkspace(w));});
test('save interval is bounded and typed',()=>{for(const n of [0,-1,1,20000,'1000']){const w=clone(base);w.index.schemaVersion=4;w.index.preferences={...PREFERENCE_DEFAULTS,saveDelay:n};w.index.activity=[];assert.throws(()=>validateWorkspace(w));}});
test('new progress preferences are bounded enums',()=>{for(const [key,value] of [['groupProgress','leaves'],['progressVisual','gauge']]){const w=clone(base);w.index.schemaVersion=4;w.index.preferences={...PREFERENCE_DEFAULTS,[key]:value};w.index.activity=[];assert.throws(()=>validateWorkspace(w));}});
test('all-false progress is zero',()=>{const s=progressStats(base.documents[0]);assert.equal(s.done,0);assert.equal(s.total,15);});
test('closed parent covers descendants but not unrelated groups',()=>{const d=clone(base.documents[0]);d.state.shape=true;const s=progressStats(d);assert.equal(s.done,6);assert.equal(s.explicit,1);assert.equal(s.covered,5);});
test('rollup does not write child booleans',()=>{const d=clone(base.documents[0]);d.state.shape=true;const before=JSON.stringify(d);progressStats(d);assert.equal(JSON.stringify(d),before);});
test('explicit-only counts survive switching back',()=>{const d=clone(base.documents[0]);d.state.shape=true;assert.equal(progressStats(d,null,false).done,1);});
test('shared supporting items count once and any closed ancestor covers them',()=>{const d=clone(base.documents[0]);d.model.items.find(i=>i.id==='make').requires.push('purpose');d.state.make=true;const s=progressStats(d);assert.equal(s.total,15);assert.equal(s.done,5);assert.equal(progressStats(d,'purpose').done,1);});
test('unchecking parent restores only explicit contributions',()=>{const d=clone(base.documents[0]);d.state.shape=true;d.state.purpose=true;progressStats(d);d.state.shape=false;assert.equal(progressStats(d).done,1);});
test('group progress can exclude the heading itself',()=>{const d=clone(base.documents[0]);d.state.purpose=true;const s=progressStats(d,'shape',true,false);assert.equal(s.total,5);assert.equal(s.done,1);assert.equal(s.explicit,1);assert.equal(s.includesSelf,false);});
test('flat group progress includes the heading itself',()=>{const d=clone(base.documents[0]);d.state.shape=true;const s=progressStats(d,'shape',true,true);assert.equal(s.total,6);assert.equal(s.done,6);assert.equal(s.explicit,1);assert.equal(s.covered,5);assert.equal(s.includesSelf,true);});
test('children-only group progress reaches 100 when parent covers descendants',()=>{const d=clone(base.documents[0]);d.state.shape=true;const s=progressStats(d,'shape',true,false);assert.equal(s.total,5);assert.equal(s.done,5);assert.equal(s.explicit,0);assert.equal(s.covered,5);});
test('whole-checklist progress remains flat across all tasks',()=>{const d=clone(base.documents[0]);d.state.shape=true;const s=progressStats(d,null,true,false);assert.equal(s.total,15);assert.equal(s.done,6);});
test('fold state does not affect progress',()=>{const d=clone(base.documents[0]);d.state.shape=true;const a=progressStats(d);d.view.collapsed=['shape','make','share'];assert.deepEqual(progressStats(d),a);});
console.log(`${count} preference/progress checks passed.`);
