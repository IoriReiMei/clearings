// SPDX-License-Identifier: MIT
// Copyright (c) 2026 The Hermit. See ../LICENSE.
'use strict';
// Synthetic Bridge -> ordinary context item -> browser import/render/export.
// In-memory storage and a new headless browser; no live helper or user profile.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {spawnSync}=require('node:child_process');
const {createHash}=require('node:crypto');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const python=process.env.CLEARINGS_TEST_PYTHON||(process.platform==='win32'?'python':'python3');
const code=`
import json,sys,tempfile
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'tools'))
from clearings_local import Bridge,RuntimeBridge
from clearings_agent import AgentWorkspace
with tempfile.TemporaryDirectory(prefix='clearings-browser-context-') as temp:
    bridge=Bridge(Path(temp)/'config')
    doc=json.loads((root/'examples/generic/program_overview.json').read_text(encoding='utf-8'))
    ws={'format':'checklist-studio-workspace','schemaVersion':1,'index':{'format':'checklist-studio-index','schemaVersion':4,'libraryId':'browser-context-fixture','defaultChecklist':doc['documentId'],'entries':[{'id':doc['documentId'],'file':'fixture.json'}],'tracked':[],'activity':[],'preferences':{'library':True,'tracked':True,'map':True,'theme':'system','displayName':'Fixture human'}},'documents':[doc]}
    bridge.sync(ws,1)
    api=AgentWorkspace(RuntimeBridge(bridge),'Browser fixture',True)
    prepared=api.prepare_handoff(doc['documentId'],['purpose'],'Keep continuity visible','Read requirements; no execution','Ask the owner about the fixture',evidence='<img src=x onerror=window.contextInjected=true>',parent_item_id='purpose')
    draft=api.propose_handoff(prepared['handoffToken'],'browser-context')
    api.commit(draft['proposalId'])
    print(json.dumps({'workspace':bridge.refresh_for_ai()['effectiveWorkspace'],'itemId':prepared['contextItemId']},ensure_ascii=True))
`;
const fixture=spawnSync(python,['-B','-c',code,root],{encoding:'utf8'});
assert.equal(fixture.status,0,fixture.stderr);
const data=JSON.parse(fixture.stdout),cid=data.workspace.documents[0].documentId;
require('../tools/contract.cjs').validateWorkspace(data.workspace);
const app=fs.readFileSync(path.join(root,fs.existsSync(path.join(root,'LC_CHECKLIST.html'))?'LC_CHECKLIST.html':'index.html'),'utf8');
const mock=fs.readFileSync(path.join(root,'tests/browser_storage_mock.js'),'utf8');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
 try{
  for(const viewport of [{width:1440,height:960},{width:390,height:844}]){
   const page=await browser.newPage({viewport,bypassCSP:true});
   const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/*',route=>route.abort());
   await page.exposeFunction('__digest',bytes=>[...createHash('sha256').update(Buffer.from(bytes)).digest()]);
   await page.evaluate(mock);
   await page.evaluate(()=>Object.defineProperty(crypto,'subtle',{configurable:true,value:{digest:async(_algorithm,bytes)=>Uint8Array.from(await __digest([...new Uint8Array(bytes)])).buffer}}));
   await page.setContent(app);
   await page.waitForFunction(()=>window.Clearings?.storage().ready);
   await page.locator('#importInput').setInputFiles({name:'fictional-context.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(data.workspace))});
   await page.locator('[data-action="import-separate"]').click();
   await page.waitForFunction(()=>Clearings.snapshot().index.libraryId==='browser-context-fixture');
   const snapshot=await page.evaluate(()=>Clearings.snapshot());
   const doc=snapshot.documents.find(d=>d.documentId===cid);
   assert.equal(doc.model.items.find(i=>i.id==='purpose').detail,data.workspace.documents[0].model.items.find(i=>i.id==='purpose').detail);
   assert.notEqual(doc.state[data.itemId],true);
   assert.equal(doc.model.items.find(i=>i.id==='purpose').response||'','');
   const title=page.locator('[data-step-row="purpose"] > .task-row .row-title');
   await title.click();
   const context=page.locator('[data-step-row="'+data.itemId+'"]');
   await context.waitFor({state:'visible'});
   assert.equal((await context.innerText()).includes('Ask the owner about the fixture'),false);
   await context.locator(':scope > .task-row .row-title').click();
   await page.getByText('Ask the owner about the fixture',{exact:false}).first().waitFor({state:'visible'});
   assert.equal(await page.evaluate(()=>window.contextInjected===true),false);
   await context.locator(':scope > .task-row [data-menu="step"]').click();
   await page.locator('[data-command="ai-context"]').click();
   const exported=JSON.parse(await page.locator('.ai-source').inputValue());
   assert.ok(exported.instructions.includes('self-resumption'));
   assert.ok(exported.document.model.items.some(i=>i.id===data.itemId));
   assert.equal(await page.evaluate(()=>Clearings.appVersion),'0.4.7');
   assert.deepEqual(errors,[]);
   await page.close();
   console.log('PASS nested context import, folded description, safe rendering and AI export at '+viewport.width+'px');
  }
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
