<!--
SPDX-License-Identifier: MPL-2.0
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->
# Clearings 0.4.2 source candidate

A local-first checklist that grows into an outline. The app has no account,
analytics, bundled AI, external font, or runtime dependency for ordinary use.

![Clearings in dark mode](docs/preview.png)

## Open Clearings

Open `index.html` in a normal browser window, or serve the same files from a
stable HTTPS address such as GitHub Pages. Choose a username, then start a
workspace, import a backup, or explore the fictional examples. The app saves
ordinary changes in this browser's IndexedDB. It does not upload checklist data.
Export a workspace backup regularly; browser storage is not an independent
backup. A different browser, profile, file location, or site address may open a
separate workspace. Export from the old location before switching, and import
the backup at the new location. Never replace your own JSON with the examples.

The optional source-ZIP Windows `Start_Clearings.cmd` opens a loopback-only local helper
for a remembered home folder and assistant proposal handoff. It requires
Python 3.10 or newer installed with the Windows launcher or `pythonw.exe` on
the path.
This helper is **not** used by `index.html` opened directly or by GitHub Pages.
The public helper uses `127.0.0.1:18765`; the personal working helper keeps
`127.0.0.1:8765`. A native installer would bundle the helper, so its user would
not need a separate Python installation. Windows, Mac, and Linux installer
recipes are included for review, but this source ZIP is not an installer and no
native binaries have been published. The helper's browser address has separate storage, so export and import once
when moving from the standalone page. See [Local handoff](docs/LOCAL_HANDOFF.md).

## Use the outline

- The left side holds checklists and tracked shortcuts; the center shows the
  selected outline; the right side browses the tree independently.
- Names open items. Checkboxes alone mark work complete. Parent progress can
  count only supporting tasks, and the left progress bars span the list width.
- Click a parent title to fold or unfold its sub-tasks. Double-click an
  underlined task title to focus it. On opening a checklist, only the first
  unfinished parent starts expanded; deeper levels start folded.
- Drag a six-dot grip to reorder a checklist or sibling item. The held tile
  glides to its destination, or returns if the drop is invalid. Reduced-motion
  preference skips the movement. Menus and Shift + Up/Down offer alternatives.
- New items ask for a title first. Optional details include choosing another
  active checklist as parent. Deleting an item can promote its sub-tasks or,
  after confirmation, remove its unshared sub-tree.
- **Settings** covers identity, saving, startup, storage, Refresh behavior and
  recent changes. **Templates** in the workspace menu offers the included
  GitHub release and patch-update checklists. Choose a template, then make a
  new checklist or add it under an existing item; each choice makes a fresh,
  unchecked copy. Settings links to the same picker. **Preferences** covers appearance, progress, motion and
  optional controls. **Refresh Clearings** is for incoming changes; normal
  browser saving does not depend on it.

Export a single checklist to share it. Imports are previewed, and replacing an
entire workspace is a separate explicit choice. External assistant proposals
also require review. When the local helper is used, independent edits can
combine and competing edits wait for a checklist-level choice; display names
and colors are attribution hints, not identity verification. See
[External assistant guide](AI_CHECKLIST_GUIDE.md).

## Hosting and verification

This package is prepared for review; placing it in a GitHub repository or
enabling Pages is a separate owner action. If hosted, keep the site address
stable so returning browsers find the same workspace. The hosted page needs
network access to load, and Clearings does not promise offline page caching.
See [Hosting](docs/HOSTING.md), [real-browser check](docs/NATIVE_SMOKE_TEST.md),
and [verification limits](CLEARINGS_VERIFICATION.md).

The included examples and GitHub planning templates are fictional or blank.
The app and designated files use MPL 2.0; see [license](LICENSE),
[scope](LICENSE_SCOPE.md), and [third-party notes](THIRD_PARTY_NOTES.md).
