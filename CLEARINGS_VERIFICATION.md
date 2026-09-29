<!-- SPDX-License-Identifier: MPL-2.0 -->
# Clearings 0.4.3 verification boundary

This source release adds AI-to-AI task commits before browser Refresh, durable
creator/current-completer records, a human Move to dialog, explicit same-list
AI removal, own-proposal withdrawal, and installer lifecycle support. The owner
requested private distribution; repository visibility is a separate owner choice.

## Checks included with this release

- Pure app contract, schema, operation planner, merge, preferences and packaging
  checks. Python independently checks signed commits and matches browser merge
  results for concurrent editing, completion, movement and deletion.
- Regression checks for a second assistant editing a newly signed checklist
  before any browser Refresh; attribution retention; pending-proposal retention;
  rejection of locked or stale work; own-author withdrawal; helper shutdown.
- `local_handoff_browser.test.cjs` uses real Chromium, real IndexedDB and a
  disposable loopback helper. It exercises two assistants before Refresh,
  creator/completer display, hierarchy moves, conflict resolution, recovery and
  refusal of a stale second browser. It does not open the owner's profile.
- `clearings_0_4_browser.test.cjs` supplements that with simulated browser-storage
  and UI edge cases. It is not evidence of native filesystem persistence.
- The manual GitHub workflow verifies the exact allowlisted manifest, builds
  Windows x64, macOS arm64/x64 and Linux x64, then opens each bundled helper with
  isolated configuration/home and verifies its served page and shutdown.
- The Windows lifecycle check installs into a temporary location, saves fictional
  handoff data, upgrades with its helper running, then uninstalls with its helper
  running. Exact handoff bytes must survive. CLI JSON output is also checked.
  A failed workflow must be corrected before its artifacts are released.

## Deliberate limits

The automated browser run is Chromium on Windows. The owner's Firefox profile,
Safari, OS browser selection, Gatekeeper/SmartScreen dialogs, accessibility tools
and interactive Mac/Linux installation were not exercised by those checks.
CI helper success does not certify those native journeys. Windows legacy-process
compatibility additionally checks authenticated identity and the OS executable
path before stopping an old helper; legacy migration is narrower evidence than
an end-to-end test against every earlier binary. Linux users of an old review
build without shutdown must close that helper before installing the new build.

Windows artifacts are unsigned. Mac artifacts are ad-hoc signed and not notarized.
They remain review downloads until the owner chooses distribution and completes
any desired platform signing. Source and binary checksums establish byte identity,
not authorship or freedom from defects.

Clearings does not start assistants, run project work, synchronize across devices
or authenticate individual local AI processes. Its commits are attributed local
records, not cryptographic signatures. Browser Refresh remains necessary for the
human display, while assistants can read the committed effective state immediately.
A later human edit can still conflict with an assistant commit; the system holds
that conflict rather than silently declaring either side authoritative.

Deletion uses a conservative full-document freshness check; even an unrelated
concurrent content edit requires replanning. Task mutation parity covers add/edit,
check/uncheck, hierarchy movement/reordering and explicit same-list removal.
Browser-only appearance, file pickers and navigation are not remote AI APIs.
Cross-checklist moves of an existing item are not supplied by either task move UI
or AI operation packet.

The document remains schema 2 with an additive optional `attribution` field.
Older strict apps may reject enriched exports. Original historical exports and
source snapshots remain available; no saved personal workspace is rewritten by
installation. Unknown historical authorship is not invented. Recent activity is
bounded; durable creator and current-completer stamps are not an unlimited audit log.
