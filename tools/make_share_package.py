#!/usr/bin/env python3
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Create an explicit-allowlist release, never a recursive copy of user data.

Run from any directory. Only the named app/docs/tests and fictional samples are
included. Existing output is refused unless --force is explicitly requested.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile
# Running the packager inside an extracted release must not add cache files to
# that release and invalidate its exact-file manifest.
sys.dont_write_bytecode = True
from sync_templates import assert_current

ROOT = Path(__file__).resolve().parents[1]
# Local source -> public package name. The public app gets a generic filename.
FILES = {
    'LC_CHECKLIST.html': 'index.html',
    'docs/GITHUB_RELEASE_README.md': 'README.md',
    'AI_CHECKLIST_GUIDE.md': 'AI_CHECKLIST_GUIDE.md',
    'docs/RELEASE_VERIFICATION_0_4_2.md': 'CLEARINGS_VERIFICATION.md',
    'LICENSE': 'LICENSE',
    'LICENSE_SCOPE.md': 'LICENSE_SCOPE.md',
    'THIRD_PARTY_NOTES.md': 'THIRD_PARTY_NOTES.md',
    'docs/GITHUB_START_CLEARINGS.cmd': 'Start_Clearings.cmd',
    'templates/clearings_github_release.json': 'templates/clearings_github_release.json',
    'templates/clearings_github_patch.json': 'templates/clearings_github_patch.json',
    'tests/clearings-release.test.cjs': 'tests/clearings-release.test.cjs',
    'schema/checklist-studio.schema.json': 'schema/checklist-studio.schema.json',
    'examples/generic/checklist_index.json': 'examples/generic/checklist_index.json',
    'examples/generic/program_overview.json': 'examples/generic/program_overview.json',
    'examples/generic/weekend_workshop.json': 'examples/generic/weekend_workshop.json',
    'examples/proposals/add-feedback-step.json': 'examples/proposals/add-feedback-step.json',
    'docs/preview.png': 'docs/preview.png',
    'tools/contract.cjs': 'tools/contract.cjs',
    'tools/validate_checklist.cjs': 'tools/validate_checklist.cjs',
    'tools/merge.cjs': 'tools/merge.cjs',
    'tools/clearings_local.py': 'tools/clearings_local.py',
    'tools/make_share_package.py': 'tools/make_share_package.py',
    'tools/sync_templates.py': 'tools/sync_templates.py',
    'tests/contract.test.cjs': 'tests/contract.test.cjs',
    'packaging/build_native.py': 'packaging/build_native.py',
    'packaging/README.md': 'packaging/README.md',
    'packaging/build_mac_dmg.py': 'packaging/build_mac_dmg.py',
    'packaging/build_linux_run.py': 'packaging/build_linux_run.py',
    'packaging/test_native.py': 'packaging/test_native.py',
    'packaging/linux/install.sh.in': 'packaging/linux/install.sh.in',
    'packaging/windows/Clearings.nsi': 'packaging/windows/Clearings.nsi',
    '.github/workflows/build-installers.yml': '.github/workflows/build-installers.yml',
}

FILES.update({
    'docs/HOSTING.md':'docs/HOSTING.md',
    'docs/NATIVE_SMOKE_TEST.md':'docs/NATIVE_SMOKE_TEST.md',
    'docs/LOCAL_HANDOFF.md':'docs/LOCAL_HANDOFF.md',
    'tests/browser_storage_mock.js':'tests/browser_storage_mock.js',
    'tests/preferences.test.cjs':'tests/preferences.test.cjs',
    'tests/clearings_0_4_browser.test.cjs':'tests/clearings_0_4_browser.test.cjs',
    'tests/local_handoff_browser.test.cjs':'tests/local_handoff_browser.test.cjs',
    'tests/merge.test.cjs':'tests/merge.test.cjs',
    'tests/test_clearings_local.py':'tests/test_clearings_local.py',
})

# Notices for JSON/image files travel with the exact allowlisted assets.
for notice in ['schema/checklist-studio.schema.json.license', 'docs/preview.png.license', 'examples/generic/weekend_workshop.json.license', 'examples/generic/program_overview.json.license', 'examples/generic/checklist_index.json.license', 'examples/proposals/add-feedback-step.json.license', 'templates/clearings_github_release.json.license', 'templates/clearings_github_patch.json.license']:
    FILES[notice] = notice

