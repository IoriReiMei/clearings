# Coordination and recovery in working source

These additions are in the development edition. They do not change the version
number or replace previously published installers. Restart the helper and reconnect
already-running MCP clients once when first adopting this code, then reload the page.
Old strict readers do not understand the new optional fields or attribution records.

## Keeping the everyday view quiet

Description remains the main field. New Item and Edit Item use the same compact
width as Settings, with a taller Description. Response, Review, MCP acknowledgement,
Assignment and More options are folded until opened. A focused end item shows its
description and populated discussion sections; Response starts folded there too.
Parent descriptions stay inside their explicit Details section. Overview text can
still be edited in place. A Response does not alter the description.

Use Response for a human-to-AI or AI-to-human handoff. A changed, nonempty Response
requests attention through a separate Needs Review indicator, with the response
writer's role and name. A changed, nonempty Review answers it and clears that
indicator. The item menu also offers Clear Review Indicator. Reviewing an older
response while someone changes it is held for explicit comparison.

Clear New Change Indicators is available at the Checklists heading, on a checklist,
and on an item (including that item's descendants). It does not clear Needs Review
or change checkmarks. Empty Refresh keeps the current indicators. A Refresh that
applies a new batch replaces the old indicators with that batch, including when
several checklists arrive together. Clearing the middle of a highlighted series
splits its bracket. The clear action's Undo refuses to replace newer indicators.

The sidebar has Recently Completed, Work Map, and For your-name views. Recently
Completed uses explicit completion stamps; it does not infer parent completion.
Dates remain available in item history and tooltips. Work Map separates accepted
assignments from handoffs awaiting a reply or declined, plus unassigned open end items. For your-name gathers
human assignments addressed to that name and AI responses requesting attention.
It is a view of saved records, not a notification delivery service or agent launcher.

## Records for people and AI

Document schema version remains 2. Old items need none of these optional fields:

- `response`, `review`, `mcpAcknowledgement`: text, with the usual 200,000-character limit.
- `needsReview`: boolean.
- `assignment`: `null`, or `{id, assignee, role, status, note}`. Use a fresh stable
  assignment ID on reassignment. Role is `human` or `assistant`; status is `pending`,
  `accepted`, `declined`, `completed` or `cancelled`. Names are 1–80 characters;
  notes are at most 20,000 characters.

An assignee can record acceptance or decline, and an explanation in the assignment
note. Reassignment records the previous assignment as superseded. Completion and
reopening append receipts without inventing elapsed-time evidence. The Work Map
shows time since the recorded assignment; detailed receipts retain their timestamps.
Assignments coordinate intent and never grant authority to execute work.

The optional document `attribution` map retains creation/completion stamps and
last-editor stamps for `text`, `detail`, `response`, `review`, and
`mcpAcknowledgement`. Each stamp comes from the actual applied change and actor.
`assignmentHistory` retains assignment receipts, including actor, role and time.
Missing historical authors remain unknown. The item history dialog displays these
records. Display names are collaboration labels, not authenticated identities.

Discussion and assignment edits remain available inside completed scopes;
structural edits keep their existing completion locks. Archived lists remain
read-only. Undo/Redo records human changes only and preserves independent AI work.

## Automatic local recovery

Browser saves now include a recovery copy of the workspace and editor draft in
the existing handoff. Save and quit flushes the browser save, waits for its local
sync, drains active helper writes, then creates a recovery backup before stopping.
Normal tray/CLI stops back up the last successful browser sync; they cannot capture
keystrokes that the browser has not saved yet. A backup failure leaves the helper
running and reports the problem.

Recovery files live in `recovery/` inside the existing configured Clearings home:
`latest.json`, the previous good `previous.json`, and checksum-addressed copies of
referenced history archives. Backups include the app version, handoff, proposals,
receipts, browser workspace and recoverable draft. They exclude application source,
release binaries and helper credentials/session files. This is local recovery on
the same drive; an exported copy elsewhere remains useful for drive failure.

On startup, a missing handoff can be recovered from a valid latest or previous
backup. Existing handoff files, including damaged ones, are never overwritten by
automatic recovery. An empty browser can recover the saved browser record and
draft. A populated browser keeps its own record and the existing generation
conflict checks. A corrupt or unsupported backup is not silently forced into it.

## Applying compatible working-source updates

Public release checks remain automatic by default and may be turned off in Settings.
Downloading and installing a release remain the human's choice. In the working
edition, App updates also offers Apply helper update when edited local source is
compatible with the running host. It never fetches or executes code from a supplied
URL or path, and it does not install a GitHub release.

The HTTP listener, port and browser authorization token stay in place. A compatible
update replaces only the Bridge data engine and merge/validation code. A syntax-tree
comparison requires the host, imports, authentication, locking, startup, update
mechanism, and protected Bridge lifecycle methods to remain unchanged. Tray changes
and frozen installer updates require a normal restart. Page changes load when the
person reloads the page; applying the helper does not force a page reload.

The update drains active writes, creates a backup, validates the candidate against
saved/pending documents, checks source preimages again, and switches the engine.
Failure leaves the previous engine active and releases the pause. The shared
maintenance lease blocks writes from new helper/MCP code during the switch, with a
five-minute crash expiry; startup on the same exclusively bound origin releases
an abandoned lease. Newly connected clients and the CLI follow the approved source
identity. Existing upgraded MCP clients load an approved compatible engine on their
next call. Changes to MCP tool definitions or the stable host require reconnection.

HTTP writers receive status 503 and `{code: "CLEARINGS_UPDATING", retryable: true,
retryAfterMs: 1000}`. MCP exposes the same code and retry information as a tool error:
“Clearings is restarting for an update, please hold.” Retry with the same request ID.
Browser sync retries a temporary pause up to four times before preserving its local
copy and reporting that the handoff needs attention.

`clearings_propose_existing` and `clearings_propose_new` accept an optional
`request_id`. Use a fresh ID for a new logical proposal and reuse it for an uncertain
retry. Reusing it with changed content is refused. Its original proposal/commit
receipt remains available after history archiving. Repeating a signed commit by
the same author returns that commit instead of applying it again. Read-only MCP
connections remain read-only; no assignment or review field changes that boundary.
