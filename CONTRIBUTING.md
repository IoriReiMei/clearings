<!-- SPDX-License-Identifier: MIT -->
<!-- Copyright (c) 2026 The Hermit. See LICENSE for the full MIT notice. -->
# Work on a Clearings fork

Start with [Run Clearings from source](docs/QUICKSTART.md). A clean checkout runs
directly; there is no frontend build step. Set `clearings.json` to your own
release repository, or `null` while you are not publishing releases.

## Find the source

- `index.html` contains the page, styles and browser logic. The maintainer's
  working tree calls this file `LC_CHECKLIST.html`; the public packager renames it.
- `tools/clearings_local.py` provides the local helper and release checks.
- `tools/clearings_commit.py`, `tools/contract.cjs` and `tools/merge.cjs` implement
  corresponding Python/JavaScript validation and merging rules. Keep them aligned.
- `tools/clearings_mcp.py` is the optional local MCP adapter.
- `templates/` holds fictional release-plan templates. After editing these,
  run `python tools/sync_templates.py --write` and review the embedded page copy.

Keep descriptions, response/review fields, completion attribution and saved data
compatible. Use fictional fixtures when reporting or testing bugs.

The source folder's `AGENTS.md` leads assistants to `AI_START_HERE.md`. The MCP
guide tool serves sections of that same file and the detailed
`AI_CHECKLIST_GUIDE.md`, so keep them current when changing user-facing behavior.
If you rename a topic heading, update `GUIDE_TOPICS` in `tools/clearings_mcp.py`.
Update its `GUIDE_REVISION` with a guidance revision. With the optional SDK
installed, run `python -B -m unittest discover -s tests -p test_clearings_mcp.py`
to check discovery, topics and the collaboration workflow using fictional data.

## Run focused checks

Use the Python command available on your system (`python`, `python3`, or `py -3`).
The Python tests use the standard library; MCP-specific tests may skip without
the optional SDK. JavaScript tests additionally need a supported Node.js LTS.

```text
python clearings.py --check
python -B -m unittest discover -s tests -p test_clearings_source_setup.py
python -B -m unittest discover -s tests -p test_clearings_updates.py
node tests/contract.test.cjs
node tests/merge.test.cjs
```

The **Source checks** GitHub Actions workflow runs these checks on Windows,
macOS and Linux, with Python 3.10 and 3.14. It uses read-only repository access,
does not require secrets or an earlier release, and never publishes. Fork owners
may need to enable Actions in GitHub. These are verification targets, not a
claim that every platform was manually tested. Native installers have a separate
manual build workflow and their own verification requirements.

## Package only intended source

From the source root, create a new output path outside the checkout:

```text
python -B tools/make_share_package.py --output ../clearings-source-review.zip
python -m zipfile -e ../clearings-source-review.zip ../clearings-source-review
python -B tools/make_share_package.py --verify-dir ../clearings-source-review
```

The explicit allowlist includes application source, docs, tests and fictional
examples. It excludes personal checklists, settings, session tokens, recovery
backups and repository history. Never zip the development folder recursively.
The generated manifest describes the exact package bytes; editing a fork makes
its old manifest stale. Generate a fresh package and verify that extracted
package instead of weakening the checks or hand-editing the manifest.

Packaging materializes your configured release source in the standalone page
and includes it in native build inputs. Publishing is a separate decision.
The current package recipes prepare Clearings 0.4.7. Before
giving a fork its own version, update and review the page, helper, packager, native recipes, release
notes and version checks together. Merely setting updateRepository does not
change version comparisons. Native builder instructions are in
[packaging/README.md](packaging/README.md).

Keep the MIT notices and the separate third-party notices with the corresponding
files; see [LICENSE_SCOPE.md](LICENSE_SCOPE.md). Do not include real workspace
exports, session files or access tokens in contributions or bug reports.
