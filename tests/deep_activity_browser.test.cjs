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
// Disposable browser fixture: never opens the owner's Clearings profile or handoff.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {createHash}=require('node:crypto');
const {chromium}=require(process.env.CLEARINGS_PLAYWRIGHT_MODULE||'playwright');
const {validateWorkspace}=require('../tools/contract.cjs');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,fs.existsSync(path.join(root,'LC_CHECKLIST.html'))?'LC_CHECKLIST.html':'index.html'),'utf8');
const mock=fs.readFileSync(path.join(root,'tests/browser_storage_mock.js'),'utf8');
const logo='721d33078041e4a1852525dd0c336fbe6f7d2d0c50968fc27072e24d12d68824';

async function run(){
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
 try{
  const seed=await browser.newPage({bypassCSP:true});
  await seed.evaluate(mock);await seed.setContent(html);
  await seed.waitForFunction(()=>window.Clearings?.storage().ready);
  await seed.locator('#welcomeName').fill('Fixture editor');await seed.locator('#tryExample').click();
  const workspace=await seed.evaluate(()=>Clearings.snapshot());await seed.close();
  const doc=workspace.documents.find(d=>d.documentId==='example-overview');
  // One descendant is reachable both directly and through first-look.
  doc.model.items.find(i=>i.id==='shape').requires.push('build-demo');
  doc.state.feedback=true;
  workspace.index.tracked.push({id:'tracked-first-look',checklistId:doc.documentId,itemId:'first-look'});
  workspace.index.activity=[
   {id:'deep-1',at:'2026-10-07T12:00:00Z',actor:'Morrow',role:'assistant',action:'updated',checklistId:doc.documentId,itemId:'build-demo',approvedBy:'Fixture editor',highlight:true,unread:true},
   {id:'deep-2',at:'2026-10-07T12:01:00Z',actor:'Morrow',role:'assistant',action:'updated',checklistId:doc.documentId,itemId:'build-demo',approvedBy:'Fixture editor',highlight:true,unread:true},
   {id:'deep-3',at:'2026-10-07T12:02:00Z',actor:'Morrow',role:'assistant',action:'completed',checklistId:doc.documentId,itemId:'feedback',approvedBy:'Fixture editor',highlight:true,unread:true},
   {id:'deep-4',at:'2026-10-07T12:03:00Z',actor:'Morrow',role:'assistant',action:'updated',checklistId:doc.documentId,itemId:'shape',approvedBy:'Fixture editor',highlight:true,unread:true}
  ];
  validateWorkspace(workspace);
  const page=await browser.newPage({viewport:{width:1440,height:980},bypassCSP:true});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.evaluate(mock);await page.setContent(html);await page.waitForFunction(()=>window.Clearings?.storage().ready);
  await page.locator('#importInput').setInputFiles({name:'fictional-workspace.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(workspace))});
  await page.locator('[data-action="import-separate"]').click();
  const brand=await page.locator('.brand-mark').getAttribute('src');
  assert.ok(brand.startsWith('data:image/png;base64,'));
  assert.equal(createHash('sha256').update(Buffer.from(brand.split(',')[1],'base64')).digest('hex'),logo);
  assert.equal(await page.locator('#checklistUnread').isVisible(),true);
  assert.equal(await page.locator('#libraryList [data-library-id="example-overview"] .checklist-changes').innerText(),'3 CHANGES');
  assert.equal(await page.locator('#pageContent [data-root-group="shape"] > .group-header .scope-tag').innerText(),'2 CHANGES INSIDE');
  assert.equal(await page.locator('#pageContent [data-root-group="shape"] > .group-header .change-tag:not(.scope-tag)').innerText(),'UPDATED','the parent owns only its own action');
  assert.equal(await page.locator('#pageContent [data-root-group="shape"] > .group-header .check-highlight').count(),0,'a child completion does not claim the parent completed');
  assert.equal(await page.locator('#pageContent [data-step-row="first-look"] > .task-row .scope-tag').innerText(),'2 CHANGES INSIDE');
  assert.equal(await page.locator('#pageContent [data-step-row="first-look"] > ol.rows').count(),0,'inside indicator survives the collapsed group');
  assert.equal(await page.locator('#trackedList [data-track-id="tracked-first-look"] .scope-tag').innerText(),'2 INSIDE');
  assert.equal(await page.locator('#trackedUnread').isVisible(),true);
  const shapeTree=page.locator('#mapTree .tree-row').filter({has:page.locator('[data-tree-path="[\\"shape\\"]"]')});
  assert.equal(await shapeTree.locator('.scope-tag').innerText(),'2 INSIDE');
  await page.locator('#mapTree [data-fold="shape"]').first().click();
  assert.equal(await shapeTree.locator('.scope-tag').innerText(),'2 INSIDE','outline parent remains marked while collapsed');
  await page.locator('#mapTree [data-fold="shape"]').first().click();
  assert.equal(await page.locator('#mapTree [data-tree-path="[\\"shape\\",\\"first-look\\"]"]').locator('..').locator('.scope-tag').innerText(),'2 INSIDE');
  if(process.env.CLEARINGS_SCOPE_PREVIEW)await page.screenshot({path:process.env.CLEARINGS_SCOPE_PREVIEW,animations:'disabled'});
  await page.locator('#appMenu').click();await page.locator('#menu [data-command="preferences"]').click();
  await page.locator('[data-pref="showClearIndicators"]').check();
  await page.locator('#editorDialog [data-action="close-dialog"]').first().click();
  await page.locator('#clearIndicators').click();
  assert.equal(await page.locator('.scope-tag').count(),0);
  assert.equal(await page.locator('#checklistUnread').isVisible(),false);
  await page.locator('#toast [data-action="undo"]').click();
  assert.equal(await page.locator('#pageContent [data-root-group="shape"] > .group-header .scope-tag').innerText(),'2 CHANGES INSIDE');
  assert.equal(await page.locator('#mapTree .scope-tag').count()>0,true);
  await page.locator('#libraryList [data-library-id="example-overview"] [data-menu="checklist"]').click();
  await page.locator('#menu [data-command="mark-indicator-seen"]').click();
  assert.equal(await page.locator('.scope-tag').count(),0);
  assert.equal(await page.locator('#trackedUnread').isVisible(),false);
  const result=await page.evaluate(()=>Clearings.snapshot());
  assert.equal(result.documents.find(d=>d.documentId==='example-overview').state.feedback,true);
  assert.equal(result.index.activity.length,4);
  assert.ok(result.index.activity.every(a=>!a.highlight&&!a.unread));
  assert.deepEqual(errors,[]);
  await page.close();
  console.log('Deep activity remains discoverable through parents, tracked scopes and outline; clear, Undo and seen preserve state.');
 }finally{await browser.close()}
}
run().catch(error=>{console.error(error);process.exitCode=1});
