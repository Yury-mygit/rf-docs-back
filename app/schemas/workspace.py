from uuid import UUID

from app.schemas.common import CamelModel


class WorkspaceCreate(CamelModel):
    id: UUID
    title: str = ""
    position: int = 0
    created_at: int
    updated_at: int


class WorkspacePatch(CamelModel):
    title: str | None = None
    position: int | None = None
    updated_at: int


class WorkspaceResponse(CamelModel):
    id: UUID
    title: str
    position: int
    created_at: int
    updated_at: int
    deleted_at: int | None
