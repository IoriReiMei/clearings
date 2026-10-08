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
"""Pure, conservative Clearings document merge for the local AI handoff.

The browser retains its independent validator and merge. This module refuses
anything it cannot safely represent, so a committed handoff never depends on
an unreviewed browser-side repair.
"""
from __future__ import annotations

import copy
from datetime import datetime
import math
import re

ID = re.compile(r"[A-Za-z0-9._-]{1,200}\Z")
FORBIDDEN = {"__proto__", "prototype", "constructor"}
DOC_FIELDS = ("title", "subtitle", "description", "footer", "archived", "references")
ITEM_FIELDS = ("text", "detail", "label", "tags", "parents", "requires", "order")
MEANING_FIELDS = ("text", "detail", "label", "tags", "parents", "requires")


def valid_id(value):
    return isinstance(value, str) and bool(ID.fullmatch(value)) and value not in FORBIDDEN


def _keys(value, allowed, label):
    if not isinstance(value, dict) or set(value) != set(allowed):
        raise ValueError(f"Invalid {label} fields")


def _distinct(value, label):
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value) or len(value) != len(set(value)):
        raise ValueError(f"Invalid {label} IDs")


def validate_document(document):
    """Check the native version-2 structure and links before AI-side commit."""
    _keys({k: v for k, v in document.items() if k != "attribution"}, ("format", "schemaVersion", "documentId", *DOC_FIELDS,
                     "updatedAt", "model", "state", "view"), "checklist")
    if document.get("format") not in ("checklist-studio-document", "local-companion-checklist") or document.get("schemaVersion") != 2 or not valid_id(document.get("documentId")):
        raise ValueError("Invalid checklist format or identity")
    for name in ("title", "subtitle", "description", "footer"):
        if not isinstance(document.get(name), str) or len(document[name]) > 200000:
            raise ValueError(f"Invalid checklist {name}")
    if not document["title"].strip() or not isinstance(document.get("archived"), bool):
        raise ValueError("Invalid checklist title or archive state")
    stamp = document.get("updatedAt")
    if stamp is not None:
        if not isinstance(stamp, str):
            raise ValueError("Invalid checklist saved time")
        try:
            datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Invalid checklist saved time") from exc
    if not isinstance(document.get("references"), list):
        raise ValueError("Invalid checklist references")
    for reference in document["references"]:
        _keys(reference, ("title", "href"), "reference")
        if not isinstance(reference.get("title"), str) or not isinstance(reference.get("href"), str):
            raise ValueError("Invalid checklist reference")
        href = reference["href"]
        edge_space = " \t\n\r\f\v\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
        if (not href or href[0] in edge_space or href[-1] in edge_space or len(href) > 2000 or
                any(ord(c) < 32 or ord(c) == 127 for c in href) or "\\" in href or
                href.startswith(("//", "\\\\")) or
                (re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", href) and not href.lower().startswith(("http://", "https://")))):
            raise ValueError("Unsafe checklist reference")
    model = document.get("model")
    _keys(model, ("branches", "roots", "items"), "model")
    if not isinstance(model.get("branches"), list) or len(model["branches"]) > 2000 or not isinstance(model.get("items"), list) or len(model["items"]) > 20000:
        raise ValueError("Invalid checklist size")
    _distinct(model.get("roots"), "root")
    branches = set()
    for branch in model["branches"]:
        _keys(branch, ("id", "title"), "branch")
        if not valid_id(branch.get("id")) or branch["id"] in branches or not isinstance(branch.get("title"), str):
            raise ValueError("Invalid checklist branch")
        branches.add(branch["id"])
    items = {}
    for item in model["items"]:
        _keys(item, ("id", *ITEM_FIELDS), "item")
        key = item.get("id")
        if not valid_id(key) or key in items:
            raise ValueError("Invalid or duplicate item ID")
        for name in ("text", "detail", "label"):
            if not isinstance(item.get(name), str) or len(item[name]) > 200000:
                raise ValueError(f"Invalid item {name}")
        if (not item["text"].strip() or type(item.get("order")) not in (int, float)
                or not math.isfinite(item["order"])):
            raise ValueError("Invalid item title or order")
        for name in ("parents", "tags", "requires"):
            _distinct(item.get(name), name)
        if any(parent not in branches for parent in item["parents"]):
            raise ValueError("Item refers to a missing category")
        items[key] = item
    if any(key not in items for key in model["roots"]):
        raise ValueError("Missing root item")
    if any(child not in items for item in items.values() for child in item["requires"]):
        raise ValueError("Missing supporting item")
    state = document.get("state")
    if not isinstance(state, dict) or any(key not in items or type(value) is not bool for key, value in state.items()):
        raise ValueError("Invalid checkmark state")
    view = document.get("view")
    _keys(view, ("collapsed",), "view")
    _distinct(view.get("collapsed"), "collapsed")
    if any(key not in items for key in view["collapsed"]):
        raise ValueError("Fold refers to a missing item")
    seen, visiting = set(), set()
    def visit(start):
        stack = [(start, False, 0)]
        while stack:
            key, leaving, depth = stack.pop()
            if leaving:
                visiting.remove(key)
                seen.add(key)
            elif key not in seen:
                if key in visiting or depth > 96:
                    raise ValueError("Checklist has a cycle or excessive depth")
                visiting.add(key)
                stack.append((key, True, depth))
                stack.extend((child, False, depth + 1) for child in reversed(items[key]["requires"]))
    for root in model["roots"]:
        visit(root)
    if len(seen) != len(items):
        raise ValueError("Some items are unreachable")
    attribution = document.get("attribution", {})
    if not isinstance(attribution, dict) or any(key not in items for key in attribution):
        raise ValueError("Invalid item attribution")
    for record in attribution.values():
        if not isinstance(record, dict) or set(record) - {"created", "completed"}:
            raise ValueError("Invalid attribution record")
        for stamp in record.values():
            if (not isinstance(stamp, dict) or set(stamp) - {"actor", "role", "at", "commitId", "approvedBy"}
                    or not isinstance(stamp.get("actor"), str) or not stamp["actor"].strip()
                    or len(stamp["actor"]) > 80 or stamp.get("role") not in {"human", "assistant"}):
                raise ValueError("Invalid attribution stamp")
            try:
                datetime.fromisoformat(stamp["at"].replace("Z", "+00:00"))
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                raise ValueError("Invalid attribution time") from exc
            if stamp.get("commitId") is not None and not valid_id(stamp["commitId"]):
                raise ValueError("Invalid attribution commit")
            if stamp.get("approvedBy") is not None and (not isinstance(stamp["approvedBy"], str) or not stamp["approvedBy"].strip() or len(stamp["approvedBy"]) > 80):
                raise ValueError("Invalid attribution approver")
    return document


def stamp_attribution(document, before, stamp):
    """Derive durable labels from applied changes, never from proposed labels."""
    old_ids = {x["id"] for x in before["model"]["items"]} if before else set()
    records = copy.deepcopy(before.get("attribution", {})) if before else {}
    for item in document["model"]["items"]:
        key = item["id"]
        record = records.setdefault(key, {})
        if key not in old_ids:
            record["created"] = copy.deepcopy(stamp)
        prior = bool(before and before["state"].get(key) is True)
        done = document["state"].get(key) is True
        if done and not prior:
            record["completed"] = copy.deepcopy(stamp)
        elif not done:
            record.pop("completed", None)
    kept = {x["id"] for x in document["model"]["items"]}
    document["attribution"] = {key: value for key, value in records.items() if key in kept and value}


def locked_items(document):
    items = {x["id"]: x for x in document["model"]["items"]}
    locked = set()
    todo = [child for item in items.values() if document["state"].get(item["id"]) is True for child in item["requires"]]
    while todo:
        key = todo.pop()
        if key not in locked:
            locked.add(key)
            todo.extend(items[key]["requires"])
    return locked


def merge_documents(base, current, incoming):
    """Three-way merge; any conflict keeps the entire commit out of AI state."""
    for document in (base, current, incoming):
        validate_document(document)
    if len({base["documentId"], current["documentId"], incoming["documentId"]}) != 1:
        raise ValueError("Checklist identities differ")
    if any(base[key] != incoming[key] for key in ("format", "schemaVersion", "documentId")):
        raise ValueError("Checklist identity or format cannot change")
    removed = {i["id"] for i in base["model"]["items"]} - {i["id"] for i in incoming["model"]["items"]}
    if removed:
        visible = lambda d: {k: v for k, v in d.items() if k not in ("updatedAt", "view", "attribution")}
        if visible(current) == visible(incoming):
            return {"merged": copy.deepcopy(current), "conflicts": [], "applied": 0, "already": 1}
        if visible(current) != visible(base):
            return {"merged": copy.deepcopy(current), "conflicts": ["document:deletion-stale"], "applied": 0, "already": 0}
        locked = locked_items(current)
        current_items = {i["id"]: i for i in current["model"]["items"]}
        proposed_items = {i["id"]: i for i in incoming["model"]["items"]}
        changed = removed | {key for key, item in proposed_items.items() if current_items.get(key) != item}
        changed |= {key for key in current["state"].keys() | incoming["state"].keys() if current["state"].get(key, False) != incoming["state"].get(key, False)}
        closed_links = any(current["state"].get(key) is True and item["requires"] != current_items[key]["requires"] for key, item in proposed_items.items() if key in current_items)
        lists = [(current["model"]["roots"], incoming["model"]["roots"])] + [(item["requires"], proposed_items.get(key, {"requires": []})["requires"]) for key, item in current_items.items()]
        locked_links = any(any((old.index(key) if key in old else -1) != (new.index(key) if key in new else -1) for key in locked) for old, new in lists)
        if changed & locked or closed_links or locked_links:
            return {"merged": copy.deepcopy(current), "conflicts": ["document:deletion-locked"], "applied": 0, "already": 0}
        merged = copy.deepcopy(incoming)
        kept = {i["id"] for i in merged["model"]["items"]}
        merged["view"] = {"collapsed": [key for key in current["view"]["collapsed"] if key in kept]}
        merged["attribution"] = {key: copy.deepcopy(value) for key, value in current.get("attribution", {}).items() if key in kept}
        validate_document(merged)
        return {"merged": merged, "conflicts": [], "applied": 1, "already": 0}
    merged = copy.deepcopy(current)
    conflicts = []
    applied = already = 0
    locked = locked_items(current)

    def compare(key, old, present, proposed, setter):
        nonlocal applied, already
        if proposed == old:
            return
        if present == proposed:
            already += 1
            return
        if (key == "model:roots" or key.endswith(":requires")) and isinstance(old, list) and isinstance(proposed, list):
            affected = {item for item in old + proposed if
                        (old.index(item) if item in old else -1) !=
                        (proposed.index(item) if item in proposed else -1)}
            if affected & locked:
                conflicts.append(key + ":locked")
                return
        if present == old:
            setter(copy.deepcopy(proposed))
            applied += 1
            return
        if (key in ("model:roots", "model:branches") or key.endswith(":requires")) and all(isinstance(x, list) for x in (old, present, proposed)) and present[:len(old)] == old and proposed[:len(old)] == old:
            combined = copy.deepcopy(present)
            for addition in proposed[len(old):]:
                identity = addition.get("id") if isinstance(addition, dict) else addition
                matches = [x for x in combined if (x.get("id") if isinstance(x, dict) else x) == identity]
                if matches and any(x != addition for x in matches):
                    break
                if not matches:
                    combined.append(copy.deepcopy(addition))
            else:
                setter(combined)
                applied += 1
                return
        conflicts.append(key)

    for field in DOC_FIELDS:
        compare("document:" + field, base[field], current[field], incoming[field],
                lambda value, field=field: merged.__setitem__(field, value))
    for field in ("roots", "branches"):
        compare("model:" + field, base["model"][field], current["model"][field], incoming["model"][field],
                lambda value, field=field: merged["model"].__setitem__(field, value))
    old_items = {x["id"]: x for x in base["model"]["items"]}
    current_items = {x["id"]: x for x in current["model"]["items"]}
    incoming_items = {x["id"]: x for x in incoming["model"]["items"]}
    merged_items = {x["id"]: x for x in merged["model"]["items"]}
    locked = locked_items(current)
    for item in incoming["model"]["items"]:
        key = item["id"]
        old = old_items.get(key)
        present = current_items.get(key)
        if old is None:
            compare("item:" + key + ":add", None, present, item,
                    lambda value: (merged["model"]["items"].append(value), merged_items.__setitem__(key, value)))
            continue
        if present is None:
            if item != old or incoming["state"].get(key, False) != base["state"].get(key, False):
                conflicts.append("item:" + key + ":missing")
            continue
        target = merged_items[key]
        changed = any(item[f] != old[f] and item[f] != present[f] for f in ITEM_FIELDS) or (
            incoming["state"].get(key, False) != base["state"].get(key, False) and
            incoming["state"].get(key, False) != current["state"].get(key, False))
        if changed and (key in locked or current["state"].get(key) is True and item["requires"] != old["requires"] and item["requires"] != present["requires"]):
            conflicts.append("item:" + key + ":locked")
            continue
        base_done = base["state"].get(key) is True
        present_done = current["state"].get(key) is True
        incoming_done = incoming["state"].get(key) is True
        present_meaning = any(present[field] != old[field] for field in MEANING_FIELDS)
        incoming_meaning = any(item[field] != old[field] for field in MEANING_FIELDS)
        for field in ITEM_FIELDS:
            if (incoming_meaning and present_done != base_done and field in MEANING_FIELDS and
                    item[field] != old[field] and item[field] != present[field]):
                conflicts.append("item:" + key + ":" + field)
            else:
                compare("item:" + key + ":" + field, old[field], present[field], item[field],
                        lambda value, field=field: target.__setitem__(field, value))
        if incoming_done != base_done and present_meaning and any(item[f] != present[f] for f in MEANING_FIELDS):
            conflicts.append("state:" + key)
        else:
            compare("state:" + key, base_done, present_done, incoming_done,
                    lambda value: merged["state"].__setitem__(key, value))
    for key, value in incoming["state"].items():
        if key not in old_items and key in incoming_items and value is True:
            compare("state:" + key, False, current["state"].get(key) is True, True,
                    lambda value, key=key: merged["state"].__setitem__(key, value))
    if not conflicts:
        validate_document(merged)
    return {"merged": merged, "conflicts": sorted(set(conflicts)), "applied": applied, "already": already}
