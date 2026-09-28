// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
'use strict';
// No npm dependencies. Tests execute the app's actual pure validation block.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const localApp = path.resolve(__dirname, '../LC_CHECKLIST.html');
const app = fs.existsSync(localApp) ? localApp : path.resolve(__dirname, '../index.html');
const html = fs.readFileSync(app, 'utf8');
const block = html.split('/* CONTRACT_BEGIN: pure validators and proposal planning; shared by local tests. */')[1]?.split('/* CONTRACT_END */')[0];
assert.ok(block, 'Pure app contract markers are present');
const box = {crypto:webcrypto,TextEncoder,Blob};
vm.createContext(box);
vm.runInContext(block + '\nthis.contract={validateDocument,validateWorkspace,migrateDocument,aiHash,planAIChanges,canonicalJSON,aiDocumentKey};',box);
const api=box.contract;
const clone=x=>JSON.parse(JSON.stringify(x));
const sample=path.resolve(__dirname,'../examples/generic');
const index=JSON.parse(fs.readFileSync(path.join(sample,'checklist_index.json'),'utf8'));
const docs=index.entries.map(e=>JSON.parse(fs.readFileSync(path.join(sample,e.file),'utf8')));
const workspace={format:'checklist-studio-workspace',schemaVersion:1,index,documents:docs};
const original=clone(docs[0]);
let passed=0;
async function test(name,fn){try{await fn();passed++;console.log('PASS '+name)}catch(e){console.error('FAIL '+name);throw e}}
async function reject(name,fn,match){await test(name,async()=>{await assert.rejects(async()=>fn(),match)})}
const packet=async(d,operations)=>({format:'checklist-studio-changes',schemaVersion:1,documentId:d.documentId,baseSha256:await api.aiHash(d),operations});
const blankItem=(id,text)=>({id,order:1,parents:[],label:'',tags:[],text,detail:'',requires:[]});
(async()=>{
 await test('generic workspace round trip',()=>assert.equal(JSON.stringify(api.validateWorkspace(workspace)),JSON.stringify(workspace)));
 await test('legacy format markers preserved',()=>{const w=clone(workspace);w.format='local-companion-checklist-workspace';w.index.format='local-companion-checklist-index';w.documents.forEach(d=>d.format='local-companion-checklist');assert.equal(JSON.stringify(api.validateWorkspace(w)),JSON.stringify(w))});
 await reject('future schema rejected',()=>api.validateDocument({...original,schemaVersion:999}),/Unsupported/);
 await reject('unknown data preserved by refusal',()=>api.validateDocument({...original,unrecognized:'keep me'}),/unsupported field/);
 await reject('duplicate item ID rejected',()=>{const d=clone(original);d.model.items.push(clone(d.model.items[0]));api.validateDocument(d)},/duplicate/);
 await reject('dangling hierarchy rejected',()=>{const d=clone(original);d.model.items[0].requires.push('missing');api.validateDocument(d)},/Missing/);
 await reject('cycle rejected',()=>{const d=clone(original);d.model.items.find(i=>i.id==='purpose').requires=['shape'];api.validateDocument(d)},/cycle/);
 await reject('orphan rejected',()=>{const d=clone(original);d.model.items.push(blankItem('unlinked','Unlinked'));api.validateDocument(d)},/no path/);
 await reject('prototype key ID rejected',()=>{const d=clone(original);d.model.items[0].id='__proto__';api.validateDocument(d)},/ID/);
 await reject('unsafe file path rejected',()=>{const w=clone(workspace);w.index.entries[0].file='../secret.json';api.validateWorkspace(w)},/filename/);
 await reject('case-insensitive filename collision rejected',()=>{const w=clone(workspace);w.index.entries[1].file=w.index.entries[0].file.toUpperCase();api.validateWorkspace(w)},/filename/);
 await reject('javascript link rejected',()=>{const d=clone(original);d.references=[{title:'Unsafe',href:'javascript:alert(1)'}];api.validateDocument(d)},/links/);
 await reject('tracked dangling item rejected',()=>{const w=clone(workspace);w.index.tracked[0].itemId='gone';api.validateWorkspace(w)},/missing/);
 await test('shared items do not become duplicates',()=>{const d=clone(original);d.model.items.find(i=>i.id==='make').requires.push('purpose');assert.equal(api.validateDocument(d).model.items.length,original.model.items.length)});
 await test('AI hash ignores fold state and write timestamp',async()=>{const d=clone(original);d.view.collapsed=['shape'];d.updatedAt='2026-09-25T12:00:00Z';assert.equal(await api.aiHash(d),await api.aiHash(original))});
 await test('AI hash is stable under object key order',async()=>{const d=Object.fromEntries(Object.entries(original).reverse());assert.equal(await api.aiHash(d),await api.aiHash(original))});
 await test('AI title edit is scoped and leaves input untouched',async()=>{const p=await packet(original,[{op:'update-item',id:'purpose',changes:{text:'A clearer purpose'}}]);const result=await api.planAIChanges(original,p);assert.equal(result.document.model.items.find(i=>i.id==='purpose').text,'A clearer purpose');assert.equal(original.model.items.find(i=>i.id==='purpose').text,'Describe who it helps');assert.equal(JSON.stringify(result.document.state),JSON.stringify(original.state))});
 await test('AI adds parent then nested child unchecked',async()=>{const p=await packet(original,[{op:'add-item',parentId:null,item:blankItem('extra','Extra')},{op:'add-item',parentId:'extra',item:blankItem('sub','Subtask')}]);const r=await api.planAIChanges(original,p);assert.ok(r.document.model.roots.includes('extra'));assert.equal(r.document.model.items.find(i=>i.id==='extra').requires[0],'sub');assert.equal(r.document.state.sub,undefined);assert.equal(r.summary[0].after.requires.length,0)});
 await test('AI sibling reordering only changes ordered edge list',async()=>{const p=await packet(original,[{op:'reorder',parentId:'shape',itemIds:['first-look','boundaries','purpose']}]);const r=await api.planAIChanges(original,p);assert.equal(JSON.stringify(r.document.model.items.find(i=>i.id==='shape').requires),'["first-look","boundaries","purpose"]');assert.equal(JSON.stringify(r.document.model.items.map(i=>i.id)),JSON.stringify(original.model.items.map(i=>i.id)))});
 await reject('AI stale content rejected',async()=>{const p=await packet(original,[{op:'update-item',id:'purpose',changes:{text:'Changed'}}]);const d=clone(original);d.title+=' updated';await api.planAIChanges(d,p)},/changed since/);
 await reject('AI stale completion rejected',async()=>{const p=await packet(original,[{op:'update-item',id:'purpose',changes:{text:'Changed'}}]);const d=clone(original);d.state.purpose=true;await api.planAIChanges(d,p)},/changed since/);
 await reject('AI wrong checklist rejected',async()=>{const p=await packet(original,[{op:'set-done',id:'shape',done:true}]);p.documentId='other';await api.planAIChanges(original,p)},/different checklist/);
 await reject('AI missing fingerprint rejected',()=>api.planAIChanges(original,{format:'checklist-studio-changes',schemaVersion:1,documentId:original.documentId,operations:[]}),/baseSha256/);
 await reject('AI unsupported delete rejected',async()=>api.planAIChanges(original,await packet(original,[{op:'delete',id:'purpose'}])),/Unsupported operation/);
 await reject('AI ID replacement rejected',async()=>api.planAIChanges(original,await packet(original,[{op:'update-item',id:'purpose',changes:{id:'new'}}])),/unsupported field/);
 await reject('AI hierarchy disguised as edit rejected',async()=>api.planAIChanges(original,await packet(original,[{op:'update-item',id:'shape',changes:{requires:[]}}])),/unsupported field/);
 await reject('AI duplicate new ID rejected',async()=>api.planAIChanges(original,await packet(original,[{op:'add-item',parentId:null,item:blankItem('purpose','Collision')}])),/unique/);
 await reject('AI incomplete sibling order rejected',async()=>api.planAIChanges(original,await packet(original,[{op:'reorder',parentId:'shape',itemIds:['purpose']}])),/exactly/);
 await reject('AI unknown category rejected',async()=>api.planAIChanges(original,await packet(original,[{op:'update-item',id:'purpose',changes:{parents:['unknown']}}])),/category/);
 await reject('AI locked descendant rejected',async()=>{const d=clone(original);d.state.shape=true;await api.planAIChanges(d,await packet(d,[{op:'update-item',id:'purpose',changes:{text:'Locked'}}]))},/locks/);
 await reject('AI locked second parent path rejected',async()=>{const d=clone(original);d.model.items.find(i=>i.id==='make').requires.push('purpose');d.state.make=true;await api.planAIChanges(d,await packet(d,[{op:'update-item',id:'purpose',changes:{text:'Locked'}}]))},/locks/);
 await reject('AI adding below closed heading rejected',async()=>{const d=clone(original);d.state.shape=true;await api.planAIChanges(d,await packet(d,[{op:'add-item',parentId:'shape',item:blankItem('blocked','Blocked') }]))},/completed heading/);
 await reject('AI invalid batch never mutates source',async()=>{const before=JSON.stringify(original);try{await api.planAIChanges(original,await packet(original,[{op:'update-item',id:'purpose',changes:{text:'Would change'}},{op:'reorder',parentId:'shape',itemIds:['gone']}]))}finally{assert.equal(JSON.stringify(original),before)}},/exactly/);
 await test('AI explicit parent closure leaves children untouched',async()=>{const r=await api.planAIChanges(original,await packet(original,[{op:'set-done',id:'shape',done:true}]));assert.equal(r.document.state.shape,true);assert.equal(r.document.state.purpose,undefined);assert.equal(r.completionChanges,1)});
 await test('AI escaped markup remains text in stored data',async()=>{const r=await api.planAIChanges(original,await packet(original,[{op:'update-item',id:'purpose',changes:{text:'<img src=x onerror=alert(1)>'}}]));assert.equal(r.document.model.items.find(i=>i.id==='purpose').text,'<img src=x onerror=alert(1)>')});
 await reject('AI op count is bounded',async()=>api.planAIChanges(original,await packet(original,Array(101).fill({op:'set-done',id:'purpose',done:false}))),/1–100/);
 await test('app blocks unsolicited network connections',()=>assert.ok(html.includes("connect-src 'none'")));
 console.log('\n'+passed+' contract checks passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
