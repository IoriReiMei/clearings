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
 for(const href of [' javascript:alert(1)','\tjavascript:alert(1)',' //attacker.example/path','\ufeffjavascript:alert(1)','https://example.test/path\n'])
  await reject('trimmed unsafe reference '+JSON.stringify(href),()=>{const d=clone(original);d.references=[{title:'Unsafe',href}];api.validateDocument(d)},/links/);
 await test('ordinary HTTP and relative references remain valid',()=>{const d=clone(original);d.references=[{title:'Web',href:'https://example.test/path'},{title:'Local',href:'docs/notes with spaces.html'}];api.validateDocument(d)});
 await reject('tracked dangling item rejected',()=>{const w=clone(workspace);w.index.tracked[0].itemId='gone';api.validateWorkspace(w)},/missing/);
 await test('shared items do not become duplicates',()=>{const d=clone(original);d.model.items.find(i=>i.id==='make').requires.push('purpose');assert.equal(api.validateDocument(d).model.items.length,original.model.items.length)});
 await test('center rendering bounds a valid shared-task diamond without deleting links',()=>{
 const rendering=html.split('const CENTER_ROW_LIMIT=1200;')[1]?.split('function renderCenter(){')[0];
  assert.ok(rendering,'bounded center renderer is present');
  const presentation=['tagPreview','rowTags','inlineTags','previewText'].map(name=>{
   const line=html.match(new RegExp('^function '+name+'\\(.*$', 'm'))?.[0];
   assert.ok(line,`presentation helper ${name} is present`);return line;
  }).join('\n');
  const items=[];
  for(let level=0;level<24;level++)for(const side of ['a','b']){
   const id=side+level,requires=level===23?['last']:['a'+(level+1),'b'+(level+1)];
   items.push({id,text:id,requires,label:'',tags:[],detail:''});
  }
  items.push({id:'last',text:'last',requires:[],label:'',tags:[],detail:''});
  const byId=new Map(items.map(item=>[item.id,item]));
  Object.assign(box,{node:(_doc,id)=>byId.get(id),isLocked:()=>false,centerIsCollapsed:()=>false,
   // This graph fixture has no activity; notification behavior has its own browser checks.
   highlightedActivity:()=>null,latestActivity:()=>null,changesInside:()=>null,insideTag:()=>'',contextLocked:()=>false,
   gripHTML:()=>'',progressHTML:()=>'',menuButton:()=>'',
   esc:String,detailsOpen:new Set()});
  vm.runInContext(presentation+'\nconst CENTER_ROW_LIMIT=1200;'+rendering+'\nthis.renderRowsForTest=renderRows;this.setCenterPageForTest=(key,index)=>centerPages.set(key,index);',box);
  const d={documentId:'diamond',state:{},model:{items,roots:['a0']}};
  const rendered=box.renderRowsForTest(d,['a0'],null,{count:0,notice:false});
  const occurrences=(rendered.match(/data-step-row=/g)||[]).length;
  assert.ok(occurrences>items.length,'valid shared links remain visible');
  assert.ok(occurrences<=1200,`rendered ${occurrences} occurrences`);
  assert.ok(rendered.length<2_000_000,'HTML allocation is bounded');
  assert.match(rendered,/This view shows a bounded part of the checklist/);
  assert.equal(items.length,49,'the underlying graph is preserved');
  const flat=Array.from({length:1201},(_,n)=>({id:'flat'+n,text:'Flat '+n,requires:[],label:'',tags:[],detail:''}));
  const flatById=new Map(flat.map(item=>[item.id,item]));box.node=(_doc,id)=>flatById.get(id);
  const flatDoc={documentId:'flat',state:{},model:{items:flat,roots:flat.map(i=>i.id)}};
  const first=box.renderRowsForTest(flatDoc,flat.map(i=>i.id),'parent',{count:0,notice:false});
  assert.equal((first.match(/data-step-row=/g)||[]).length,1200);
  assert.match(first,/data-index="1200"/);
  box.setCenterPageForTest('flat:parent',1200);
  const last=box.renderRowsForTest(flatDoc,flat.map(i=>i.id),'parent',{count:0,notice:false});
  assert.equal((last.match(/data-step-row=/g)||[]).length,1);
  assert.match(last,/flat1200/);
  const shared=byId.get('last');
  shared.text='T'.repeat(200_000);shared.label='L'.repeat(10_000);
  shared.tags=Array(1000).fill('G'.repeat(1000));shared.detail='D'.repeat(100_000);
  box.detailsOpen.add('diamond:last');
  box.node=(_doc,id)=>byId.get(id);
  const loaded=box.renderRowsForTest(d,['a0'],null,{count:0,notice:false});
  assert.ok(loaded.length<2_000_000,`shared expanded rows allocated ${loaded.length} characters`);
  assert.ok(!loaded.includes('T'.repeat(1000))&&!loaded.includes('L'.repeat(1000)),'long repeated text is previewed');
  assert.equal(shared.text.length,200_000,'stored title is unchanged');
  assert.equal(shared.tags.length,1000,'stored tags are unchanged');
 });
 await test('AI hash ignores fold state and write timestamp',async()=>{const d=clone(original);d.view.collapsed=['shape'];d.updatedAt='2026-09-25T12:00:00Z';assert.equal(await api.aiHash(d),await api.aiHash(original))});
 await test('AI hash is stable under object key order',async()=>{const d=Object.fromEntries(Object.entries(original).reverse());assert.equal(await api.aiHash(d),await api.aiHash(original))});
 await test('AI title edit is scoped and leaves input untouched',async()=>{const p=await packet(original,[{op:'update-item',id:'purpose',changes:{text:'A clearer purpose'}}]);const result=await api.planAIChanges(original,p);assert.equal(result.document.model.items.find(i=>i.id==='purpose').text,'A clearer purpose');assert.equal(original.model.items.find(i=>i.id==='purpose').text,'Describe who it helps');assert.equal(JSON.stringify(result.document.state),JSON.stringify(original.state))});
 await test('AI adds parent then nested child unchecked',async()=>{const p=await packet(original,[{op:'add-item',parentId:null,item:blankItem('extra','Extra')},{op:'add-item',parentId:'extra',item:blankItem('sub','Subtask')}]);const r=await api.planAIChanges(original,p);assert.ok(r.document.model.roots.includes('extra'));assert.equal(r.document.model.items.find(i=>i.id==='extra').requires[0],'sub');assert.equal(r.document.state.sub,undefined);assert.equal(r.summary[0].after.requires.length,0)});
 await test('AI sibling reordering only changes ordered edge list',async()=>{const p=await packet(original,[{op:'reorder',parentId:'shape',itemIds:['first-look','boundaries','purpose']}]);const r=await api.planAIChanges(original,p);assert.equal(JSON.stringify(r.document.model.items.find(i=>i.id==='shape').requires),'["first-look","boundaries","purpose"]');assert.equal(JSON.stringify(r.document.model.items.map(i=>i.id)),JSON.stringify(original.model.items.map(i=>i.id)))});
 await test('AI move preserves the item and its checkmark',async()=>{const d=clone(original);d.state.purpose=true;const p=await packet(d,[{op:'move-items',itemIds:['purpose'],fromParentId:'shape',toParentId:'make',beforeId:null}]);const r=await api.planAIChanges(d,p);assert.equal(r.document.model.items.find(i=>i.id==='shape').requires.includes('purpose'),false);assert.equal(r.document.model.items.find(i=>i.id==='make').requires.at(-1),'purpose');assert.equal(JSON.stringify(r.document.model.items.find(i=>i.id==='purpose')),JSON.stringify(d.model.items.find(i=>i.id==='purpose')));assert.equal(r.document.state.purpose,true)});
 await test('AI shared item move changes only the named parent link',async()=>{const d=clone(original);d.model.items.find(i=>i.id==='make').requires.push('purpose');const p=await packet(d,[{op:'move-items',itemIds:['purpose'],fromParentId:'shape',toParentId:'share',beforeId:null}]);const r=await api.planAIChanges(d,p);assert.equal(r.document.model.items.find(i=>i.id==='make').requires.includes('purpose'),true);assert.equal(r.document.model.items.find(i=>i.id==='shape').requires.includes('purpose'),false);assert.equal(r.document.model.items.find(i=>i.id==='share').requires.includes('purpose'),true);assert.equal(r.document.model.items.filter(i=>i.id==='purpose').length,1)});
 await reject('AI move to descendant refuses a cycle',async()=>api.planAIChanges(original,await packet(original,[{op:'move-items',itemIds:['shape'],fromParentId:null,toParentId:'purpose',beforeId:null}])),/cycle/);
 await reject('AI move missing destination is refused',async()=>api.planAIChanges(original,await packet(original,[{op:'move-items',itemIds:['purpose'],fromParentId:'shape',toParentId:'missing',beforeId:null}])),/Missing item/);
 await reject('AI move from checked ancestor is refused',async()=>{const d=clone(original);d.state.shape=true;await api.planAIChanges(d,await packet(d,[{op:'move-items',itemIds:['purpose'],fromParentId:'shape',toParentId:'make',beforeId:null}]))},/completed heading/);
 await reject('AI move cannot silently replace an existing shared link',async()=>{const d=clone(original);d.model.items.find(i=>i.id==='make').requires.push('purpose');await api.planAIChanges(d,await packet(d,[{op:'move-items',itemIds:['purpose'],fromParentId:'shape',toParentId:'make',beforeId:null}]))},/already links/);
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