def verify_directory(directory: Path) -> None:
    """Check the exact materialized release bytes, not only a ZIP in memory."""
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError(f'Not a release directory: {directory}')
    entries = list(directory.rglob('*'))
    if any(path.is_symlink() for path in entries):
        raise ValueError('Release directory contains a symbolic link.')
    actual = {path.relative_to(directory).as_posix(): path for path in entries if path.is_file()}
    manifest_path = actual.get('MANIFEST.json')
    if manifest_path is None:
        raise ValueError('Release directory has no MANIFEST.json.')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or set(actual) != set(manifest) | {'MANIFEST.json'}:
        raise ValueError('Release file inventory differs from MANIFEST.json.')
    for name, digest in manifest.items():
        if not isinstance(digest, str) or hashlib.sha256(actual[name].read_bytes()).hexdigest() != digest:
            raise ValueError(f'Release byte mismatch: {name}')
    print(f'Verified {len(manifest)} release files byte-for-byte in {directory}.')

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'clearings-share.zip')
    parser.add_argument('--force', action='store_true', help='Replace an existing release ZIP only.')
    parser.add_argument('--verify-dir', type=Path, help='Verify an extracted release without changing it.')
    args=parser.parse_args()
    if args.verify_dir is not None:
        if args.force: parser.error('--force cannot be used with --verify-dir.')
        verify_directory(args.verify_dir.resolve())
        return
    output=args.output.resolve()
    if output.exists() and not args.force:
        parser.error(f'Output exists: {output}. Choose another name or explicitly pass --force.')
    app_source = ROOT/'LC_CHECKLIST.html'
    if not app_source.exists(): app_source = ROOT/'index.html'
    if b"appVersion:'0.4.2'" not in app_source.read_bytes():
        raise ValueError('This packager is for Clearings 0.4.2 only; review the allowlist and release note for another version.')
    assert_current(app_source, ROOT)
    payload: dict[str,bytes]={}
    extracted_release = app_source.name == 'index.html'
    for source,destination in FILES.items():
        src=ROOT/source
        if extracted_release and not src.exists(): src=ROOT/destination
        if src.is_symlink() or not src.is_file() or not src.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError(f'Missing/unsafe allowlisted source: {source}')
        if output==src.resolve(): raise ValueError('Output must not replace a source file.')
        data=src.read_bytes()
        # Keep packaged text stable across Windows and other checkout line endings.
        # The preview image is the only binary input in this explicit allowlist.
        if destination != 'docs/preview.png': data=data.replace(b'\r\n',b'\n')
        payload[destination]=data
    payload['.gitignore']=b'# SPDX-License-Identifier: MPL-2.0\n# Keep personal libraries under data/ and review before sharing.\n/data/\n/checklist_index.json\n/checklist-*.json\n/program_overview.json\n/build-output/\n/artifacts/\n*.zip\n*.dmg\n*.run\n__pycache__/\n'
    payload['.nojekyll']=b''
    payload['RELEASE_NOTE.txt']=b'SPDX-License-Identifier: MPL-2.0\nClearings 0.4.2 - a local installer-source candidate, not an automatic publication.\nThis update separates installed and working helper addresses, and adds Windows, macOS, and Linux build recipes.\nThe standalone index.html works without Python. A future native installer can bundle the helper so recipients need no Python install.\nThe source ZIP is not itself a native installer; built binaries require platform checks, licensing review, and owner publication.\nThe app and designated release files use MPL 2.0; see LICENSE and LICENSE_SCOPE.md.\nOnly allowlisted code, docs, tests, fictional examples and blank GitHub planning templates are included.\nPersonal exports, browser data, private repository history and the working folder are not collected.\nNative browser persistence at the final address still needs an owner smoke check.\nReview this package before sharing. No originality certification is claimed.\n'
    manifest={name:hashlib.sha256(data).hexdigest() for name,data in payload.items()}
    payload['MANIFEST.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    output.parent.mkdir(parents=True,exist_ok=True)
    mode='w' if args.force else 'x'
    with zipfile.ZipFile(output,mode,compression=zipfile.ZIP_DEFLATED) as archive:
        for name,data in payload.items(): archive.writestr(name,data)
    print(f'Created {output} ({len(payload)} explicitly included files).')
    print('No user library or repository history was collected. Review the ZIP before sharing.')

if __name__=='__main__':
    try: main()
    except (OSError,ValueError,zipfile.BadZipFile) as exc: raise SystemExit(str(exc))
