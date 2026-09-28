// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
'use strict';
// Local release/compatibility checks; no network, accounts or user data writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {spawnSync} = require('node:child_process');
const {createHash} = require('node:crypto');
const api = require('../tools/contract.cjs');
const root = path.resolve(__dirname, '..');
const packager=path.resolve(root,'tools/make_share_package.py');
const archivedApp=path.resolve(root,'../archive/release_0_4_0/index.html');
const appPath = fs.existsSync(path.join(root, 'LC_CHECKLIST.html'))
  ? path.join(root, 'LC_CHECKLIST.html') : path.join(root, 'index.html');
const html = fs.readFileSync(appPath, 'utf8');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const json = file => JSON.parse(read(file));
const clone = x => JSON.parse(JSON.stringify(x));
const doc = json('templates/clearings_github_release.json');
const patchDoc = json('templates/clearings_github_patch.json');
const sourceDoc = clone(doc);
let passed = 0;
function test(name, fn) { fn(); passed++; console.log('PASS ' + name); }
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'clearings-release-'));
const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
function runPython(args) {
  const p = spawnSync(python, args, {encoding:'utf8'});
  if (p.error) throw p.error;
  assert.equal(p.status, 0, p.stderr || p.stdout);
  return p.stdout;
}
try {
  test('visible app name is Clearings', () => {
    assert.ok(html.includes('<title>Clearings</title>'));
    assert.ok(html.includes('<span>CLEARINGS</span>'));
    assert.ok(!html.includes('<title>Checklist Studio</title>'));
  });
  test('storage and wire identifiers remain backward compatible', () => {
    assert.ok(html.includes("STORE='checklist-studio:recovery:v1'"));
    assert.ok(html.includes("LEGACY_STORE='lc:checklist-studio:recovery:v1'"));
    assert.ok(html.includes("const AI_FORMAT='checklist-studio-changes'"));
    assert.ok(html.includes("appVersion:'0.4.2'"));
    assert.ok(!html.includes("format:'clearings-document'"));
  });
  test('overview folding and drag-to-focus interaction ships in the app', () => {
    assert.ok(html.includes("data-action=\"toggle-center-fold\""));
    assert.ok(html.includes("drag.target={kind:drag.kind==='step'?'focus':'open-checklist'}"));
    assert.ok(html.includes('Drop to open here'));
    assert.ok(html.includes('outline-checklist-title outline-root'));
    assert.ok(html.includes('function glideGripTo('));
  });
  test('progress visuals and group-scope preferences ship in the app', () => {
    assert.ok(html.includes("groupProgress:'children'"));
    assert.ok(html.includes("progressVisual:'bar'"));
    assert.ok(html.includes("Supporting tasks only"));
    assert.ok(html.includes("Progress bar"));
    assert.ok(html.includes("Pie"));
    assert.ok(html.includes('class="progress-track"'));
    assert.ok(html.includes('class="progress-pie"'));
  });
  test('standard MPL license wording survives source newline conversion', () => {
    const text = fs.readFileSync(path.join(root,'LICENSE'),'utf8').replace(/\r\n/g,'\n');
    const hash = createHash('sha256').update(text,'utf8').digest('hex');
    assert.equal(hash, '1f256ecad192880510e84ad60474eab7589218784b9a50bc7ceee34c2b91f1d5');
  });
  test('bundled templates match reviewed JSON and start unchecked', () => {
    const block=html.match(/\/\* BUNDLED_TEMPLATES_BEGIN \*\/\s*const BUNDLED_TEMPLATES = ([\s\S]*?);\s*\/\* BUNDLED_TEMPLATES_END \*\//);
    assert.ok(block,'The standalone app must contain its reviewed templates.');
    assert.deepEqual(JSON.parse(block[1]),[doc,patchDoc]);
    assert.deepEqual(clone(api.validateDocument(patchDoc)),patchDoc);
    assert.deepEqual(patchDoc.state,{});
    assert.ok(html.includes("button('templates','Templates…')"));
    assert.match(html,/Add under existing item/);
  });
  test('AI guide describes the current index and progress preferences', () => {
    const guide=read('AI_CHECKLIST_GUIDE.md');
    assert.match(guide,/accepts versions 1, 2, 3, and 4/);
    assert.match(guide,/`groupProgress`.*`children`/);
    assert.match(guide,/`progressVisual`.*`bar`/);
    assert.match(guide,/AI change packets[\s\S]*version 1/);
  });
  test('app and development source contain MPL notices', () => {
    for (const file of [appPath, ...['tools/contract.cjs','tools/validate_checklist.cjs',
      'tools/clearings_local.py','tools/make_share_package.py','tests/contract.test.cjs',
      'tests/clearings-release.test.cjs'].map(x => path.join(root,x))]) {
      assert.ok(fs.readFileSync(file,'utf8').includes('SPDX-License-Identifier: MPL-2.0'), file);
    }
  });
  test('release checklist passes the real document validator without mutation', () => {
    assert.deepEqual(clone(api.validateDocument(doc)), doc);
    assert.deepEqual(doc, sourceDoc);
  });
  test('release plan has five groups, no inferred completion, and no date deadline', () => {
    assert.equal(doc.model.roots.length, 5);
    assert.equal(doc.model.items.length, 21);
    assert.deepEqual(doc.state, {});
    assert.equal(doc.updatedAt, null);
    assert.equal(doc.archived, false);
    assert.match(doc.subtitle,/Optional/);
    assert.match(doc.description,/No deadline/);
    assert.ok(doc.model.items.every(i => i.detail.trim()));
  });
  test('publishing is a separate manual owner decision', () => {
    const decision=doc.model.items.find(i => i.id==='owner-decision');
    assert.match(decision.detail,/explicitly decide/);
    assert.match(decision.detail,/not treat.*authorization to upload/);
    assert.ok(decision.tags.includes('later'));
    assert.ok(doc.view.collapsed.includes('github-later'));
  });
  test('new checklist can join a library without modifying existing documents', () => {
    const index=json('examples/generic/checklist_index.json');
    const documents=index.entries.map(e=>json('examples/generic/'+e.file));
    const original=clone(documents);
    index.entries.push({id:doc.documentId,file:'clearings_github_release.json'});
    const workspace={format:'checklist-studio-workspace',schemaVersion:1,index,documents:[...documents,clone(doc)]};
    const result=clone(api.validateWorkspace(workspace));
    assert.deepEqual(result.documents.slice(0,-1),original);
    assert.equal(result.documents.at(-1).documentId,doc.documentId);
  });
  test('closed parent and unchecked supporting items remain legal', () => {
    const d=clone(doc);d.state['github-later']=true;
    const checked=clone(api.validateDocument(d));
    assert.equal(checked.state['github-later'],true);
    assert.equal(checked.state['owner-decision'],undefined);
  });
  test('a real legacy saved document preserves its format, title and checks', () => {
    const d=clone(doc);d.format='local-companion-checklist';
    d.title='Retained private title';d.state.readme=true;
    assert.deepEqual(clone(api.validateDocument(d)),d);
  });
  test('JSON and image files have adjacent non-invasive notices', () => {
    for(const file of ['schema/checklist-studio.schema.json','docs/preview.png',
      'examples/generic/checklist_index.json','examples/generic/program_overview.json',
      'examples/generic/weekend_workshop.json','examples/proposals/add-feedback-step.json',
      'templates/clearings_github_release.json','templates/clearings_github_patch.json']) {
      assert.match(read(file+'.license'),/SPDX-License-Identifier: MPL-2.0/);
    }
  });
  const zip=path.join(temp,'clearings.zip');
  test('release source and builder agree on 0.4.2',()=>{
    assert.match(html,/appVersion:'0\.4\.2'/);
    assert.match(fs.readFileSync(packager,'utf8'),/Clearings 0\.4\.2 - a local installer-source candidate/);
    const publicLauncher=fs.existsSync(path.join(root,'docs/GITHUB_START_CLEARINGS.cmd'))
      ?path.join(root,'docs/GITHUB_START_CLEARINGS.cmd'):path.join(root,'Start_Clearings.cmd');
    assert.match(fs.readFileSync(publicLauncher,'utf8'),/py\.exe -3 -c/);
    assert.doesNotMatch(fs.readFileSync(publicLauncher,'utf8'),/C:\\Users\\/);
  });
  test('packager creates a local release with license, helper and template', () => {
    runPython([packager,'--output',zip]);
    const names=JSON.parse(runPython(['-c','import json,sys,zipfile; print(json.dumps(zipfile.ZipFile(sys.argv[1]).namelist()))',zip]));
    for(const name of ['index.html','LICENSE','LICENSE_SCOPE.md','THIRD_PARTY_NOTES.md',
      'templates/clearings_github_release.json','templates/clearings_github_release.json.license',
      'templates/clearings_github_patch.json','templates/clearings_github_patch.json.license',
      'Start_Clearings.cmd','tools/clearings_local.py','tools/merge.cjs','docs/LOCAL_HANDOFF.md',
      'packaging/build_native.py','packaging/build_linux_run.py',
      'packaging/build_mac_dmg.py','packaging/windows/Clearings.nsi',
      '.github/workflows/build-installers.yml'])
      assert.ok(names.includes(name),name);
    for(const name of ['checklist_index.json','program_overview.json','private_review.json','.git/config'])
      assert.ok(!names.includes(name),name);
    assert.ok(!names.some(n=>n.includes('archive/')||n.includes('working/')||n.includes('owner-private')));
    assert.ok(names.every(n=>!n.endsWith('.patch')&&!n.includes('..')&&!n.startsWith('/')));
  });
  test('manifest checks every packed byte and notices survive packing', () => {
    runPython(['-c', `import sys,zipfile,json,hashlib
with zipfile.ZipFile(sys.argv[1]) as z:
 m=json.loads(z.read('MANIFEST.json'))
 assert set(m)==set(z.namelist())-{'MANIFEST.json'}
 for name,digest in m.items(): assert hashlib.sha256(z.read(name)).hexdigest()==digest,name
 assert b'<title>Clearings</title>' in z.read('index.html')
 assert b'SPDX-License-Identifier: MPL-2.0' in z.read('index.html')
 assert b'No license has been selected' not in z.read('RELEASE_NOTE.txt')
 assert json.loads(z.read('templates/clearings_github_release.json'))['state']=={}
print('OK')`, zip]);
  });
  test('materialized release rejects changed line endings', () => {
    const extracted=path.join(temp,'verify-dir');
    runPython(['-c','import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])',zip,extracted]);
    runPython([packager,'--verify-dir',extracted]);
    const readme=path.join(extracted,'README.md');
    fs.writeFileSync(readme,fs.readFileSync(readme,'utf8').replace(/\n/g,'\r\n'));
    const p=spawnSync(python,[packager,'--verify-dir',extracted],{encoding:'utf8'});
    assert.notEqual(p.status,0);
    assert.match(p.stderr+p.stdout,/Release byte mismatch: README.md/);
  });
  test('existing ZIP is refused without a force request', () => {
    const before=fs.readFileSync(zip);
    const p=spawnSync(python,[packager,'--output',zip],{encoding:'utf8'});
    assert.notEqual(p.status,0);assert.deepEqual(fs.readFileSync(zip),before);
  });
  test('standalone package can be repackaged without development repository', () => {
    const extracted=path.join(temp,'standalone');
    runPython(['-c','import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])',zip,extracted]);
    const second=path.join(temp,'second.zip');
    runPython([path.join(extracted,'tools/make_share_package.py'),'--output',second]);
    runPython(['-c', `import sys,zipfile
with zipfile.ZipFile(sys.argv[1]) as a, zipfile.ZipFile(sys.argv[2]) as b:
 assert set(a.namelist())==set(b.namelist())
 for n in a.namelist(): assert a.read(n)==b.read(n), n
print('OK')`,zip,second]);
  });
  if(fs.existsSync(archivedApp))test('archived 0.4.0 app keeps its version',()=>{
    assert.match(fs.readFileSync(archivedApp,'utf8'),/appVersion:'0\.4\.0'/);
  });
  console.log(`\n${passed} Clearings release checks passed.`);
} finally {
  // This is the temporary directory created by this test, never a user's library.
  fs.rmSync(temp,{recursive:true,force:true});
}
