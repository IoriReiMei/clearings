# SPDX-License-Identifier: MIT
"""Optional local stdio MCP adapter for Clearings' existing Bridge.

Install the pinned official SDK in a separate environment. This process never
starts the browser helper, changes settings, or opens a network listener.
"""
from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path
import sys

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from clearings_local import Bridge, load_json


def bridge_call(method, *args):
    """Expose expected Bridge rejections without presenting them as server crashes."""
    try:
        return method(*args)
    except (ValueError, KeyError) as exc:
        raise ToolError(str(exc)) from exc


def item_paths(document: dict) -> tuple[dict[str, list[str]], set[str]]:
    """Choose one stable path and identify items with multiple root paths."""
    items = {item["id"]: item for item in document["model"]["items"]}
    incoming = {key: 0 for key in items}
    for item in items.values():
        for child in item["requires"]:
            incoming[child] += 1
    remaining = incoming.copy()
    path_counts = {key: int(key in document["model"]["roots"]) for key in items}
    topology = deque(key for key, count in remaining.items() if count == 0)
    while topology:
        key = topology.popleft()
        for child in items[key]["requires"]:
            path_counts[child] = min(2, path_counts[child] + path_counts[key])
            remaining[child] -= 1
            if remaining[child] == 0:
                topology.append(child)
    paths = {root: [root] for root in document["model"]["roots"]}
    queue = deque(document["model"]["roots"])
    while queue:
        key = queue.popleft()
        for child in items[key]["requires"]:
            if child not in paths:
                paths[child] = paths[key] + [child]
                queue.append(child)
    return paths, {key for key, count in path_counts.items() if count > 1}


def existing_bridge(config_dir: str, home: str) -> Bridge:
    """Check the existing configuration and matching home at startup."""
    config = Path(config_dir).expanduser()
    chosen_home = Path(home).expanduser()
    if not config.is_absolute() or not chosen_home.is_absolute():
        raise ValueError("Pass absolute --config-dir and --home paths")
    if not config.is_dir() or not (config / "settings.json").is_file():
        raise ValueError("An existing Clearings config and settings.json are required")
    if not chosen_home.is_dir():
        raise ValueError("The configured Clearings home must already exist")
    settings = load_json(config / "settings.json")
    if not isinstance(settings, dict) or not isinstance(settings.get("home"), str):
        raise ValueError("Existing Clearings settings have no home")
    if Path(settings["home"]).expanduser().resolve() != chosen_home.resolve():
        raise ValueError("--home differs from the existing Clearings setting")
    bridge = Bridge(config.resolve())
    if bridge.home() != chosen_home.resolve():
        raise ValueError("The Clearings home changed during startup")
    return bridge


