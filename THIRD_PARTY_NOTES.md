<!--
SPDX-License-Identifier: MPL-2.0
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->
# Clearings — known inputs and review boundaries

Clearings was developed through human-directed design and substantial AI-generated
implementation. This note describes observable release inputs, not a claim that
every generated line has been proven unique.

## Runtime and assets

The release app contains inline HTML, CSS and JavaScript. It does not import an
external script/stylesheet, runtime UI package, icon library or downloadable font.
The grip dots are CSS elements; font names refer to system fonts, not bundled
font files. The screenshot is a capture of this app with its supplied fictional
examples, not an image of private checklist data.

Native browser APIs and familiar interface conventions are used. Their use is
not presented as exclusive invention. No claim of legal clearance of the code,
visual design or the name Clearings is made here.

## Separately installed development tools

| Tool | Use in this project | Distributed in the ZIP? |
| --- | --- | --- |
| Playwright for Python | Working-only legacy browser regression driver | No. Its tests and browser binaries are not in this ZIP. |
| Playwright for Node.js | Optional local-handoff browser regression driver | No. The new browser test imports it; the package and browser binaries are installed separately. |
| Python 3.10+ | Packaging and the optional local handoff helper | No. The standalone page needs none. |
| Node.js | Structural validation and contract/release tests | No. |

Playwright for Python's upstream license is Apache-2.0. Its upstream license and
project are at https://github.com/microsoft/playwright-python and
https://raw.githubusercontent.com/microsoft/playwright-python/main/LICENSE
(checked September 26, 2026). This note does not replace upstream notices or
change the terms of any separately installed tools.

Playwright for Node.js is likewise used only as a separately installed test
dependency. Its upstream project and Apache-2.0 license are at
https://github.com/microsoft/playwright and
https://github.com/microsoft/playwright/blob/main/LICENSE
(checked September 27, 2026). No Playwright package or browser binary is
included in the intended Clearings release.

The standard MPL text in LICENSE is reproduced as a license, not attributed to
the Clearings author. See LICENSE_SCOPE.md for its source.

## Scope of inspection

The release checks inspect file structure, notices and functionality. They are
not a source-similarity search, a completed third-party provenance audit, or legal
advice. This release does not assert that an independent audit has occurred.

For a concrete attribution concern, identify the local file and passage/asset,
the suspected upstream work and a link or other matching evidence. Preserve
existing notices while investigating. Raise it with whoever supplied your copy;
if a public repository is later created, its issue tracker can also collect
specific reports. Do not post private account information or secrets in a report.

## Browser-autosave update (0.3)

No new runtime library, UI template, icon, font, or external asset was added.
The in-memory IndexedDB adapter under tests/ is a narrow test fixture authored
for these checks, not a production storage implementation and not proof of native
persistence. Playwright remains a separately installed Apache-2.0 testing tool.
An attempted installation of extra test tooling did not complete; no such package
was included in the app or release.

Browser API documentation consulted for this update (not copied as a UI template):
- https://developer.mozilla.org/en-US/docs/Web/API/IndexedDB_API/Using_IndexedDB
- https://developer.mozilla.org/en-US/docs/Web/API/IDBTransaction/complete_event
- https://developer.mozilla.org/en-US/docs/Web/API/StorageManager/persist
- https://developer.mozilla.org/en-US/docs/Web/API/Storage_API/Storage_quotas_and_eviction_criteria

This scoped dependency observation is not a new source-similarity or legal audit.

## Local handoff update (0.4.1)

The optional loopback helper uses Python's standard library. The browser page
still contains its own inline CSS and JavaScript and adds no bundled framework,
font, icon package, or image. `docs/preview.png` is unchanged from 0.4.0.
`tests/local_handoff_browser.test.cjs` uses the separately installed Node.js
Playwright package noted above. A dated, bounded source comparison is retained
in the development records; it is not an infringement clearance.

## Installer builds (0.4.3)

The optional native installer recipes use PyInstaller to bundle Python and the
standard-library helper. Windows setup compilation uses NSIS; Mac DMG creation
uses Apple's `hdiutil`; Linux uses shell, tar and base64 for a per-user installer.
Those tools are build-time inputs, not libraries imported by the HTML app.
Native executables will additionally contain a Python runtime and PyInstaller
bootloader. The build recipe copies their license texts beside the program and
refuses a bundle if either is missing. Before public distribution, audit the
complete collected dependency set and platform installer notices. These sources alone are
not a completed binary-license audit or a signed release.

When an installed runtime lacks a separate license file, the 0.4.3 build recipe
accepts the official Python 3.14.7 fallback at
`packaging/licenses/PYTHON-3.14-LICENSE.txt`, copied from
https://raw.githubusercontent.com/python/cpython/v3.14.7/LICENSE
(SHA-256 `b0e25a78cffb43f4d92de8b61ccfa1f1f98ecbc22330b54b5251e7b6ba010231`).
A different runtime without its own license file stops for review. The older
`PYTHON-3.12-LICENSE.txt` remains as a reference for previous source-build users;
it is not the runtime license fallback for 0.4.3. Both are third-party legal
text under their own terms, not Clearings' MPL-2.0.
