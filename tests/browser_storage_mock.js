// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// TEST ONLY. Narrow in-memory adapter for this app's IDB operations. This is NOT
// a replacement for a native IndexedDB test and is never loaded by the app.
(() => {
 const records=new Map(), store=new Map();
 window.__records=records;window.__store=store;window.__failWrite=false;window.__slowWrite=0;
 Object.defineProperty(window,'localStorage',{configurable:true,value:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,String(v)),removeItem:k=>store.delete(k)}});
 function transaction(name,mode){
  const tx={error:null,oncomplete:null,onabort:null},stage=new Map(records);let pending=0,ended=false,timer;
  const finish=()=>{clearTimeout(timer);timer=setTimeout(()=>{
   if(ended||pending)return;
   if(mode==='readwrite'&&window.__failWrite){tx.error=new DOMException('Injected full disk / denied storage','QuotaExceededError');tx.abort();return;}
   ended=true;if(mode==='readwrite'){records.clear();for(const pair of stage)records.set(...pair);}
   tx.oncomplete?.({target:tx});
  },mode==='readwrite'?window.__slowWrite:0);};
  tx.abort=()=>{if(ended)return;ended=true;clearTimeout(timer);setTimeout(()=>tx.onabort?.({target:tx}),0);};
  const op=fn=>{const req={result:undefined,error:null};pending++;setTimeout(()=>{if(ended)return;try{req.result=fn();req.onsuccess?.({target:req});}catch(e){tx.error=e;tx.abort();}finally{pending--;finish();}},0);return req;};
  tx.objectStore=()=>({get:k=>op(()=>structuredClone(stage.get(k))),put:(v,k)=>op(()=>{stage.set(k,structuredClone(v));return k;}),delete:k=>op(()=>stage.delete(k))});finish();return tx;
 }
 const db={objectStoreNames:{contains:()=>true},transaction,close(){},onversionchange:null};
 window.__testDB=db;
 Object.defineProperty(window,'indexedDB',{configurable:true,value:{open(){const req={};setTimeout(()=>{req.result=db;req.onsuccess?.({target:req});},0);return req;}}});
 Object.defineProperty(navigator,'storage',{configurable:true,value:{persisted:async()=>false,persist:async()=>window.__grantPersistence===true}});
})();
