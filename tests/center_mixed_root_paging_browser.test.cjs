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

// Fictional import in a fresh browser context. No helper or owner workspace.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.CLEARINGS_PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,fs.existsSync(path.join(root,'LC_CHECKLIST.html'))?'LC_CHECKLIST.html':'index.html'));
const example=JSON.parse(fs.readFileSync(path.join(root,'examples/generic/program_overview.json'),'utf8'));
const item=id=>({id,order:0,parents:[],label:'',tags:[],text:id,detail:'Fictional review item',requires:[]});
const children=Array.from({length:2001},(_,index)=>'child'+index);
const doc={...example,documentId:'mixed-root-fixture',title:'Fictional mixed roots',references:[],state:{},view:{collapsed:[]}};
delete doc.attribution;
// The group ID deliberately resembles the root-page key. Child and root
// cursors must remain independent even when their textual keys coincide.
doc.model={branches:[],roots:['root-level','root-leaf'],items:[{...item('root-level'),requires:children},...children.map(item),item('root-leaf')]};

async function run(){
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'});
 try{
  const context=await browser.newContext(),page=await context.newPage();
  await context.route('**/*',route=>route.request().url()==='http://clearings-review.invalid/'?route.fulfill({status:200,contentType:'text/html',body:html}):route.abort());
  await page.goto('http://clearings-review.invalid/');
  await page.waitForFunction(()=>window.Clearings?.storage().ready);
  await page.locator('#importInput').setInputFiles({name:'mixed.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(doc))});
  await page.locator('[data-action="import-separate"]').click();
  await page.waitForFunction(()=>Clearings.storage().savedAt&&!Clearings.storage().dirty);
  const checked=()=>page.evaluate(()=>Clearings.snapshot().documents.find(d=>d.documentId==='mixed-root-fixture').state);
  await page.locator('#pageContent [data-check="child0"]').check();
  assert.equal(await page.locator('#pageContent [data-check="root-leaf"]').count(),0);
  const next=page.locator('#pageContent [data-action="center-page"][data-root-page="1"][data-id=""]');
  assert.equal(await next.getAttribute('data-index'),'1');
  await next.click();
  await page.locator('#pageContent [data-check="root-leaf"]').check();
  assert.equal((await checked()).child0,true);
  assert.equal((await checked())['root-leaf'],true);
  await page.locator('#pageContent [data-root-page="1"][data-index="0"]').click();
  assert.equal(await page.locator('#pageContent [data-check="child0"]').isChecked(),true);
  await page.locator('#pageContent [data-action="center-page"][data-id="root-level"][data-index="1200"]').click();
  assert.equal(await page.locator('#pageContent [data-check="child1200"]').count(),1);
  await page.locator('#breadcrumbs [data-action="open-checklist"]').click();
  assert.equal(await page.locator('#pageContent [data-check="root-level"]').count(),1);
  assert.equal(await page.locator('#pageContent [data-check="root-leaf"]').isChecked(),true);
  await page.locator('#pageContent [data-action="center-page"][data-id="root-level"][data-index="0"]').click();
  await page.locator('#breadcrumbs [data-action="open-checklist"]').click();
  await page.locator('#pageContent [data-root-page="1"][data-index="1"]').click();
  assert.equal(await page.locator('#pageContent [data-check="root-leaf"]').isChecked(),true);
  await context.close();
  console.log('Mixed-root center paging advances and preserves item IDs/checks.');
 }finally{await browser.close()}
}
run().catch(error=>{console.error(error);process.exitCode=1});
