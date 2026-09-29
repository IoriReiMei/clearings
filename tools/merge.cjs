// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const localApp=path.join(__dirname,'../LC_CHECKLIST.html');
const html=fs.readFileSync(fs.existsSync(localApp)?localApp:path.join(__dirname,'../index.html'),'utf8');
const block=html.split('/* MERGE_BEGIN: pure three-way comparison, also used by focused tests. */')[1]?.split('/* MERGE_END */')[0];
if(!block)throw Error('Merge contract is missing from the app.');
const scope={documentLocks:require('./contract.cjs').documentLocks};vm.createContext(scope);vm.runInContext(block+'\nthis.mergeChecklistDocuments=mergeChecklistDocuments;',scope);
module.exports={mergeChecklistDocuments:scope.mergeChecklistDocuments};
