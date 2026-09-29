<!--
SPDX-License-Identifier: MPL-2.0
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->
# Two-minute real-browser check

This is a check with fictional data, not a request to risk a real workspace.
The loopback browser test uses real Chromium and IndexedDB in a disposable profile.
A supplementary UI test simulates storage. Neither certifies every user browser.

1. In a normal (not private) browser window, open the **new versioned**
   `index.html` or your final hosted URL. If you are moving from an older release
   path, first open that old path and export a fresh workspace backup. Keep the
   old folder and backup until the new path passes this check. Import the backup
   at the new path; do not expect browser storage to move with the HTML file.
   For a new installation, choose a username and start a workspace. If storage is unavailable, Clearings
   must explicitly say Export-only; do not assume autosave works there.
2. Add an item called `Reopen check`, mark it done, and wait for **Saved on this
   device**. Close the tab, reopen the same file/URL, and check that the item and
   its checkmark return without another welcome/setup prompt.
3. Enter but do not Apply a second item's title. Wait for **Saved · editor draft
   kept**. Close/reopen, Resume the draft, verify the title, then Apply it once.
4. Export a workspace backup. Import one example checklist as a separate list and
   confirm the original items remain. Switch a progress or theme preference and
   reopen to confirm it survived too.
5. Put two checklists in the left library. Drag the lower one's six-dot grip
   above the other. The tile and its dots should settle together. Close and reopen: the top one should open. In Settings,
   turn off **Open the top checklist on startup** and set another checklist as
   default; close and reopen to check that choice too.
   In the central overview, click a heading with supporting items twice: its
   rows should fold and unfold smoothly. With reduced motion selected in
   Preferences, the same change should be immediate. On reopening, only the
   first unfinished parent group should be expanded and its deeper groups
   folded. Double-click an underlined task title to focus that task; use the
   checklist breadcrumb to return.
6. In a new step form, enter only a title. Verify **More details (optional)**
   stays folded until opened. Try **Discard draft** and confirm it did not add a
   step. Add the optional Smoke Test Checklist from Settings once, and confirm
   adding it again does not duplicate it.
7. For the optional assistant flow, choose a freshly made changes JSON with
   **Refresh Clearings**. Inspect the preview and reject it once; nothing should
   change. Apply it after review. NEW/UPDATED/checkmark highlights should appear
   only for approved incoming changes. Clicking Checklists/Tracked folds its list without clearing indicators. An empty
   Refresh preserves highlights; a second empty Refresh after the cooldown clears
   them, with Undo. Mark indicator as seen clears one checklist explicitly.
   Enable the optional Clear Indicators button in Preferences to clear them manually. Checkmark
   changes require their separate confirmation checkbox. A stale proposal must
   be refused. This requires a real proposal file; skip if you do not have one.
8. Export another backup from the new version. Confirm it downloaded. If you
   update an app at the **same** path later, replace only its HTML and check that
   your saved workspace still opens. Test a hosted address separately from a
   downloaded file.

Record browser/version and whether you used a file URL or HTTPS. A pass in one
browser is not a pass in all browsers. Export JSON before switching browsers,
moving the file, changing site URLs, clearing site data, or deleting a profile.
