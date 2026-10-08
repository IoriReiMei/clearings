#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# MIT License
#
# Copyright (c) 2026 The Hermit
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""Create a single-file per-user Linux installer from the native bundle."""
from pathlib import Path
import argparse
import base64
import io
import os
import tarfile

ROOT = Path(__file__).resolve().parent
VERSION = "0.4.6"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    bundle = args.dist.resolve() / "Clearings"
    if any(not (bundle / name).is_file() for name in
           ("Clearings", "source.zip", "PYTHON_LICENSE.txt", "PYINSTALLER_LICENSE.txt")):
        raise ValueError("Missing native program, public source, or runtime license")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    installer = output / f"Clearings-Install-{VERSION}-Linux-x64.run"
    if installer.exists():
        raise ValueError(f"Refusing to replace {installer}")
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        archive.add(bundle, arcname="Clearings", recursive=True)
    script = (ROOT / "linux" / "install.sh.in").read_text(encoding="utf-8")
    script = script.replace("@VERSION@", VERSION)
    if not script.endswith("__CLEARINGS_PAYLOAD__\n"):
        raise ValueError("Installer template marker is missing")
    encoded = base64.b64encode(payload.getvalue())
    with installer.open("xb") as target:
        target.write(script.encode("utf-8"))
        for offset in range(0, len(encoded), 76):
            target.write(encoded[offset:offset + 76] + b"\n")
    os.chmod(installer, 0o755)
    print(f"Created per-user Linux installer: {installer}")


if __name__ == "__main__":
    main()
