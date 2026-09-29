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
const {spawn,spawnSync}=require('node:child_process');
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
  page.on('response',async r=>{if(r.url().endsWith('/api/sync')&&r.status()>=400)console.error('SYNC REFUSAL',r.status(),await r.text())});
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
  if(process.env.CLEARINGS_SETTINGS_PREVIEW)await page.screenshot({path:process.env.CLEARINGS_SETTINGS_PREVIEW,animations:'disabled'});
  for(const heading of ['Identity','Refresh Clearings','Saving & storage','Getting started','Checklist templates'])assert.equal(await page.locator('#dialogFields').getByRole('heading',{name:heading}).count(),1);
  assert.equal(await page.locator('#dialogFields').getByRole('heading',{name:'Recent changes'}).count(),0);
  assert.notEqual(await page.locator('#dialogFields .pref-section').nth(1).evaluate(x=>getComputedStyle(x).borderTopStyle),'none');
  const savingHelp=page.locator('[aria-label="Help: Saving & storage"]');
  await savingHelp.hover();assert.equal(await savingHelp.locator('xpath=following-sibling::*[1]').isVisible(),true);
  await savingHelp.click();assert.equal(await savingHelp.getAttribute('aria-expanded'),'true');
  await page.locator('[name="humanName"]').click();assert.equal(await savingHelp.getAttribute('aria-expanded'),'false');
  await page.locator('[data-pref="openTopChecklist"]').uncheck();
  await page.locator('[data-pref="clearOnRefreshPress"]').check();
  await page.locator('[data-action="restore-settings-defaults"]').click();
  await page.waitForFunction(()=>document.querySelector('#dialogFields [data-pref="openTopChecklist"]')?.checked===true);
  assert.equal(await page.locator('[data-pref="clearOnRefreshPress"]').isChecked(),false);
  assert.equal(await page.locator('[name="humanName"]').inputValue(),'Human tester');
  await page.locator('#editorDialog [data-action="close-dialog"]').first().click();
  await page.locator('#appMenu').click();await page.locator('#menu [data-command="recent-actions"]').click();
  assert.equal(await page.locator('#dialogTitle').innerText(),'Recent actions');
  assert.equal(await page.locator('#dialogApply').isVisible(),false);
  await page.locator('#editorDialog [data-action="close-dialog"]').first().click();
  await page.locator('.new-list[data-action="new-checklist"]').click();
  assert.equal(await page.locator('[data-action="import-from-new"]').count(),1);
  const picker=page.waitForEvent('filechooser');await page.locator('[data-action="import-from-new"]').click();await picker;
  assert.equal(await page.locator('#editorDialog').evaluate(x=>x.open),false);
  // A new-list proposal stays pending until its preview is accepted.
  const beforeNew=await page.evaluate(()=>Clearings.snapshot());
  const newDoc=structuredClone(beforeNew.documents.find(d=>d.documentId==='example-overview'));
  newDoc.documentId='incoming-fixture-list';newDoc.title='Incoming fixture list';newDoc.state={};
  await page.evaluate(async incoming=>{const response=await fetch('/api/propose-new',{method:'POST',headers:{'Content-Type':'application/json','X-Clearings-Token':window.__CLEARINGS_LOCAL_TOKEN__},body:JSON.stringify({incoming,actor:'Morrow fixture'})});if(!response.ok)throw new Error(await response.text())},newDoc);
  // This fixture represents an unsigned proposal saved by a pre-commit build.
  const fixtureHandoff=path.join(temp,'config','home','clearings_handoff.json');
  const legacyPacket=JSON.parse(fs.readFileSync(fixtureHandoff,'utf8'));
  delete legacyPacket.proposals.at(-1).requiresCommit;
  fs.writeFileSync(fixtureHandoff,JSON.stringify(legacyPacket));
  await page.locator('#refreshButton').click();
  await page.waitForFunction(()=>document.getElementById('dialogTitle').textContent==='Add incoming checklist?');
  assert.deepEqual(await page.evaluate(()=>Clearings.snapshot()),beforeNew);
  await page.locator('#editorDialog [data-action="close-dialog"]').first().click();
  assert.deepEqual(await page.evaluate(()=>Clearings.snapshot()),beforeNew);
  await page.waitForTimeout(800);await page.locator('#refreshButton').click();
  await page.waitForFunction(()=>document.getElementById('dialogTitle').textContent==='Add incoming checklist?');
  await page.locator('#dialogApply').click();
  await page.waitForFunction(()=>Clearings.snapshot().documents.some(d=>d.documentId==='incoming-fixture-list'));
  assert.equal((await page.evaluate(()=>Clearings.snapshot())).documents.length,beforeNew.documents.length+1);
  assert.deepEqual((await page.evaluate(()=>Clearings.snapshot())).documents.find(d=>d.documentId==='incoming-fixture-list').state,{});
  assert.equal(await page.locator('.library-row[data-library-id="incoming-fixture-list"] .change-tag.ai').count(),1);
  assert.equal(await page.locator('#checklistUnread.ai').count(),1);
  await page.waitForTimeout(800);await page.locator('#refreshButton').click();
  await page.waitForFunction(()=>!document.getElementById('refreshButton').disabled);
  assert.equal((await page.evaluate(()=>Clearings.snapshot())).documents.filter(d=>d.documentId==='incoming-fixture-list').length,1);
  // New assistant drafts remain invisible. One signed commit attributes all
  // of its visible changes; a second assistant can sign an independent edit.
  const baseShared=await page.evaluate(()=>structuredClone(Clearings.snapshot().documents.find(d=>d.documentId==='example-overview')));
  const linden=structuredClone(baseShared),morrow=structuredClone(baseShared);
  linden.model.items.find(i=>i.id==='purpose').detail='Signed Linden detail';
  linden.model.items.find(i=>i.id==='boundaries').detail='Signed Linden boundary';
  morrow.model.items.find(i=>i.id==='make').text='Signed Morrow title';
  async function submit(base,incoming,actor){return page.evaluate(async x=>{const r=await fetch('/api/propose',{method:'POST',headers:{'Content-Type':'application/json','X-Clearings-Token':window.__CLEARINGS_LOCAL_TOKEN__},body:JSON.stringify(x)});if(!r.ok)throw new Error(await r.text());return (await r.json()).proposalId},{base,incoming,actor})}
  function commit(id,author){const result=spawnSync(python,['-B',path.join(root,'tools','clearings_local.py'),'--config-dir',path.join(temp,'config'),'commit-proposal',id,'--author',author],{encoding:'utf8',windowsHide:true});if(result.status!==0)throw new Error(result.stderr||result.stdout);return JSON.parse(result.stdout)}
  const lindenId=await submit(baseShared,linden,'Morrow draft'),morrowId=await submit(baseShared,morrow,'Morrow');
  await page.waitForTimeout(800);await page.locator('#refreshButton').click();
  await page.waitForFunction(()=>!document.getElementById('refreshButton').disabled);
  assert.notEqual((await page.evaluate(()=>Clearings.snapshot())).documents.find(d=>d.documentId==='example-overview').model.items.find(i=>i.id==='purpose').detail,'Signed Linden detail');
  assert.equal(commit(lindenId,'Linden').commit.author,'Linden');
  assert.equal(commit(morrowId,'Morrow').commit.author,'Morrow');
  await page.waitForTimeout(800);await page.locator('#refreshButton').click();
  await page.waitForFunction(()=>Clearings.snapshot().documents.find(d=>d.documentId==='example-overview').model.items.find(i=>i.id==='make').text==='Signed Morrow title');
  const signedActivity=(await page.evaluate(()=>Clearings.snapshot())).index.activity.filter(a=>a.role==='assistant'&&['Linden','Morrow'].includes(a.actor)&&['purpose','boundaries','make'].includes(a.itemId));
  assert.equal(signedActivity.filter(a=>a.actor==='Linden').length,2);
  assert.equal(signedActivity.filter(a=>a.actor==='Morrow').length,1);
  assert.equal(new Set(signedActivity.filter(a=>a.actor==='Linden').map(a=>a.commitId)).size,1);
  assert.notEqual(signedActivity.find(a=>a.actor==='Linden').commitId,signedActivity.find(a=>a.actor==='Morrow').commitId);
  assert.ok(signedActivity.every(a=>a.highlight&&a.unread));
  const signedNew=structuredClone(baseShared);signedNew.documentId='signed-fixture-list';signedNew.title='Signed fixture list';signedNew.state={};
  const signedNewId=await page.evaluate(async incoming=>{const r=await fetch('/api/propose-new',{method:'POST',headers:{'Content-Type':'application/json','X-Clearings-Token':window.__CLEARINGS_LOCAL_TOKEN__},body:JSON.stringify({incoming,actor:'Wick'})});if(!r.ok)throw new Error(await r.text());return (await r.json()).proposalId},signedNew);
  commit(signedNewId,'Wick');
  const beforeDisplay=JSON.parse(spawnSync(python,['-B',path.join(root,'tools','clearings_local.py'),'--config-dir',path.join(temp,'config'),'read','--checklist',signedNew.documentId],{encoding:'utf8',windowsHide:true}).stdout).effectiveDocument;
  const secondAuthor=structuredClone(beforeDisplay);secondAuthor.state.purpose=true;
  const secondCommitId=await submit(beforeDisplay,secondAuthor,'Linden');commit(secondCommitId,'Linden');
  const expectedAttribution=JSON.parse(spawnSync(python,['-B',path.join(root,'tools','clearings_local.py'),'--config-dir',path.join(temp,'config'),'read','--checklist',signedNew.documentId],{encoding:'utf8',windowsHide:true}).stdout).effectiveDocument.attribution;
  await page.waitForTimeout(800);
  await page.waitForFunction(()=>!document.getElementById('refreshButton').disabled&&!document.body.classList.contains('local-applying'));
  await page.route('**/api/handoff',async route=>{await new Promise(resolve=>setTimeout(resolve,1000));await route.continue()},{times:1});
  const frozenCheck=page.locator('[data-check]:visible').first(),frozenIdentity=await frozenCheck.evaluate(el=>({id:el.dataset.check,doc:el.dataset.doc,checked:el.checked}));
  await frozenCheck.focus();await page.evaluate(()=>document.getElementById('refreshButton').click());
  await page.waitForFunction(()=>document.body.classList.contains('local-applying'));assert.equal(await page.locator('#center').evaluate(el=>!!el.closest('[inert]')),true);await page.keyboard.press('Space');
  assert.equal(await frozenCheck.isChecked(),frozenIdentity.checked);
  try{await page.waitForFunction(()=>Clearings.snapshot().documents.some(d=>d.documentId==='signed-fixture-list'))}catch(error){console.error('signed-new failure',{toast:await page.locator('#toast').innerText(),errors,childLog});throw error}
  await page.waitForFunction(()=>Clearings.snapshot().documents.find(d=>d.documentId==='signed-fixture-list')?.state.purpose===true);
  assert.deepEqual((await page.evaluate(()=>Clearings.snapshot())).documents.find(d=>d.documentId==='signed-fixture-list').attribution,expectedAttribution);
  assert.equal(expectedAttribution.purpose.created.actor,'Wick');assert.equal(expectedAttribution.purpose.completed.actor,'Linden');
  await page.locator('.library-row[data-library-id="signed-fixture-list"] .library-open').click();
  if(await page.locator('.group-name[data-id="shape"]').getAttribute('aria-expanded')==='false')await page.locator('.group-name[data-id="shape"]').dispatchEvent('click',{detail:0});
  await page.locator('[data-menu="step"][data-id="purpose"][data-doc="signed-fixture-list"]').first().click();
  await page.locator('#menu [data-command="task-history"]').click();
  assert.match(await page.locator('#dialogFields').innerText(),/Wick/);assert.match(await page.locator('#dialogFields').innerText(),/Linden/);
  await page.locator('#editorDialog [data-action="close-dialog"]').first().click();
  for(const destination of ['', 'make']){
   await page.locator('[data-menu="step"][data-id="purpose"][data-doc="signed-fixture-list"]').first().click();
   await page.locator('#menu [data-command="move-to"]').click();await page.locator('[name="destination"]').selectOption(destination);await page.locator('#dialogApply').click();
   await page.waitForFunction(()=>!document.getElementById('editorDialog').open);
   const moved=(await page.evaluate(()=>Clearings.snapshot())).documents.find(d=>d.documentId==='signed-fixture-list');
   assert.equal(moved.state.purpose,true);assert.deepEqual(moved.attribution.purpose,expectedAttribution.purpose);
   assert.ok(destination?moved.model.items.find(i=>i.id===destination).requires.includes('purpose'):moved.model.roots.includes('purpose'));
  }
  if(await page.locator('.group-name[data-id="make"]').getAttribute('aria-expanded')==='false')await page.locator('.group-name[data-id="make"]').dispatchEvent('click',{detail:0});
  const summary=page.locator('.library-row[data-library-id="signed-fixture-list"] .checklist-changes');
  assert.match(await summary.innerText(),/CHANGES?/);assert.doesNotMatch(await summary.innerText(),/COMPLETED/);
  const bracket=page.locator('#pageContent [data-step-row="purpose"]');
  assert.equal(await bracket.evaluate(el=>getComputedStyle(el,'::before').borderBottomWidth),'2px');
  if(process.env.CLEARINGS_DELIVERY_PREVIEW)await page.screenshot({path:process.env.CLEARINGS_DELIVERY_PREVIEW,animations:'disabled'});
  await page.waitForFunction(()=>!Clearings.storage().dirty&&!Clearings.storage().saving);
  await page.locator('[data-action="library-view"]').first().click();
  assert.match(await page.locator('[data-library-card="signed-fixture-list"] .checklist-changes').innerText(),/CHANGES?/);
  if(process.env.CLEARINGS_OVERVIEW_PREVIEW)await page.screenshot({path:process.env.CLEARINGS_OVERVIEW_PREVIEW,animations:'disabled'});
  await page.locator('[data-library-card="signed-fixture-list"] .library-card-title').click();


  assert.equal(await page.locator('#editorDialog').evaluate(x=>x.open),false);
  await page.locator('#appMenu').click();await page.locator('#menu [data-command="local-settings"]').click();
  await page.locator('[data-action="create-practice-conflict"]').click();
  try{await page.waitForFunction(()=>document.getElementById('dialogTitle').textContent==='Review checklist conflict',null,{timeout:10000})}catch(e){console.error('practice state',{title:await page.locator('#dialogTitle').innerText(),toast:await page.locator('#toast').innerText(),errors,childLog,exit:child.exitCode});throw e}
  assert.match(await page.locator('#dialogFields').innerText(),/Browser version/);
  assert.match(await page.locator('#dialogFields').innerText(),/Incoming JSON version/);
  if(process.env.CLEARINGS_PREVIEW)await page.screenshot({path:process.env.CLEARINGS_PREVIEW,animations:'disabled'});
  // A pending conflict in one list must not hold an independent list.
  await page.locator('#editorDialog [data-action="close-dialog"]').first().click();
  await page.evaluate(async()=>{const base=structuredClone(Clearings.snapshot().documents.find(d=>d.documentId==='example-overview')),incoming=structuredClone(base);incoming.model.items.find(i=>i.id==='purpose').text='An independent JSON edit';const headers={'Content-Type':'application/json','X-Clearings-Token':window.__CLEARINGS_LOCAL_TOKEN__};const response=await fetch('/api/propose',{method:'POST',headers,body:JSON.stringify({base,incoming,actor:'Assistant tester',note:'Other checklist'})});if(!response.ok)throw new Error(await response.text());const proposalId=(await response.json()).proposalId;const signed=await fetch('/api/commit',{method:'POST',headers,body:JSON.stringify({proposalId,author:'Assistant tester'})});if(!signed.ok)throw new Error(await signed.text())});
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
  await page.locator('.library-row[data-library-id="example-overview"] .library-open').click();
  if(await page.locator('.group-name[data-id="shape"]').getAttribute('aria-expanded')==='false')await page.locator('.group-name[data-id="shape"]').dispatchEvent('click',{detail:0});
  if(await page.locator('.row-title[data-id="first-look"]').getAttribute('aria-expanded')==='false')await page.locator('.row-title[data-id="first-look"]').dispatchEvent('click',{detail:0});
  await page.keyboard.down('Control');
  assert.equal(await page.evaluate(()=>document.body.classList.contains('show-tags')),true);
  assert.ok(await page.locator('.row-tags:visible').count()>0);
  await page.keyboard.up('Control');
  assert.equal(await page.evaluate(()=>document.body.classList.contains('show-tags')),false);
  await page.locator('#appMenu').click();await page.locator('#menu [data-command="local-settings"]').click();
  await page.locator('[name="humanName"]').focus();
  await page.keyboard.down('Shift');
  assert.equal(await page.evaluate(()=>document.body.classList.contains('show-attribution')),false);
  await page.keyboard.up('Shift');
  await page.locator('#editorDialog [data-action="close-dialog"]').first().click();
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
  assert.ok(highlights.some(Boolean));
  await page.waitForTimeout(800);await page.locator('#refreshButton').click();
  await page.locator('#toast').getByText('No updates found. Press Refresh again to clear notifications.').waitFor();
  assert.deepEqual(await page.evaluate(()=>Clearings.snapshot().index.activity.map(a=>a.highlight)),highlights);
  assert.match(await page.locator('#toast').innerText(),/Press Refresh again/);
  assert.equal(await page.locator('#refreshButton').isDisabled(),true);
  await page.evaluate(()=>document.getElementById('refreshButton').click());
  assert.deepEqual(await page.evaluate(()=>Clearings.snapshot().index.activity.map(a=>a.highlight)),highlights);
  await page.waitForTimeout(800);
  await page.locator('#refreshButton').click();await page.waitForFunction(()=>!document.getElementById('refreshButton').disabled);
  assert.ok((await page.evaluate(()=>Clearings.snapshot().index.activity)).every(a=>!a.highlight&&!a.unread));
  assert.match(await page.locator('#toast').innerText(),/Notifications removed/);
  await page.locator('#toast [data-action="undo"]').click();
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
  assert.equal(packet.receipts.length,9);
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
