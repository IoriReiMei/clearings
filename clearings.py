#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 The Hermit. See LICENSE for the full MIT notice.
"""Start a source checkout, or check it without opening a browser or writing data."""
import sys
sys.dont_write_bytecode = True

import argparse
import importlib.util
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent


def check_setup(root=ROOT):
    if sys.version_info < (3, 10):
        raise ValueError('Clearings needs Python 3.10 or newer. Install Python from https://www.python.org/downloads/.')
    app = root / ('LC_CHECKLIST.html' if (root / 'LC_CHECKLIST.html').is_file() else 'index.html')
    required = [app] + [root / 'tools' / name for name in
                       ('clearings_local.py', 'clearings_commit.py', 'clearings_tray.py')]
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    if missing:
        raise ValueError('Extract the complete source ZIP first. Missing: ' + ', '.join(missing))
    sys.path.insert(0, str(root / 'tools'))
    spec = importlib.util.spec_from_file_location('clearings_setup_check', required[1])
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    config = helper.read_release_config(root)
    return helper, config


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog=
        'Run without options to open Clearings. Additional arguments go to the local helper; '
        'for example: clearings.py serve --no-tray. Use Save and quit in the app to stop it.')
    parser.add_argument('--check', action='store_true', help='Check Python, source files and update configuration; change nothing.')
    options, helper_args = parser.parse_known_args()
    if options.check and helper_args:
        parser.error('--check cannot be combined with helper arguments')
    try:
        helper, config = check_setup()
    except (OSError, ValueError, ImportError, SyntaxError) as exc:
        print('Clearings setup: ' + str(exc), file=sys.stderr)
        return 1
    if options.check:
        print('Clearings source is ready.')
        print('Python: ' + sys.version.split()[0] + ' (no pip packages needed for the app)')
        print('Local address: http://127.0.0.1:' + str(helper.PORT) + '/')
        print('Release checks: ' + (config['updateRepository'] or 'disabled by this distribution'))
        print('Optional AI/MCP setup: docs/CLEARINGS_MCP.md')
        print('No helper started, network contacted, or workspace written.')
        return 0
    try:
        return subprocess.call([sys.executable, '-B', str(ROOT / 'tools/clearings_local.py'),
                                *(helper_args or ['serve'])])
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
