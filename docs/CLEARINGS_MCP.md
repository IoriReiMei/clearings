# Optional local MCP adapter (0.4.7)

`tools/clearings_mcp.py` exposes the existing Clearings handoff through a local
stdio MCP process. It does not launch the browser helper, open a network port,
schedule an assistant, or alter the app's stored formats. The browser remains
the live editor. Signed commits are visible to another assistant's effective
read immediately; the browser shows them after **Refresh Clearings**.

For a welcoming introduction, begin with [AI_START_HERE.md](../AI_START_HERE.md).
Assistants pointed at the source folder can discover it through
[AGENTS.md](../AGENTS.md). The same guidance is available inside MCP through
`clearings_get_guide`, so a connected assistant does not need filesystem access
to learn the collaboration workflow or explain the app to another user.

This adapter uses the official Python MCP SDK, pinned to `mcp==2.2.0` in
`tools/requirements-mcp.txt`. Install it in a separate Python 3.10+ environment
for the MCP host; the installed Clearings app and its normal CLI do not need the
SDK. For example, using a Python installation that supports `venv`:

```powershell
python -m venv C:\path\to\clearings-mcp-venv
& C:\path\to\clearings-mcp-venv\Scripts\python.exe -m pip install -r C:\path\to\clearings\tools\requirements-mcp.txt
```

Configure an MCP client to launch the environment's Python with these **fixed
startup arguments** (the paths shown are examples, not values supplied to
tools):

```text
-B C:\path\to\clearings\tools\clearings_mcp.py
--config-dir C:\Users\YOU\AppData\Local\Clearings-Release
--home C:\Users\YOU\Documents\Clearings\Installed
--actor YourAssistantName
```

Start the app once before connecting an assistant. The example above uses a
public source checkout on Windows. On macOS/Linux, create the virtual environment
with `python3 -m venv`, use its `bin/python`, and supply absolute paths for that
computer. Public-source settings default to `~/.local/Clearings-Release` on
those platforms; the default home is `~/Documents/Clearings/Installed`.

`--config-dir` and `--home` must be absolute and must already match the
Clearings settings. The maintainer's working layout instead stores settings under
`%LOCALAPPDATA%\Clearings` on Windows (`~/.local/Clearings` elsewhere), with
`Documents/Clearings` as the home. If you chose another home, use the actual home
recorded there. The adapter checks these paths at startup, but `Bridge.home()`
reloads settings later: `--home` is not a lifetime destination pin. The
startup checks are not race-proof if settings change during construction;
the Bridge may create a directory before a later mismatch is detected. Stop
MCP processes before changing the Clearings home or settings, then restart
them with matching arguments. When first adopting the coordination additions, restart
the helper and reconnect MCP processes so they understand Review, assignment and
per-field attribution. Older strict readers may reject these records. Subsequent
compatible data-engine updates approved in the human page are adopted by upgraded
MCP clients on their next call. Tool-definition/host changes require reconnection.
See [coordination and recovery](COORDINATION_AND_RECOVERY.md). The actor is a display label, not an
authenticated identity. Set it once per MCP process. Keep the process local
to the computer and give access only to trusted local assistants.

The default connection exposes nine read-only tools; `--write` adds six writing
tools. Tool discovery includes descriptions, typed input schemas and safety hints.
This flag is not an OS sandbox or permission to perform work the user did not ask for.
No mutation tool accepts an author override, filesystem path or command.

| Tool | Purpose | Mode |
| --- | --- | --- |
| clearings_get_guide | Short usage/teaching topics, including context | Read |
| clearings_get_status | Read readiness, write preconditions and recovery | Read |
| clearings_list_checklists | Locate lists and pending changes | Read |
| clearings_read_checklist | Full effective document or marked partial branch | Read |
| clearings_read_item | Complete item, attribution, scope and revision | Read |
| clearings_search_items | Find task IDs from matching text | Read |
| clearings_get_briefing | Paged assignments, replies and changes for an actor | Read |
| clearings_preview_proposal | Paged field/completion preview and conflicts | Read |
| clearings_prepare_handoff | Prepare unsaved context with source task references | Read |
| clearings_propose_item_edits | Stage precise revision-checked fields | Write |
| clearings_propose_handoff | Stage a prepared ordinary context item | Write |
| clearings_propose_existing | Stage a full-document edit | Write |
| clearings_propose_new | Stage an unchecked new checklist | Write |
| clearings_commit_proposal | Sign a draft after current merge checks | Write |
| clearings_withdraw_proposal | Withdraw your own proposal with a receipt | Write |

