from typing import Literal
from uuid import UUID

from app.schemas.common import CamelModel


DocKind = Literal["page", "change_map", "project_root", "website_base"]


class DocCreate(CamelModel):
    id: UUID
    workspace_id: UUID
    parent_id: UUID | None = None
    title: str = "Без названия"
    body_md: str = ""
    kind: DocKind = "page"
    slug: str | None = None
    position: int = 0
    created_at: int
    updated_at: int


class DocPatch(CamelModel):
    title: str | None = None
    body_md: str | None = None
    parent_id: UUID | None = None
    kind: DocKind | None = None
    slug: str | None = None
    position: int | None = None
    updated_at: int


class DocTreeItem(CamelModel):
    id: UUID
    workspace_id: UUID
    parent_id: UUID | None
    title: str
    kind: DocKind
    slug: str | None
    position: int
    updated_at: int


class DocResponse(CamelModel):
    id: UUID
    workspace_id: UUID
    parent_id: UUID | None
    title: str
    body_md: str
    kind: DocKind
    slug: str | None
    position: int
    created_at: int
    updated_at: int
    deleted_at: int | None


class DocSearchHit(CamelModel):
    id: UUID
    title: str
    kind: DocKind
    snippet: str
    rank: float


class DocRevisionMeta(CamelModel):
    id: UUID
    doc_id: UUID
    title: str
    author: str | None
    created_at: int


class DocRevisionFull(CamelModel):
    id: UUID
    doc_id: UUID
    title: str
    body_md: str
    author: str | None
    created_at: int
