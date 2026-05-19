"""Публичные endpoints для landing_app + share-ссылки на страницы.

Без auth (whitelisted в Caddy: /api/v1/site/* в docs.dev.raftforge.art).
landing_app тащит JSON через httpx и рендерит HTML у себя. Share-ссылки
рендерятся прямо тут и отдаются как HTML.
"""

import html as html_lib
from uuid import UUID

import mistune
from sqlalchemy import select
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import APIError
from app.core.utils import now_ms
from app.models.models import Doc, ShareToken
from app.schemas.common import CamelModel

router = APIRouter(prefix="/site", tags=["site"])

_markdown = mistune.create_markdown(escape=True)


_PUBLIC_PAGE_TMPL = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{title}</title>
<style>
  body {{ margin: 0; background: #0e0f12; color: #e7e9ee; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; line-height: 1.6; -webkit-font-smoothing: antialiased; }}
  .wrap {{ max-width: 820px; margin: 0 auto; padding: 32px 24px 80px; }}
  h1.share-title {{ margin: 0 0 4px; font-size: 28px; line-height: 1.2; letter-spacing: -0.01em; }}
  .share-meta {{ color: #8b93a3; font-size: 13px; margin-bottom: 28px; }}
  article h1, article h2, article h3, article h4 {{ line-height: 1.25; margin-top: 1.4em; }}
  article p, article ul, article ol {{ margin: 0.6em 0; }}
  article pre {{ background: #16181d; padding: 12px 14px; border-radius: 6px; overflow-x: auto; font-size: 13px; }}
  article code {{ background: rgba(255,255,255,0.06); padding: 1px 6px; border-radius: 4px; font-size: 0.92em; }}
  article pre code {{ background: transparent; padding: 0; }}
  article a {{ color: #ff6a3d; }}
  article blockquote {{ border-left: 3px solid #23262d; padding-left: 12px; color: #b9c1cf; margin: 12px 0; }}
  article table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  article th, article td {{ border: 1px solid #23262d; padding: 6px 10px; text-align: left; }}
  article img {{ max-width: 100%; height: auto; }}
  article hr {{ border: 0; border-top: 1px solid #23262d; margin: 20px 0; }}
</style>
</head>
<body>
  <div class="wrap">
    <h1 class="share-title">{title}</h1>
    <div class="share-meta">{meta}</div>
    <article>{body}</article>
  </div>
</body>
</html>"""


def _render_public_page(title: str, body_md: str, meta: str) -> str:
    return _PUBLIC_PAGE_TMPL.format(
        title=html_lib.escape(title or "Без названия"),
        meta=html_lib.escape(meta),
        body=_markdown(body_md or ""),
    )


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


@router.get("/share/{token}", response_class=HTMLResponse)
async def get_shared_doc(
    token: UUID, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    share = await db.get(ShareToken, token)
    if share is None:
        raise APIError(404, "share_not_found", "share token not found")
    if share.expires_at <= now_ms():
        raise APIError(410, "share_expired", "share link has expired")
    doc = await db.get(Doc, share.doc_id)
    if not doc or doc.deleted_at is not None:
        raise APIError(404, "doc_not_found", "linked document is unavailable")
    return HTMLResponse(_render_public_page(
        doc.title, doc.body_md, "Документ доступен по временной ссылке.",
    ))


@router.get("/contracts/{slug}", response_class=HTMLResponse)
async def get_api_contract(
    slug: str, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    q = select(Doc).where(
        Doc.slug == slug,
        Doc.kind == "api_contract",
        Doc.deleted_at.is_(None),
    )
    doc = (await db.execute(q)).scalar_one_or_none()
    if doc is None:
        raise APIError(404, "not_found", f"api contract '{slug}' not found")
    return HTMLResponse(_render_public_page(
        doc.title, doc.body_md, "Публичный API контракт.",
    ))


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
