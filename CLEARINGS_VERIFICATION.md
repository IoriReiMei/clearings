<!-- SPDX-License-Identifier: MPL-2.0 -->
# Clearings 0.4.5 verification boundary

Group menus offer Collapse all when open and Expand all when collapsed. Both
include nested groups. In a focused view, the title remains visible and its menu
folds or unfolds the descendant groups. Leaf tasks have no fold command. Shared
groups retain one fold state across their occurrences, consistent with existing
title clicks. Center folds last for the page session; outline folds remain separate.
The operation does not modify checklist contents, checks, attribution or unread
indicators. No saved document or proposal format changes.

Save and quit now waits for an in-flight browser save, saves any newer edits,
then waits for local handoff completion before requesting helper shutdown. The
interface is temporarily inert while this completes. A failed save or blocked
handoff keeps the helper running and restores the interface with an explanation.
The tray's Stop helper command still requires browser edits to be saved first.

The real Chromium handoff check covers nested collapse/expand, focused scope,
unaffected sibling groups and outline, exact workspace equality after folding,
retained checked children and assistant indicators. It also exercises a blocked
handoff on quit and a deliberately delayed sync with a newer edit, comparing the
final handoff snapshot before shutdown. All browser data and helpers are fixtures.

The four-platform build validates packaged source and native helpers. Windows
uses the exact checksummed 0.4.4 installer to exercise running-helper upgrade to
0.4.5, reinstall and uninstall with byte-identical fictional handoff retention.
The installer replaces bundled files; it does not compare installed versions,
prevent downgrades, discover updates or remove arbitrary obsolete bundle files.
This update removes no previous program paths.

The working browser origin and installed origin stay separate. Names and commit
receipts remain declared local attribution, not authenticated identities or
cryptographic signatures. Clearings coordinates authorized assistants; it does
not launch them. Older documents remain readable; attribution exports require
0.4.3 or newer.

Windows binaries are unsigned. Mac builds are ad-hoc signed and not notarized.
The owner's Firefox workspace, Safari, interactive Mac/Linux installation,
assistive technologies and every display scale are not certified by these
automated checks. Release as a beta with these limits until broader hands-on
coverage and distribution signing justify a stronger claim. Repository visibility
remains the owner's decision.
