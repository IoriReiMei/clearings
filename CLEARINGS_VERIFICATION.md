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
# Clearings 0.4.6 verification boundary

Clearings 0.4.6 brings the current working app into the MIT release: protected
local-helper sessions, bind-first startup, explicit resolved-history archiving,
larger aggregate handoffs, bounded group navigation, nested change indicators
and the supplied Clearings mark. Existing document, workspace and proposal
identifiers remain compatible. The release page records the exact source commit,
build results and download checksums.

## Local helper and saved work

The public loopback page contains no reusable session credential. A launch uses
a short-lived, one-use ticket, and helper control checks the responding process
before sending an authenticated command. Windows protects session metadata with
the current account's DPAPI context; POSIX requires owner-private metadata.
Startup retains an exclusive listener before replacing stale session metadata
and preserves a protected recovery copy. Unit and browser checks use disposable
settings, fictional work and separate ports.

Aggregate handoffs allow up to 64 MiB, while ordinary imported/proposed JSON and
HTTP request bodies retain their 16 MiB limits. Explicit resolved-history
archiving preserves an exact preimage and retains pending work. This does not
increase browser workspace capacity or remove other resource limits.

## App and installer checks

Source checks cover contracts, merge and delivery behavior, preferences, MIT
notices, allowlisted packaging and exact-file manifests. Browser checks cover
local handoff, save and reopen, folding, change indicators and long-group paging.
The native build checks the source manifest and exercises the bundled helper
against a disposable configuration on each target platform.

Windows upgrade checks use the exact checksummed 0.4.5 installer, close its own
running helper through the installed CLI, and check upgrade, reinstall and
uninstall with byte-identical fictional handoff retention. Linux closes the
existing installed helper before switching its managed version link. Close
Clearings with Save and quit before replacing the macOS app.

## Beta limits

Windows binaries are unsigned. macOS builds use ad-hoc signing and are not
notarized. Interactive Mac/Linux installation, Safari/Firefox persistence,
assistive technologies and every display scale need broader hands-on coverage.
Automated checks do not certify those journeys. Export a workspace backup before
upgrading or changing browser origins, and verify the reopened copy before
discarding an older backup.

Clearings coordinates authorized assistants; it does not launch them. Actor
names and receipts record declared local attribution. Automatic updates,
downgrade prevention and arbitrary obsolete-file cleanup remain future work.
Earlier release artifacts retain their original notices and verification scope.
