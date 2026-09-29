<!--
SPDX-License-Identifier: MPL-2.0
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->
# Local handoff in 0.4.3

The Windows installer bundles the helper; open Clearings from its shortcut.
Assistants use `ClearingsCLI.exe` beside the launcher. No separate runtime is
needed. **Save and quit Clearings** stops its helper after saving.

For the optional source-only download, double-click `Start_Clearings.cmd`.
It needs Python 3.10 or newer with the Windows launcher (`pyw.exe`) or `pythonw.exe` on the
path. The helper binds only to `127.0.0.1` and opens Clearings in your normal
browser. If no page opens, run `py -3 -B tools\clearings_local.py serve` in a
terminal to see an error. The standalone `index.html` remains usable without
Python; GitHub Pages serves that standalone page, not the helper.

This public edition uses `127.0.0.1:18765`, separate from the development
helper's `127.0.0.1:8765`. Its local settings live in `Clearings-Release` under
the account's local application-data directory. Its default handoff lives in
`Documents/Clearings/Installed`. Installing a newer build at the same address
does not move browser data. If an older helper is still running with different
app bytes or from a different installation, close it before launching the new
build; Clearings refuses to open the wrong copy. The browser's own IndexedDB is
still the live workspace, so export a backup before changing browser/profile,
address, or installation method.

The helper owns one `clearings_handoff.json` in the home folder selected under
**⋯ → Settings**. The working edition defaults to `Documents\Clearings`; the installed edition
defaults to `Documents\Clearings\Installed`. The browser's
IndexedDB holds the visible browser workspace. A local assistant can read the
saved browser snapshot and the shared state that includes signed AI commits.
An assistant submits a draft, then signs a ready commit once with a display
name. Other assistants see that commit immediately. Pressing **Refresh Clearings**
compares signed commits with the browser copy and shows their changes with blue
attribution. Independent edits combine. Earlier unsigned proposals retain their
historical Refresh behavior; new drafts do not become visible changes.
Conflicting edits wait beside a warning on the affected checklist until a
choice is made in **⋯ → Manage conflicts**. Browser is shown on the left,
incoming JSON on the right. No pending proposal silently overwrites another
checklist. The helper's CLI and data rules are described in
`AI_CHECKLIST_GUIDE.md`.

The helper address, downloaded file, and hosted site each have separate
browser storage. Export a backup from your existing page before changing how
you open Clearings. Import it in the new page once. If the browser is empty
and the handoff already holds a saved snapshot, Clearings offers an explicit
restore; it never silently replaces an existing browser workspace. Keep the
backup after import. Author names identify displayed edits for convenience, not
cryptographic security. A stale browser is stopped from overwriting a newer
handoff; a conflict between a committed AI edit and later browser edit is held
for review.

The included tests use disposable home folders and browser profiles. They do
not establish persistence in your own browser; follow `docs/NATIVE_SMOKE_TEST.md`
there before relying on a new path.