Start with status and a briefing, read the relevant task, then propose, preview
and commit. For exact limits, retry behavior and examples of keeping context,
see [focused workflows](../AI_CHECKLIST_GUIDE.md#focused-agent-workflows-in-047)
and [task context](../AI_START_HERE.md#saving-context-under-tasks).

The status tool still returns recovery information when data reads or host
adoption fail. It does not probe the browser helper or test filesystem writes.
Discovering a tool or loading a guide alone does not establish read/write readiness.

Call `clearings_get_guide` first. Its default `start` topic is brief; choose
`collaboration`, `human`, `handoff`, `context`, `setup`, `recovery`, or `reference` as needed.
The response identifies the guide revision, adapter version, configured actor,
and `writeEnabled` for this process. These are capability labels, not new user
permissions. The guide reads only its two fixed bundled Markdown files, never
the personal workspace, and remains available when checklist data needs repair.
Each read is capped at 64 KiB; an incomplete source copy produces an explanatory
tool error. Existing MCP sessions need reconnection to discover this added tool;
the guide addition alone does not require a browser-helper restart. Clients that
support reconnecting one server can do that without restarting other assistants.

Use `clearings_list_checklists` to find IDs and pending/committed status. Use
`clearings_search_items` to locate a task by title, description, response, review,
MCP acknowledgement, label, or tag. It
returns a bounded list of IDs, one root-to-item path per match, shortened
descriptions, and effective completion states. Active lists are searched by
default; `include_archived=true` opts into archived lists. An item with more
than one root-to-item path has `sharedParentPaths=true`, including descendants
below a shared parent; the displayed path is one valid path. Search results include a shortened Response preview when present. A full
`effectiveDocument` or branch read carries the complete Response text. Search results
are context, never a proposal base. `match.field` identifies the matched field and
`match.excerpt` includes the matched passage, limited to 160 characters. Case-folded
matches retain the original spelling, including characters such as sharp s.

Search scans active checklists by default. With `include_archived=true`, it
follows the workspace index order rather than putting active lists first.
The result count is capped at 50, but response bytes and latency have no fixed
general bound. Search builds one predecessor and capped path count per item only
for a checklist contributing a result, then reconstructs paths only for returned
matches. A 3,000-item synthetic chain verifies this representation; no production
latency claim is implied. If a search omits related items because their text does not
match, read the relevant marked-partial branch for context.

Read a full `effectiveDocument` with `clearings_read_checklist`, copy it as `base`,
change only the intended fields in a separate `incoming` document, then
propose and commit. A `branch_id` read is marked partial and is context only;
never use it as the proposal base. `effective_only=true` returns the same full
effective document as a valid proposal base while omitting the saved duplicate
and proposal history. The default full read remains unchanged. To inspect the
full history or conflicts, use that default read. The two read options cannot
be combined. For a new list, propose a complete version-2
document with unchecked items, then commit. Only the configured actor can
withdraw its own proposal. On a stale conflict, read again, withdraw the old
draft if appropriate, and prepare a new proposal; never overwrite the handoff
file. The adapter delegates all merge, attribution, and conflict decisions to
`Bridge`, preserving unrelated fields. The native document schema remains strict.

Use Response for a cross-role handoff, Review to answer it, and
`mcpAcknowledgement` for a connector receipt. Keep the task description intact
when replying. Assignment status and receipts coordinate intent, not execution
permission. Full effective reads include all these optional fields.

Use a fresh `request_id` when proposing and reuse it for retries of the same
payload. A temporary `CLEARINGS_UPDATING` error means wait one second and retry
with that ID. A repeated commit returns its existing receipt. A different payload
under an already-used request ID is refused. This is explicit deduplication;
requests without an ID retain the original proposal behavior.

Focused verification uses disposable synthetic Clearings state and two
independent stdio client sessions. It does not write the owner's handoff.
In ordinary source or installer builds without the optional MCP SDK, the MCP
test module explicitly skips its focused cases. Install
`tools/requirements-mcp.txt` to run them; a present but broken SDK still fails
the import. Native installers do not bundle the optional Python MCP SDK or
configure a client's connection; use the source adapter and setup above.
