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
// Load the pure data contract from the shipped app: a single source of truth.
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {webcrypto}=require('node:crypto');
const localApp=path.join(__dirname,'../LC_CHECKLIST.html');
const html=fs.readFileSync(fs.existsSync(localApp)?localApp:path.join(__dirname,'../index.html'),'utf8');
const block=html.split('/* CONTRACT_BEGIN: pure validators and proposal planning; shared by local tests. */')[1]?.split('/* CONTRACT_END */')[0];
if(!block)throw new Error('Cannot locate the pure contract in the application.');
const scope={crypto:webcrypto,TextEncoder,Blob};
vm.createContext(scope);
vm.runInContext(block+'\nthis.api={validateDocument,validateWorkspace,migrateDocument,aiHash,planAIChanges,canonicalJSON,aiDocumentKey,progressStats,PREFERENCE_DEFAULTS,documentLocks,planRemoval,stampAttribution,backfillAttribution};',scope);
module.exports=scope.api;
