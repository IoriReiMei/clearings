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
"""Small loopback-only bridge for the optional one-click Clearings workflow.

The browser's IndexedDB remains the live workspace. This helper owns one
user-selected handoff JSON; agents use the CLI rather than editing it in place.
"""
from __future__ import annotations

import argparse
import ast
import base64
import binascii
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import select
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser

from clearings_commit import merge_documents, validate_document, stamp_attribution
from clearings_tray import WindowsTray, WindowsStartup

MAX_BYTES = 16 * 1024 * 1024
MAX_HANDOFF_BYTES = 64 * 1024 * 1024
REQUEST_DEADLINE = 10.0
MAX_HANDLERS = 8
BOOTSTRAP_SECONDS = 30.0
FILE_NAME = "clearings_handoff.json"
VERSION = "0.4.7"
WINDOWS_TRAY = os.name == "nt"
# The working helper already owns 8765 and its existing browser workspace.
# Keep it there; installed/public Clearings has a separate, stable origin.
ROOT = (Path(sys._MEIPASS) if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent.parent)
APP = ROOT / "LC_CHECKLIST.html"
if not APP.exists():
    APP = ROOT / "index.html"
CHANNEL = "release" if APP.name == "index.html" else "working"
PORT = 18765 if CHANNEL == "release" else 8765
# Capture the working helper's code at process start. Its page is intentionally
# read live, but a changed server implementation needs a fresh process.
PROGRAM = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else ROOT.resolve()
if getattr(sys, "frozen", False) and PROGRAM.name == "ClearingsCLI.exe":
    PROGRAM = PROGRAM.with_name("Clearings.exe")
HELPER_SHA256 = (hashlib.sha256(PROGRAM.read_bytes()).hexdigest() if getattr(sys, "frozen", False)
                 else hashlib.sha256(b"".join(Path(__file__).with_name(name).read_bytes()
                     for name in ("clearings_local.py", "clearings_commit.py", "clearings_tray.py"))).hexdigest())
APP_SHA256 = hashlib.sha256(APP.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def retain_proposals(proposals):
    """Keep all history until an exact preimage has been archived."""
    return proposals


def stop_legacy_windows_process(pid, executable):
    """Compatibility for old helpers without shutdown: verify the OS image path."""
    if os.name != "nt" or type(pid) is not int or pid <= 0:
        raise RuntimeError("Close the earlier Clearings helper before updating this installation.")
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000 | 0x0001 | 0x00100000, False, pid)
    if not handle:
        raise RuntimeError("Cannot verify the earlier Clearings process; close it before updating.")
    try:
        buffer = ctypes.create_unicode_buffer(32768);length = wintypes.DWORD(len(buffer))
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
            raise RuntimeError("Cannot verify the earlier Clearings executable")
        if os.path.normcase(str(Path(buffer.value).resolve())) != os.path.normcase(str(Path(executable).resolve())):
            raise RuntimeError("The saved process belongs to another program; it was not stopped")
        if not kernel.TerminateProcess(handle, 0) or kernel.WaitForSingleObject(handle, 10000) != 0:
            raise RuntimeError("The earlier Clearings process did not stop")
    finally:
        kernel.CloseHandle(handle)


def stop_server(bridge, *, installation=None):
    """Stop only a proved helper for the exact installed program."""
    session_path = bridge.root / "session.json"
    if not session_path.exists():
        return False
    try:
        session = load_private_session(session_path)
    except RuntimeError:
        outer = load_json(session_path, {})
        if outer.get("format") == "clearings-protected-session-v1":
            raise
        old_port = outer.get("port")
        if type(old_port) is int and 1 <= old_port <= 65535 and _listener_present(old_port):
            raise RuntimeError("Close the earlier Clearings helper manually before updating; no files were changed.")
        return False
    port = session["port"]
    if not 1 <= port <= 65535:
        raise RuntimeError("Invalid protected Clearings port")
    expected = program_identity(bridge)
    if installation and session["identity"].get("program") != str(Path(installation).resolve()):
        raise RuntimeError("A different Clearings installation owns this address; close it before updating.")
    if session["identity"] != expected:
        raise RuntimeError("An earlier Clearings version needs manual closure before updating; no files were changed.")
    if not verify_listener(session, bridge, port):
        return False
    authenticated_control(session, "shutdown", port)
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
                probe.listen(1)
                return True
            except OSError:
                time.sleep(.1)
    raise RuntimeError("The helper has not released its address; no files were changed.")


def config_dir(override: str | None = None) -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local"))
    name = "Clearings-Release" if CHANNEL == "release" else "Clearings"
    return Path(override or os.environ.get("CLEARINGS_CONFIG_DIR") or base / name).resolve()


def windows_startup(root: Path, port: int):
    """Describe this exact copy's quiet sign-in command; do not register it here."""
    if not 1 <= port <= 65535:
        raise ValueError("Choose a valid Clearings port for Windows startup")
    root = root.resolve()
    default_base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local"))
    default_root = (default_base / ("Clearings-Release" if CHANNEL == "release" else "Clearings")).resolve()
    if getattr(sys, "frozen", False):
        executable = PROGRAM
        command = [str(executable)]
        required = [executable]
    else:
        executable = Path(sys.executable).resolve().with_name("pythonw.exe")
        script = Path(__file__).resolve()
        command = [str(executable), "-B", str(script)]
        required = [executable, script]
    # An inherited development override may not exist at the next sign-in.
    # Carry it explicitly rather than silently opening a different workspace.
    if root != default_root:
        command += ["--config-dir", str(root)]
    command += ["serve", "--no-browser"]
    if port != PORT:
        command += ["--port", str(port)]
    name = "Clearings" if CHANNEL == "release" else "Clearings working"
    if root != default_root or port != PORT:
        identity = os.path.normcase(str(root)) + ":" + str(port)
        name += " " + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return WindowsStartup(name=name, command=subprocess.list2cmdline(command),
                          required_files=[*required, root / "settings.json"])


def program_identity(bridge: "Bridge") -> dict:
    """Only a server for these exact app bytes and this installation may be reused."""
    program = PROGRAM
    identity = {"channel": CHANNEL, "appSha256": APP_SHA256,
                "program": str(program), "config": str(bridge.root.resolve())}
    if HELPER_SHA256 is not None:
        identity["helperSha256"] = HELPER_SHA256
    return identity


