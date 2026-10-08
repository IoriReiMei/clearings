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
"""Wrap the native Mac app in an unsigned review DMG; signing is a later gate."""
from pathlib import Path
import argparse
import platform
import shutil
import subprocess
import tempfile

VERSION = "0.4.6"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    app = args.dist.resolve() / "Clearings.app"
    if not (app / "Contents" / "MacOS" / "Clearings").is_file():
        raise ValueError("Missing native Clearings.app")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    image = output / f"Clearings-{VERSION}-macOS-{platform.machine()}.dmg"
    if image.exists():
        raise ValueError(f"Refusing to replace {image}")
    with tempfile.TemporaryDirectory(prefix="clearings-dmg-") as temp:
        stage = Path(temp)
        shutil.copytree(app, stage / "Clearings.app", symlinks=True)
        (stage / "Applications").symlink_to("/Applications", target_is_directory=True)
        subprocess.run(["hdiutil", "create", "-volname", "Clearings", "-srcfolder",
                        str(stage), "-format", "UDZO", str(image)], check=True)
    print(f"Created unsigned review image: {image}")


if __name__ == "__main__":
    main()
