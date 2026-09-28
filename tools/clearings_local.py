# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Small loopback-only bridge for the optional one-click Clearings workflow.

The browser's IndexedDB remains the live workspace. This helper owns one
user-selected handoff JSON; agents use the CLI rather than editing it in place.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import webbrowser

MAX_BYTES = 16 * 1024 * 1024
FILE_NAME = "clearings_handoff.json"
VERSION = "0.4.2"
# The working helper already owns 8765 and its existing browser workspace.
# Keep it there; installed/public Clearings has a separate, stable origin.
ROOT = (Path(sys._MEIPASS) if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent.parent)
APP = ROOT / "LC_CHECKLIST.html"
if not APP.exists():
    APP = ROOT / "index.html"
CHANNEL = "release" if APP.name == "index.html" else "working"
PORT = 18765 if CHANNEL == "release" else 8765


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def config_dir(override: str | None = None) -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local"))
    name = "Clearings-Release" if CHANNEL == "release" else "Clearings"
    return Path(override or os.environ.get("CLEARINGS_CONFIG_DIR") or base / name).resolve()


def program_identity(bridge: "Bridge") -> dict:
    """Only a server for these exact app bytes and this installation may be reused."""
    program = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else ROOT.resolve()
    return {"channel": CHANNEL, "appSha256": hashlib.sha256(APP.read_bytes()).hexdigest(),
            "program": str(program), "config": str(bridge.root.resolve())}


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    if path.stat().st_size > MAX_BYTES:
        raise ValueError(f"{path.name} exceeds 16 MB")
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("Handoff exceeds 16 MB; nothing was written")
    fd, temp_name = tempfile.mkstemp(prefix=".clearings-", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


@contextmanager
def file_lock(path: Path):
    """One writer across the local helper and its command-line tools."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class Bridge:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.config_path = root / "settings.json"
        self.lock_path = root / "handoff.lock"
        if not self.config_path.exists():
            if root != config_dir():
                home = root / "home"
            else:
                home = Path.home() / "Documents" / "Clearings"
                if CHANNEL == "release":
                    home = home / "Installed"
            home.mkdir(parents=True, exist_ok=True)
            atomic_json(self.config_path, {"home": str(home.resolve())})

    def home(self) -> Path:
        settings = load_json(self.config_path)
        path = Path(settings["home"]).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("The configured Clearings home folder is unavailable")
        return path

    def handoff_path(self) -> Path:
        return self.home() / FILE_NAME

    def read(self):
        packet = load_json(self.handoff_path())
        if packet is None:
            return {"format": "clearings-local-handoff", "schemaVersion": 1,
                    "libraryId": None, "snapshot": None, "snapshotAt": None,
                    "generation": 0, "proposals": [], "receipts": []}
        if packet.get("format") != "clearings-local-handoff" or packet.get("schemaVersion") != 1:
            raise ValueError("Unrecognized handoff file; it was not changed")
        return packet

    def change(self, edit):
        with file_lock(self.lock_path):
            packet = self.read()
            result = edit(packet)
            if result is not None:
                atomic_json(self.handoff_path(), packet)
            return result

    def set_home(self, text: str):
        candidate = Path(text).expanduser().resolve()
        if not candidate.is_dir():
            raise ValueError("Choose an existing folder for Clearings home")
        with file_lock(self.lock_path):
            old = self.read()
            if any(p.get("status") == "pending" for p in old["proposals"]):
                raise ValueError("Resolve or export pending changes before changing home folders")
            target = candidate / FILE_NAME
            if target.exists():
                existing = load_json(target)
                if existing.get("format") != "clearings-local-handoff":
                    raise ValueError("That folder contains a different handoff file")
                if (existing.get("libraryId") not in (None, old.get("libraryId")) or
                        existing.get("generation", 0) > old.get("generation", 0)):
                    raise ValueError("That folder has another or newer library; nothing was changed")
            atomic_json(self.config_path, {"home": str(candidate)})
        return str(candidate)

    def sync(self, workspace: dict, generation: int, expected_generation: int | None = None):
        if workspace.get("format") not in ("checklist-studio-workspace", "local-companion-checklist-workspace"):
            raise ValueError("Expected a Clearings workspace snapshot")
        library_id = workspace.get("index", {}).get("libraryId")
        if not isinstance(library_id, str) or not isinstance(generation, int) or generation < 1:
            raise ValueError("Invalid workspace identity or generation")

        def edit(packet):
            if expected_generation is not None and packet["generation"] != expected_generation:
                raise ValueError("The handoff generation changed in another browser; it was not overwritten")
            if packet["libraryId"] not in (None, library_id):
                raise ValueError("This home folder belongs to another checklist library. Change home in Settings; neither copy was overwritten")
            if packet["libraryId"] == library_id and generation < packet["generation"]:
                raise ValueError("The browser offered an older generation; the handoff was not rolled back")
            if (packet["libraryId"] == library_id and generation == packet["generation"] and
                    packet["snapshot"] is not None and packet["snapshot"] != workspace):
                raise ValueError("Another browser supplied different content at this generation; the handoff was not overwritten")
            packet["libraryId"] = library_id
            packet["snapshot"] = workspace
            packet["snapshotAt"] = now()
            packet["generation"] = generation
            return {"generation": generation, "snapshotAt": packet["snapshotAt"]}
        return self.change(edit)

    def propose(self, base: dict, incoming: dict, actor: str, note: str = ""):
        if not isinstance(base, dict) or not isinstance(incoming, dict) or not isinstance(actor, str):
            raise ValueError("A proposed change needs its base, new document, and display name")
        actor = actor.strip()[:80]
        if not actor:
            raise ValueError("A proposed change needs its base, new document, and display name")
        doc_id = base.get("documentId")
        if not doc_id or incoming.get("documentId") != doc_id:
            raise ValueError("The base and proposed checklist IDs differ")
        base_items = {item.get("id") for item in base.get("model", {}).get("items", [])}
        incoming_items = {item.get("id") for item in incoming.get("model", {}).get("items", [])}
        if base_items - incoming_items:
            raise ValueError("Removing existing items through the handoff is not supported")

        def edit(packet):
            snapshot = packet["snapshot"]
            if snapshot is None or not any(d.get("documentId") == doc_id for d in snapshot["documents"]):
                raise ValueError("This checklist is not in the latest browser snapshot")
            if len([p for p in packet["proposals"] if p["status"] == "pending"]) >= 100:
                raise ValueError("Too many pending proposals")
            proposal = {"id": uuid.uuid4().hex, "documentId": doc_id,
                        "actor": actor, "note": str(note)[:500], "createdAt": now(),
                        "base": base, "incoming": incoming, "status": "pending",
                        "suggestedChoices": {}}
            packet["proposals"].append(proposal)
            packet["proposals"] = packet["proposals"][-150:]
            return {"proposalId": proposal["id"], "documentId": doc_id}
        return self.change(edit)

    def decide(self, proposal_id: str, choices: dict, actor: str):
        if not isinstance(choices, dict) or not actor.strip():
            raise ValueError("Resolution choices and a display name are required")
        if any(value not in ("browser", "json") for value in choices.values()):
            raise ValueError("Resolution choices must be browser or json")

        def edit(packet):
            proposal = next((p for p in packet["proposals"] if p["id"] == proposal_id), None)
            if proposal is None or proposal["status"] != "pending":
                raise ValueError("Pending proposal not found")
            proposal["suggestedChoices"] = {"actor": actor.strip()[:80], "choices": choices, "at": now()}
            return {"proposalId": proposal_id, "choices": len(choices)}
        return self.change(edit)

    def mark(self, proposal_id: str, status: str, summary: str, actor: str):
        if status not in ("applied", "already-current", "dismissed"):
            raise ValueError("Invalid proposal outcome")

        def edit(packet):
            proposal = next((p for p in packet["proposals"] if p["id"] == proposal_id), None)
            if proposal is None or proposal["status"] != "pending":
                raise ValueError("Pending proposal not found")
            proposal["status"] = status
            receipt = {"proposalId": proposal_id, "documentId": proposal["documentId"],
                       "status": status, "at": now(), "actor": actor.strip()[:80],
                       "summary": str(summary)[:500]}
            packet["receipts"].append(receipt)
            packet["receipts"] = packet["receipts"][-150:]
            return receipt
        return self.change(edit)


def handler_for(bridge: Bridge, token: str, port: int):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def send(self, status: int, value=None, content_type="application/json"):
            raw = (json.dumps(value, ensure_ascii=False).encode("utf-8") if content_type == "application/json"
                   else value)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(raw)

        def authorized(self):
            return self.headers.get("X-Clearings-Token") == token

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                html = APP.read_text(encoding="utf-8")
                marker = "<!-- CLEARINGS_LOCAL_BRIDGE -->"
                if marker not in html:
                    self.send(500, {"error": "Local bridge marker missing from app"})
                    return
                # The portable file cannot contact anything. Only the served copy
                # may speak to its own loopback origin for the handoff API.
                html = html.replace("connect-src 'none'", "connect-src 'self'")
                html = html.replace(marker, "<script>window.__CLEARINGS_LOCAL_TOKEN__=" + json.dumps(token) + ";</script>")
                self.send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/favicon.ico":
                self.send(204, b"", "image/x-icon")
                return
            if not self.authorized():
                self.send(403, {"error": "Local bridge token required"})
                return
            try:
                if path == "/api/state":
                    packet = bridge.read()
                    self.send(200, {"home": str(bridge.home()), "file": str(bridge.handoff_path()),
                                    "generation": packet["generation"], "snapshotAt": packet["snapshotAt"],
                                    "pending": sum(p["status"] == "pending" for p in packet["proposals"])})
                elif path == "/api/identity":
                    self.send(200, program_identity(bridge))
                elif path == "/api/handoff":
                    self.send(200, bridge.read())
                else:
                    self.send(404, {"error": "Not found"})
            except (ValueError, OSError, KeyError) as exc:
                self.send(409, {"error": str(exc)})

        def do_POST(self):
            if not self.authorized() or self.headers.get("Origin") not in (None, f"http://127.0.0.1:{port}"):
                self.send(403, {"error": "Local bridge authorization failed"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                self.send(415, {"error": "Expected JSON"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 0 or size > MAX_BYTES:
                    self.send(413, {"error": "Request exceeds 16 MB"})
                    return
                data = json.loads(self.rfile.read(size))
                path = self.path.split("?", 1)[0]
                if path == "/api/settings":
                    answer = {"home": bridge.set_home(data["home"])}
                elif path == "/api/sync":
                    answer = bridge.sync(data["workspace"], data["generation"], data.get("expectedGeneration"))
                elif path == "/api/propose":
                    answer = bridge.propose(data["base"], data["incoming"], data["actor"], data.get("note", ""))
                elif path == "/api/decide":
                    answer = bridge.decide(data["proposalId"], data["choices"], data["actor"])
                elif path == "/api/mark":
                    answer = bridge.mark(data["proposalId"], data["status"], data.get("summary", ""), data["actor"])
                else:
                    self.send(404, {"error": "Not found"})
                    return
                self.send(200, answer)
            except (ValueError, OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
                self.send(409, {"error": str(exc)})
    return Handler


class LocalServer(ThreadingHTTPServer):
    # HTTPServer's SO_REUSEADDR can admit a second listener on Windows. A
    # shortcut must never appear to start successfully while another copy owns
    # the same browser origin.
    allow_reuse_address = False

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def run_server(bridge: Bridge, port: int, open_browser: bool):
    session_path = bridge.root / "session.json"
    previous = load_json(session_path, {})
    if previous.get("port") == port and previous.get("token"):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/identity",
                                     headers={"X-Clearings-Token": previous["token"]})
        try:
            with urllib.request.urlopen(req, timeout=1) as response:
                identity = json.load(response)
                if identity != program_identity(bridge):
                    raise RuntimeError("Another Clearings copy or version is running on this address. "
                                       "Close that Clearings helper before opening this one; no data was changed.")
                if open_browser:
                    webbrowser.open(f"http://127.0.0.1:{port}/")
                return
        except (urllib.error.URLError, TimeoutError, ValueError):
            pass
    token = secrets.token_urlsafe(32)
    try:
        server = LocalServer(("127.0.0.1", port), handler_for(bridge, token, port))
    except OSError as exc:
        raise RuntimeError(f"Clearings cannot use 127.0.0.1:{port}. Close the other program "
                           "using this address, then reopen Clearings; no data was changed.") from exc
    atomic_json(session_path, {"port": port, "token": token, "pid": os.getpid(), "startedAt": now()})
    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{port}/")
    if sys.stdout is not None:
        print(f"Clearings local helper ready on 127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main():
    if sys.platform == "darwin":
        # Finder may append this process serial number when opening an .app.
        sys.argv[:] = [sys.argv[0]] + [arg for arg in sys.argv[1:] if not arg.startswith("-psn_")]
    # A packaged app is launched by a shortcut without command-line arguments.
    if len(sys.argv) == 1:
        sys.argv.append("serve")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"Clearings {VERSION}")
    parser.add_argument("--config-dir", help="Test/alternate local helper settings directory")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start the local helper and open Clearings")
    serve.add_argument("--port", type=int, default=PORT)
    serve.add_argument("--no-browser", action="store_true")
    sub.add_parser("status", help="Show handoff state without checklist contents")
    sub.add_parser("snapshot", help="Print the last browser-saved workspace JSON")
    propose = sub.add_parser("propose", help="Submit a full-document edit for review")
    propose.add_argument("--base", required=True, type=Path)
    propose.add_argument("--incoming", required=True, type=Path)
    propose.add_argument("--actor", required=True)
    propose.add_argument("--note", default="")
    decide = sub.add_parser("decide", help="Suggest choices for listed conflicts")
    decide.add_argument("proposal_id")
    decide.add_argument("--choices", required=True, type=Path)
    decide.add_argument("--actor", required=True)
    args = parser.parse_args()
    bridge = Bridge(config_dir(args.config_dir))
    if args.command == "serve":
        run_server(bridge, args.port, not args.no_browser)
    elif args.command == "status":
        packet = bridge.read()
        print(json.dumps({"home": str(bridge.home()), "snapshotAt": packet["snapshotAt"],
                          "generation": packet["generation"], "libraryId": packet["libraryId"],
                          "pending": [{k: p[k] for k in ("id", "documentId", "actor", "createdAt")}
                                      for p in packet["proposals"] if p["status"] == "pending"],
                          "recentReceipts": packet["receipts"][-5:]}, indent=2))
    elif args.command == "snapshot":
        print(json.dumps(bridge.read()["snapshot"], ensure_ascii=False, indent=2))
    elif args.command == "propose":
        print(json.dumps(bridge.propose(load_json(args.base), load_json(args.incoming), args.actor, args.note)))
    elif args.command == "decide":
        print(json.dumps(bridge.decide(args.proposal_id, load_json(args.choices), args.actor)))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if sys.stderr is not None:
            print(f"Clearings local helper: {exc}", file=sys.stderr)
        if getattr(sys, "frozen", False) or sys.executable.lower().endswith("pythonw.exe"):
            try:
                report = config_dir() / "last_launch_error.txt"
                report.parent.mkdir(parents=True, exist_ok=True)
                report.write_text(f"{now()}\n{exc}\n", encoding="utf-8")
            except OSError:
                pass
            try:
                if os.name == "nt":
                    import ctypes
                    ctypes.windll.user32.MessageBoxW(0, str(exc), "Clearings could not start", 0x10)
                elif sys.platform == "darwin":
                    subprocess.run(["osascript", "-e", "display alert \"Clearings could not start\" message "
                                    + json.dumps(str(exc))], timeout=5, check=False)
                elif shutil.which("zenity"):
                    subprocess.Popen(["zenity", "--error", "--title=Clearings could not start",
                                      "--text=" + str(exc)])
            except Exception:
                pass
        raise
