#!/usr/bin/env python3
# SPDX-License-Identifier: MPL-2.0
"""Build Clearings' bundled helper from an exact public source snapshot.

Run this on each target operating system. It creates no installer and performs
no upload; the platform packagers consume its dist/ output afterward.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.4.2"


def source_files() -> list[Path]:
    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError("The public source manifest is missing or invalid")
    files = []
    for name, digest in sorted(manifest.items()):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != name:
            raise ValueError(f"Unsafe manifest path: {name}")
        path = ROOT / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing public source: {name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Public source differs from manifest: {name}")
        files.append(path)
    if b"appVersion:'0.4.2'" not in (ROOT / "index.html").read_bytes():
        raise ValueError("The public app version is not 0.4.2")
    return files


def write_source_archive(destination: Path, files: list[Path]) -> None:
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files + [ROOT / "MANIFEST.json"]:
            archive.write(path, path.relative_to(ROOT).as_posix())


def copy_runtime_licenses(bundle: Path) -> None:
    python_candidates = [Path(sys.base_prefix) / name for name in
                         ("LICENSE.txt", "LICENSE", "LICENSE.md")]
    python_license = next((path for path in python_candidates if path.is_file()), None)
    if python_license is None:
        raise ValueError("Cannot find this Python runtime's license; refusing an incomplete bundle")
    distribution = metadata.distribution("pyinstaller")
    notices = [entry for entry in distribution.files or []
               if str(entry).replace("\\", "/").endswith(".dist-info/licenses/COPYING.txt")]
    pyinstaller_license = distribution.locate_file(notices[0]) if notices else None
    if pyinstaller_license is None or not Path(pyinstaller_license).is_file():
        raise ValueError("Cannot find the PyInstaller bootloader license")
    shutil.copyfile(python_license, bundle / "PYTHON_LICENSE.txt")
    shutil.copyfile(pyinstaller_license, bundle / "PYINSTALLER_LICENSE.txt")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    files = source_files()
    if args.verify_only:
        print(f"Verified {len(files)} public source files; no build started.")
        return
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Build output is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
               "--onedir", "--name", "Clearings", "--distpath", str(output),
               "--workpath", str(output / "build"), "--specpath", str(output / "spec"),
               "--add-data", str(ROOT / "index.html") + os.pathsep + "."]
    if sys.platform in ("win32", "darwin"):
        command.append("--windowed")
    if sys.platform == "darwin":
        command += ["--osx-bundle-identifier", "org.clearings.app"]
    command.append(str(ROOT / "tools" / "clearings_local.py"))
    subprocess.run(command, check=True)
    bundle = (output / "Clearings.app" / "Contents" / "Resources" if sys.platform == "darwin"
              else output / "Clearings")
    if not bundle.is_dir():
        raise ValueError("PyInstaller did not produce the expected bundle")
    write_source_archive(bundle / "source.zip", files)
    copy_runtime_licenses(bundle)
    if sys.platform == "darwin":
        # PyInstaller ad-hoc signs the .app before these notices are added.
        # Seal the final resource set again; public Developer ID signing and
        # notarization remain a separate release gate.
        app = output / "Clearings.app"
        subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True)
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    print(f"Built {sys.platform} bundle with public source archive: {bundle}")


if __name__ == "__main__":
    main()
