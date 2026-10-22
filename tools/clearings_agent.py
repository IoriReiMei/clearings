# SPDX-License-Identifier: MIT
# Copyright (c) 2026 The Hermit. See ../LICENSE.
"""Bounded agent views over the supported Bridge; no direct workspace writes."""
from __future__ import annotations

from collections import OrderedDict
import copy
import hashlib
import json
import secrets
import time
from threading import RLock

from clearings_commit import DOC_FIELDS, ITEM_FIELDS, merge_documents, stamp_attribution, validate_document
from clearings_local import Bridge, HelperUpdating, VERSION, now


def failure(exc):
    """Stable, actionable error envelope, also usable when the workspace cannot load."""
    message = str(exc)
    code, action, retry = "INVALID_REQUEST", "Correct the request using the guide and current read.", False
    if isinstance(exc, HelperUpdating):
        return {"code": exc.code, "message": message, "retryable": True,
                "retryAfterMs": exc.retry_after_ms,
                "nextAction": "Wait the stated interval, then retry the identical request and request_id."}
    if "Reconnect this MCP" in message or "helper host" in message:
        code, action = "RECONNECT_REQUIRED", "Reconnect this Clearings MCP server when safe. Do not restart other active work."
    elif "Unrecognized handoff" in message or "No browser-saved workspace" in message:
        code, action = "WORKSPACE_UNAVAILABLE", "Confirm the intended configured home and browser save. Preserve existing data; do not overwrite it to force recovery."
    elif "STALE_ITEM" in message:
        code, action = "STALE_ITEM", "Read the item again, reconcile the change, then use a new request_id."
    elif "EXPIRED" in message:
        code, action = "CONTEXT_EXPIRED", "Start a fresh briefing. For a handoff, check existing proposals and receipts before preparing again; do not duplicate an uncertain save."
    elif "request ID was already used" in message:
        code, action = "REQUEST_ID_REUSED", "Use the original payload for a retry, or a new ID for a different change."
    elif "conflict" in message.lower() or "closed" in message.lower():
        code, action = "CONFLICT", "Read the current checklist and proposal preview; reconcile without overwriting other work."
    elif "NOT_FOUND" in message or "not found" in message.lower() or "Unknown checklist" in message:
        code, action = "NOT_FOUND", "List current checklists and read the intended task or proposal."
    elif isinstance(exc, OSError):
        code, action = "STORAGE_UNAVAILABLE", "Check the configured home and access. Preserve existing data; do not recreate it."
        # Do not expose local paths from operating-system exceptions.
        message = type(exc).__name__ + ": Clearings could not access its configured storage."
    return {"code": code, "message": message, "retryable": retry, "nextAction": action}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def bounded(value, limit=262144):
    if len(encoded(value)) > limit:
        raise ValueError("Result exceeds 256 KiB; use a smaller selection or the full checklist workflow")
    return value


class SessionCache:
    """Opaque short-lived handles, bounded in both count and bytes; never saved as memory."""
    def __init__(self, clock=time.monotonic, max_bytes=8 * 1024 * 1024):
        self.clock, self.max_bytes = clock, max_bytes
        self.entries = OrderedDict()
        self.lock = RLock()

    def put(self, kind, value):
        with self.lock:
            return self._put(kind, value)

    def _put(self, kind, value):
        size = len(encoded(value))
        if size > self.max_bytes:
            raise ValueError("Selection exceeds the session cache limit; select one smaller checklist or task")
        self._expire()
        while self.entries and (len(self.entries) >= 64 or sum(e[3] for e in self.entries.values()) + size > self.max_bytes):
            self.entries.popitem(last=False)
        token = secrets.token_urlsafe(24)
        self.entries[token] = (self.clock() + 1800, kind, copy.deepcopy(value), size)
        return token

    def _expire(self):
        for token, entry in list(self.entries.items()):
            if entry[0] <= self.clock():
                del self.entries[token]

    def get(self, token, kind):
        with self.lock:
            self._expire()
            entry = self.entries.get(token)
            if entry is None or entry[1] != kind:
                raise ValueError("CONTEXT_EXPIRED: Unknown, expired or wrong-kind session handle")
            return copy.deepcopy(entry[2])


