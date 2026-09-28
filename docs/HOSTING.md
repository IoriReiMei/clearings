<!--
SPDX-License-Identifier: MPL-2.0
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
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
