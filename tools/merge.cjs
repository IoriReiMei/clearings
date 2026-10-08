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
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const localApp=path.join(__dirname,'../LC_CHECKLIST.html');
const html=fs.readFileSync(fs.existsSync(localApp)?localApp:path.join(__dirname,'../index.html'),'utf8');
const block=html.split('/* MERGE_BEGIN: pure three-way comparison, also used by focused tests. */')[1]?.split('/* MERGE_END */')[0];
if(!block)throw Error('Merge contract is missing from the app.');
const scope={documentLocks:require('./contract.cjs').documentLocks};vm.createContext(scope);vm.runInContext(block+'\nthis.mergeChecklistDocuments=mergeChecklistDocuments;',scope);
module.exports={mergeChecklistDocuments:scope.mergeChecklistDocuments};
