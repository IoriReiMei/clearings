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
test('concurrent source-list change holds a move for review',()=>{
 const base=copy(original),browser=copy(base),incoming=copy(base);
 item(browser,'shape').requires.push('browser-child');
 browser.model.items.push({id:'browser-child',order:999,parents:[],label:'',tags:[],text:'Browser child',detail:'',requires:[]});
 item(incoming,'shape').requires=item(incoming,'shape').requires.filter(id=>id!=='purpose');
 item(incoming,'make').requires.push('purpose');
 const result=mergeChecklistDocuments(base,browser,incoming);
 assert.ok(result.unresolved.some(x=>x.key==='item:shape:requires'));
 assert.equal(item(result.merged,'shape').requires.includes('purpose'),true);
});
