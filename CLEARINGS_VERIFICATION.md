<!-- SPDX-License-Identifier: MIT -->
<!-- Copyright (c) 2026 The Hermit. See ../LICENSE. -->
# Clearings 0.4.7 verification

The owner approved publication of Clearings 0.4.7 on October 22, 2026 after
trying the working interface. Local checks are recorded below. The
[0.4.7 release notes](https://github.com/IoriReiMei/clearings/releases/tag/v0.4.7)
record the exact build commit, native workflow results and downloadable checksums.
This file does not carry forward 0.4.6 installer results as evidence for 0.4.7.

The release adds focused revision-checked MCP edits, paged actor briefings,
readiness diagnostics, readable proposal previews/receipts and explicit context
handoffs. Context remains ordinary checklist data; no new saved document schema
or model memory system was introduced. Source contains the quiet editors,
review/assignment workflow, recovery improvements, source setup and animation
changes prepared since the published 0.4.6 release.

The Windows helper also supports explicit per-user sign-in startup and opening
the page by double-clicking its tray icon. Startup begins disabled, launches
quietly, preserves other startup entries, and is removable from the tray menu.
The source CLI provides status/enable/disable operations without starting a
helper. The uninstaller recipe removes only its exact owned startup command.

## Local checks

Verified on Windows with a staged source copy and disposable fictional workspaces:

- Python regression suite: all 174 cases passed, including 25 tray/startup cases,
  17 agent workflow cases and eight actual MCP SDK stdio cases. Two native Windows
  tray cases used temporary icons to check registration/restoration/cleanup and
  double-click message handling. Startup registration tests use a fake registry.
  Earlier version-specific fixtures were corrected for 0.4.7.
- 54 JavaScript contract checks, 11 merge checks and the coordination/parity
  scenario across four saved transitions passed.
- 25 release checks passed, including allowlisted packaging, exact byte manifests,
  existing-output refusal, import-shadow rejection and standalone repackaging.
- Chromium context integration passed at 1440px and 390px: an agent-created
  context child imports into the page, starts folded, preserves the source task,
  safely renders supplied markup as text and exports the updated AI instructions.
  This uses simulated in-memory storage and blocked requests, not a real profile.
- Publication browser checks passed for the current overview, context import,
  deep activity indicators, mixed-root paging and the local handoff rehearsal.
  The handoff rehearsal uses a disposable real Chromium profile and temporary
  helper: automatic recovery, independent signed edits, conflict decisions,
  stale-browser refusal and save-before-shutdown are covered. Its private-session
  protection is simulated; native session protection is checked separately.

The owner workspace and running helpers were excluded. MCP and loopback tests
used isolated test subprocesses. This does not establish native installer,
cross-platform, real-home adoption, large-workspace latency or owner acceptance.
The final source ZIP has an exact per-file manifest; its adjacent checksum and
release record identify the published bytes.

## Native qualification and remaining limits

The release workflow builds Windows x64, macOS Apple silicon/Intel and Linux
x64 from one exact allowlisted source commit. Windows qualification includes
upgrade from the checksummed 0.4.6 installer, reinstall, startup registration
preservation and removal during uninstall, and unchanged fictional handoff
bytes. Source checks exercise the optional MCP SDK separately. Consult the
release notes for completed results; these recipes alone do not establish them.

Real Windows sign-in and physical tray mouse interaction, interactive Mac/Linux
installation, Safari/Firefox, and adoption in every existing MCP client remain
hands-on acceptance work. Temporary tray icons and posted messages do not prove
those journeys. Reconnect clients at a safe stopping point to discover new tools.
No owner workspace or running collaborator is part of installer qualification.

The working origin remains 127.0.0.1:8765; public source and installed origin
remain 127.0.0.1:18765. Existing MCP clients need a safe reconnect to discover
new tools. Earlier stable-host changes and the versioned host update require
normal adoption at a convenient stopping point. This preparation does not
restart a helper or client. Compatible data-engine updates remain supported.

Network hosting, LAN access, remote-access configuration and cross-device sync
are deferred. Installers are not made seamless by an MCP reconnect. Existing
platform signing/notarization limitations remain until separately qualified.