def build_server(bridge: Bridge, actor: str, *, allow_write: bool = False) -> MCPServer:
    """Register only tools allowed for this process; Bridge owns all changes."""
    if not isinstance(actor, str) or not actor.strip() or len(actor.strip()) > 80:
        raise ValueError("--actor must be a display name of 1 to 80 characters")
    actor = actor.strip()
    server = MCPServer("Clearings local", instructions=(
        "Local checklist handoff. Actor names are declared labels, not verified "
        "identities. Read the full effective document before drafting; "
        "effective_only returns that exact proposal base with less context. "
        "Branches and item search results are not proposal bases. Signed "
        "commits appear to other AI "
        "readers immediately and in the human page after Refresh Clearings."
    ))

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def clearings_list_checklists() -> dict:
        """List effective checklists and handoff status without reading files by path."""
        state = bridge_call(bridge.refresh_for_ai)
        workspace = state["effectiveWorkspace"]
        if workspace is None:
            return {"libraryId": state["libraryId"], "generation": state["generation"],
                    "checklists": [], "message": "No browser-saved workspace yet"}
        default_id = workspace["index"].get("defaultChecklist")
        documents = {doc["documentId"]: doc for doc in workspace["documents"]}
        return {"libraryId": state["libraryId"], "generation": state["generation"],
                "snapshotAt": state["snapshotAt"],
                "checklists": [{"id": item["id"], "title": documents[item["id"]]["title"],
                                "archived": documents[item["id"]]["archived"],
                                "isDefault": item["id"] == default_id}
                               for item in workspace["index"]["entries"]],
                "committedAwaitingBrowser": state["committedAwaitingBrowser"],
                "committedConflicts": state["committedConflicts"],
                "pendingProposals": [{"id": p["id"], "documentId": p["documentId"],
                                      "actor": p["actor"], "signed": bool(p.get("commit"))}
                                     for p in state["pendingUnapplied"]]}

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def clearings_read_checklist(checklist_id: str, branch_id: str | None = None,
                                 effective_only: bool = False) -> dict:
        """Read a checklist; effective_only omits saved state and proposal history."""
        if effective_only and branch_id is not None:
            raise ToolError("effective_only requires a full checklist, not a partial branch")
        read = bridge_call(bridge.read_checklist, checklist_id, branch_id)
        if not effective_only:
            return read
        return {"libraryId": read["libraryId"], "snapshotAt": read["snapshotAt"],
                "generation": read["generation"], "checklistId": read["checklistId"],
                "documentFormat": read["documentFormat"],
                "documentSchemaVersion": read["documentSchemaVersion"],
                "partial": False, "readOnly": True, "effectiveOnly": True,
                "pendingProposalCount": len(read["pendingUnapplied"]),
                "committedAwaitingBrowserCount": len(read["committedAwaitingBrowser"]),
                "committedConflictCount": len(read["committedConflicts"]),
                "effectiveDocument": read["effectiveDocument"]}

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def clearings_search_items(query: str, include_archived: bool = False,
                               limit: int = 20) -> dict:
        """Find up to 50 effective items by text, detail, label or tag."""
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 120:
            raise ToolError("query must contain 1 to 120 nonblank characters")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ToolError("limit must be an integer from 1 to 50")
        if type(include_archived) is not bool:
            raise ToolError("include_archived must be a boolean")
        state = bridge_call(bridge.refresh_for_ai)
        workspace = state["effectiveWorkspace"]
        result = {"libraryId": state["libraryId"], "generation": state["generation"],
                  "query": query.strip(), "includeArchived": include_archived,
                  "limit": limit, "partial": True, "notAProposalBase": True,
                  "results": [], "hasMore": False}
        if workspace is None:
            return result
        docs = {doc["documentId"]: doc for doc in workspace["documents"]}
        needle = query.strip().casefold()
        for entry in workspace["index"]["entries"]:
            doc = docs[entry["id"]]
            if doc["archived"] and not include_archived:
                continue
            paths, shared = item_paths(doc)
            for item in doc["model"]["items"]:
                fields = (item["text"], item["detail"], item["label"], *item["tags"])
                if not any(needle in field.casefold() for field in fields):
                    continue
                if len(result["results"]) == limit:
                    result["hasMore"] = True
                    return result
                result["results"].append({"checklistId": doc["documentId"],
                                          "checklistTitle": doc["title"][:160],
                                          "archived": doc["archived"],
                                          "itemId": item["id"],
                                          "text": item["text"][:160],
                                          "detail": item["detail"][:160],
                                          "completed": doc["state"].get(item["id"]) is True,
                                          "pathIds": paths[item["id"]],
                                          "sharedParentPaths": item["id"] in shared})
        return result

    if allow_write:
        @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                 idempotentHint=False, openWorldHint=False))
        def clearings_propose_existing(base: dict, incoming: dict, note: str = "") -> dict:
            """Draft a full-document edit using the exact effectiveDocument as base."""
            return bridge_call(bridge.propose, base, incoming, actor, note)

        @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                 idempotentHint=False, openWorldHint=False))
        def clearings_propose_new(incoming: dict, note: str = "") -> dict:
            """Draft a complete version-2 new checklist with all items unchecked."""
            return bridge_call(bridge.propose_new, incoming, actor, note)

        @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                                 idempotentHint=False, openWorldHint=False))
        def clearings_commit_proposal(proposal_id: str) -> dict:
            """Sign one pending proposal through Bridge's existing conflict checks."""
            return bridge_call(bridge.commit_proposal, proposal_id, actor)

        @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                                 idempotentHint=False, openWorldHint=False))
        def clearings_withdraw_proposal(proposal_id: str, reason: str) -> dict:
            """Withdraw this actor's pending proposal and preserve its receipt."""
            return bridge_call(bridge.withdraw, proposal_id, actor, reason)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", required=True, help="Existing Clearings config directory")
    parser.add_argument("--home", required=True, help="Existing configured Clearings home")
    parser.add_argument("--actor", required=True, help="Declared display name for this process")
    parser.add_argument("--write", action="store_true", help="Expose draft/commit/withdraw tools")
    args = parser.parse_args()
    bridge = existing_bridge(args.config_dir, args.home)
    build_server(bridge, args.actor, allow_write=args.write).run(transport="stdio")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Clearings MCP: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
