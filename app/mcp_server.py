"""FastMCP server exposing docs tools over /mcp.

Тонкий wrapper над `/api/v1/docs/*` через httpx-loopback на 127.0.0.1:8000
со static API_KEY. Авторство ревизий — `claude@local` (за `auth_required docs-dev`
в Caddy ходит только этот юзер с api_token grant'ом docs-dev; правки от Юрия
идут через browser-UI и проставляются автоматически).
"""
import uuid
from typing import Any

import httpx
from fastmcp import FastMCP

from app.core.config import settings
from app.core.utils import now_ms

mcp = FastMCP("ln-docs")

INTERNAL_BASE = "http://127.0.0.1:8000/api/v1"
AUTHOR = "claude@local"


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=INTERNAL_BASE,
        headers={
            "Authorization": f"Bearer {settings.api_key}",
            "X-User-Email": AUTHOR,
        },
        timeout=10.0,
    )


@mcp.tool
async def docs_workspaces_list() -> list[dict]:
    """List all live workspaces (top-level grouping above docs)."""
    async with _client() as c:
        r = await c.get("/workspaces")
        r.raise_for_status()
        return r.json()


@mcp.tool
async def docs_workspace_create(title: str, position: int = 0) -> dict:
    """Create a new workspace. Server generates id and timestamps."""
    ts = now_ms()
    body = {
        "id": str(uuid.uuid4()),
        "title": title,
        "position": position,
        "createdAt": ts,
        "updatedAt": ts,
    }
    async with _client() as c:
        r = await c.post("/workspaces", json=body)
        r.raise_for_status()
        return r.json()


@mcp.tool
async def docs_workspace_rename(id: str, title: str) -> dict:
    """Rename a workspace."""
    body = {"title": title, "updatedAt": now_ms()}
    async with _client() as c:
        r = await c.patch(f"/workspaces/{id}", json=body)
        r.raise_for_status()
        return r.json()


@mcp.tool
async def docs_tree(workspace_id: str) -> list[dict]:
    """List all live docs in a workspace as a flat array. Build the tree via parent_id on the client side."""
    async with _client() as c:
        r = await c.get("/docs/tree", params={"workspaceId": workspace_id})
        r.raise_for_status()
        return r.json()


@mcp.tool
async def docs_read(id: str) -> dict:
    """Read a single doc with full markdown body."""
    async with _client() as c:
        r = await c.get(f"/docs/{id}")
        r.raise_for_status()
        return r.json()


@mcp.tool
async def docs_search(q: str, workspace_id: str | None = None, limit: int = 20) -> list[dict]:
    """Full-text search (FTS5). Returns hits with id, title, snippet and bm25 rank. Optional workspace_id filter."""
    params: dict[str, Any] = {"q": q, "limit": limit}
    if workspace_id is not None:
        params["workspaceId"] = workspace_id
    async with _client() as c:
        r = await c.get("/docs/search", params=params)
        r.raise_for_status()
        return r.json()


@mcp.tool
async def docs_create(
    workspace_id: str,
    title: str,
    body_md: str = "",
    parent_id: str | None = None,
    kind: str = "page",
    slug: str | None = None,
) -> dict:
    """Create a doc in a workspace. Server generates id and timestamps.

    kind: 'page' (default, may have children) | 'change_map' (no children) |
    'project_root' (may have children, exactly one website_base allowed) |
    'website_base' (no children, must be a child of a project_root, max 1 per parent) |
    'api_contract' (no children, public via /api/v1/site/contracts/{slug}).

    slug: optional URL-slug; allowed for kind ∈ {'project_root', 'api_contract'}.
    Must match [a-z0-9-]{1,64} and be globally unique among active docs.
    """
    ts = now_ms()
    body = {
        "id": str(uuid.uuid4()),
        "workspaceId": workspace_id,
        "title": title,
        "bodyMd": body_md,
        "parentId": parent_id,
        "kind": kind,
        "slug": slug,
        "createdAt": ts,
        "updatedAt": ts,
    }
    async with _client() as c:
        r = await c.post("/docs", json=body)
        r.raise_for_status()
        return r.json()


@mcp.tool
async def docs_update(
    id: str,
    title: str | None = None,
    body_md: str | None = None,
    parent_id: str | None = None,
    kind: str | None = None,
    slug: str | None = None,
) -> dict:
    """Update fields of a doc. Pass only what you want to change.

    kind values: 'page' | 'change_map' | 'project_root' | 'website_base' | 'api_contract'.
    slug: allowed for kind ∈ {'project_root', 'api_contract'}; pass empty string '' to clear.
    Constraints validated server-side; ошибка 400/409 при нарушениях
    (см. docs_create описание).
    """
    body: dict[str, Any] = {"updatedAt": now_ms()}
    if title is not None:
        body["title"] = title
    if body_md is not None:
        body["bodyMd"] = body_md
    if parent_id is not None:
        body["parentId"] = parent_id
    if kind is not None:
        body["kind"] = kind
    if slug is not None:
        body["slug"] = slug or None
    async with _client() as c:
        r = await c.patch(f"/docs/{id}", json=body)
        r.raise_for_status()
        return r.json()


@mcp.tool
async def docs_delete(id: str) -> dict:
    """Soft-delete a doc. Restore with docs_restore."""
    async with _client() as c:
        r = await c.delete(f"/docs/{id}")
        r.raise_for_status()
        return {"ok": True}


@mcp.tool
async def docs_restore(id: str) -> dict:
    """Restore a soft-deleted doc."""
    async with _client() as c:
        r = await c.post(f"/docs/{id}/restore")
        r.raise_for_status()
        return r.json()


@mcp.tool
async def docs_revisions(id: str, limit: int = 20) -> list[dict]:
    """List revisions metadata for a doc (newest first)."""
    async with _client() as c:
        r = await c.get(f"/docs/{id}/revisions", params={"limit": limit})
        r.raise_for_status()
        return r.json()


mcp_http_app = mcp.http_app(path="/")
