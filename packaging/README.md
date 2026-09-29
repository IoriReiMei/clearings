<!-- SPDX-License-Identifier: MPL-2.0 -->
# Clearings native installers

The source ZIP is a reviewable input, not a native installer. The manual
`.github/workflows/build-installers.yml` workflow builds four unsigned review
artifacts from that input. It uploads workflow artifacts only; it does not
create a GitHub Release or modify anyone's Clearings workspace.
The exact-file manifest and `.gitattributes` preserve source bytes across
platform checkouts. CI requests Python 3.12 and includes reviewed official
license text for its observed 3.12.10/3.12.14 variants when the installed
runtime has no separate license file; other versions stop for review.

| System | Review artifact | What installing does |
| --- | --- | --- |
| Windows x64 | `Clearings-Setup-0.4.3-Windows-x64.exe` | Installs under the current user's local Programs folder. Desktop and Start Menu shortcuts are separate installer choices, both unchecked by default. No administrator rights or separate Python install is intended. |
| macOS Apple silicon / Intel | Architecture-specific `.dmg` | Open the image and drag `Clearings.app` into Applications. This is a review image with ad-hoc signing only, not Developer ID signed or notarized. |
| Linux x64 | `Clearings-Install-0.4.3-Linux-x64.run` | Installs under the current user's local data folder and creates an application-menu entry and, where possible, a Desktop shortcut. Some desktops require “Allow launching” for downloaded files or shortcuts. `sh Clearings-Install-0.4.3-Linux-x64.run` is the fallback. |

The installed helper opens Clearings in the user's ordinary browser at
`http://127.0.0.1:18765/`. That address must remain the same across updates
for the browser's saved workspace to remain visible. The development helper
continues using port 8765 and its old files. Installed Clearings keeps local
settings in a separate `Clearings-Release` folder and defaults its JSON handoff
to `Documents/Clearings/Installed`. Browser IndexedDB remains the live workspace;
the installer does not migrate or back it up. Export a workspace backup before
changing browser, browser profile, or installation method, and import it once
in the installed edition. Never discard the original before checking the copy.

The bundle includes `source.zip` with the exact public sources and manifest,
plus the Python and PyInstaller license texts from the build environment.
Personal checklists, private LC material and development archives are not
packaged. On Windows, uninstall removes the installed program directory and
shortcuts; it leaves the browser workspace and handoff directory alone. The
Linux installer retains earlier version directories for a deliberate later
cleanup. macOS app replacement likewise does not clear browser or handoff data.

Before public distribution, build and execute each artifact on its target
system; test fresh install, saved-workspace reopen, update, running-old-version
behavior and uninstall. Review third-party notices for bundled Python and
PyInstaller. Sign Windows and Mac artifacts as appropriate; notarize Mac for a
smooth public launch. Only then decide whether to publish the checked artifacts
through GitHub Releases. A passing source test or CI build is not that decision.

## Installer lifecycle in 0.4.3

Windows stops only the authenticated helper from the exact installation path
before upgrading or uninstalling. If it cannot verify shutdown, it stops the
installation instead of overwriting running files. A separate `ClearingsCLI.exe`
provides JSON output for assistants using the same configuration and helper identity.
Failures in CLI/installer commands return an error rather than a hidden dialog.
Uninstall preserves browser storage, settings and handoff files.

Linux uses the staged new helper to stop the old installation before switching
its managed version link. For a pre-0.4.3 review helper without shutdown support,
close the old helper first. Earlier version directories stay intact. On macOS,
use Save and quit Clearings before replacing the app in Applications.

Build from the allowlisted source directory, never the personal working folder:
`python -B packaging/build_native.py --output build-output`. Run `tools/make_share_package.py --verify-dir PATH` to reject
missing, extra or changed release files; the native builder checks listed bytes. The CI workflow is manual and uploads
artifacts; release publication is a separate operation.
