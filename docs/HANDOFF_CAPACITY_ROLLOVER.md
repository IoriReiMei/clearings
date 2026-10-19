<!-- SPDX-License-Identifier: MIT -->
# Bounded handoff history rollover

Clearings keeps a browser workspace snapshot and full before-and-after copies
of assistant proposals in one local handoff. The aggregate handoff has a 64 MiB
read/write limit. Individual imported/proposed documents and HTTP request
bodies keep their separate 16 MiB limits. These bounds prevent an accidental
or malformed file from causing unbounded memory use; removing the aggregate
limit would not solve growth from repeated full-document proposals.

When an ordinary handoff edit would cross the aggregate limit, the helper now
checks for proposals that were already terminal in the saved file. It writes
and verifies an exact, hash-named preimage archive under the configured home,
then removes only those unchanged terminal proposals from the active handoff.
The active handoff keeps a descriptor listing the archived IDs and hash. A
proposal newly marked terminal by the current edit remains active until a
later archive can capture that exact version. Pending proposals, unknown
statuses and fields, the browser snapshot, receipts, library identity and
generation stay in the active file.

The archive is prepared and checked before the active handoff is replaced.
If preparation or replacement fails, the prior active file remains intact;
an already verified archive may remain as an idempotent recovery artifact.
If the active file would still exceed the limit after safe archiving, the
edit fails without discarding pending work. The explicit `archive-resolved`
command remains available and uses the same verified archive writer.

This change is a source patch. Existing 0.4.6 installer binaries are unchanged
until a separately qualified build and release. It does not enlarge browser
workspace capacity or guarantee room for arbitrary numbers of pending
proposals. Assistants should continue to use the supported signed handoff and
Refresh workflow, rather than editing the JSON or archives directly.
