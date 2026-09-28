// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
'use strict';
// Isolated loopback UI test. It never opens the owner's browser profile or handoff.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const net=require('node:net');
const {spawn}=require('node:child_process');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const python=process.env.CLEARINGS_TEST_PYTHON||process.env.PYTHON||'python';
const executable=process.env.CHROMIUM_EXECUTABLE||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
async function freePort(){return new Promise((resolve,reject)=>{const s=net.createServer();s.once('error',reject);s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p))})})}
async function waitReady(url,child){for(let i=0;i<100;i++){if(child.exitCode!==null)throw new Error('Helper stopped before opening');try{const r=await fetch(url);if(r.ok)return}catch{}await new Promise(r=>setTimeout(r,50))}throw new Error('Helper did not open')}
async function run(){
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'clearings-handoff-test-'));
 const port=await freePort(),url=`http://127.0.0.1:${port}/`;
 const child=spawn(python,['-B',path.join(root,'tools','clearings_local.py'),'--config-dir',path.join(temp,'config'),'serve','--port',String(port),'--no-browser'],{windowsHide:true,stdio:'pipe'});
 let childLog='';child.stderr.on('data',x=>childLog+=x.toString());child.stdout.on('data',x=>childLog+=x.toString());
 let browser;try{
  await waitReady(url,child);
  assert.equal((await fetch(url+'api/handoff')).status,403);
  const token=JSON.parse(fs.readFileSync(path.join(temp,'config','session.json'),'utf8')).token;
  assert.equal((await fetch(url+'api/sync',{method:'POST',headers:{'X-Clearings-Token':token,'Content-Type':'application/json','Origin':'http://example.invalid'},body:'{}'})).status,403);
  browser=await chromium.launch({headless:true,executablePath:executable});
  const page=await browser.newPage({viewport:{width:1440,height:980}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
  await page.goto(url);await page.waitForFunction(()=>window.Clearings?.storage().ready);
  await page.locator('#welcomeName').fill('First editor');
  await page.locator('#tryExample').click();await page.waitForFunction(()=>Clearings.storage().savedAt&&!Clearings.storage().dirty);
  assert.equal((await page.evaluate(()=>Clearings.snapshot())).index.preferences.displayName,'First editor');
  await page.locator('#appMenu').click();await page.locator('#menu [data-command="local-settings"]').click();
  await page.locator('[name="humanName"]').fill('Human tester');
  await page.locator('#dialogApply').click();
  await page.waitForFunction(()=>Clearings.snapshot().index.preferences.displayName==='Human tester');
  await page.locator('#appMenu').click();await page.locator('#menu [data-command="preferences"]').click();
  assert.equal(await page.locator('#dialogFields').getByText('Saving & storage').count(),0);
  await page.locator('[data-pref="theme"]').selectOption('dark');
  await page.locator('[data-pref="showClearIndicators"]').check();
  assert.equal(await page.locator('#clearIndicators').isVisible(),true);
  await page.locator('[data-action="reset-preferences"]').click();
  await page.waitForFunction(()=>document.querySelector('#dialogFields [data-pref="theme"]')?.value==='system');
  assert.equal(await page.locator('#clearIndicators').isHidden(),true);
  assert.equal((await page.evaluate(()=>Clearings.snapshot())).index.preferences.displayName,'Human tester');
  await page.locator('#editorDialog [data-action="close-dialog"]').first().click();
  await page.locator('#appMenu').click();await page.locator('#menu [data-command="local-settings"]').click();
  await page.waitForFunction(()=>document.getElementById('dialogTitle').textContent==='Settings');
  for(const heading of ['Saving & storage','Getting started','Recent changes'])assert.equal(await page.locator('#dialogFields').getByRole('heading',{name:heading}).count(),1);
  await page.locator('[data-pref="openTopChecklist"]').uncheck();
  await page.locator('[data-pref="clearOnRefreshPress"]').check();
  await page.locator('[data-action="restore-settings-defaults"]').click();
  await page.waitForFunction(()=>document.querySelector('#dialogFields [data-pref="openTopChecklist"]')?.checked===true);
  assert.equal(await page.locator('[data-pref="clearOnRefreshPress"]').isChecked(),false);
  assert.equal(await page.locator('[name="humanName"]').inputValue(),'Human tester');
  await page.locator('#editorDialog [data-action="close-dialog"]').first().click();
  await page.locator('#appMenu').click();await page.locator('#menu [data-command="local-settings"]').click();
  await page.locator('[data-action="create-practice-conflict"]').click();
  try{await page.waitForFunction(()=>document.getElementById('dialogTitle').textContent==='Review checklist conflict',null,{timeout:10000})}catch(e){console.error('practice state',{title:await page.locator('#dialogTitle').innerText(),toast:await page.locator('#toast').innerText(),errors,childLog,exit:child.exitCode});throw e}
  assert.match(await page.locator('#dialogFields').innerText(),/Browser version/);
  assert.match(await page.locator('#dialogFields').innerText(),/Incoming JSON version/);
  if(process.env.CLEARINGS_PREVIEW)await page.screenshot({path:process.env.CLEARINGS_PREVIEW,animations:'disabled'});
  // A pending conflict in one list must not hold an independent list.
  await page.locator('#editorDialog [data-action="close-dialog"]').first().click();
  await page.evaluate(async()=>{const base=structuredClone(Clearings.snapshot().documents.find(d=>d.documentId==='example-overview')),incoming=structuredClone(base);incoming.model.items.find(i=>i.id==='purpose').text='An independent JSON edit';const response=await fetch('/api/propose',{method:'POST',headers:{'Content-Type':'application/json','X-Clearings-Token':window.__CLEARINGS_LOCAL_TOKEN__},body:JSON.stringify({base,incoming,actor:'Assistant tester',note:'Other checklist'})});if(!response.ok)throw new Error(await response.text())});
  await page.locator('#refreshButton').click();
  await page.waitForFunction(()=>Clearings.snapshot().documents.find(d=>d.documentId==='example-overview').model.items.find(i=>i.id==='purpose').text==='An independent JSON edit');
  assert.equal(await page.locator('#libraryList .conflict-warning').count(),1);
  await page.locator('#libraryList .conflict-warning').click();
  await page.locator('input[name="resolution-0"][value="browser"]').check();
  await page.locator('#dialogApply').click();
  await page.waitForFunction(()=>!document.getElementById('editorDialog').open);
  assert.equal((await page.evaluate(()=>Clearings.snapshot())).documents.find(d=>d.title==='Clearings · Conflict Practice').model.items[0].text,'Browser version');
  assert.equal(await page.locator('#libraryList .conflict-warning').count(),0);
  await page.keyboard.down('Shift');
  assert.ok((await page.locator('.actor-label.browser:visible').allTextContents()).includes('Human tester'));
  await page.keyboard.up('Shift');
  await page.locator('#appMenu').click();await page.locator('#menu [data-command="local-settings"]').click();
  await page.locator('[data-action="create-practice-conflict"]').click();
  await page.waitForFunction(()=>document.getElementById('dialogTitle').textContent==='Review checklist conflict');
  await page.locator('input[name="resolution-0"][value="json"]').check();
  await page.locator('#dialogApply').click();
  await page.waitForFunction(()=>!document.getElementById('editorDialog').open);
  assert.equal((await page.evaluate(()=>Clearings.snapshot())).documents.filter(d=>d.title==='Clearings · Conflict Practice').at(-1).model.items[0].text,'Incoming JSON version');
  await page.keyboard.down('Shift');
  assert.ok((await page.locator('.actor-label.json:visible').allTextContents()).includes('Practice JSON'));
  await page.keyboard.up('Shift');
  const highlights=await page.evaluate(()=>Clearings.snapshot().index.activity.map(a=>a.highlight));
  await page.locator('#refreshButton').click();await page.waitForFunction(()=>!document.getElementById('refreshButton').disabled);
  assert.deepEqual(await page.evaluate(()=>Clearings.snapshot().index.activity.map(a=>a.highlight)),highlights);
  await page.locator('#appMenu').click();await page.locator('#menu [data-command="local-settings"]').click();
  await page.locator('[data-pref="clearOnRefreshPress"]').check();
  assert.equal(await page.locator('#clearIndicators').isHidden(),true);
  assert.equal(Object.hasOwn((await page.evaluate(()=>Clearings.snapshot())).index.preferences,'clearOnRefreshPress'),false);
  await page.locator('[data-pref="clearOnRefreshPress"]').uncheck();
  assert.equal(await page.locator('#clearIndicators').isHidden(),true);
  await page.locator('#editorDialog [data-action="close-dialog"]').first().click();
  await page.locator('#appMenu').click();await page.locator('#menu [data-command="preferences"]').click();
  await page.locator('[data-pref="showClearIndicators"]').check();
  assert.equal(await page.locator('#clearIndicators').isVisible(),true);
  await page.locator('#editorDialog [data-action="close-dialog"]').first().click();
  // A separately authorized assistant choice is rechecked at Refresh.
  await page.locator('#appMenu').click();await page.locator('#menu [data-command="local-settings"]').click();
  await page.locator('[data-action="create-practice-conflict"]').click();
  await page.waitForFunction(()=>document.getElementById('dialogTitle').textContent==='Review checklist conflict');
  await page.locator('#editorDialog [data-action="close-dialog"]').first().click();
  await page.evaluate(async()=>{const token=window.__CLEARINGS_LOCAL_TOKEN__,headers={'X-Clearings-Token':token};const packet=await (await fetch('/api/handoff',{headers})).json(),proposal=packet.proposals.findLast(p=>p.status==='pending'),item=proposal.base.model.items[0];const response=await fetch('/api/decide',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({proposalId:proposal.id,choices:{['item:'+item.id+':text']:'json'},actor:'Assistant tester'})});if(!response.ok)throw new Error(await response.text())});
  await page.waitForTimeout(800);
  await page.locator('#refreshButton').click();
  try{await page.waitForFunction(()=>Clearings.snapshot().documents.filter(d=>d.title==='Clearings · Conflict Practice').at(-1).model.items[0].text==='Incoming JSON version',null,{timeout:10000})}catch(e){console.error('assistant choice state',{toast:await page.locator('#toast').innerText(),pending:JSON.parse(fs.readFileSync(path.join(temp,'config','home','clearings_handoff.json'),'utf8')).proposals.filter(p=>p.status==='pending'),errors});throw e}
  await page.waitForFunction(()=>!document.getElementById('refreshButton').disabled);
  const packet=JSON.parse(fs.readFileSync(path.join(temp,'config','home','clearings_handoff.json'),'utf8'));
  assert.equal(packet.proposals.filter(p=>p.status==='pending').length,0);
  assert.equal(packet.receipts.length,4);
  const fresh=await browser.newContext(),recovered=await fresh.newPage();
  await recovered.goto(url);await recovered.waitForFunction(()=>window.Clearings?.storage().ready);
  const olderGeneration=await page.evaluate(()=>Clearings.storage().generation);
  await recovered.locator('#restoreHandoff').click();
  await recovered.waitForFunction(()=>Clearings.snapshot().documents.some(d=>d.title==='Clearings · Conflict Practice'));
  assert.equal((await recovered.evaluate(()=>Clearings.snapshot())).documents.filter(d=>d.title==='Clearings · Conflict Practice').at(-1).model.items[0].text,'Incoming JSON version');
  await recovered.locator('#toast').getByText('Saved local handoff restored in this browser.').waitFor();
  await recovered.locator('#appMenu').click();await recovered.locator('#menu [data-command="local-settings"]').click();
  await recovered.locator('[name="humanName"]').fill('New browser');await recovered.locator('#dialogApply').click();
  await recovered.waitForFunction(g=>Clearings.storage().generation>g&&!Clearings.storage().dirty&&!Clearings.storage().saving,olderGeneration);
  const handoffFile=path.join(temp,'config','home','clearings_handoff.json');let newerGeneration=0;
  for(let attempt=0;attempt<100;attempt++){newerGeneration=JSON.parse(fs.readFileSync(handoffFile,'utf8')).generation;if(newerGeneration>olderGeneration)break;await new Promise(resolve=>setTimeout(resolve,50))}
  assert.ok(newerGeneration>olderGeneration,'The second browser must actually save a newer handoff first');
  await page.locator('#appMenu').click();await page.locator('#menu [data-command="local-settings"]').click();
  await page.locator('[name="humanName"]').fill('Old browser');await page.locator('#dialogApply').click();
  await page.waitForFunction(()=>document.getElementById('saveLabel').textContent.includes('handoff needs attention'));
  assert.equal((await page.evaluate(()=>Clearings.snapshot())).index.preferences.displayName,'Old browser');
  assert.equal(JSON.parse(fs.readFileSync(handoffFile,'utf8')).generation,newerGeneration);
  await fresh.close();
  assert.deepEqual(errors,[]);
  console.log('Clearings local handoff and two-sided conflict rehearsal passed.');
 }finally{
  await browser?.close();
  if(child.exitCode===null){child.kill();await new Promise(resolve=>{child.once('exit',resolve);setTimeout(resolve,2000)})}
  const safe=path.resolve(temp).startsWith(path.resolve(os.tmpdir())+path.sep)&&path.basename(temp).startsWith('clearings-handoff-test-');
  if(safe)fs.rmSync(temp,{recursive:true,force:true});
 }
}
run().catch(e=>{console.error(e);process.exitCode=1});
