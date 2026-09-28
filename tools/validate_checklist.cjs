#!/usr/bin/env node
// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
'use strict';
// Read-only structural validation. Does not run instructions inside checklist text.
const fs=require('node:fs');
const path=require('node:path');
const api=require('./contract.cjs');
const MAX=16*1024*1024;
function read(file){const s=fs.statSync(file);if(!s.isFile()||s.size>MAX)throw new Error('Not a file, or larger than 16 MB: '+file);return JSON.parse(fs.readFileSync(file,'utf8').replace(/^\uFEFF/,''))}
function main(){
 if(process.argv.length!==3)throw new Error('Usage: node tools/validate_checklist.cjs <checklist.json | backup.json | library-folder>');
 const target=path.resolve(process.argv[2]);let value;
 if(fs.statSync(target).isDirectory()){
  const ix=read(path.join(target,'checklist_index.json'));
  if(!Array.isArray(ix.entries)||ix.entries.length>1000)throw new Error('Invalid library entries.');
  let bytes=0;
  const docs=ix.entries.map(e=>{
   if(typeof e.file!=='string'||!/^[A-Za-z0-9][A-Za-z0-9._-]{0,190}\.json$/.test(e.file)||e.file.includes('..')||e.file.toLowerCase()==='checklist_index.json')throw new Error('Unsafe checklist filename.');
   const file=path.join(target,e.file);bytes+=fs.statSync(file).size;if(bytes>MAX)throw new Error('Library exceeds 16 MB.');return read(file);
  });
  value={format:ix.format==='local-companion-checklist-index'?'local-companion-checklist-workspace':'checklist-studio-workspace',schemaVersion:1,index:ix,documents:docs};
 }else value=read(target);
 if(['checklist-studio-workspace','local-companion-checklist-workspace'].includes(value.format)){
  const w=api.validateWorkspace(value);console.log(`OK: ${w.documents.length} checklist(s), ${w.documents.reduce((n,d)=>n+d.model.items.length,0)} items. Structure validated; no content changed.`);
 }else{const d=api.validateDocument(value);console.log(`OK: ${d.title} (${d.model.items.length} items). Structure validated; no content changed.`)}
}
try{main()}catch(e){console.error('INVALID: '+e.message);process.exitCode=1}
