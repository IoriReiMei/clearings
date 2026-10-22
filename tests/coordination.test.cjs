// SPDX-License-Identifier: MIT
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const {validateDocument,stampAttribution}=require('../tools/contract.cjs'),{mergeChecklistDocuments}=require('../tools/merge.cjs');
const source=JSON.parse(fs.readFileSync(path.join(__dirname,'../examples/generic/program_overview.json'))),id=source.model.items.at(-1).id;
const clone=x=>JSON.parse(JSON.stringify(x)),item=d=>d.model.items.find(i=>i.id===id),stamp={actor:'Human fixture',role:'human',at:'2026-10-21T10:00:00Z'};
const stages=[],first=clone(source);item(first).response='Please review this question.';stampAttribution(first,source,stamp);validateDocument(first);assert.equal(item(first).needsReview,true);stages.push(first);
const second=clone(first);item(second).review='Considered.';stampAttribution(second,first,{...stamp,actor:'AI fixture',role:'assistant'});validateDocument(second);assert.equal(item(second).needsReview,false);assert.equal(second.attribution[id].response.actor,'Human fixture');stages.push(second);
const third=clone(second);item(third).assignment={id:'assignment-one',assignee:'Hermit fixture',role:'human',status:'pending',note:'Question'};stampAttribution(third,second,stamp);validateDocument(third);stages.push(third);
const fourth=clone(third);item(fourth).assignment={id:'assignment-two',assignee:'AI fixture',role:'assistant',status:'accepted',note:'Reassigned'};stampAttribution(fourth,third,stamp);validateDocument(fourth);assert.deepEqual(clone(fourth.attribution[id].assignmentHistory).map(e=>e.status),['pending','superseded','accepted']);stages.push(fourth);
const incoming=clone(first),current=clone(first);item(incoming).review='Answer to earlier response';item(current).response='A newer question';
const key='item:'+id+':review-response';let result=mergeChecklistDocuments(first,current,incoming);assert(result.unresolved.some(c=>c.key===key));
result=mergeChecklistDocuments(first,current,incoming,{[key]:'browser'});assert.equal(result.unresolved.length,0);assert.equal(item(result.merged).response,'A newer question');assert.equal(item(result.merged).review,undefined);
result=mergeChecklistDocuments(first,current,incoming,{[key]:'json'});assert.equal(result.unresolved.length,0);assert.equal(item(result.merged).review,'Answer to earlier response');
const python=process.env.CLEARINGS_TEST_PYTHON||'python';
const code=`import sys,json,copy\nsys.path.insert(0,sys.argv[1])\nfrom clearings_commit import stamp_attribution,validate_document\nx=json.load(sys.stdin); old=x['source']; out=[]\nfor n,stage in enumerate(x['stages']):\n d=copy.deepcopy(stage); d.pop('attribution',None); s=x['stamp'].copy()\n if n==1: s.update(actor='AI fixture',role='assistant')\n stamp_attribution(d,old,s); validate_document(d); out.append(d); old=d\njson.dump(out,sys.stdout)`;
const child=spawnSync(python,['-B','-c',code,path.join(__dirname,'../tools')],{input:JSON.stringify({source,stages,stamp}),encoding:'utf8'});assert.equal(child.status,0,child.stderr);assert.deepEqual(JSON.parse(child.stdout),stages.map(clone));
console.log('PASS review conflict choices, independent authors, assignment receipts, and JavaScript/Python parity across four saved transitions.');
