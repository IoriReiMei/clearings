<!--
SPDX-License-Identifier: MPL-2.0
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->
# Clearings — license scope

Clearings uses the Mozilla Public License 2.0 (MPL-2.0). The full, unmodified
standard text is in `LICENSE`. This file explains scope; it adds no license terms.

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

Source files carry SPDX/Exhibit A notices. Non-commentable JSON and image files
have neighboring `.license` notices, which must accompany those files when copied.
The full LICENSE includes Exhibit B as part of the standard text; this project
has not separately designated its files incompatible with secondary licenses.

## Not a blanket license for the surrounding folder

When the app is installed under another project's `checklists/` directory, this
notice does **not** apply to that surrounding repository, its Git history, private
notes, real `checklist_index.json`, personal checklist JSON, backups, or unrelated
files placed beside the app. The MPL is not attached to documents merely because
the app opens, edits, imports or exports them.

Existing third-party notices retain their own terms. Development tools installed
separately are not relicensed by this notice; see `THIRD_PARTY_NOTES.md`.

## Standard text and sources

The bundled LICENSE is the standard MPL-2.0 text from this build environment's
`/usr/share/common-licenses/MPL-2.0`. One trailing space was removed; all license
wording is unchanged.
SHA-256: `1f256ecad192880510e84ad60474eab7589218784b9a50bc7ceee34c2b91f1d5`.

Official text and application guidance (consulted September 26, 2026):
- https://www.mozilla.org/en-US/MPL/2.0/
- https://www.mozilla.org/media/MPL/2.0/index.txt
- https://www.mozilla.org/en-US/MPL/2.0/FAQ/

This is a license and scope notice, not an originality certification.
