// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
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
