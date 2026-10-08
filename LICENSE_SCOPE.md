<!--
SPDX-License-Identifier: MIT
MIT License

Copyright (c) 2026 The Hermit

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
-->
# Clearings — license scope

Clearings' current source uses the MIT License. The Hermit authorized this change
on October 8, 2026. The full permission notice, copyright notice and warranty
disclaimer are in `LICENSE`. This file explains scope; it adds no license terms.

## Included Clearings material

The license notices apply to the following Clearings release files, to the extent
rights in the contributed material can be licensed:

- `LC_CHECKLIST.html`, named `index.html` in the standalone package, including its
  inline CSS and JavaScript. This is the source file edited during development;
  there is no separate bundled/minified runtime or hidden source build.
- The Clearings scripts in `tools/`, `tests/`, and `packaging/`, the optional
  Windows `Start_Clearings.cmd` launcher, the build workflow, and the schema in
  `schema/`.
- The supplied fictional examples in `examples/` and the release-plan templates in
  `templates/` (not a user's personal records made with them).
- The supplied application documentation, release notes and `docs/preview.png`.
  Historic verification reports describe their own dated runs, not current certification.

Source files carry MIT copyright and permission notices. Non-commentable JSON
and image files have neighboring `.license` notices, which must accompany those
files when copied. Retain the MIT copyright and permission notice in copies or
substantial portions of the licensed material.
The CPython license copies at `packaging/licenses/PYTHON-3.12-LICENSE.txt`
and `packaging/licenses/PYTHON-3.14-LICENSE.txt` are third-party legal text under
their own terms; this change does not relicense them.

## Not a blanket license for the surrounding folder

When the app is installed under another project's `checklists/` directory, this
notice does **not** apply to that surrounding repository, its Git history, private
notes, real `checklist_index.json`, personal checklist JSON, backups, or unrelated
files placed beside the app. The MIT License is not attached to documents merely because
the app opens, edits, imports or exports them.

Existing third-party notices retain their own terms. Development tools installed
separately are not relicensed by this notice; see `THIRD_PARTY_NOTES.md`.

## Earlier releases and standard text

Preserved earlier releases, source snapshots and dated verification records keep
their original MPL-2.0 notices and terms. The new MIT release does not remove the
permissions already granted under MPL-2.0. Historical release files were not
rewritten to make them appear to have shipped under MIT.

The MIT wording follows the [Open Source Initiative's standard text](https://opensource.org/license/mit),
with the project's copyright notice and line wrapping. License SHA-256:
`b2dd045787a762f8e3746fb97ee7171ebc9e33f60cba080af0d404a3d44337c8`.

This is a license and scope notice, not an originality certification.
