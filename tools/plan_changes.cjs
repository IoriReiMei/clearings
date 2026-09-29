// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
'use strict';
// Materialize a reviewed operation list for the existing Clearings handoff.
// This tool only reads the two named inputs and writes one new output file.
const fs=require('node:fs');
const path=require('node:path');
const api=require('./contract.cjs');
async function main(argv){
 const args={};for(let n=0;n<argv.length;n+=2){const key=argv[n];if(!['--base','--operations','--output'].includes(key)||!argv[n+1]||Object.hasOwn(args,key))throw Error('Use --base BASE.json --operations OPS.json --output NEW.json');args[key]=argv[n+1]}
 if(argv.length!==6||Object.keys(args).length!==3)throw Error('Use --base BASE.json --operations OPS.json --output NEW.json');
 const basePath=path.resolve(args['--base']),operationsPath=path.resolve(args['--operations']),outputPath=path.resolve(args['--output']);
 if(outputPath===basePath||outputPath===operationsPath)throw Error('Output must be a separate new file.');
 const base=api.validateDocument(JSON.parse(fs.readFileSync(basePath,'utf8')));
 const operations=JSON.parse(fs.readFileSync(operationsPath,'utf8'));
 const packet={format:'checklist-studio-changes',schemaVersion:1,documentId:base.documentId,baseSha256:await api.aiHash(base),operations};
 const plan=await api.planAIChanges(base,packet);
 fs.writeFileSync(outputPath,JSON.stringify(plan.document,null,2)+'\n',{encoding:'utf8',flag:'wx'});
 console.log(JSON.stringify({documentId:base.documentId,operations:plan.summary,completionChanges:plan.completionChanges,output:outputPath},null,2));
}
if(require.main===module)main(process.argv.slice(2)).catch(error=>{console.error(error.message);process.exitCode=1});
module.exports={main};