class AgentWorkspace:
    def __init__(self, bridge, actor, allow_write=False, cache=None):
        self.bridge, self.actor, self.allow_write = bridge, actor, allow_write
        self.cache = cache or SessionCache()

    def snapshot(self):
        packet = self.bridge.read()
        workspace, awaiting, conflicts = self.bridge.effective_workspace(packet)
        return packet, workspace, awaiting, conflicts

    @staticmethod
    def document(workspace, checklist_id):
        document = next((d for d in (workspace or {}).get("documents", []) if d["documentId"] == checklist_id), None)
        if document is None:
            raise ValueError("CHECKLIST_NOT_FOUND: No effective checklist with that ID")
        return document

    def status(self):
        result = {"actor": self.actor, "identityVerified": False, "adapterVersion": VERSION,
                  "writeToolsExposed": self.allow_write, "writeProbePerformed": False,
                  "browserHelperConnection": "not-probed", "readReady": False,
                  "writeReadiness": "unavailable", "checkedAt": now(),
                  "sessionHandles": "Expire after 30 minutes, cache eviction or MCP reconnect"}
        try:
            result["source"] = self.bridge.source_status()
            result["engineFingerprint"] = self.bridge.current.runtime_hash
            packet, workspace, awaiting, conflicts = self.snapshot()
            result.update(readReady=True, workspaceAvailable=workspace is not None,
                          libraryId=packet["libraryId"], generation=packet["generation"],
                          snapshotAt=packet["snapshotAt"], committedAwaitingBrowser=len(awaiting),
                          committedConflictCount=len(conflicts))
            busy = self.bridge.busy.is_set()
            result["writeReadiness"] = ("read-only" if not self.allow_write else "paused" if busy
                                         else "eligible" if workspace is not None else "needs-browser-save")
            result["nextAction"] = ("Read the current task, then propose only authorized changes. Commit checks still apply."
                                     if workspace is not None else "Open the intended browser workspace and let it save and sync.")
            if not self.allow_write:
                result["nextAction"] = "This connection is read-only. Use an authorized write connection or an exported proposal."
            elif busy:
                result["nextAction"] = "The data engine is updating. Retry after 1000 ms with the identical request."
        except (ValueError, KeyError, OSError, HelperUpdating) as exc:
            result["problem"] = failure(exc)
            result["nextAction"] = result["problem"]["nextAction"]
        return result

    def read_item(self, checklist_id, item_id):
        packet, workspace, _, conflicts = self.snapshot()
        doc = self.document(workspace, checklist_id)
        revision = Bridge.item_revision(doc, item_id, packet["libraryId"])
        items = {i["id"]: i for i in doc["model"]["items"]}
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
        closed = sorted(key for key in ancestors | {item_id} if doc["state"].get(key) is True)
        return bounded({"checklistId": checklist_id, "libraryId": packet["libraryId"],
                        "generation": packet["generation"], "snapshotAt": packet["snapshotAt"],
                        "partial": True, "notAFullDocumentProposalBase": True,
                        "revision": revision, "item": items[item_id],
                        "completed": doc["state"].get(item_id) is True,
                        "attribution": doc.get("attribution", {}).get(item_id, {}),
                        "archived": doc["archived"], "closedScope": bool(closed),
                        "closedScopeIds": closed[:50], "closedScopeCount": len(closed),
                        "ancestors": [{"itemId": key, "text": items[key]["text"][:160]}
                                      for key in sorted(ancestors)[:50]],
                        "ancestorCount": len(ancestors),
                        "committedConflicts": [c for c in conflicts if c["documentId"] == checklist_id],
                        "nextAction": "Use revision with propose_item_edits; structural changes require the full effectiveDocument."})

    def briefing(self, for_actor=None, checklist_id=None, since=None, cursor=None, limit=20):
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        target = self.actor if for_actor is None else for_actor.strip()
        if not 1 <= len(target) <= 80:
            raise ValueError("for_actor must be 1-80 nonblank characters")
        filters = [target.casefold(), checklist_id, since]
        if cursor:
            page = self.cache.get(cursor, "briefing-page")
            if page["filters"] != filters:
                raise ValueError("Keep the same actor, checklist and since when following a cursor")
        else:
            packet, workspace, awaiting, conflicts = self.snapshot()
            if checklist_id is not None:
                self.document(workspace, checklist_id)
            previous = self.cache.get(since, "checkpoint") if since else None
            if previous and (previous["scope"] != filters[:2] or previous["libraryId"] != packet["libraryId"]):
                raise ValueError("The checkpoint belongs to a different library, actor or checklist")
            current, relevant = {}, set()
            for doc in (workspace or {}).get("documents", []):
                if doc["archived"] or (checklist_id is not None and doc["documentId"] != checklist_id):
                    continue
                for item in doc["model"]["items"]:
                    assignment = item.get("assignment") or {}
                    assigned = assignment.get("assignee", "").casefold() == target.casefold()
                    response_author = doc.get("attribution", {}).get(item["id"], {}).get("response", {}).get("actor", "")
                    review = bool(item.get("needsReview") and (not assignment or assigned)
                                  and response_author.casefold() != target.casefold())
                    key = doc["documentId"] + "/" + item["id"]
                    completed = doc["state"].get(item["id"]) is True
                    if (assigned and not completed and assignment.get("status") in ("pending", "accepted")) or review:
                        relevant.add(key)
                    if key not in relevant and key not in (previous or {}).get("items", {}):
                        continue
                    row = {"checklistId": doc["documentId"], "itemId": item["id"],
                           "title": item["text"][:160], "completed": doc["state"].get(item["id"]) is True,
                           "assignment": {k: assignment.get(k) for k in ("assignee", "role", "status")} if assignment else None,
                           "needsReview": bool(item.get("needsReview")), "response": item.get("response", "")[:240]}
                    fingerprint = hashlib.sha256(encoded([item, doc["state"].get(item["id"], False),
                                                          doc.get("attribution", {}).get(item["id"], {})])).hexdigest()
                    current[key] = {"hash": fingerprint, "row": row}
            keys = relevant if previous is None else relevant | set(previous["relevant"])
            rows = []
            for key in sorted(keys):
                old = (previous or {}).get("items", {}).get(key)
                item = current.get(key)
                if previous and item and old and item["hash"] == old["hash"]:
                    continue
                row = copy.deepcopy((item or old)["row"])
                row["change"] = "current" if previous is None else "left-scope" if item is None else "changed" if old else "new"
                rows.append(row)
            checkpoint = {"scope": filters[:2], "libraryId": packet["libraryId"],
                          "items": {key: current[key] for key in relevant}, "relevant": sorted(relevant)}
            # Page state holds its final checkpoint until the last page, so unread rows cannot be skipped.
            page = {"filters": filters, "rows": rows, "offset": 0, "checkpoint": checkpoint,
                    "meta": {"forActor": target, "libraryId": packet["libraryId"],
                             "generation": packet["generation"], "snapshotAt": packet["snapshotAt"],
                             "observedAt": now(), "totalItems": len(rows),
                             "committedAwaitingBrowserCount": len(awaiting),
                             "conflicts": [{"proposalId": c["proposalId"], "checklistId": c["documentId"],
                                            "reason": c["reason"][:240]} for c in conflicts[:50]],
                             "conflictCount": len(conflicts),
                             "pendingProposals": [{"proposalId": p["id"], "checklistId": p["documentId"],
                                                   "actor": p["actor"], "committed": bool(p.get("commit"))}
                                                  for p in packet["proposals"] if p["status"] == "pending"][:100]}}
        offset = page["offset"]
        result = {**page["meta"], "items": page["rows"][offset:offset + limit],
                  "partial": True, "notAProposalBase": True, "nextCursor": None, "checkpoint": None,
                  "scope": "Active assignments and replies needing attention for this actor; changes include tasks leaving that scope.",
                  "notice": "Labels are not verified identities or agent liveness. Handles expire after 30 minutes, eviction or reconnect."}
        page["offset"] += limit
        if page["offset"] < len(page["rows"]):
            result["nextCursor"] = self.cache.put("briefing-page", page)
        else:
            result["checkpoint"] = self.cache.put("checkpoint", page["checkpoint"])
        return bounded(result)

    def preview(self, proposal_id, offset=0, limit=25):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Use a nonnegative offset and a limit from 1 to 50")
        packet = self.bridge.read()
        proposal = next((p for p in packet["proposals"] if p["id"] == proposal_id), None)
        if proposal is None:
            raise ValueError("Proposal not found; a retained commit receipt may still be available by repeating commit")
        effective, _, held = self.bridge.effective_workspace(packet, exclude_id=proposal_id)
        incoming, base = proposal["incoming"], proposal.get("base")
        current = next((d for d in (effective or {}).get("documents", []) if d["documentId"] == proposal["documentId"]), None)
        conflicts = [c["reason"] for c in held if c["documentId"] == proposal["documentId"]]
        before, after = base, incoming
        applied = 0
        if proposal.get("kind") == "create":
            if current:
                conflicts.append("Checklist ID already exists")
            applied = len(incoming["model"]["items"]) + 1
        elif current is None:
            conflicts.append("Checklist is missing")
        else:
            merged = merge_documents(base, current, incoming)
            conflicts.extend(merged["conflicts"])
            applied = merged["applied"]
            if not conflicts:
                before, after = current, merged["merged"]
                # Derived review flags are part of the preview too. This internal
                # synthetic stamp is not returned as a commit or actual receipt.
                stamp_attribution(after, before, {"actor": proposal["actor"], "role": "assistant", "at": now()})
            if effective["index"].get("defaultChecklist") == proposal["documentId"] and merged["merged"]["archived"]:
                conflicts.append("The default checklist cannot be archived")
        position = packet["proposals"].index(proposal)
        if any(p["status"] == "pending" and p["documentId"] == proposal["documentId"]
               and not p.get("requiresCommit") and not p.get("commit") and not p.get("committedAt")
               for p in packet["proposals"][:position]):
            conflicts.append("An older unsigned proposal awaits browser Refresh")
        changes = []

        def add(item_id, field, old, new):
            if old != new:
                def excerpt(value):
                    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
                    return {"text": text[:240], "truncated": len(text) > 240}
                changes.append({"itemId": item_id, "field": field, "before": excerpt(old), "after": excerpt(new)})

        for field in DOC_FIELDS:
            add(None, field, (before or {}).get(field), after.get(field))
        old_items = {i["id"]: i for i in (before or {}).get("model", {}).get("items", [])}
        new_items = {i["id"]: i for i in after["model"]["items"]}
        for key in sorted(old_items.keys() | new_items.keys()):
            old, new = old_items.get(key), new_items.get(key)
            if old is None or new is None:
                add(key, "item", old, new)
            else:
                for field in ITEM_FIELDS:
                    add(key, field, old.get(field), new.get(field))
            add(key, "completed", (before or {}).get("state", {}).get(key, False), after["state"].get(key, False))
        for field in ("roots", "branches"):
            add(None, "model." + field, (before or {}).get("model", {}).get(field), after["model"].get(field))
        return bounded({"proposalId": proposal_id, "actor": proposal["actor"], "status": proposal["status"],
                        "commit": proposal.get("commit"), "generation": packet["generation"],
                        "conflicts": conflicts[:50], "conflictCount": len(conflicts),
                        "readyToCommitAtRead": not conflicts and bool(applied) and proposal["status"] == "pending"
                                               and not proposal.get("commit") and not proposal.get("committedAt"),
                        "changes": changes[offset:offset + limit], "totalChanges": len(changes),
                        "nextOffset": offset + limit if offset + limit < len(changes) else None,
                        "note": "Excerpts are not edit payloads. Commit rechecks the latest state; browser incorporation does not prove human review."})

    def draft_receipt(self, receipt):
        try:
            return {**receipt, "preview": self.preview(receipt["proposalId"]), "savedAs": "proposal"}
        except (ValueError, KeyError, OSError, HelperUpdating) as exc:
            return {**receipt, "previewUnavailable": failure(exc), "savedAs": "proposal"}

    def commit(self, proposal_id):
        receipt = self.bridge.commit_proposal(proposal_id, self.actor)
        # A successful write must never be reported as failed because a later read failed.
        try:
            packet, _, awaiting, conflicts = self.snapshot()
            delivery = "unknown"
            if any(x["proposalId"] == proposal_id for x in conflicts):
                delivery = "conflict-needs-review"
            elif any(x["proposalId"] == proposal_id for x in awaiting):
                delivery = "committed-awaiting-browser"
            elif any(x.get("proposalId") == proposal_id and x.get("status") in ("applied", "already-current")
                     for x in packet["receipts"]):
                delivery = "incorporated-by-browser"
            return {**receipt, "delivery": delivery, "humanReviewConfirmed": False,
                    "nextAction": "Human: use Refresh Clearings for awaiting changes. AI: re-read the effective task to verify."}
        except (ValueError, KeyError, OSError, HelperUpdating) as exc:
            return {**receipt, "delivery": "unknown", "deliveryCheckProblem": failure(exc), "humanReviewConfirmed": False}

    def prepare_handoff(self, checklist_id, item_ids, goal, progress, next_step, decisions="",
                        evidence="", open_questions="", parent_item_id=None, recipient=None, recipient_role="assistant"):
        if not isinstance(item_ids, list) or not 1 <= len(item_ids) <= 25 or any(not isinstance(k, str) for k in item_ids) or len(set(item_ids)) != len(item_ids):
            raise ValueError("Select 1-25 distinct source item IDs")
        fields = {"Goal": goal, "Decisions and reasons": decisions, "Progress": progress,
                  "Evidence and files": evidence, "Open questions": open_questions, "Next step": next_step}
        if any(not isinstance(v, str) or len(v) > 12000 for v in fields.values()) or not all(fields[k].strip() for k in ("Goal", "Progress", "Next step")):
            raise ValueError("Goal, progress and next_step are required; each context section is limited to 12,000 characters")
        if recipient_role not in ("human", "assistant") or (recipient is not None and (not isinstance(recipient, str) or not 1 <= len(recipient.strip()) <= 80)):
            raise ValueError("Use a 1-80 character recipient and human or assistant role")
        packet, workspace, _, conflicts = self.snapshot()
        base = self.document(workspace, checklist_id)
        if any(c["documentId"] == checklist_id for c in conflicts):
            raise ValueError("Resolve committed conflicts before preparing context")
        items = {item["id"]: item for item in base["model"]["items"]}
        sources = [{"checklistId": checklist_id, "itemId": key,
                    "revision": Bridge.item_revision(base, key, packet["libraryId"]),
                    "title": items[key]["text"][:160], "completed": base["state"].get(key) is True} for key in item_ids]
        incoming = copy.deepcopy(base)
        key = "context-" + secrets.token_hex(12)
        text = "# Working context\n\n" + "\n\n".join("## " + name + "\n" + (value.strip() or "Not recorded.") for name, value in fields.items())
        text += "\n\n## Source tasks\n" + "\n".join("- " + source["checklistId"] + "/" + source["itemId"] + " (recorded check: " + str(source["completed"]).lower() + "; revision: " + source["revision"] + ")" for source in sources)
        text += "\n\nPrepared by " + self.actor + " at " + now() + ". Read current tasks and project instructions before resuming. Saved context does not notify an agent."
        item = {"id": key, "text": "Working context — " + (recipient.strip() if recipient else self.actor),
                "detail": text, "parents": [], "requires": [], "tags": ["context", "handoff"], "label": "",
                "order": max((i["order"] for i in items.values()), default=0) + 1}
        if recipient:
            item["assignment"] = {"id": "assignment-" + secrets.token_hex(12), "assignee": recipient.strip(),
                                  "role": recipient_role, "status": "pending", "note": "Read the working context before accepting."}
        incoming["model"]["items"].append(item)
        incoming["state"][key] = False
        if parent_item_id is not None:
            parent = next((i for i in incoming["model"]["items"] if i["id"] == parent_item_id and i["id"] != key), None)
            if parent is None:
                raise ValueError("ITEM_NOT_FOUND: The parent task does not exist")
            parent["requires"].append(key)
        else:
            incoming["model"]["roots"].append(key)
        validate_document(incoming)
        result = merge_documents(base, base, incoming)
        if result["conflicts"]:
            raise ValueError("Context conflicts with a closed scope: " + ", ".join(result["conflicts"]))
        payload = {"base": base, "incoming": incoming, "sources": sources, "libraryId": packet["libraryId"]}
        token = self.cache.put("handoff", payload)
        return bounded({"handoffToken": token, "contextItemId": key, "parentItemId": parent_item_id,
                        "sources": sources, "text": text, "saved": False,
                        "nextAction": "Review these notes, then propose_handoff and commit. Reuse this context item for later notes with focused edits."})

    def propose_handoff(self, handoff_token, request_id):
        if not request_id:
            raise ValueError("A handoff proposal requires a request_id")
        handoff = self.cache.get(handoff_token, "handoff")
        # Frozen payload gives the normal persistent request-ID mechanism identical retries.
        receipt = self.bridge.propose(handoff["base"], handoff["incoming"], self.actor,
                                     "Save working context; no message sent", request_id,
                                     expected_library_id=handoff["libraryId"])
        return self.draft_receipt(receipt)
