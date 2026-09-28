#!/usr/bin/env python3
# SPDX-License-Identifier: MPL-2.0
"""Exercise a built Clearings binary with disposable settings and no browser."""
from pathlib import Path
import argparse
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def executable(dist: Path) -> Path:
    if sys.platform == "win32":
        return dist / "Clearings" / "Clearings.exe"
    if sys.platform == "darwin":
        return dist / "Clearings.app" / "Contents" / "MacOS" / "Clearings"
    return dist / "Clearings" / "Clearings"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", required=True, type=Path)
    args = parser.parse_args()
    app = executable(args.dist.resolve())
    if not app.is_file():
        raise ValueError(f"Built Clearings program is missing: {app}")
    licenses = (args.dist.resolve() / "Clearings.app" / "Contents" / "Resources"
                if sys.platform == "darwin" else app.parent)
    for name in ("source.zip", "PYTHON_LICENSE.txt", "PYINSTALLER_LICENSE.txt"):
        if not (licenses / name).is_file():
            raise ValueError(f"Native bundle lacks {name}")
    with tempfile.TemporaryDirectory(prefix="clearings-native-check-") as temp:
        config = Path(temp) / "settings"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        child = subprocess.Popen([str(app), "--config-dir", str(config), "serve",
                                  "--port", str(port), "--no-browser"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 15
            while not (config / "session.json").exists():
                if child.poll() is not None:
                    raise RuntimeError(f"Clearings exited early with code {child.returncode}")
                if time.monotonic() > deadline:
                    raise TimeoutError("Clearings did not create its disposable session")
                time.sleep(0.05)
            session = json.loads((config / "session.json").read_text(encoding="utf-8"))
            headers = {"X-Clearings-Token": session["token"]}
            identity_request = urllib.request.Request(f"http://127.0.0.1:{port}/api/identity",
                                                      headers=headers)
            while True:
                try:
                    with urllib.request.urlopen(identity_request, timeout=1) as response:
                        identity = json.load(response)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.05)
            assert identity["channel"] == "release", identity
            assert identity["config"] == str(config.resolve()), identity
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
                page = response.read()
            assert b"appVersion:'0.4.2'" in page
            assert b"window.__CLEARINGS_LOCAL_TOKEN__" in page
            print("Bundled Clearings served the 0.4.2 page from disposable settings.")
        finally:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
            if child.stderr:
                child.stderr.close()


if __name__ == "__main__":
    main()
