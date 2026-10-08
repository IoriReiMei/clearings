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
# Toolchain review — September 29, 2026

The GitHub workflow now pins these verified official releases. All four Actions
use `runs.using: node24`; their commit pins record the reviewed release bytes.

| Component | Version | Source |
| --- | --- | --- |
| checkout Action | 7.0.1 | https://github.com/actions/checkout/releases/tag/v7.0.1 |
| setup-node Action | 7.0.0 | https://github.com/actions/setup-node/releases/tag/v7.0.0 |
| setup-python Action | 7.0.0 | https://github.com/actions/setup-python/releases/tag/v7.0.0 |
| upload-artifact Action | 7.0.1 | https://github.com/actions/upload-artifact/releases/tag/v7.0.1 |
| Node for tests | 24.21.0, current LTS | https://nodejs.org/en/about/previous-releases |
| Bundled Python | 3.14.7, current stable feature series | https://www.python.org/downloads/release/python-3147/ |
| PyInstaller | 6.22.3 | https://pypi.org/project/pyinstaller/6.22.3/ |
| NSIS | 3.13 | https://nsis.sourceforge.io/Docs/AppendixF.html |

The earlier workflow declared Node 20 Actions and tested with Node 22. Updating
only the test version would not change the Actions' own runtime. Both are now
updated. Node is a development/test tool, not bundled in the Clearings installer.
The source launcher still uses an existing Python installation; this release does
not update machine-wide software.

Hosted Windows 2025, macOS 15 (both architectures) and Ubuntu 22.04 runners are
compatibility targets managed by GitHub. The Linux baseline intentionally keeps
its older supported glibc for portable binaries; a newer OS label is not required
to use current build tools. The workflow validates all four resulting helpers.

Review these pins and upstream support again before the next release. This dated
review is not an automatic updater. Official Python license fallback:
`https://raw.githubusercontent.com/python/cpython/v3.14.7/LICENSE`.
