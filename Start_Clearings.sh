#!/bin/sh
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 The Hermit. See LICENSE for the full MIT notice.
# Run with: sh Start_Clearings.sh [--check]
set -eu
clearings_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -n "${CLEARINGS_PYTHON:-}" ]; then
    exec "$CLEARINGS_PYTHON" -B "$clearings_dir/clearings.py" "$@"
fi
if command -v python3 >/dev/null 2>&1; then
    exec python3 -B "$clearings_dir/clearings.py" "$@"
fi
printf '%s\n' 'Clearings needs Python 3.10 or newer. Install Python, then run this launcher again.' >&2
printf '%s\n' 'Setup guide: docs/QUICKSTART.md' >&2
exit 1
