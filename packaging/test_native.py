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
        config.mkdir(exist_ok=True, mode=0o700)
        (Path(temp) / "handoff").mkdir()
        (config / "settings.json").write_text(json.dumps({"home": str(Path(temp) / "handoff")}), encoding="utf-8")
        if sys.platform == "win32":
            result = subprocess.run([str(app.with_name("ClearingsCLI.exe")), "--config-dir", str(config), "status"], check=True, capture_output=True, text=True)
            assert json.loads(result.stdout)["generation"] == 0
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        child = subprocess.Popen([str(app), "--config-dir", str(config), "serve",
                                  "--port", str(port), "--no-browser", "--no-tray"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            # Intel macOS runners can take longer to launch an ad-hoc-signed app.
            deadline = time.monotonic() + 45
            while not (config / "session.json").exists():
                if child.poll() is not None:
                    raise RuntimeError(f"Clearings exited early with code {child.returncode}")
                if time.monotonic() > deadline:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)
                    detail = child.stderr.read().decode("utf-8", errors="replace")[-1000:]
                    raise TimeoutError("Clearings did not create its disposable session within "
                                       f"45 seconds; stderr tail: {detail or '[empty]'}")
                time.sleep(0.05)
            session = json.loads((config / "session.json").read_text(encoding="utf-8"))
            assert session["format"] == "clearings-protected-session-v1" and "token" not in session
            while True:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                        page = response.read()
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.05)
            assert b"appVersion:'0.4.6'" in page
            assert b"window.__CLEARINGS_LOCAL_TOKEN__" not in page
            command_app = app.with_name("ClearingsCLI.exe") if sys.platform == "win32" else app
            reused = subprocess.run([str(command_app), "--config-dir", str(config), "serve",
                                     "--port", str(port), "--no-browser", "--no-tray"],
                                    timeout=10, capture_output=True)
            assert reused.returncode == 0, reused.stderr
            if sys.platform == "win32":
                result = subprocess.run([str(command_app), "--config-dir", str(config), "status"], check=True, capture_output=True, text=True)
                assert json.loads(result.stdout)["generation"] == 0
            refused = subprocess.run([str(app), "--config-dir", str(config), "stop", "--installation", str(Path(temp) / "not-this-program")], timeout=10, capture_output=True)
            assert refused.returncode != 0 and child.poll() is None
            stopped = subprocess.run([str(command_app), "--config-dir", str(config), "stop"], timeout=20)
            assert stopped.returncode == 0
            child.wait(timeout=15)
            print("Bundled Clearings served the 0.4.6 page from disposable settings.")
        finally:
            if child.poll() is None:
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
