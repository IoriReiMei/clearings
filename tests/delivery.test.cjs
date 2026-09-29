// SPDX-License-Identifier: MPL-2.0
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const api=require('../tools/contract.cjs');
const base=JSON.parse(fs.readFileSync(path.join(__dirname,'../examples/generic/program_overview.json'),'utf8'));
const copy=x=>JSON.parse(JSON.stringify(x));
const item=(d,id)=>d.model.items.find(i=>i.id===id);
async function plan(d,operations){return api.planAIChanges(d,{format:'checklist-studio-changes',schemaVersion:1,documentId:d.documentId,baseSha256:await api.aiHash(d),operations})}
(async()=>{
 let d=copy(base);d.state.purpose=true;d.attribution={purpose:{completed:{actor:'Linden',role:'assistant',at:'2026-09-29T00:00:00Z'}}};
 let r=await plan(d,[{op:'remove-item',id:'shape',mode:'keep-subtasks'}]);
 assert.ok(r.document.model.roots.includes('purpose'));assert.equal(r.document.state.purpose,true);assert.equal(r.document.attribution.purpose.completed.actor,'Linden');
 d=copy(base);item(d,'make').requires.push('purpose');
 r=await plan(d,[{op:'remove-item',id:'shape',mode:'subtree'}]);
 assert.ok(item(r.document,'purpose'));assert.ok(!item(r.document,'boundaries'));assert.ok(item(r.document,'make').requires.includes('purpose'));
 d=copy(base);item(d,'make').requires.push('purpose');d.state.make=true;
 await assert.rejects(()=>plan(d,[{op:'remove-item',id:'purpose',mode:'keep-subtasks'}]),/completed/);
 await assert.rejects(()=>plan(d,[{op:'move-items',itemIds:['boundaries'],fromParentId:'shape',toParentId:'shape',beforeId:'purpose'}]),/locks/);
 assert.ok(item(d,'purpose'),'Invalid batch must preserve the source');
 d=copy(base);for(const key of [...d.model.roots])d=(await plan(d,[{op:'remove-item',id:key,mode:'subtree'}])).document;
 assert.equal(d.model.items.length,0);api.validateDocument(d);
 d=copy(base);const stamp={actor:'Morrow',role:'assistant',at:'2026-09-29T00:00:00Z'};api.stampAttribution(d,null,stamp);
 const before=copy(d);d.state.purpose=true;api.stampAttribution(d,before,{...stamp,actor:'Linden'});
 const exported=JSON.parse(JSON.stringify(d));assert.equal(exported.attribution.purpose.created.actor,'Morrow');assert.equal(exported.attribution.purpose.completed.actor,'Linden');
 const activity=Array.from({length:510},(_,n)=>({action:'updated',checklistId:d.documentId,itemId:'boundaries',actor:'Someone',role:'human',at:stamp.at}));
 api.backfillAttribution(d,activity);assert.equal(d.attribution.purpose.completed.actor,'Linden');
 console.log('Delivery checks passed: removal modes, shared descendants, lock parity, empty list, durable attribution.');
})().catch(e=>{console.error(e);process.exitCode=1});
