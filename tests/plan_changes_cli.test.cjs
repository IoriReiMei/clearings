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
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'..');
const tool=path.join(root,'tools','plan_changes.cjs');
const input=path.join(root,'examples','generic','program_overview.json');
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'clearings-plan-'));
try{
 const base=path.join(temp,'base.json'),ops=path.join(temp,'operations.json'),output=path.join(temp,'incoming.json');
 fs.copyFileSync(input,base);
 fs.writeFileSync(ops,JSON.stringify([{op:'move-items',itemIds:['purpose'],fromParentId:'shape',toParentId:'make',beforeId:null}]));
 const before=fs.readFileSync(base);
 const node=process.execPath;
 const args=[tool,'--base',base,'--operations',ops,'--output',output];
 const first=spawnSync(node,args,{encoding:'utf8'});
 assert.equal(first.status,0,first.stderr);
 const incoming=JSON.parse(fs.readFileSync(output,'utf8'));
 assert.ok(incoming.model.items.find(i=>i.id==='make').requires.includes('purpose'));
 assert.deepEqual(fs.readFileSync(base),before);
 const second=spawnSync(node,args,{encoding:'utf8'});
 assert.notEqual(second.status,0,'A second run must not overwrite the first proposal');
 assert.ok(incoming.model.items.find(i=>i.id==='make').requires.includes('purpose'));
 console.log('Clearings operation materializer passed.');
}finally{
 const resolved=path.resolve(temp),prefix=path.resolve(os.tmpdir())+path.sep;
 if(resolved.startsWith(prefix)&&path.basename(resolved).startsWith('clearings-plan-'))fs.rmSync(resolved,{recursive:true,force:true});
}
