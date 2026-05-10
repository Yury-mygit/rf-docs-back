from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import verify_token
from app.core.exceptions import APIError
from app.core.utils import now_ms
from app.models.models import Doc, Workspace
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspacePatch,
    WorkspaceResponse,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    include_deleted: bool = Query(default=False, alias="includeDeleted"),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_token),
) -> list[Workspace]:
    q = select(Workspace)
    if not include_deleted:
        q = q.where(Workspace.deleted_at.is_(None))
    q = q.order_by(Workspace.position.asc(), Workspace.created_at.asc())
    return list((await db.execute(q)).scalars().all())


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: WorkspaceCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_token),
) -> Workspace:
    if await db.get(Workspace, body.id):
        raise APIError(409, "conflict", f"Workspace with id '{body.id}' already exists")
    ws = Workspace(**body.model_dump(), deleted_at=None)
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return ws


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_token),
) -> Workspace:
    ws = await db.get(Workspace, workspace_id)
    if not ws or ws.deleted_at is not None:
        raise APIError(404, "workspace_not_found", f"Workspace with id '{workspace_id}' does not exist")
    return ws


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def patch_workspace(
    workspace_id: UUID,
    body: WorkspacePatch,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_token),
) -> Workspace:
    ws = await db.get(Workspace, workspace_id)
    if not ws or ws.deleted_at is not None:
        raise APIError(404, "workspace_not_found", f"Workspace with id '{workspace_id}' does not exist")
    if body.updated_at >= ws.updated_at:
        data = body.model_dump(exclude_unset=True)
        updated_at = data.pop("updated_at")
        for key, value in data.items():
            setattr(ws, key, value)
        ws.updated_at = updated_at
        await db.commit()
        await db.refresh(ws)
    return ws


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_token),
) -> None:
    ws = await db.get(Workspace, workspace_id)
    if not ws or ws.deleted_at is not None:
        raise APIError(404, "workspace_not_found", f"Workspace with id '{workspace_id}' does not exist")
    live_docs = await db.scalar(
        select(func.count(Doc.id)).where(
            Doc.workspace_id == workspace_id, Doc.deleted_at.is_(None)
        )
    )
    if live_docs:
        raise APIError(
            409,
            "workspace_not_empty",
            f"Workspace has {live_docs} live doc(s); delete or move them first",
        )
    ts = now_ms()
    ws.deleted_at = ts
    ws.updated_at = ts
    await db.commit()


@router.post("/{workspace_id}/restore", response_model=WorkspaceResponse)
async def restore_workspace(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_token),
) -> Workspace:
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise APIError(404, "workspace_not_found", f"Workspace with id '{workspace_id}' does not exist")
    if ws.deleted_at is None:
        raise APIError(400, "not_deleted", f"Workspace '{workspace_id}' is not deleted")
    ts = now_ms()
    ws.deleted_at = None
    ws.updated_at = ts
    await db.commit()
    await db.refresh(ws)
    return ws
