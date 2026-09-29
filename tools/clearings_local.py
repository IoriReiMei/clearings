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
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser

from clearings_commit import merge_documents, validate_document, stamp_attribution

MAX_BYTES = 16 * 1024 * 1024
FILE_NAME = "clearings_handoff.json"
VERSION = "0.4.3"
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
                 else hashlib.sha256(Path(__file__).read_bytes() + Path(__file__).with_name("clearings_commit.py").read_bytes()).hexdigest())
APP_SHA256 = hashlib.sha256(APP.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def retain_proposals(proposals):
    """Never evict pending work to make room for resolved history."""
    resolved = {p["id"] for p in proposals if p["status"] != "pending"}
    recent = {p["id"] for p in [p for p in proposals if p["id"] in resolved][-150:]}
    return [p for p in proposals if p["status"] == "pending" or p["id"] in recent]


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
    """Stop only the authenticated helper for this exact installed program."""
    session = load_json(bridge.root / "session.json", {})
    if not session.get("token") or not session.get("port"):
        return False
    port = session["port"]
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Invalid saved helper port")
    headers = {"X-Clearings-Token": session["token"]}
    try:
        with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/identity", headers=headers), timeout=2) as response:
            identity = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError("The running helper could not verify this installation. Close it before updating; no files were changed.") from exc
    except urllib.error.URLError as exc:
        # Refused connection means no listener; timeout/other errors do not.
        if isinstance(exc.reason, ConnectionRefusedError) or getattr(exc.reason, "winerror", None) == 10061:
            return False
        raise RuntimeError("Cannot verify the running helper; no files were changed.") from exc
    expected = program_identity(bridge)
    expected_program = str(Path(installation).resolve()) if installation else expected["program"]
    if (identity.get("program") != expected_program or identity.get("config") != expected["config"] or identity.get("channel") != expected["channel"]):
        raise RuntimeError("A different Clearings installation owns this address; close it before updating.")
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/shutdown", data=b"{}", headers={**headers, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            if json.load(response) != {"stopping": True}:
                raise RuntimeError("Helper did not acknowledge shutdown")
    except urllib.error.HTTPError as exc:
        if exc.code != 404 or not installation or CHANNEL != "release":
            raise
        stop_legacy_windows_process(session.get("pid"), expected_program)
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
                pid = session.get("pid")
                if os.name == "nt" and type(pid) is int and pid != os.getpid():
                    import ctypes
                    from ctypes import wintypes
                    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                    kernel.OpenProcess.restype = wintypes.HANDLE
                    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                    handle = kernel.OpenProcess(0x00100000, False, pid)
                    if handle:
                        try:
                            if kernel.WaitForSingleObject(handle, 10000) != 0:
                                raise RuntimeError("The helper process is still exiting; retry before updating files")
                        finally:
                            kernel.CloseHandle(handle)
                return True
            except OSError:
                time.sleep(.1)
    raise RuntimeError("The helper has not released its address; no files were changed.")


def config_dir(override: str | None = None) -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local"))
    name = "Clearings-Release" if CHANNEL == "release" else "Clearings"
    return Path(override or os.environ.get("CLEARINGS_CONFIG_DIR") or base / name).resolve()


def program_identity(bridge: "Bridge") -> dict:
    """Only a server for these exact app bytes and this installation may be reused."""
    program = PROGRAM
    identity = {"channel": CHANNEL, "appSha256": APP_SHA256,
                "program": str(program), "config": str(bridge.root.resolve())}
    if HELPER_SHA256 is not None:
        identity["helperSha256"] = HELPER_SHA256
    return identity


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
        validate_document(base)
        validate_document(incoming)

        def edit(packet):
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
            packet["proposals"] = retain_proposals(packet["proposals"])
            return {"proposalId": proposal["id"], "documentId": doc_id}
        return self.change(edit)

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
            if proposal is None or proposal["status"] != "pending":
                raise ValueError("Pending proposal not found")
            if proposal.get("commit"):
                if proposal["commit"]["author"] != author:
                    raise ValueError("This commit already has another author")
                return {"proposalId": proposal_id, "commit": proposal["commit"],
                        "alreadyCommitted": True}
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
            return {"proposalId": proposal_id, "commit": commit,
                    "alreadyCommitted": False}
        return self.change(edit)

    def propose_new(self, incoming: dict, actor: str, note: str = ""):
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
                    self.send(200, bridge.browser_handoff())
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
                elif path == "/api/propose-new":
                    answer = bridge.propose_new(data["incoming"], data["actor"], data.get("note", ""))
                elif path == "/api/commit":
                    answer = bridge.commit_proposal(data["proposalId"], data["author"])
                elif path == "/api/decide":
                    answer = bridge.decide(data["proposalId"], data["choices"], data["actor"])
                elif path == "/api/mark":
                    answer = bridge.mark(data["proposalId"], data["status"], data.get("summary", ""), data["actor"])
                elif path == "/api/shutdown":
                    # Serve the acknowledgement before stopping the loop; this
                    # endpoint is protected by the same local session token.
                    self.send(200, {"stopping": True})
                    self.wfile.flush()
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
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
    # POSIX needs address reuse for the previous connections' TIME_WAIT state.
    # SO_REUSEPORT stays disabled: concurrent listeners are never permitted.
    allow_reuse_address = os.name != "nt"
    allow_reuse_port = False

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        # HTTPServer additionally resolves getfqdn(host), which can block on
        # system DNS even for loopback. This local-only server needs no lookup.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def run_server(bridge: Bridge, port: int, open_browser: bool):
    session_path = bridge.root / "session.json"
    previous = load_json(session_path, {})
    if previous.get("port") == port and previous.get("token"):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/identity",
                                     headers={"X-Clearings-Token": previous["token"]})
        try:
            with urllib.request.urlopen(req, timeout=1) as response:
                identity = json.load(response)
                expected = program_identity(bridge)
                if identity == expected:
                    if open_browser:
                        webbrowser.open(f"http://127.0.0.1:{port}/")
                    return
                same_working_helper = (isinstance(identity, dict)
                    and "helperSha256" in identity
                    and all(identity.get(key) == expected[key]
                            for key in ("channel", "program", "config")))
                if not same_working_helper:
                    raise RuntimeError("Another Clearings copy or version is running on this address. "
                                       "Close that Clearings helper before opening this one; no data was changed.")
                shutdown = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/shutdown", data=b"{}",
                    headers={"X-Clearings-Token": previous["token"],
                             "Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(shutdown, timeout=2) as stopped:
                        if json.load(stopped) != {"stopping": True}:
                            raise RuntimeError("The earlier Clearings helper did not acknowledge a restart.")
                except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                    raise RuntimeError("The earlier Clearings helper could not be restarted. "
                                       "Close it before opening this one; no data was changed.") from exc
                for _ in range(30):
                    try:
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                            if os.name == "nt":
                                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                            else:
                                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                            probe.bind(("127.0.0.1", port))
                            probe.listen(1)
                        break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("The earlier Clearings helper did not release its address. "
                                       "Close it before opening this one; no data was changed.")
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
    stop = sub.add_parser("stop", help="Stop this installation's local helper without changing workspace data")
    stop.add_argument("--installation", help="Exact installed executable path when called by an installer")
    sub.add_parser("status", help="Show handoff state without checklist contents")
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
    if args.command == "stop" and not config_dir(args.config_dir).exists():
        return
    bridge = Bridge(config_dir(args.config_dir))
    if args.command == "serve":
        run_server(bridge, args.port, not args.no_browser)
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
                          "recentReceipts": packet["receipts"][-5:]}, indent=2))
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
