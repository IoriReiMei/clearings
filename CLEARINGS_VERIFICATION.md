<!-- SPDX-License-Identifier: MPL-2.0 -->
# Clearings 0.4.2 — installer preparation and limits

This source candidate retains the 0.4.1 checklist document and proposal formats.
The app interface is unchanged except for its version label. The loopback helper
and packaging files are new work; the 0.4.1 candidate and archived 0.4.0 remain
separate historical snapshots.

The personal working helper remains on `127.0.0.1:8765` with its existing
settings and handoff location. The public/installed helper uses
`127.0.0.1:18765`, a separate `Clearings-Release` settings directory, and a
default handoff in `Documents/Clearings/Installed`. A launcher reuses a server
only when its app bytes, program path, channel and settings directory match.
Otherwise it reports the conflict instead of silently opening the wrong copy.
The installed browser origin is designed to remain stable across updates; it
does not import a workspace from an old file, site, or working-copy address.

The public source includes manually triggered build recipes for Windows x64,
macOS arm64/x64 and Linux x64. The recipes bundle the Python helper, add a
source archive, and create a per-user Windows setup executable, ad-hoc-signed Mac
DMG or Linux per-user installer. They **do not publish** a GitHub release. The
source ZIP itself still has a Python-dependent optional launcher; recipients of
a verified native installer would not need to install Python.

Before public distribution, each native build needs execution on its target
platform, a real-browser save/reopen and migration check, an update/uninstall
check that preserves personal data, dependency-license review, and signing or
platform trust review. Developer ID signing/notarization and Windows signing are not
configured. Linux desktop environments differ in whether a downloaded `.run`
file or desktop shortcut is allowed to launch by double-click; the shell-run
fallback must be documented and tested. No platform artifact is represented as
ready for release merely because its recipe or CI artifact exists.
