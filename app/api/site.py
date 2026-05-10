"""Публичные endpoints для landing_app.

Без auth (whitelisted в Caddy: /api/v1/site/* в docs.dev.raftforge.art).
landing_app тащит JSON через httpx и рендерит HTML у себя.
"""

from sqlalchemy import select
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import APIError
from app.models.models import Doc
from app.schemas.common import CamelModel

router = APIRouter(prefix="/site", tags=["site"])


class ProjectMeta(CamelModel):
    slug: str
    title: str


class ProjectPage(CamelModel):
    slug: str
    title: str
    body_md: str


@router.get("/projects", response_model=list[ProjectMeta])
async def list_projects(db: AsyncSession = Depends(get_db)) -> list[ProjectMeta]:
    q_roots = (
        select(Doc)
        .where(
            Doc.kind == "project_root",
            Doc.slug.is_not(None),
            Doc.deleted_at.is_(None),
        )
        .order_by(Doc.title.asc())
    )
    roots = list((await db.execute(q_roots)).scalars().all())
    if not roots:
        return []
    wb_q = select(Doc.parent_id).where(
        Doc.kind == "website_base",
        Doc.deleted_at.is_(None),
        Doc.parent_id.in_([r.id for r in roots]),
    )
    wb_parents = {row[0] for row in (await db.execute(wb_q)).all()}
    return [
        ProjectMeta(slug=r.slug, title=r.title or r.slug)
        for r in roots
        if r.id in wb_parents
    ]


@router.get("/p/{slug}", response_model=ProjectPage)
async def get_project_page(slug: str, db: AsyncSession = Depends(get_db)) -> ProjectPage:
    q_root = select(Doc).where(
        Doc.kind == "project_root",
        Doc.slug == slug,
        Doc.deleted_at.is_(None),
    )
    root = (await db.execute(q_root)).scalar_one_or_none()
    if root is None:
        raise APIError(404, "not_found", f"project '{slug}' not found")

    q_wb = select(Doc).where(
        Doc.kind == "website_base",
        Doc.parent_id == root.id,
        Doc.deleted_at.is_(None),
    )
    wb = (await db.execute(q_wb)).scalar_one_or_none()
    body_md = wb.body_md if wb else ""
    return ProjectPage(slug=slug, title=root.title or slug, body_md=body_md)
