# Optional local MCP adapter (working 0.4.6)

`tools/clearings_mcp.py` exposes the existing Clearings handoff through a local
stdio MCP process. It does not launch the browser helper, open a network port,
schedule an assistant, or alter the app's stored formats. The browser remains
the live editor. Signed commits are visible to another assistant's effective
read immediately; the browser shows them after **Refresh Clearings**.

This adapter uses the official Python MCP SDK, pinned to `mcp==2.2.0` in
`tools/requirements-mcp.txt`. Install it in a separate Python 3.10+ environment
for the MCP host; the installed Clearings app and its normal CLI do not need the
SDK. For example, using a Python installation that supports `venv`:

```powershell
python -m venv C:\path\to\clearings-mcp-venv
& C:\path\to\clearings-mcp-venv\Scripts\python.exe -m pip install -r C:\path\to\checklists\working\tools\requirements-mcp.txt
```

Configure an MCP client to launch the environment's Python with these **fixed
startup arguments** (the paths shown are examples, not values supplied to
tools):

```text
-B C:\path\to\checklists\working\tools\clearings_mcp.py
--config-dir C:\Users\YOU\AppData\Local\Clearings
--home C:\Users\YOU\Documents\Clearings
--actor Linden
```

`--config-dir` and `--home` must be absolute and must already match the
Clearings settings. The working app normally stores settings under
`%LOCALAPPDATA%\Clearings`; if you chose another home, use the actual home
recorded there. The adapter checks these paths at startup, but `Bridge.home()`
reloads settings later: `--home` is not a lifetime destination pin. The
startup checks are not race-proof if settings change during construction;
the Bridge may create a directory before a later mismatch is detected. Stop
MCP processes before changing the Clearings home or settings, then restart
them with matching arguments. The actor is a display label, not an
authenticated identity. Set it once per MCP process. Keep the process local
to the computer and give access only to trusted local assistants.

Without another flag the process registers only the read-only checklist tools
`clearings_list_checklists`, `clearings_read_checklist`, and
`clearings_search_items`; this is not an OS
filesystem sandbox. Add `--write` at launch to advertise the four
mutation tools: `clearings_propose_existing`, `clearings_propose_new`,
`clearings_commit_proposal`, and `clearings_withdraw_proposal`. That flag
controls which tools exist; it is not a substitute for the host's ordinary
approvals or the user's authorization to change a checklist. None of the tool
arguments accepts a filesystem path, command, URL, or actor override.

Use `clearings_list_checklists` to find IDs and pending/committed status. Use
`clearings_search_items` to locate a task by text, detail, label, or tag. It
returns a bounded list of IDs, one root-to-item path per match, shortened
descriptions, and effective completion states. Active lists are searched by
default; `include_archived=true` opts into archived lists. An item with more
than one root-to-item path has `sharedParentPaths=true`, including descendants
below a shared parent; the displayed path is one valid path. Search results
are context, never a proposal base.

Search scans active checklists by default. With `include_archived=true`, it
follows the workspace index order rather than putting active lists first.
The result count is capped at 50, but response bytes and latency have no fixed
general bound. The current implementation constructs a path for every item
before matching, including items it will not return. A predecessor-only or
lazy path calculation is a possible future optimization, not a measured
improvement yet. If a search omits related items because their text does not
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
`Bridge`, including preserving unknown document fields.

Focused verification uses disposable synthetic Clearings state and two
independent stdio client sessions. It does not write the owner's handoff.
In ordinary source or installer builds without the optional MCP SDK, the MCP
test module explicitly skips its focused cases. Install
`tools/requirements-mcp.txt` to run them; a present but broken SDK still fails
the import. Release installers remain at 0.4.6 and do not bundle this adapter.
