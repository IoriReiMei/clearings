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
# Optional static hosting (GitHub Pages)

No deployment is performed by this release.

1. Create a separate repository containing only the extracted clean release.
   `index.html`, `README.md`, and `LICENSE` belong at its root.
2. In the repository's Settings → Pages, choose Deploy from a branch, then the
   intended branch and root folder. Save and wait for GitHub to report its URL.
3. Use that stable HTTPS URL. Do the native smoke check on the browser you intend
   to use before recommending it to someone else.

GitHub Pages serves the app; the app keeps workspace data in each user's browser.
There is no checklist server, account sync, analytics or app-managed upload.
GitHub still handles normal page requests. Do not publish your private data or
turn an unrelated private working repository public to host the app.

Keep the site address stable. A different origin or app directory can have a
separate browser database. Export JSON before moving a workspace to a new address.
A `.nojekyll` file is included for plain static hosting. Offline page caching is
not included in this edition. Ordinary browser cache is not an offline guarantee.

Official setup instructions (consulted 2026-09-26):
https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site
