// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
'use strict';
const assert=require('node:assert/strict');
const {mergeChecklistDocuments}=require('../tools/merge.cjs');
const {validateDocument}=require('../tools/contract.cjs');
const original=require('../examples/generic/program_overview.json');
const copy=x=>JSON.parse(JSON.stringify(x));
function test(label,run){run();console.log('PASS '+label)}
function item(d,id){return d.model.items.find(x=>x.id===id)}

test('already checked on both sides is not a conflict',()=>{
 const base=copy(original),browser=copy(base),incoming=copy(base);
 browser.state.purpose=true;incoming.state.purpose=true;
 const result=mergeChecklistDocuments(base,browser,incoming);
 assert.equal(result.conflicts.length,0);
 assert.equal(result.merged.state.purpose,true);
});
test('independent edits on one checklist are retained together',()=>{
 const base=copy(original),browser=copy(base),incoming=copy(base);
 item(browser,'purpose').detail='Browser detail';item(incoming,'boundaries').text='JSON title';
 const result=mergeChecklistDocuments(base,browser,incoming);
 assert.equal(result.conflicts.length,0);
 assert.equal(item(result.merged,'purpose').detail,'Browser detail');
 assert.equal(item(result.merged,'boundaries').text,'JSON title');
 validateDocument(result.merged);
});
test('different edits to one field conflict and can be chosen',()=>{
 const base=copy(original),browser=copy(base),incoming=copy(base);
 item(browser,'purpose').text='Browser title';item(incoming,'purpose').text='JSON title';
 const first=mergeChecklistDocuments(base,browser,incoming);
 assert.deepEqual(Array.from(first.unresolved,x=>x.key),['item:purpose:text']);
 const chosen=mergeChecklistDocuments(base,browser,incoming,{'item:purpose:text':'json'});
 assert.equal(chosen.unresolved.length,0);
 assert.equal(item(chosen.merged,'purpose').text,'JSON title');
});
test('completion does not erase a newer failure note',()=>{
 const base=copy(original),browser=copy(base),incoming=copy(base);
 item(browser,'purpose').detail='Firefox check failed';incoming.state.purpose=true;
 const result=mergeChecklistDocuments(base,browser,incoming);
 assert.ok(result.unresolved.some(x=>x.key==='state:purpose'));
 assert.notEqual(result.merged.state.purpose,true);
});
test('a proposal does not mutate its inputs',()=>{
 const base=copy(original),browser=copy(base),incoming=copy(base);
 incoming.state.purpose=true;
 const before=[copy(base),copy(browser),copy(incoming)];
 mergeChecklistDocuments(base,browser,incoming);
 assert.deepEqual([base,browser,incoming],before);
});
test('a new item and its checked state stay together',()=>{
 const base=copy(original),browser=copy(base),incoming=copy(base);
 incoming.model.items.push({id:'fresh-item',order:999,parents:[],label:'',tags:[],text:'Finish a new step',detail:'',requires:[]});
 incoming.model.roots.push('fresh-item');incoming.state['fresh-item']=true;
 const result=mergeChecklistDocuments(base,browser,incoming);
 assert.equal(result.unresolved.length,0);
 assert.equal(result.merged.state['fresh-item'],true);
 validateDocument(result.merged);
});
test('independent children under one heading both survive',()=>{
 const base=copy(original),browser=copy(base),incoming=copy(base);
 const make=(id,text)=>({id,order:999,parents:[],label:'',tags:[],text,detail:'',requires:[]});
 browser.model.items.push(make('browser-child','Browser child'));
 incoming.model.items.push(make('json-child','JSON child'));
 item(browser,'shape').requires.push('browser-child');
 item(incoming,'shape').requires.push('json-child');
 const result=mergeChecklistDocuments(base,browser,incoming);
 assert.equal(result.unresolved.length,0);
 assert.deepEqual(Array.from(item(result.merged,'shape').requires).slice(-2),['browser-child','json-child']);
 validateDocument(result.merged);
});