def control_mac(secret: str, purpose: str, challenge: str, identity: dict,
                port: int, extra: str = "") -> str:
    """Domain-separated proof for one exact helper, address and fresh request."""
    message = json.dumps([purpose, challenge, identity, port, extra],
                         ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    """Bind the complete Windows session to this OS account, with no UI."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    source = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    function.restype = wintypes.BOOL
    function.argtypes = ([ctypes.POINTER(Blob), wintypes.LPCWSTR] if protect else
                         [ctypes.POINTER(Blob), ctypes.POINTER(wintypes.LPWSTR)]) + [
                             ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                             wintypes.DWORD, ctypes.POINTER(Blob)]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(incoming), None, None, None, None, 1,
                    ctypes.byref(outgoing)):
        raise OSError(ctypes.get_last_error(), "Cannot protect or read the private Clearings session")
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel.LocalFree(ctypes.cast(outgoing.data, ctypes.c_void_p))


def _private_posix_path(path: Path) -> None:
    for item in (path.parent, path):
        if item.is_symlink() or item.stat().st_uid != os.getuid() or item.stat().st_mode & 0o077:
            raise RuntimeError("Clearings session requires an owner-private config folder and file")


def write_private_session(path: Path, session: dict) -> None:
    raw = json.dumps(session, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if os.name == "nt":
        payload = base64.b64encode(_dpapi(raw, protect=True)).decode("ascii")
    else:
        if path.parent.is_symlink() or path.parent.stat().st_uid != os.getuid() or path.parent.stat().st_mode & 0o077:
            raise RuntimeError("Clearings config folder must be owner-private before serving")
        payload = base64.b64encode(raw).decode("ascii")
    atomic_json(path, {"format": "clearings-protected-session-v1", "payload": payload})
    if os.name != "nt":
        _private_posix_path(path)


def load_private_session(path: Path):
    if not path.exists():
        return None
    outer = load_json(path, {})
    if outer.get("format") != "clearings-protected-session-v1" or not isinstance(outer.get("payload"), str):
        raise RuntimeError("Earlier Clearings session cannot be verified; close its helper manually")
    if os.name != "nt":
        _private_posix_path(path)
    try:
        raw = base64.b64decode(outer["payload"], validate=True)
        data = json.loads(_dpapi(raw, protect=False) if os.name == "nt" else raw)
    except (ValueError, OSError, TypeError, binascii.Error) as exc:
        raise RuntimeError("Clearings session protection could not be verified") from exc
    if (not isinstance(data, dict) or not isinstance(data.get("token"), str)
            or not isinstance(data.get("identity"), dict) or type(data.get("port")) is not int):
        raise RuntimeError("Invalid protected Clearings session")
    return data


def preserve_session_bytes(path: Path, raw: bytes) -> Path:
    """Keep an exact, private, reversible pre-replacement session snapshot."""
    if len(raw) > MAX_BYTES:
        raise RuntimeError("Earlier Clearings session is too large to preserve")
    if os.name == "nt":
        payload = _dpapi(raw, protect=True)
    else:
        _private_posix_path(path)
        payload = raw
    envelope = (json.dumps({"format": "clearings-session-recovery-v1",
                            "payload": base64.b64encode(payload).decode("ascii")},
                           separators=(",", ":")) + "\n").encode("ascii")
    backup = path.with_name("session-recovery-" + uuid.uuid4().hex + ".json")
    fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(envelope)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        backup.unlink(missing_ok=True)
        raise
    return backup


def restore_session_bytes(path: Path, raw: bytes) -> None:
    """Restore a displaced session after a failed, owned-socket startup."""
    fd, temp_name = tempfile.mkstemp(prefix=".clearings-session-", suffix=".tmp",
                                     dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_session_bytes(path: Path) -> bytes:
    with path.open("rb") as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise RuntimeError("Earlier Clearings session is too large to preserve")
    return raw


class LaunchState:
    """Small, one-use launch and replay ledger for a single running helper."""
    def __init__(self):
        self.lock = threading.Lock()
        self.pending = {}
        self.used = {}

    def _prune(self):
        current = time.monotonic()
        self.pending = {key: end for key, end in self.pending.items() if end > current}
        self.used = {key: end for key, end in self.used.items() if end > current}

    def claim(self, challenge: str, stamp: int) -> bool:
        with self.lock:
            self._prune()
            current = int(time.monotonic() * 1000)
            if (type(stamp) is not int or stamp <= current - 30000 or stamp > current + 2000
                    or challenge in self.used or len(self.used) >= 32):
                return False
            self.used[challenge] = (stamp + 30000) / 1000
            return True

    def issue(self) -> str:
        with self.lock:
            self._prune()
            if len(self.pending) >= 16:
                raise ValueError("Too many pending Clearings launches; try again shortly")
            nonce = secrets.token_urlsafe(32)
            self.pending[nonce] = time.monotonic() + BOOTSTRAP_SECONDS
            return nonce

    def redeem(self, nonce: str) -> bool:
        with self.lock:
            self._prune()
            return self.pending.pop(nonce, None) is not None


def _listener_present(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except ConnectionRefusedError:
        return False
    except OSError as exc:
        raise RuntimeError("Cannot establish who owns the Clearings address") from exc


def local_json_request(port: int, path: str, body: dict | None = None) -> dict:
    """Tiny direct-loopback client: no proxy/redirect, bounded bytes and wall time."""
    deadline = time.monotonic() + 3
    raw_body = b"" if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    if len(raw_body) > 4096:
        raise RuntimeError("Clearings control request is too large")
    method = "GET" if body is None else "POST"
    headers = (f"{method} {path} HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n"
               "Accept: application/json\r\nConnection: close\r\n")
    if body is not None:
        headers += f"Content-Type: application/json\r\nContent-Length: {len(raw_body)}\r\n"
    request = headers.encode("ascii") + b"\r\n" + raw_body
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3) as connection:
            connection.settimeout(max(.01, deadline - time.monotonic()))
            connection.sendall(request)
            connection.setblocking(False)
            packet = b""
            length = None
            while True:
                header, marker, content = packet.partition(b"\r\n\r\n")
                if marker:
                    if len(header) > 2048:
                        raise RuntimeError("Clearings control response headers are too large")
                    lines = header.split(b"\r\n")
                    if not re.fullmatch(rb"HTTP/1\.[01] 200(?: .*)?", lines[0]):
                        raise RuntimeError("Clearings listener returned an unexpected status")
                    fields = {}
                    for line in lines[1:]:
                        key, sep, value = line.partition(b":")
                        if not sep:
                            raise RuntimeError("Malformed Clearings control response")
                        fields.setdefault(key.lower(), []).append(value.strip())
                    sizes = fields.get(b"content-length", [])
                    if (len(sizes) != 1 or not sizes[0].isdigit()
                            or len(fields.get(b"content-type", [])) != 1
                            or fields[b"content-type"][0] != b"application/json"):
                        raise RuntimeError("Malformed Clearings control response")
                    length = int(sizes[0])
                    if length > 2048:
                        raise RuntimeError("Clearings control response is too large")
                    if len(content) >= length:
                        answer = json.loads(content[:length])
                        if not isinstance(answer, dict):
                            raise RuntimeError("Malformed Clearings control reply")
                        return answer
                if len(packet) >= 4096:
                    raise RuntimeError("Clearings control response is too large")
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([connection], [], [], remaining)[0]:
                    raise RuntimeError("Clearings control response timed out")
                chunk = connection.recv(min(2048, 4096 - len(packet)))
                if not chunk:
                    raise RuntimeError("Clearings control response ended early")
                packet += chunk
    except (OSError, ValueError, IndexError) as exc:
        raise RuntimeError("Clearings listener did not provide a valid bounded reply") from exc


def verify_listener(session: dict, bridge: "Bridge", port: int) -> bool:
    """Challenge the incumbent before giving it a token or opening its origin."""
    if session["port"] != port or session["identity"] != program_identity(bridge):
        raise RuntimeError("An earlier Clearings version may own this address. Close its helper manually; no data was changed.")
    if not _listener_present(port):
        return False
    challenge = secrets.token_urlsafe(32)
    try:
        answer = local_json_request(port, f"/api/identity-proof?challenge={challenge}")
    except RuntimeError as exc:
        raise RuntimeError("The listener did not prove its Clearings identity; no credential was sent") from exc
    expected = control_mac(session["token"], "identity", challenge, session["identity"], port)
    if not isinstance(answer, dict) or not isinstance(answer.get("proof"), str) or not hmac.compare_digest(answer["proof"], expected):
        raise RuntimeError("The listener did not prove its Clearings identity; no credential was sent")
    return True


def authenticated_control(session: dict, op: str, port: int) -> dict:
    """Send a one-use MAC, never the reusable session secret, to a proved helper."""
    challenge = secrets.token_urlsafe(32)
    stamp = int(time.monotonic() * 1000)
    identity = session["identity"]
    claim = {"op": op, "challenge": challenge, "stamp": stamp,
             "proof": control_mac(session["token"], "request-" + op, challenge,
                                  identity, port, str(stamp))}
    answer = local_json_request(port, "/api/control", claim)
    nonce = answer.get("nonce", "") if isinstance(answer, dict) else ""
    expected = control_mac(session["token"], "response-" + op, challenge, identity, port, nonce)
    if not isinstance(answer, dict) or not isinstance(answer.get("proof"), str) or not hmac.compare_digest(answer["proof"], expected):
        raise RuntimeError("Clearings helper control reply was not authentic")
    return answer


def _size_label(limit: int) -> str:
    return (f"{limit // (1024 * 1024)} MiB" if limit % (1024 * 1024) == 0
            else f"{limit} bytes")


def read_bounded_bytes(path: Path, limit: int) -> bytes:
    with path.open("rb") as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"{path.name} exceeds {_size_label(limit)}")
    return raw


def load_json(path: Path, default=None, *, max_bytes: int | None = None):
    if not path.exists():
        return default
    limit = MAX_BYTES if max_bytes is None else max_bytes
    return json.loads(read_bounded_bytes(path, limit).decode("utf-8"))


def atomic_json(path: Path, value, *, max_bytes: int | None = None,
                compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    limit = MAX_BYTES if max_bytes is None else max_bytes
    raw = ((json.dumps(value, ensure_ascii=False, separators=(",", ":")) if compact
            else json.dumps(value, ensure_ascii=False, indent=2)) + "\n").encode("utf-8")
    if len(raw) > limit and not compact:
        raw = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if len(raw) > limit:
        label = "Handoff" if path.name == FILE_NAME else path.name
        raise ValueError(f"{label} exceeds {_size_label(limit)}; nothing was written")
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


class HelperUpdating(ValueError):
    code = "CLEARINGS_UPDATING"
    retry_after_ms = 1000

    def __init__(self):
        super().__init__("Clearings is restarting for an update, please hold. Retry in one second with the same request ID.")


class Bridge:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.config_path = root / "settings.json"
        self.lock_path = root / "handoff.lock"
        self.maintenance_path = root / "helper-maintenance.json"
        self.maintenance_id = None
        self.runtime_hash = HELPER_SHA256
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
        packet = load_json(self.handoff_path(), max_bytes=MAX_HANDOFF_BYTES)
        if packet is None:
            return {"format": "clearings-local-handoff", "schemaVersion": 1,
                    "libraryId": None, "snapshot": None, "snapshotAt": None,
                    "generation": 0, "proposals": [], "receipts": []}
        if packet.get("format") != "clearings-local-handoff" or packet.get("schemaVersion") != 1:
            raise ValueError("Unrecognized handoff file; it was not changed")
        return packet

    def browser_handoff(self):
        """Expose signed commits and legacy proposals, never new unsigned drafts."""
        packet = self.read()
        packet["proposals"] = [proposal for proposal in packet["proposals"]
                               if proposal.get("status") != "pending" or
                               not proposal.get("requiresCommit") or
                               proposal.get("commit") or proposal.get("committedAt")]
        return packet

    def refresh_for_ai(self):
        """Read saved browser state and committed checkmarks awaiting display."""
        packet = self.read()
        effective, awaiting, conflicts = self.effective_workspace(packet)
        return {"libraryId": packet["libraryId"], "snapshotAt": packet["snapshotAt"],
                "generation": packet["generation"], "savedWorkspace": packet["snapshot"],
                "effectiveWorkspace": effective, "committedAwaitingBrowser": awaiting,
                "committedConflicts": conflicts,
                "pendingUnapplied": [p for p in packet["proposals"] if p["status"] == "pending"],
                "readOnly": True}

    @staticmethod
    def completion_changes(proposal):
        """Accept only existing-item false-to-true state edits, without other edits."""
        base, incoming = proposal.get("base"), proposal.get("incoming")
        if not isinstance(base, dict) or not isinstance(incoming, dict):
            raise ValueError("Completion needs an existing checklist proposal")
        if ({k: v for k, v in base.items() if k != "state"} !=
                {k: v for k, v in incoming.items() if k != "state"}):
            raise ValueError("Completion proposal also changes checklist content")
        before, after = base.get("state"), incoming.get("state")
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise ValueError("Completion proposal needs valid state maps")
        ids = {item.get("id") for item in base.get("model", {}).get("items", [])}
        changed = [key for key in before.keys() | after.keys()
                   if before.get(key) != after.get(key)]
        if (not changed or any(key not in ids or before.get(key) not in (None, False)
                               or after.get(key) is not True for key in changed)):
            raise ValueError("Only existing unchecked items may be committed complete")
        return changed

    @classmethod
    def effective_workspace(cls, packet, exclude_id=None):
        """Replay signed commits in order without changing the browser snapshot."""
        effective = copy.deepcopy(packet["snapshot"])
        if effective is None:
            return None, [], []
        awaiting, conflicts = [], []
        for proposal in packet["proposals"]:
            if (proposal.get("id") == exclude_id or proposal.get("status") != "pending" or
                    not (proposal.get("commit") or proposal.get("committedAt"))):
                continue
            author = (proposal.get("commit") or {}).get("author") or proposal.get("committedBy") or proposal["actor"]
            stamp = {"actor": author, "role": "assistant",
                     "at": (proposal.get("commit") or {}).get("at") or proposal.get("committedAt") or proposal["createdAt"],
                     "commitId": (proposal.get("commit") or {}).get("id")}
            doc_id = proposal["documentId"]
            document = next((d for d in effective["documents"] if d.get("documentId") == doc_id), None)
            try:
                if proposal.get("kind") == "create":
                    incoming = validate_document(copy.deepcopy(proposal["incoming"]))
                    if document is not None:
                        visible = {key: value for key, value in document.items()
                                   if key not in ("updatedAt", "view", "attribution")}
                        submitted = {key: value for key, value in incoming.items()
                                     if key not in ("updatedAt", "view", "attribution")}
                        if visible != submitted:
                            raise ValueError("New checklist ID already has different content")
                    else:
                        incoming.pop("attribution", None)
                        stamp_attribution(incoming, None, stamp)
                        filename = f"checklist-{doc_id}.json"
                        if any(entry["file"].lower() == filename.lower()
                               for entry in effective["index"]["entries"]):
                            raise ValueError("New checklist filename already exists")
                        effective["documents"].append(incoming)
                        effective["index"]["entries"].append({"id": doc_id, "file": filename})
                        if effective["index"].get("defaultChecklist") is None and not incoming["archived"]:
                            effective["index"]["defaultChecklist"] = doc_id
                    item_ids = [item["id"] for item in incoming["model"]["items"]]
                else:
                    if document is None:
                        raise ValueError("Committed checklist is missing")
                    result = merge_documents(proposal["base"], document, proposal["incoming"])
                    if result["conflicts"]:
                        raise ValueError("Conflicting fields: " + ", ".join(result["conflicts"]))
                    if (doc_id == effective["index"].get("defaultChecklist") and
                            result["merged"]["archived"]):
                        raise ValueError("The default checklist cannot be archived")
                    stamp_attribution(result["merged"], document, stamp)
                    effective["documents"][effective["documents"].index(document)] = result["merged"]
                    kept = {i["id"] for i in result["merged"]["model"]["items"]}
                    effective["index"]["tracked"] = [t for t in effective["index"].get("tracked", []) if t["checklistId"] != doc_id or t.get("itemId") is None or t["itemId"] in kept]
                    if "activity" in effective["index"]:
                        effective["index"]["activity"] = [a for a in effective["index"].get("activity", []) if a["checklistId"] != doc_id or a.get("itemId") is None or a["itemId"] in kept]
                    item_ids = sorted({key for key in proposal["incoming"]["state"]
                                       if proposal["base"]["state"].get(key) != proposal["incoming"]["state"].get(key)})
            except (ValueError, KeyError, TypeError) as exc:
                conflicts.append({"proposalId": proposal["id"], "documentId": doc_id,
                                  "reason": str(exc)})
                continue
            awaiting.append({"proposalId": proposal["id"], "documentId": doc_id,
                             "itemIds": item_ids, "actor": author,
                             "commitId": (proposal.get("commit") or {}).get("id"),
                             "changeCount": (proposal.get("commit") or {}).get("changeCount"),
                             "committedAt": (proposal.get("commit") or {}).get("at") or proposal["committedAt"]})
        return effective, awaiting, conflicts

    def read_checklist(self, checklist_id: str, branch_id: str | None = None):
        """Read one saved list or a marked partial branch, plus pending suggestions."""
        packet = self.read()
        snapshot = packet["snapshot"]
        effective, awaiting, conflicts = self.effective_workspace(packet)
        if snapshot is None:
            raise ValueError("No browser-saved workspace is available")
        document = next((d for d in snapshot["documents"]
                         if d.get("documentId") == checklist_id), None)
        pending = [p for p in packet["proposals"]
                   if p["status"] == "pending" and p.get("documentId") == checklist_id]
        effective_document = next((d for d in effective["documents"]
                                  if d.get("documentId") == checklist_id), None)
        if document is None and effective_document is None:
            raise ValueError("Unknown checklist ID; uncommitted new lists appear in refresh")
        result = {"libraryId": packet["libraryId"], "snapshotAt": packet["snapshotAt"],
                  "generation": packet["generation"], "checklistId": checklist_id,
                  "documentFormat": effective_document.get("format"),
                  "documentSchemaVersion": effective_document.get("schemaVersion"),
                  "partial": branch_id is not None, "readOnly": True,
                  "pendingUnapplied": pending,
                  "committedAwaitingBrowser": [entry for entry in awaiting
                                                if entry["documentId"] == checklist_id],
                  "committedConflicts": [entry for entry in conflicts
                                         if entry["documentId"] == checklist_id]}
        if branch_id is None:
            result["savedDocument"] = document
            result["effectiveDocument"] = effective_document
            return result

        items = effective_document.get("model", {}).get("items", [])
        by_id = {item["id"]: item for item in items}
        if branch_id not in by_id:
            raise ValueError("Unknown branch item ID")
        roots = effective_document["model"]["roots"]
        incoming_links = {item_id: [] for item_id in by_id}
        for root_id in roots:
            if root_id in incoming_links:
                incoming_links[root_id].append(None)
        for parent in items:
            for child_id in parent.get("requires", []):
                if child_id in incoming_links:
                    incoming_links[child_id].append(parent["id"])

        descendants = set()
        stack = [branch_id]
        while stack:
            item_id = stack.pop()
            if item_id in descendants:
                continue
            descendants.add(item_id)
            stack.extend(by_id[item_id].get("requires", []))
        context = set()
        stack = list(descendants)
        while stack:
            item_id = stack.pop()
            for parent_id in incoming_links[item_id]:
                if parent_id is not None and parent_id not in descendants and parent_id not in context:
                    context.add(parent_id)
                    stack.append(parent_id)
        selected = descendants | context
        result["branch"] = {
            "branchId": branch_id,
            "descendantIds": sorted(descendants),
            "ancestorAndSharedParentIds": sorted(context),
            "rootIds": [root_id for root_id in roots if root_id in selected],
            "items": [item for item in items if item["id"] in selected],
            "state": {item_id: value for item_id, value in effective_document.get("state", {}).items()
                      if item_id in selected},
            "incomingLinks": {item_id: incoming_links[item_id] for item_id in selected},
            "excludedChildIds": {item_id: [child for child in by_id[item_id].get("requires", [])
                                           if child not in selected] for item_id in selected},
            "notAProposalBase": True,
        }
        return result

    def check_maintenance(self):
        state = load_json(self.maintenance_path, {})
        if state.get("until", 0) > time.time():
            raise HelperUpdating()
        approved = load_json(self.root / "approved-source.json", {})
        if approved.get("helperSha256", self.runtime_hash) != self.runtime_hash:
            raise HelperUpdating()

    def begin_maintenance(self):
        """Drain the one-writer lock, then make new writers return a retry error."""
        self.check_maintenance()
        with file_lock(self.lock_path):
            self.check_maintenance()
            self.maintenance_id = uuid.uuid4().hex
            atomic_json(self.maintenance_path, {"id": self.maintenance_id,
                                               "until": time.time() + 300})

    def end_maintenance(self):
        with file_lock(self.lock_path):
            state = load_json(self.maintenance_path, {})
            if self.maintenance_id and state.get("id") == self.maintenance_id:
                self.maintenance_path.unlink(missing_ok=True)
            self.maintenance_id = None

    def prepare_shutdown(self):
        self.begin_maintenance()
        try:
            return self.backup_workspace()
        except BaseException:
            self.end_maintenance()
            raise

    def change(self, edit):
        self.check_maintenance()
        with file_lock(self.lock_path):
            self.check_maintenance()
            packet = self.read()
            before = copy.deepcopy(packet)
            result = edit(packet)
            if result is not None:
                size = len((json.dumps(packet, ensure_ascii=False,
                                       separators=(",", ":")) + "\n").encode("utf-8"))
                if size <= MAX_HANDOFF_BYTES:
                    atomic_json(self.handoff_path(), packet,
                                max_bytes=MAX_HANDOFF_BYTES, compact=True)
                else:
                    self._change_with_resolved_rollover(before, packet)
            return result

    def _change_with_resolved_rollover(self, before, packet):
        """Archive unchanged terminal history before publishing an oversize edit.

        The archive is the exact on-disk preimage. A proposal that this edit
        changed (including a newly resolved one) stays active until a later
        rollover can preserve that version in an exact preimage.
        """
        path = self.handoff_path()
        if not path.exists():
            raise ValueError(f"Handoff exceeds {_size_label(MAX_HANDOFF_BYTES)}; nothing was written")
        prior = read_bounded_bytes(path, MAX_HANDOFF_BYTES)
        if json.loads(prior) != before:
            raise ValueError("Handoff changed while reading; nothing was archived")
        old_proposals, new_proposals = before.get("proposals"), packet.get("proposals")
        archives = packet.get("resolvedProposalArchives", [])
        if not isinstance(old_proposals, list) or not isinstance(new_proposals, list) or not isinstance(archives, list):
            raise ValueError("Unrecognized handoff history; nothing was written")
        old_by_id = {p.get("id"): p for p in old_proposals if isinstance(p, dict)}
        new_by_id = {p.get("id"): p for p in new_proposals if isinstance(p, dict)}
        if (len(old_by_id) != len(old_proposals) or len(new_by_id) != len(new_proposals)
                or None in old_by_id or None in new_by_id):
            raise ValueError("Ambiguous proposal history; nothing was written")
        if (not old_by_id.keys() <= new_by_id.keys() or
                archives != before.get("resolvedProposalArchives", [])):
            raise ValueError("Handoff history changed unexpectedly; nothing was written")
        terminal = {"applied", "already-current", "dismissed"}
        archived = [p["id"] for p in old_proposals if p.get("status") in terminal
                    and new_by_id.get(p["id"]) == p]
        if not archived:
            raise ValueError(f"Handoff exceeds {_size_label(MAX_HANDOFF_BYTES)}; nothing was written")
        digest = hashlib.sha256(prior).hexdigest()
        descriptor = {"file": "archives/clearings-resolved-" + digest + ".json",
                      "sha256": digest, "bytes": len(prior),
                      "libraryId": before["libraryId"], "generation": before["generation"],
                      "resolvedProposalIds": archived}
        compact = copy.deepcopy(packet)
        archived_ids = set(archived)
        compact["proposals"] = [p for p in new_proposals if p["id"] not in archived_ids]
        compact["resolvedProposalArchives"] = [*archives, descriptor]
        after_bytes = len((json.dumps(compact, ensure_ascii=False,
                                      separators=(",", ":")) + "\n").encode("utf-8"))
        if after_bytes > MAX_HANDOFF_BYTES:
            raise ValueError(f"Handoff exceeds {_size_label(MAX_HANDOFF_BYTES)} after archiving resolved history; nothing was written")
        self._publish_archive_preimage(prior, descriptor)
        atomic_json(path, compact, max_bytes=MAX_HANDOFF_BYTES, compact=True)

    def _publish_archive_preimage(self, prior, descriptor):
        """Publish and verify an exact preimage under the configured home."""
        home = self.home().resolve()
        archive = home / descriptor["file"]
        archive.parent.mkdir(exist_ok=True)
        if archive.parent.resolve() != home / "archives":
            raise ValueError("Archive directory leaves Clearings home; active handoff unchanged")
        digest = descriptor["sha256"]
        if not archive.exists():
            # Use ordinary inherited permissions, not mkstemp's restrictive
            # temporary-file ACL. A crash leaves at most an orphan .part.
            staging = archive.parent / (".clearings-resolved-" + digest +
                                        "." + uuid.uuid4().hex + ".part")
            with staging.open("xb") as stream:
                stream.write(prior)
                stream.flush()
                os.fsync(stream.fileno())
            if (staging.stat().st_size != len(prior) or
                    hashlib.sha256(staging.read_bytes()).hexdigest() != digest or
                    not os.access(staging, os.R_OK)):
                raise ValueError("Staged archive verification failed; active handoff unchanged")
            if archive.exists():
                raise ValueError("Archive appeared during staging; active handoff unchanged")
            os.replace(staging, archive)
        if (not archive.is_file() or archive.stat().st_size != len(prior) or
                hashlib.sha256(archive.read_bytes()).hexdigest() != digest or
                not os.access(archive, os.R_OK)):
            raise ValueError("Archive verification failed; active handoff unchanged")

    def archive_resolved(self, dry_run: bool = False):
        """Explicitly archive terminal proposals; never touch pending work.

        The archive is an exact, create-once preimage of the handoff. Writing
        and verifying it *before* replacing the active file makes interruption
        recoverable. This is deliberately not an automatic size rollover.
        """
        self.check_maintenance()
        with file_lock(self.lock_path):
            self.check_maintenance()
            packet = self.read()
            resolved = [p for p in packet["proposals"]
                        if p.get("status") in ("applied", "already-current", "dismissed")]
            if not resolved:
                return {"archived": 0, "changed": False, "dryRun": dry_run}
            prior = read_bounded_bytes(self.handoff_path(), MAX_HANDOFF_BYTES)
            if json.loads(prior) != packet:
                raise ValueError("Handoff changed while reading; nothing was archived")
            digest = hashlib.sha256(prior).hexdigest()
            relative = "archives/clearings-resolved-" + digest + ".json"
            archives = packet.get("resolvedProposalArchives", [])
            if not isinstance(archives, list):
                raise ValueError("Unrecognized archive index; nothing was archived")
            descriptor = {"file": relative, "sha256": digest,
                          "bytes": len(prior), "libraryId": packet["libraryId"],
                          "generation": packet["generation"],
                          "resolvedProposalIds": [p["id"] for p in resolved]}
            compact = copy.deepcopy(packet)
            compact["proposals"] = [p for p in packet["proposals"] if p.get("status")
                                    not in ("applied", "already-current", "dismissed")]
            compact["resolvedProposalArchives"] = [*archives, descriptor]
            after_bytes = len((json.dumps(compact, ensure_ascii=False,
                                          separators=(",", ":")) + "\n").encode("utf-8"))
            if after_bytes > MAX_HANDOFF_BYTES:
                raise ValueError("Active handoff would still exceed 64 MiB; nothing was archived")
            result = {"archived": len(resolved), "changed": not dry_run,
                      "dryRun": dry_run, "archive": descriptor,
                      "activeCompactBytes": after_bytes,
                      "pendingPreserved": sum(p.get("status") == "pending"
                                              for p in compact["proposals"])}
            if dry_run:
                return result
            self._publish_archive_preimage(prior, descriptor)
            atomic_json(self.handoff_path(), compact,
                        max_bytes=MAX_HANDOFF_BYTES, compact=True)
            return result

    def set_home(self, text: str):
        candidate = Path(text).expanduser().resolve()
        if not candidate.is_dir():
            raise ValueError("Choose an existing folder for Clearings home")
        self.check_maintenance()
        with file_lock(self.lock_path):
            self.check_maintenance()
            old = self.read()
            if any(p.get("status") == "pending" for p in old["proposals"]):
                raise ValueError("Resolve or export pending changes before changing home folders")
            target = candidate / FILE_NAME
            if target.exists():
                existing = load_json(target, max_bytes=MAX_HANDOFF_BYTES)
                if existing.get("format") != "clearings-local-handoff":
                    raise ValueError("That folder contains a different handoff file")
                if (existing.get("libraryId") not in (None, old.get("libraryId")) or
                        existing.get("generation", 0) > old.get("generation", 0)):
                    raise ValueError("That folder has another or newer library; nothing was changed")
            atomic_json(self.config_path, {"home": str(candidate)})
        return str(candidate)

    def sync(self, workspace: dict, generation: int, expected_generation: int | None = None,
             browser_record: dict | None = None):
        if workspace.get("format") not in ("checklist-studio-workspace", "local-companion-checklist-workspace"):
            raise ValueError("Expected a Clearings workspace snapshot")
        library_id = workspace.get("index", {}).get("libraryId")
        if not isinstance(library_id, str) or not isinstance(generation, int) or generation < 1:
            raise ValueError("Invalid workspace identity or generation")
        if browser_record is not None:
            if isinstance(browser_record, dict) and "workspace" not in browser_record:
                browser_record = {**browser_record, "workspace": workspace}
            if (not isinstance(browser_record, dict)
                    or browser_record.get("format") != "clearings-browser-record"
                    or browser_record.get("version") != 1
                    or browser_record.get("generation") != generation
                    or browser_record.get("workspace") != workspace
                    or not isinstance(browser_record.get("savedAt"), str)
                    or not isinstance(browser_record.get("draft"), (dict, type(None)))):
                raise ValueError("Browser recovery record does not match this save")
            if len(json.dumps(browser_record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_BYTES:
                raise ValueError("Browser recovery record exceeds 16 MB")

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
            if browser_record is not None:
                packet["browserDraft"] = {"generation": generation, "appVersion": VERSION,
                                          "savedAt": browser_record["savedAt"],
                                          "draft": browser_record.get("draft")}
            elif packet.get("browserDraft", {}).get("generation") != generation:
                packet.pop("browserDraft", None)
            return {"generation": generation, "snapshotAt": packet["snapshotAt"]}
        return self.change(edit)

    def recovery_directory(self):
        home = self.home().resolve()
        path = home / "recovery"
        if path.resolve().parent != home:
            raise ValueError("Recovery folder must stay inside the Clearings home")
        return path

    @staticmethod
    def recovery_archives(packet):
        for entry in packet.get("resolvedProposalArchives", []):
            name, digest = entry.get("file", ""), entry.get("sha256", "")
            if (not re.fullmatch(r"[a-f0-9]{64}", digest)
                    or name != f"archives/clearings-resolved-{digest}.json"):
                raise ValueError("Invalid recovery archive reference")
            yield name, digest

    @staticmethod
    def copy_recovery_archive(source, target, digest):
        raw = read_bounded_bytes(source, MAX_HANDOFF_BYTES)
        if len(raw) > MAX_HANDOFF_BYTES or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Recovery archive failed its size or checksum check")
        if target.exists():
            if hashlib.sha256(read_bounded_bytes(target, MAX_HANDOFF_BYTES)).hexdigest() != digest:
                raise ValueError("Existing recovery archive has different contents")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".clearings-recovery-", dir=target.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def _backup_locked(self):
        packet = self.read()
        if packet["snapshot"] is None:
            return {"saved": False, "reason": "No saved workspace yet"}
        directory = self.recovery_directory()
        directory.mkdir(exist_ok=True)
        if (directory / "archives").resolve().parent != directory.resolve():
            raise ValueError("Recovery archives must stay inside the recovery folder")
        if (self.home() / "archives").resolve().parent != self.home().resolve():
            raise ValueError("Archives must stay inside the saved home")
        for name, digest in self.recovery_archives(packet):
            source = self.home() / name
            if source.resolve().parent != (self.home() / "archives").resolve():
                raise ValueError("Archive path is outside the saved home")
            self.copy_recovery_archive(source, directory / name, digest)
        bundle = {"format": "clearings-recovery", "version": 1, "appVersion": VERSION,
                  "savedAt": now(), "handoff": packet}
        current = directory / "latest.json"
        if current.exists():
            # Never rotate a damaged latest copy over the previous good copy.
            try:
                prior = self._read_recovery_bundle(current)
            except (ValueError, OSError, TypeError, KeyError):
                prior = None
            if prior is not None:
                atomic_json(directory / "previous.json", prior,
                            max_bytes=MAX_HANDOFF_BYTES + MAX_BYTES, compact=True)
        atomic_json(current, bundle, max_bytes=MAX_HANDOFF_BYTES + MAX_BYTES, compact=True)
        return {"saved": True, "savedAt": bundle["savedAt"], "appVersion": VERSION}

    def backup_workspace(self):
        with file_lock(self.lock_path):
            return self._backup_locked()

    def _read_recovery_bundle(self, path):
        bundle = load_json(path, max_bytes=MAX_HANDOFF_BYTES + MAX_BYTES)
        if not isinstance(bundle, dict) or bundle.get("format") != "clearings-recovery" or bundle.get("version") != 1:
            raise ValueError("Unrecognized Clearings recovery backup")
        packet = bundle.get("handoff")
        if (not isinstance(packet, dict) or packet.get("format") != "clearings-local-handoff"
                or packet.get("schemaVersion") != 1 or not isinstance(packet.get("snapshot"), dict)
                or packet.get("libraryId") != packet["snapshot"].get("index", {}).get("libraryId")
                or type(packet.get("generation")) is not int or packet["generation"] < 1
                or not isinstance(packet.get("proposals"), list) or not isinstance(packet.get("receipts"), list)):
            raise ValueError("Invalid saved handoff in recovery backup")
        for document in packet["snapshot"].get("documents", []):
            validate_document(document)
        for name, digest in self.recovery_archives(packet):
            source = self.recovery_directory() / name
            if (self.recovery_directory() / "archives").resolve().parent != self.recovery_directory().resolve():
                raise ValueError("Recovery archives must stay inside the recovery folder")
            if source.resolve().parent != (self.recovery_directory() / "archives").resolve():
                raise ValueError("Invalid recovery archive path")
            if not source.is_file() or hashlib.sha256(read_bounded_bytes(source, MAX_HANDOFF_BYTES)).hexdigest() != digest:
                raise ValueError("Recovery backup has a missing or damaged archive")
        return bundle

    def restore_missing_handoff(self):
        """Startup recovery only fills an absent handoff; existing files always win."""
        with file_lock(self.lock_path):
            if self.handoff_path().exists():
                return False
            directory = self.recovery_directory()
            bundle = None
            for name in ("latest.json", "previous.json"):
                path = directory / name
                if not path.exists():
                    continue
                try:
                    bundle = self._read_recovery_bundle(path)
                    break
                except (ValueError, OSError, TypeError, KeyError):
                    continue
            if bundle is None:
                return False
            packet = bundle["handoff"]
            if (self.home() / "archives").resolve().parent != self.home().resolve():
                raise ValueError("Archives must stay inside the saved home")
            for name, digest in self.recovery_archives(packet):
                target = self.home() / name
                if target.resolve().parent != (self.home() / "archives").resolve():
                    raise ValueError("Archive destination is outside the saved home")
                self.copy_recovery_archive(directory / name, target, digest)
            atomic_json(self.handoff_path(), packet, max_bytes=MAX_HANDOFF_BYTES, compact=True)
            return True

    def recovery_record(self):
        packet = self.read()
        draft = packet.get("browserDraft", {})
        if packet["snapshot"] is None or draft.get("generation") != packet["generation"]:
            return {"record": None}
        return {"record": {"format": "clearings-browser-record", "version": 1,
                           "generation": packet["generation"], "savedAt": draft["savedAt"],
                           "workspace": packet["snapshot"], "draft": draft.get("draft")},
                "appVersion": draft.get("appVersion")}

    def propose(self, base: dict, incoming: dict, actor: str, note: str = "", request_id: str | None = None,
                expected_library_id: str | None = None):
        if not isinstance(base, dict) or not isinstance(incoming, dict) or not isinstance(actor, str):
            raise ValueError("A proposed change needs its base, new document, and display name")
        actor = actor.strip()[:80]
        if not actor:
            raise ValueError("A proposed change needs its base, new document, and display name")
        doc_id = base.get("documentId")
        if not doc_id or incoming.get("documentId") != doc_id:
            raise ValueError("The base and proposed checklist IDs differ")
        validate_document(base)
        validate_document(incoming)

        def edit(packet):
            if expected_library_id is not None and packet["libraryId"] != expected_library_id:
                raise ValueError("STALE_ITEM: The prepared context belongs to a different library")
            retry_payload = ["edit", base, incoming, str(note)[:500]]
            if expected_library_id is not None:
                retry_payload.append(expected_library_id)
            retry_key, retry_digest, prior = self.retry_request(packet, request_id, actor,
                                                               retry_payload)
            if prior is not None:
                return {"proposalId": prior["proposalId"], "documentId": doc_id, "alreadyProposed": True}
            return self._stage_existing(packet, base, incoming, actor, note, retry_key, retry_digest)
        return self.change(edit)

    def _stage_existing(self, packet, base, incoming, actor, note, retry_key, retry_digest):
        """Shared staging checks; caller holds the packet transaction."""
        doc_id = base["documentId"]
        snapshot, _, conflicts = self.effective_workspace(packet)
        if snapshot is None or not any(d.get("documentId") == doc_id for d in snapshot["documents"]):
            raise ValueError("This checklist is not in the latest shared workspace")
        if any(c["documentId"] == doc_id for c in conflicts):
            raise ValueError("This checklist needs committed conflict review before editing")
        if len([p for p in packet["proposals"] if p["status"] == "pending"]) >= 100:
            raise ValueError("Too many pending proposals")
        proposal = {"id": uuid.uuid4().hex, "documentId": doc_id,
                    "actor": actor, "note": str(note)[:500], "createdAt": now(),
                    "base": base, "incoming": incoming, "status": "pending",
                    "suggestedChoices": {}, "requiresCommit": True}
        packet["proposals"].append(proposal)
        if retry_key:
            packet.setdefault("retryRequests", {})[retry_key] = {
                "digest": retry_digest, "proposalId": proposal["id"]}
        packet["proposals"] = retain_proposals(packet["proposals"])
        return {"proposalId": proposal["id"], "documentId": doc_id}

    @staticmethod
    def item_revision(document, item_id, library_id):
        """Opaque optimistic revision, including completion and ancestor scope."""
        items = {item["id"]: item for item in document["model"]["items"]}
        if item_id not in items:
            raise ValueError("ITEM_NOT_FOUND: Read the checklist to locate the current item")
        parents = {key: [] for key in items}
        for item in items.values():
            for child in item["requires"]:
                parents[child].append(item["id"])
        ancestors, queue = set(), list(parents[item_id])
        while queue:
            key = queue.pop()
            if key not in ancestors:
                ancestors.add(key)
                queue.extend(parents[key])
        payload = [library_id, document["documentId"], document["archived"],
                   items[item_id], document["state"].get(item_id, False),
                   document.get("attribution", {}).get(item_id, {}),
                   [[key, document["state"].get(key, False)] for key in sorted(ancestors)]]
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":")).encode("utf-8")).hexdigest()

    def propose_item_edits(self, checklist_id, edits, actor, note, request_id):
        """Stage only explicit fields after checking revisions inside the write lock."""
        if not isinstance(actor, str) or not 1 <= len(actor.strip()) <= 80:
            raise ValueError("A proposed change needs a display name")
        actor = actor.strip()
        if not request_id:
            raise ValueError("A focused edit requires a fresh request_id; reuse it only for an identical retry")
        if not isinstance(edits, list) or not 1 <= len(edits) <= 25:
            raise ValueError("Supply between 1 and 25 item edits")
        allowed = {"text", "detail", "response", "review", "mcpAcknowledgement",
                   "needsReview", "assignment", "label", "tags", "completed"}
        seen = set()
        for edit in edits:
            if not isinstance(edit, dict) or set(edit) != {"item_id", "expected_revision", "changes"}:
                raise ValueError("Each edit needs item_id, expected_revision and changes")
            key = edit["item_id"]
            if not isinstance(key, str) or key in seen:
                raise ValueError("Item IDs must be distinct strings")
            seen.add(key)
            if not isinstance(edit["expected_revision"], str) or not re.fullmatch(r"[a-f0-9]{64}", edit["expected_revision"]):
                raise ValueError("Use the revision from clearings_read_item")
            changes = edit["changes"]
            if not isinstance(changes, dict) or not changes or set(changes) - allowed:
                raise ValueError("Focused edits accept explicit item fields, not IDs, attribution or structure")
            if "completed" in changes and type(changes["completed"]) is not bool:
                raise ValueError("completed must be true or false")
        if len(json.dumps(edits, ensure_ascii=False).encode("utf-8")) > 262144:
            raise ValueError("Focused edit exceeds 256 KiB; split it into smaller changes")

        def edit_packet(packet):
            retry_key, retry_digest, prior = self.retry_request(
                packet, request_id, actor, ["items", checklist_id, edits, str(note)[:500]])
            if prior is not None:
                return {"proposalId": prior["proposalId"], "documentId": checklist_id, "alreadyProposed": True}
            workspace, _, _ = self.effective_workspace(packet)
            base = next((d for d in (workspace or {}).get("documents", [])
                         if d["documentId"] == checklist_id), None)
            if base is None:
                raise ValueError("CHECKLIST_NOT_FOUND: Read the current checklist list")
            incoming = copy.deepcopy(base)
            items = {item["id"]: item for item in incoming["model"]["items"]}
            for edit in edits:
                key = edit["item_id"]
                if self.item_revision(base, key, packet["libraryId"]) != edit["expected_revision"]:
                    raise ValueError("STALE_ITEM: Re-read the item and reconcile before making a fresh request")
                for field, value in edit["changes"].items():
                    if field == "completed":
                        incoming["state"][key] = value
                    else:
                        items[key][field] = copy.deepcopy(value)
            validate_document(incoming)
            result = merge_documents(base, base, incoming)
            if result["conflicts"]:
                raise ValueError("ITEM_CONFLICT: " + ", ".join(result["conflicts"]))
            if not result["applied"]:
                raise ValueError("NO_CHANGE: The requested fields already have those values")
            return self._stage_existing(packet, base, incoming, actor, note, retry_key, retry_digest)
        return self.change(edit_packet)

    @staticmethod
    def retry_request(packet, request_id, actor, payload):
        if request_id is None:
            return None, None, None
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", request_id):
            raise ValueError("Request ID must be 1-128 letters, digits, dots, colons, underscores or hyphens")
        key = hashlib.sha256(json.dumps([actor, request_id], ensure_ascii=False).encode("utf-8")).hexdigest()
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                           separators=(",", ":")).encode("utf-8")).hexdigest()
        prior = packet.get("retryRequests", {}).get(key)
        if prior is not None and prior["digest"] != digest:
            raise ValueError("This request ID was already used for different content; nothing was changed")
        return key, digest, prior

    def commit_completions(self, proposal_id: str, actor: str):
        """Completion-only convenience uses the same atomic commit validation."""
        packet = self.read()
        proposal = next((p for p in packet['proposals'] if p['id'] == proposal_id), None)
        if proposal is None or proposal['status'] != 'pending':
            raise ValueError('Pending completion proposal not found')
        changed = self.completion_changes(proposal)
        result = self.commit_proposal(proposal_id, actor)
        return {**result, 'itemIds': sorted(changed), 'committedAt': result['commit']['at']}

    def commit_proposal(self, proposal_id: str, author: str):
        """Atomically sign one proposal against all earlier committed work."""
        author = author.strip()[:80]
        if not author:
            raise ValueError("A commit needs an author name")
        def edit(packet):
            position = next((i for i, p in enumerate(packet["proposals"])
                             if p["id"] == proposal_id), None)
            proposal = packet["proposals"][position] if position is not None else None
            if proposal is None:
                prior = next((value for value in packet.get("retryRequests", {}).values()
                              if value["proposalId"] == proposal_id and value.get("commit")), None)
                if prior and prior["commit"]["author"] == author:
                    return {"proposalId": proposal_id, "commit": prior["commit"], "alreadyCommitted": True}
                raise ValueError("Pending proposal not found")
            if proposal.get("commit"):
                if proposal["commit"]["author"] != author:
                    raise ValueError("This commit already has another author")
                return {"proposalId": proposal_id, "commit": proposal["commit"],
                        "alreadyCommitted": True}
            if proposal["status"] != "pending":
                raise ValueError("Pending proposal not found")
            if proposal.get("committedAt"):
                raise ValueError("This legacy completion was already committed")
            if packet["snapshot"] is None:
                raise ValueError("No browser-saved workspace is available")
            doc_id = proposal["documentId"]
            effective, _, conflicts = self.effective_workspace(packet, exclude_id=proposal_id)
            same_checklist_conflicts = [entry for entry in conflicts if entry["documentId"] == doc_id]
            if same_checklist_conflicts:
                raise ValueError("An earlier committed change needs conflict review: " +
                                 ", ".join(x["proposalId"] for x in same_checklist_conflicts))
            if any(p["status"] == "pending" and
                   p["documentId"] == doc_id and not p.get("requiresCommit") and
                   not p.get("commit") and not p.get("committedAt")
                   for p in packet["proposals"][:position]):
                raise ValueError("An older unsigned proposal for this checklist awaits browser Refresh")
            if proposal.get("kind") == "create":
                incoming = validate_document(proposal["incoming"])
                if any(d["documentId"] == doc_id for d in effective["documents"]):
                    raise ValueError("Checklist ID already exists in the shared state")
                filename = f"checklist-{doc_id}.json"
                if any(entry["file"].lower() == filename.lower()
                       for entry in effective["index"]["entries"]):
                    raise ValueError("Checklist filename already exists")
                change_count = len(incoming["model"]["items"]) + 1
            else:
                current = next((d for d in effective["documents"]
                                if d["documentId"] == doc_id), None)
                if current is None:
                    raise ValueError("Checklist is missing from the shared state")
                result = merge_documents(proposal["base"], current, proposal["incoming"])
                if result["conflicts"]:
                    raise ValueError("Commit conflicts with shared state: " +
                                     ", ".join(result["conflicts"]))
                if (doc_id == effective["index"].get("defaultChecklist") and
                        result["merged"]["archived"]):
                    raise ValueError("The default checklist cannot be archived")
                change_count = result["applied"]
                if change_count == 0:
                    raise ValueError("This proposal makes no new shared change")
            commit = {"id": uuid.uuid4().hex, "author": author, "at": now(),
                      "baseGeneration": packet["generation"], "changeCount": change_count}
            proposal["commit"] = commit
            for value in packet.get("retryRequests", {}).values():
                if value["proposalId"] == proposal_id:
                    value["commit"] = copy.deepcopy(commit)
            return {"proposalId": proposal_id, "commit": commit,
                    "alreadyCommitted": False}
        return self.change(edit)

    def propose_new(self, incoming: dict, actor: str, note: str = "", request_id: str | None = None):
        """Queue an unchecked new list; the browser validates its full schema."""
        if not isinstance(incoming, dict) or not isinstance(actor, str) or not actor.strip():
            raise ValueError("A new checklist needs a document and display name")
        doc_id = incoming.get("documentId")
        if (incoming.get("format") not in ("checklist-studio-document", "local-companion-checklist")
                or incoming.get("schemaVersion") != 2 or not isinstance(doc_id, str)
                or not re.fullmatch(r"[A-Za-z0-9._-]{1,200}", doc_id)
                or doc_id in ("__proto__", "prototype", "constructor")
                or not isinstance(incoming.get("title"), str) or not incoming["title"].strip()):
            raise ValueError("Expected a named version-2 checklist with a safe ID")
        state = incoming.get("state")
        if not isinstance(state, dict) or any(value is not False for value in state.values()):
            raise ValueError("A proposed new checklist must start with every item unchecked")

        def edit(packet):
            retry_key, retry_digest, prior = self.retry_request(packet, request_id, actor.strip()[:80],
                                                               ["create", incoming, str(note)[:500]])
            if prior is not None:
                return {"proposalId": prior["proposalId"], "documentId": doc_id, "alreadyProposed": True}
            snapshot = packet["snapshot"]
            if snapshot is None or packet["libraryId"] is None:
                raise ValueError("Start and save a Clearings workspace before proposing a new list")
            if any(d.get("documentId") == doc_id for d in snapshot["documents"]):
                raise ValueError("This checklist ID already exists in the saved workspace")
            if any(p.get("status") == "pending" and p.get("documentId") == doc_id
                   for p in packet["proposals"]):
                raise ValueError("This checklist ID already has a pending proposal")
            if len([p for p in packet["proposals"] if p["status"] == "pending"]) >= 100:
                raise ValueError("Too many pending proposals")
            proposal = {"id": uuid.uuid4().hex, "kind": "create", "documentId": doc_id,
                        "actor": actor.strip()[:80], "note": str(note)[:500], "createdAt": now(),
                        "base": None, "incoming": incoming, "status": "pending",
                        "suggestedChoices": {}, "requiresCommit": True}
            packet["proposals"].append(proposal)
            if retry_key:
                packet.setdefault("retryRequests", {})[retry_key] = {
                    "digest": retry_digest, "proposalId": proposal["id"]}
            packet["proposals"] = retain_proposals(packet["proposals"])
            return {"proposalId": proposal["id"], "documentId": doc_id,
                    "status": "pending browser validation and preview"}
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

    def withdraw(self, proposal_id, author, reason):
        if not author.strip() or not reason.strip():
            raise ValueError("Withdrawal needs your name and a reason")
        def edit(packet):
            proposal = next((p for p in packet["proposals"] if p["id"] == proposal_id), None)
            if proposal is None or proposal["status"] != "pending":
                raise ValueError("Pending proposal not found")
            owner = (proposal.get("commit") or {}).get("author") or proposal.get("committedBy") or proposal["actor"]
            if owner != author.strip():
                raise ValueError("Withdraw only your own proposal; resolve other authors' work explicitly")
            proposal["status"] = "dismissed"
            receipt = {"proposalId": proposal_id, "status": "dismissed", "at": now(),
                       "actor": author.strip(), "summary": "Withdrawn: " + reason.strip()[:450]}
            packet["receipts"].append(receipt)
            packet["receipts"] = packet["receipts"][-150:]
            return receipt
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
            if proposal.get("commit"):
                receipt["commitId"] = proposal["commit"]["id"]
                receipt["author"] = proposal["commit"]["author"]
            packet["receipts"].append(receipt)
            packet["receipts"] = packet["receipts"][-150:]
            return receipt
        return self.change(edit)


class NoUpdateRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Update redirects are not accepted")


def read_release_config(root=None):
    """A distribution may choose one public GitHub repo, or disable release checks.

    This does not configure a data home, listener, executable or arbitrary URL.
    Missing/invalid configuration must never fall back to another project's feed.
    """
    path = (ROOT if root is None else root) / "clearings.json"
    try:
        with path.open("rb") as stream:
            raw = stream.read(8193)
        if len(raw) > 8192:
            raise ValueError("file is too large")
        config = json.loads(raw)
        if (not isinstance(config, dict) or set(config) != {"schemaVersion", "updateRepository"}
                or type(config["schemaVersion"]) is not int or config["schemaVersion"] != 1):
            raise ValueError("expected schemaVersion 1 and updateRepository")
        repository = config["updateRepository"]
        if repository is not None:
            if not isinstance(repository, str) or not re.fullmatch(
                    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}", repository):
                raise ValueError("updateRepository must be owner/repository or null")
            if repository.split("/")[1] in {".", ".."}:
                raise ValueError("invalid repository name")
        return config
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        raise ValueError(f"Check clearings.json: {exc}. Release checks are disabled until fixed.") from exc


def embed_release_config(html, config):
    """Use the same small, inert configuration in served and packaged pages."""
    begin, end = "/* CLEARINGS_RELEASE_CONFIG_BEGIN */", "/* CLEARINGS_RELEASE_CONFIG_END */"
    if html.count(begin) != 1 or html.count(end) != 1:
        raise ValueError("Release configuration markers are missing or ambiguous")
    payload = json.dumps(config, ensure_ascii=True, separators=(",", ":")).replace("<", r"\u003c")
    return (html[:html.index(begin)] + begin + "\nconst RELEASE_CONFIG = " + payload + ";\n"
            + html[html.index(end):])


class AppUpdateCheck:
    """Public release metadata only; no workspace reads, downloads or installs."""
    URL = "https://api.github.com/repos/IoriReiMei/clearings/releases/latest"
    PAGE = "https://github.com/IoriReiMei/clearings/releases"
    LIMIT = 256 * 1024

    def __init__(self):
        self.lock = threading.Lock()
        self.cached = None
        self.checked = 0.0
        self.repository = None

    @staticmethod
    def version(value):
        if not isinstance(value, str) or not re.fullmatch(r"v?(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})", value):
            raise ValueError("Unsupported release version")
        return tuple(int(part) for part in value.removeprefix("v").split("."))

    def check(self):
        if not self.lock.acquire(blocking=False):
            return {"currentVersion": VERSION, "channel": CHANNEL, "status": "checking"}
        try:
            try:
                repository = read_release_config()["updateRepository"]
            except ValueError:
                return {"status": "configuration-error", "currentVersion": VERSION, "repository": None}
            if repository is None:
                return {"status": "disabled", "currentVersion": VERSION, "repository": None}
            if repository != self.repository:
                self.repository = repository
                self.cached = None
            self.URL = f"https://api.github.com/repos/{repository}/releases/latest"
            self.PAGE = f"https://github.com/{repository}/releases"
            base = {"currentVersion": VERSION, "channel": CHANNEL, "pageUrl": self.PAGE,
                    "repository": repository}
            if self.cached is not None and time.monotonic() - self.checked < 900:
                return dict(self.cached)
            result = {**base, "checkedAt": now()}
            try:
                request = urllib.request.Request(self.URL, headers={
                    "Accept": "application/vnd.github+json", "User-Agent": "Clearings-update-check",
                    "X-GitHub-Api-Version": "2026-03-10"})
                deadline = time.monotonic() + 3.0
                with urllib.request.build_opener(NoUpdateRedirects()).open(request, timeout=2) as response:
                    if response.geturl() != self.URL or response.status != 200:
                        raise ValueError("Unexpected update response")
                    raw = bytearray()
                    while True:
                        if time.monotonic() > deadline:
                            raise TimeoutError("Update check took too long")
                        chunk = response.read1(min(16384, self.LIMIT + 1 - len(raw)))
                        if not chunk:
                            break
                        raw.extend(chunk)
                        if len(raw) > self.LIMIT:
                            raise ValueError("Update metadata too large")
                release = json.loads(raw)
                if not isinstance(release, dict) or release.get("draft") is not False or release.get("prerelease") is not False:
                    raise ValueError("Expected a published stable release")
                latest = self.version(release.get("tag_name"))
                current = self.version(VERSION)
                tag = release["tag_name"]
                result.update(status="available" if latest > current else "current",
                              latestVersion=".".join(map(str, latest)),
                              pageUrl=self.PAGE + "/tag/" + tag,
                              requiresRestart=latest > current)
            except urllib.error.HTTPError as error:
                result["status"] = "no-release" if error.code == 404 else "unavailable"
            except (OSError, ValueError, TypeError, AttributeError, RecursionError):
                result["status"] = "unavailable"
            self.checked = time.monotonic()
            self.cached = result
            return dict(result)
        finally:
            self.lock.release()


def source_parts():
    if getattr(sys, "frozen", False):
        raise ValueError("Installed helper updates require a normal restart")
    return {name: read_bounded_bytes(ROOT / "tools" / name, 2 * MAX_BYTES)
            for name in ("clearings_local.py", "clearings_commit.py", "clearings_tray.py")}


def source_host_key(raw):
    """Only Bridge implementation and merge code may change without a restart.

    HTTP/authentication, startup, tray, locking and the update mechanism itself
    must remain the exact same syntax tree. New imports also require a restart.
    """
    tree = ast.parse(raw)
    protected = {"__init__", "home", "handoff_path", "check_maintenance",
                 "begin_maintenance", "end_maintenance", "prepare_shutdown"}
    for entry in tree.body:
        if isinstance(entry, ast.ClassDef) and entry.name == "Bridge":
            if any(not isinstance(part, (ast.FunctionDef, ast.Expr)) for part in entry.body):
                raise ValueError("Bridge class changes require a normal restart")
            entry.body = [part for part in entry.body if isinstance(part, ast.FunctionDef)
                          and part.name in protected]
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()


class RuntimeBridge:
    """Stable host with a replaceable data engine; no listener or token restart."""
    WRITES = {"sync", "propose", "propose_new", "propose_item_edits", "commit_proposal", "commit_completions",
              "decide", "mark", "withdraw", "set_home", "archive_resolved"}

    def __init__(self, bridge):
        self.current = bridge
        self.lock = threading.RLock()
        self.busy = threading.Event()
        self.host_key = None
        self.tray_key = None
        self.on_identity = None
        if not getattr(sys, "frozen", False):
            parts = source_parts()
            self.host_key = source_host_key(parts["clearings_local.py"])
            self.tray_key = hashlib.sha256(parts["clearings_tray.py"]).hexdigest()

    @staticmethod
    def part_hash(parts):
        return hashlib.sha256(b"".join(parts.values())).hexdigest()

    def source_status(self):
        if self.host_key is None:
            return {"status": "installed", "requiresRestart": True}
        try:
            parts = source_parts()
            if (self.part_hash(parts) == self.current.runtime_hash
                    and hashlib.sha256(APP.read_bytes()).hexdigest() == APP_SHA256):
                return {"status": "current", "requiresRestart": False}
            eligible = (source_host_key(parts["clearings_local.py"]) == self.host_key
                        and hashlib.sha256(parts["clearings_tray.py"]).hexdigest() == self.tray_key)
            return {"status": "ready" if eligible else "restart-required", "requiresRestart": not eligible}
        except (ValueError, SyntaxError, OSError):
            return {"status": "invalid", "requiresRestart": True}

    def load_candidate(self, parts):
        if (source_host_key(parts["clearings_local.py"]) != self.host_key
                or hashlib.sha256(parts["clearings_tray.py"]).hexdigest() != self.tray_key):
            raise ValueError("This update changes the helper host; save and restart normally")
        namespace = dict(globals())
        commit = {"__name__": "clearings_hot_commit", "__file__": str(ROOT / "tools/clearings_commit.py")}
        exec(compile(parts["clearings_commit.py"], commit["__file__"], "exec"), commit)
        for name in ("merge_documents", "validate_document", "stamp_attribution"):
            namespace[name] = commit[name]
        namespace["HELPER_SHA256"] = self.part_hash(parts)
        parsed = ast.parse(parts["clearings_local.py"])
        bridge_class = next(part for part in parsed.body if isinstance(part, ast.ClassDef) and part.name == "Bridge")
        exec(compile(ast.Module(body=[bridge_class], type_ignores=[]), str(ROOT / "tools/clearings_local.py"), "exec"), namespace)
        candidate = namespace["Bridge"](self.current.root)
        if candidate.home() != self.current.home():
            raise ValueError("A source update cannot change the saved-data home")
        packet = candidate.read()
        if packet["snapshot"]:
            for document in packet["snapshot"]["documents"]:
                commit["validate_document"](document)
            for proposal in packet["proposals"]:
                if proposal.get("status") == "pending":
                    for name in ("base", "incoming"):
                        if proposal.get(name) is not None:
                            commit["validate_document"](proposal[name])
            candidate.effective_workspace(packet)
        return candidate

    def follow_approved_source(self):
        approved = load_json(self.current.root / "approved-source.json", {})
        if approved.get("helperSha256", self.current.runtime_hash) == self.current.runtime_hash:
            return
        parts = source_parts()
        if approved["helperSha256"] != self.part_hash(parts):
            raise HelperUpdating()
        try:
            self.current = self.load_candidate(parts)
        except (ValueError, OSError, SyntaxError) as exc:
            raise ValueError("Reconnect this MCP client to load the updated helper host") from exc

    def __getattr__(self, name):
        value = getattr(self.current, name)
        if not callable(value):
            return value
        def call(*args, **kwargs):
            if name in self.WRITES and self.busy.is_set():
                raise HelperUpdating()
            with self.lock:
                self.follow_approved_source()
                if name in self.WRITES and self.busy.is_set():
                    raise HelperUpdating()
                return getattr(self.current, name)(*args, **kwargs)
        return call

    def apply_source_update(self):
        if self.on_identity is None:
            raise ValueError("Apply source updates from the human page")
        if self.busy.is_set():
            raise HelperUpdating()
        self.busy.set()
        try:
            with self.lock:
                if self.source_status()["status"] != "ready":
                    raise ValueError("There is no compatible source update ready; restart if the host changed")
                old = self.current
                old.begin_maintenance()
                old_identity = program_identity(old)
                identity_changed = False
                try:
                    old.backup_workspace()
                    parts = source_parts()
                    candidate = self.load_candidate(parts)
                    if parts != source_parts():
                        raise ValueError("Source files changed during validation; retry after editing finishes")
                    identity = {**old_identity, "helperSha256": candidate.runtime_hash,
                                "appSha256": hashlib.sha256(APP.read_bytes()).hexdigest()}
                    self.on_identity(identity)
                    identity_changed = True
                    atomic_json(old.root / "approved-source.json", {"helperSha256": candidate.runtime_hash, "appliedAt": now()})
                    self.current = candidate
                    globals()["HELPER_SHA256"] = candidate.runtime_hash
                    globals()["APP_SHA256"] = identity["appSha256"]
                    return {"applied": True, "requiresRestart": False}
                except BaseException:
                    if identity_changed:
                        self.on_identity(old_identity)
                    raise
                finally:
                    old.end_maintenance()
        finally:
            self.busy.clear()


def handler_for(bridge: Bridge, token: str, port: int, launches=None):
    launches = launches or LaunchState()
    def identity():
        return program_identity(bridge)
    app_updates = AppUpdateCheck()
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)
            self.deadline_timer = threading.Timer(REQUEST_DEADLINE, self.expire)
            self.deadline_timer.daemon = True
            self.deadline_timer.start()

        def expire(self):
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        def finish(self):
            try:
                super().finish()
            finally:
                self.deadline_timer.cancel()

        def log_message(self, _format, *_args):
            return

        def valid_authority(self):
            expected = f"127.0.0.1:{port or self.server.server_port}"
            return self.headers.get_all("Host", []) == [expected]

        def valid_origin(self, *, required=False):
            origins = self.headers.get_all("Origin", [])
            expected = f"http://127.0.0.1:{port or self.server.server_port}"
            return origins == [expected] if required else origins in ([], [expected])

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
            values = self.headers.get_all("X-Clearings-Token", [])
            return len(values) == 1 and hmac.compare_digest(values[0], token)

        def do_GET(self):
            if not self.valid_authority() or not self.valid_origin():
                self.send(403, {"error": "Clearings origin refused"})
                return
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
                html = html.replace(marker, "")
                try:
                    release_config = read_release_config()
                except ValueError:
                    release_config = {"schemaVersion": 1, "updateRepository": None, "error": True}
                html = embed_release_config(html, release_config)
                self.send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/favicon.ico":
                self.send(204, b"", "image/x-icon")
                return
            if path == "/api/identity-proof":
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                challenges = query.get("challenge", [])
                if len(challenges) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{32,80}", challenges[0]):
                    self.send(400, {"error": "Invalid challenge"})
                    return
                self.send(200, {"proof": control_mac(token, "identity", challenges[0],
                                                       identity(), port or self.server.server_port)})
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
                elif path == "/api/app-updates":
                    self.send(200, app_updates.check())
                elif path == "/api/source-update":
                    self.send(200, bridge.source_status() if isinstance(bridge, RuntimeBridge)
                              else {"status": "restart-required", "requiresRestart": True})
                elif path == "/api/handoff":
                    self.send(200, bridge.browser_handoff())
                elif path == "/api/recovery":
                    self.send(200, bridge.recovery_record())
                else:
                    self.send(404, {"error": "Not found"})
            except (ValueError, OSError, KeyError) as exc:
                self.send(409, {"error": str(exc)})

        def do_POST(self):
            if not self.valid_authority() or not self.valid_origin():
                self.send(403, {"error": "Clearings origin refused"})
                return
            path = self.path.split("?", 1)[0]
            if path not in ("/api/bootstrap", "/api/control") and not self.authorized():
                self.send(403, {"error": "Local bridge authorization failed"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                self.send(415, {"error": "Expected JSON"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                limit = 4096 if path in ("/api/bootstrap", "/api/control") else MAX_BYTES
                if size < 0 or size > limit:
                    self.send(413, {"error": "Request exceeds 16 MB"})
                    return
                data = json.loads(self.rfile.read(size))
                if path == "/api/bootstrap":
                    if not self.valid_origin(required=True) or not isinstance(data, dict) or not isinstance(data.get("nonce"), str) or not launches.redeem(data["nonce"]):
                        self.send(403, {"error": "Clearings launch expired or refused"})
                    else:
                        self.send(200, {"token": token})
                    return
                if path == "/api/control":
                    if not isinstance(data, dict):
                        self.send(403, {"error": "Invalid Clearings control"})
                        return
                    op, challenge, proof, stamp = (data.get("op"), data.get("challenge"),
                                                   data.get("proof"), data.get("stamp"))
                    if (op not in ("launch", "shutdown") or not isinstance(challenge, str)
                            or not re.fullmatch(r"[A-Za-z0-9_-]{32,80}", challenge)
                            or type(stamp) is not int
                            or not isinstance(proof, str) or not hmac.compare_digest(proof,
                                control_mac(token, "request-" + op, challenge, identity(),
                                            port or self.server.server_port, str(stamp)))
                            or not launches.claim(challenge, stamp)):
                        self.send(403, {"error": "Invalid Clearings control"})
                        return
                    nonce = launches.issue() if op == "launch" else ""
                    answer = {"proof": control_mac(token, "response-" + op, challenge,
                                                    identity(), port or self.server.server_port, nonce)}
                    if op == "launch":
                        answer["nonce"] = nonce
                    else:
                        bridge.prepare_shutdown()
                    self.send(200, answer)
                    if op == "shutdown":
                        self.wfile.flush()
                        threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                if path == "/api/settings":
                    answer = {"home": bridge.set_home(data["home"])}
                elif path == "/api/apply-source-update":
                    if not isinstance(bridge, RuntimeBridge):
                        raise ValueError("Restart the helper once to enable source updates")
                    answer = bridge.apply_source_update()
                elif path == "/api/sync":
                    answer = bridge.sync(data["workspace"], data["generation"], data.get("expectedGeneration"), data.get("browserRecord"))
                elif path == "/api/propose":
                    answer = bridge.propose(data["base"], data["incoming"], data["actor"], data.get("note", ""), data.get("requestId"))
                elif path == "/api/propose-new":
                    answer = bridge.propose_new(data["incoming"], data["actor"], data.get("note", ""), data.get("requestId"))
                elif path == "/api/commit":
                    answer = bridge.commit_proposal(data["proposalId"], data["author"])
                elif path == "/api/decide":
                    answer = bridge.decide(data["proposalId"], data["choices"], data["actor"])
                elif path == "/api/mark":
                    answer = bridge.mark(data["proposalId"], data["status"], data.get("summary", ""), data["actor"])
                elif path == "/api/shutdown":
                    # Serve the acknowledgement before stopping the loop; this
                    # endpoint is protected by the same local session token.
                    backup = bridge.prepare_shutdown()
                    self.send(200, {"stopping": True, "backup": backup})
                    self.wfile.flush()
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                else:
                    self.send(404, {"error": "Not found"})
                    return
                self.send(200, answer)
            except HelperUpdating as exc:
                self.send(503, {"error": str(exc), "code": exc.code,
                                "retryable": True, "retryAfterMs": exc.retry_after_ms})
            except (ValueError, OSError, KeyError, TypeError, AttributeError, SyntaxError, RuntimeError, json.JSONDecodeError) as exc:
                self.send(409, {"error": str(exc)})
    return Handler


class LocalServer(ThreadingHTTPServer):
    # HTTPServer's SO_REUSEADDR can admit a second listener on Windows. A
    # shortcut must never appear to start successfully while another copy owns
    # the same browser origin.
    # POSIX needs address reuse for the previous connections' TIME_WAIT state.
    # SO_REUSEPORT stays disabled: concurrent listeners are never permitted.
    allow_reuse_address = os.name != "nt"
    allow_reuse_port = False
    daemon_threads = True

    def handle_error(self, request, client_address):
        # A timed-out or deliberately closed local socket is an expected
        # refusal, not a traceback containing application state.
        if isinstance(sys.exc_info()[1], (ConnectionAbortedError, ConnectionResetError,
                                          BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)

    def __init__(self, *args, **kwargs):
        self.request_slots = threading.BoundedSemaphore(MAX_HANDLERS)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.request_slots.acquire(blocking=False):
            try:
                request.settimeout(.2)
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.request_slots.release()

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        # HTTPServer additionally resolves getfqdn(host), which can block on
        # system DNS even for loopback. This local-only server needs no lookup.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def run_server(bridge: Bridge, port: int, open_browser: bool, show_tray: bool = True):
    bridge = RuntimeBridge(bridge)
    session_path = bridge.root / "session.json"
    previous = None
    previous_bytes = None
    if session_path.exists():
        previous_bytes = read_session_bytes(session_path)
        try:
            previous = load_private_session(session_path)
        except RuntimeError:
            outer = load_json(session_path, {})
            if not isinstance(outer, dict) or outer.get("format") == "clearings-protected-session-v1":
                raise
            # Legacy plaintext is preserved but never used as a credential.
    token = secrets.token_urlsafe(32)
    launches = LaunchState()
    try:
        server = LocalServer(("127.0.0.1", port), handler_for(bridge, token, port, launches))
    except OSError as exc:
        # A failed exclusive bind grants no authority. Reuse only an exact
        # protected, same-identity incumbent that answers the MAC challenge.
        if previous and previous["port"] == port and \
                previous["identity"] == program_identity(bridge) and \
                verify_listener(previous, bridge, port):
            if open_browser:
                nonce = authenticated_control(previous, "launch", port).get("nonce")
                if not isinstance(nonce, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,80}", nonce):
                    raise RuntimeError("The proved helper did not issue a valid launch")
                webbrowser.open(f"http://127.0.0.1:{port}/?launch-view={secrets.token_urlsafe(8)}#clearings-launch={nonce}")
            return
        raise RuntimeError(f"Clearings cannot use 127.0.0.1:{port}. Close the other program "
                           "using this address, then reopen Clearings; no data was changed.") from exc
    tray = None
    def open_new_window():
        nonce = launches.issue()
        webbrowser.open(f"http://127.0.0.1:{port}/?launch-view={secrets.token_urlsafe(8)}#clearings-launch={nonce}")
    serving = False
    approved_path = bridge.root / "approved-source.json"
    prior_approval = load_json(approved_path)
    approval_written = False
    def stop_with_backup():
        try:
            bridge.prepare_shutdown()
            server.shutdown()
        except (ValueError, OSError) as exc:
            if sys.stderr is not None:
                print(f"Clearings stays open: {exc}", file=sys.stderr)
            return False
    try:
        # The exclusive bind proves the former listener on this origin is gone.
        # Release its crash-left pause before admitting this replacement host.
        if previous is None or previous.get("port") == port:
            with file_lock(bridge.current.lock_path):
                bridge.current.maintenance_path.unlink(missing_ok=True)
        bridge.current.restore_missing_handoff()
        # The listener remains exclusively bound throughout replacement.
        # Never let an old session be overwritten on a mere connect timeout.
        if previous_bytes is not None:
            if read_session_bytes(session_path) != previous_bytes:
                raise RuntimeError("Clearings session changed during startup; no data was changed")
            preserve_session_bytes(session_path, previous_bytes)
        write_private_session(session_path, {"port": port, "token": token,
                              "identity": program_identity(bridge), "pid": os.getpid(),
                              "startedAt": now()})
        def update_identity(identity):
            session = load_private_session(session_path)
            if not session or not hmac.compare_digest(session["token"], token):
                raise ValueError("Helper session changed; source update was refused")
            write_private_session(session_path, {**session, "identity": identity})
        bridge.on_identity = update_identity
        atomic_json(approved_path, {"helperSha256": bridge.current.runtime_hash, "appliedAt": now()})
        approval_written = True
        if WINDOWS_TRAY and show_tray:
            tray = WindowsTray(title=f"Clearings {VERSION}" + (" · working" if CHANNEL == "working" else ""),
                               address=f"127.0.0.1:{port}", identity=str(bridge.root),
                               open_app=open_new_window,
                               stop_helper=stop_with_backup,
                               startup=windows_startup(bridge.root, port)).start()
        if open_browser:
            open_new_window()
        if sys.stdout is not None:
            print(f"Clearings local helper ready on 127.0.0.1:{port}", flush=True)
        serving = True
        server.serve_forever()
    except BaseException:
        if not serving:
            if approval_written:
                if prior_approval is None:
                    approved_path.unlink(missing_ok=True)
                else:
                    atomic_json(approved_path, prior_approval)
            # Only our own newly written token may be replaced. Restore the
            # former exact bytes when present; its private backup also stays.
            try:
                current = load_private_session(session_path)
                if current and hmac.compare_digest(current["token"], token):
                    if previous_bytes is None:
                        session_path.unlink()
                    else:
                        restore_session_bytes(session_path, previous_bytes)
            except (OSError, RuntimeError):
                pass
        raise
    finally:
        server.server_close()
        if tray is not None:
            tray.close()
        if serving:
            try:
                if bridge.maintenance_id is None:
                    bridge.backup_workspace()
            finally:
                bridge.end_maintenance()


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
    serve.add_argument("--no-tray", action="store_true", help="Run without Windows tray UI for detached tests or headless use")
    startup = sub.add_parser("startup", help="Inspect or change this copy's Windows sign-in registration; do not start the helper")
    startup.add_argument("action", choices=("status", "enable", "disable", "remove-owned"))
    startup.add_argument("--port", type=int, default=PORT)
    stop = sub.add_parser("stop", help="Stop this installation's local helper without changing workspace data")
    stop.add_argument("--installation", help="Exact installed executable path when called by an installer")
    sub.add_parser("status", help="Show handoff state without checklist contents")
    archive = sub.add_parser("archive-resolved", help="Explicitly archive terminal proposal history")
    archive.add_argument("--dry-run", action="store_true", help="Inspect the change without writing")
    sub.add_parser("snapshot", help="Print the last browser-saved workspace JSON")
    sub.add_parser("refresh", help="Read saved workspace and all pending, unapplied AI proposals")
    read = sub.add_parser("read", help="Read one saved checklist or a marked partial branch")
    read.add_argument("--checklist", required=True)
    read.add_argument("--branch")
    propose = sub.add_parser("propose", help="Submit a full-document edit for review")
    propose.add_argument("--base", required=True, type=Path)
    propose.add_argument("--incoming", required=True, type=Path)
    propose.add_argument("--actor", required=True)
    propose.add_argument("--note", default="")
    propose_new = sub.add_parser("propose-new", help="Queue a new unchecked checklist for browser validation and preview")
    propose_new.add_argument("--incoming", required=True, type=Path)
    propose_new.add_argument("--actor", required=True)
    propose_new.add_argument("--note", default="")
    decide = sub.add_parser("decide", help="Suggest choices for listed conflicts")
    decide.add_argument("proposal_id")
    decide.add_argument("--choices", required=True, type=Path)
    decide.add_argument("--actor", required=True)
    complete = sub.add_parser("commit-completions", help="Commit checked-only changes for AI readers and browser Refresh")
    complete.add_argument("proposal_id")
    complete.add_argument("--actor", required=True)
    commit = sub.add_parser("commit-proposal", help="Sign one proposal into the shared AI state")
    commit.add_argument("proposal_id")
    commit.add_argument("--author", required=True)
    withdraw = sub.add_parser("withdraw", help="Withdraw your pending proposal, preserving a receipt")
    withdraw.add_argument("proposal_id")
    withdraw.add_argument("--author", required=True)
    withdraw.add_argument("--reason", required=True)
    args = parser.parse_args()
    if args.command == "startup":
        registration = windows_startup(config_dir(args.config_dir), args.port)
        if args.action == "status":
            result = registration.status()
        elif args.action == "remove-owned":
            result = registration.remove_if_owned()
        else:
            result = registration.set_enabled(args.action == "enable")
        if sys.stdout is not None:
            print(json.dumps(result, indent=2))
        return
    if args.command == "stop" and not config_dir(args.config_dir).exists():
        return
    bridge = Bridge(config_dir(args.config_dir))
    if args.command == "serve":
        run_server(bridge, args.port, not args.no_browser, not args.no_tray)
    elif args.command == "stop":
        stop_server(bridge, installation=args.installation)
    elif args.command == "status":
        packet = bridge.read()
        print(json.dumps({"home": str(bridge.home()), "snapshotAt": packet["snapshotAt"],
                          "generation": packet["generation"], "libraryId": packet["libraryId"],
                          "pending": [{**{k: p[k] for k in ("id", "documentId", "actor", "createdAt")},
                                       "commitId": (p.get("commit") or {}).get("id"),
                                       "signedBy": (p.get("commit") or {}).get("author") or p.get("committedBy")}
                                      for p in packet["proposals"] if p["status"] == "pending"],
                          "resolvedArchives": packet.get("resolvedProposalArchives", []),
                          "recentReceipts": packet["receipts"][-5:]}, indent=2))
    elif args.command == "archive-resolved":
        print(json.dumps(bridge.archive_resolved(dry_run=args.dry_run), indent=2))
    elif args.command == "snapshot":
        print(json.dumps(bridge.read()["snapshot"], ensure_ascii=False, indent=2))
    elif args.command == "refresh":
        print(json.dumps(bridge.refresh_for_ai(), ensure_ascii=False, indent=2))
    elif args.command == "read":
        print(json.dumps(bridge.read_checklist(args.checklist, args.branch), ensure_ascii=False, indent=2))
    elif args.command == "propose":
        print(json.dumps(bridge.propose(load_json(args.base), load_json(args.incoming), args.actor, args.note)))
    elif args.command == "propose-new":
        print(json.dumps(bridge.propose_new(load_json(args.incoming), args.actor, args.note)))
    elif args.command == "decide":
        print(json.dumps(bridge.decide(args.proposal_id, load_json(args.choices), args.actor)))
    elif args.command == "commit-completions":
        print(json.dumps(bridge.commit_completions(args.proposal_id, args.actor)))
    elif args.command == "commit-proposal":
        print(json.dumps(bridge.commit_proposal(args.proposal_id, args.author)))
    elif args.command == "withdraw":
        print(json.dumps(bridge.withdraw(args.proposal_id, args.author, args.reason)))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if sys.stderr is not None:
            print(f"Clearings local helper: {exc}", file=sys.stderr)
        interactive_launch = (len(sys.argv) == 1 or "serve" in sys.argv) and "--no-browser" not in sys.argv
        if interactive_launch and (getattr(sys, "frozen", False) or sys.executable.lower().endswith("pythonw.exe")):
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
        raise SystemExit(1)
