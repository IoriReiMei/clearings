<!-- SPDX-License-Identifier: MIT -->
<!-- Copyright (c) 2026 The Hermit. See LICENSE for the full MIT notice. -->
# Run Clearings from source

Download your fork with GitHub's **Code → Download ZIP**, then extract the whole
ZIP to a folder. You can also clone the repository. Personal checklists belong
outside this source folder.

## Open it

The local app needs **Python 3.10 or newer**. A current supported Python from
[python.org](https://www.python.org/downloads/) is recommended. No pip packages,
Node, Docker, administrator account, or AI subscription are needed to run it.
The launchers use an installed Python; they do not install dependencies.

Open a terminal in the extracted folder and run:

| Computer | Command |
| --- | --- |
| Windows | `py -3 clearings.py` |
| macOS or Linux | `python3 clearings.py` |

Windows also has `Start_Clearings.cmd`. On macOS/Linux, `sh Start_Clearings.sh`
does the same job without needing executable permissions. Keep the terminal
open while using this source edition. **Save and quit Clearings** saves and
stops its helper. The separately published desktop installers provide the
usual shortcut-based experience without installing Python.

If Windows has `python` but not `py`, use `python clearings.py`.

On Windows, double-click the running helper's tray icon to open the page.
Right-click it and choose **Start helper with Windows** if you want the helper
to start quietly when you sign in. The option starts off and can be unchecked
in that same menu. See [tray and startup details](LOCAL_HANDOFF.md#windows-tray-and-sign-in-control--047).
An existing virtual environment works too. `CLEARINGS_PYTHON` may point to a
particular Python executable for either platform launcher; quote paths with spaces.

The public source opens `http://127.0.0.1:18765/`. Reopening the same source
launcher reuses its helper. The maintainer's `LC_CHECKLIST.html` working layout
keeps its existing `8765` address and working launcher.

Create your workspace and choose your name in the page. To try fictional work,
import `examples/generic/program_overview.json` through the checklist import
control. Nothing imports automatically.

## Check setup without starting anything

Run `py -3 clearings.py --check` on Windows, or
`python3 clearings.py --check` on macOS/Linux. It checks the interpreter, required
source files and release configuration. It does not open the browser, start a
helper, contact GitHub, install packages, or create a workspace.

If it reports a missing file, extract the complete ZIP again. If it reports
`clearings.json`, correct that file using the example below. If another Clearings
copy already owns the address, use **Save and quit** in that copy before opening
the new one. Keep the normal address: changing it gives the browser a different
workspace. Export a workspace backup before changing source copies or addresses.

## Point a fork at its own releases

Edit the small `clearings.json` file in the source root:

```json
{
  "schemaVersion": 1,
  "updateRepository": "YOUR-GITHUB-NAME/YOUR-REPOSITORY"
}
```

Use `"updateRepository": null` if the fork does not publish releases.
Only a GitHub `owner/repository` is accepted, not a URL or a private access token.
Missing or invalid configuration disables checking; it never falls back to
the original project's releases. Correct the file and reload the page to pick
up the new setting. The packaged standalone page gets the same release link
when you build a fresh source ZIP.

Checks are on by default for a configured repository, can be turned off in the
app, and only retrieve public release metadata. Downloads and installs stay
manual. Changing the repository does not rename the app, change its version,
isolate storage, or make two copies safe to run side by side. Keep forks on
separate OS profiles/devices when you need independent simultaneous workspaces.

## Optional next steps

- [Help an AI find its way](../AI_START_HERE.md): using Clearings, explaining it
  to a person, and leaving useful continuity for another assistant. The source
  folder's [AGENTS.md](../AGENTS.md) points assistants to the same guide.
- [Connect an AI through MCP](CLEARINGS_MCP.md): separate, explicit setup with
  its own Python dependencies. The normal page does not need these.
- [Modify, test and package a fork](../CONTRIBUTING.md).
- [Static hosting](HOSTING.md): serves the page with separate browser workspaces.
  The helper remains local to this computer. Shared network hosting is future work.
