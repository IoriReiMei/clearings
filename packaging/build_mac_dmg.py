#!/usr/bin/env python3
# SPDX-License-Identifier: MPL-2.0
"""Wrap the native Mac app in an unsigned review DMG; signing is a later gate."""
from pathlib import Path
import argparse
import platform
import shutil
import subprocess
import tempfile

VERSION = "0.4.5"


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
