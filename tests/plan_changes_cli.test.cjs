// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
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
