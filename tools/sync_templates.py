#!/usr/bin/env python3
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Embed the two reviewed JSON templates in the standalone Clearings page.

The JSON files in templates/ are the editable sources. A file:// page cannot
reliably fetch adjacent files in Firefox, so the app carries inert copies.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = (
    'clearings_github_release.json',
    'clearings_github_patch.json',
)
BEGIN = '/* BUNDLED_TEMPLATES_BEGIN */'
END = '/* BUNDLED_TEMPLATES_END */'


def expected_block(root: Path = ROOT) -> str:
    documents = [json.loads((root / 'templates' / name).read_text(encoding='utf-8'))
                 for name in TEMPLATES]
    for document in documents:
        if document['state'] or document['archived']:
            raise ValueError('A bundled template must start unchecked and active.')
    payload = json.dumps(documents, ensure_ascii=False, separators=(',', ':'))
    # Keep the data inert even if a later template contains HTML-looking text.
    payload = payload.replace('<', r'\u003c').replace('\u2028', r'\u2028').replace('\u2029', r'\u2029')
    return f'{BEGIN}\nconst BUNDLED_TEMPLATES = {payload};\n{END}'


def assert_current(app: Path, root: Path = ROOT) -> None:
    source = app.read_text(encoding='utf-8').replace('\r\n', '\n')
    if source.count(BEGIN) != 1 or source.count(END) != 1:
        raise ValueError('Bundled template markers are missing or ambiguous.')
    actual = source[source.index(BEGIN):source.index(END) + len(END)]
    if actual != expected_block(root):
        raise ValueError('Bundled templates are stale. Run tools/sync_templates.py --write, then review the diff.')


def write_current(app: Path, root: Path = ROOT) -> None:
    raw = app.read_bytes()
    newline = '\r\n' if b'\r\n' in raw else '\n'
    source = raw.decode('utf-8').replace('\r\n', '\n')
    if source.count(BEGIN) != 1 or source.count(END) != 1:
        raise ValueError('Bundled template markers are missing or ambiguous.')
    start = source.index(BEGIN)
    finish = source.index(END) + len(END)
    updated = source[:start] + expected_block(root) + source[finish:]
    app.write_bytes(updated.replace('\n', newline).encode('utf-8'))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='Update the HTML after reviewing template JSON.')
    args = parser.parse_args()
    app = ROOT / ('LC_CHECKLIST.html' if (ROOT / 'LC_CHECKLIST.html').exists() else 'index.html')
    if args.write:
        write_current(app)
    assert_current(app)
    print('Bundled Clearings templates match their JSON sources.')


if __name__ == '__main__':
    main()
