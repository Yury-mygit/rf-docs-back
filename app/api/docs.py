import re
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import verify_token
from app.core.exceptions import APIError
from app.core.utils import now_ms
from app.models.models import Doc, DocRevision, ShareToken, Workspace
from app.schemas.doc import (
    DocCreate,
    DocKind,
    DocPatch,
    DocResponse,
    DocRevisionFull,
    DocRevisionMeta,
    DocSearchHit,
    DocTreeItem,
    ShareCreateResponse,
)

router = APIRouter(prefix="/docs", tags=["docs"])


KIND_VALUES: set[str] = {"page", "change_map", "project_root", "website_base", "api_contract"}
# Эти типы НЕ могут иметь подстраниц.
KIND_NO_CHILDREN: set[str] = {"change_map", "website_base", "api_contract"}
# Slug разрешён у этих типов (общий namespace, конфликты → 409).
KIND_ALLOWS_SLUG: set[str] = {"project_root", "api_contract"}
SLUG_RE = re.compile(r"^[a-z0-9-]{1,64}$")


def _validate_slug(slug: str | None, kind: str) -> None:
    if slug is None:
        return
    if kind not in KIND_ALLOWS_SLUG:
        raise APIError(
            400, "slug_conflict",
            f"slug allowed only for kind in {sorted(KIND_ALLOWS_SLUG)}, got '{kind}'",
        )
    if not SLUG_RE.fullmatch(slug):
        raise APIError(
            400, "invalid_slug",
            "slug must match [a-z0-9-]{1,64}",
        )


def _author(x_user_email: str | None) -> str | None:
    return x_user_email or None


async def _validate_workspace(db: AsyncSession, workspace_id: UUID) -> None:
    ws = await db.get(Workspace, workspace_id)
    if not ws or ws.deleted_at is not None:
        raise APIError(400, "invalid_workspace", f"Workspace '{workspace_id}' does not exist")


async def _validate_parent(
    db: AsyncSession, doc_id: UUID, parent_id: UUID, workspace_id: UUID
) -> None:
    if parent_id == doc_id:
        raise APIError(400, "invalid_parent", "Doc cannot be its own parent")
    parent = await db.get(Doc, parent_id)
    if not parent or parent.deleted_at is not None:
        raise APIError(400, "invalid_parent", f"Parent '{parent_id}' does not exist")
    if parent.workspace_id != workspace_id:
        raise APIError(400, "invalid_parent", "Parent belongs to a different workspace")
    if parent.kind in KIND_NO_CHILDREN:
        raise APIError(
            400, "invalid_parent",
            f"Parent kind='{parent.kind}' cannot have children",
        )
    cur = parent
    seen = {doc_id, parent_id}
    while cur.parent_id is not None:
        if cur.parent_id in seen:
            raise APIError(400, "invalid_parent", "Cycle detected in parent chain")
        seen.add(cur.parent_id)
        cur = await db.get(Doc, cur.parent_id)
        if cur is None:
            break


async def _has_active_children(db: AsyncSession, doc_id: UUID) -> bool:
    q = select(func.count()).select_from(Doc).where(
        Doc.parent_id == doc_id, Doc.deleted_at.is_(None)
    )
    return ((await db.execute(q)).scalar() or 0) > 0


async def _has_website_base_child(
    db: AsyncSession, parent_id: UUID, exclude_id: UUID | None = None
) -> bool:
    q = select(Doc.id).where(
        Doc.parent_id == parent_id,
        Doc.kind == "website_base",
        Doc.deleted_at.is_(None),
    )
    if exclude_id is not None:
        q = q.where(Doc.id != exclude_id)
    return (await db.execute(q)).first() is not None


async def _validate_kind_state(
    db: AsyncSession,
    *,
    doc_id: UUID,
    kind: str,
    parent_id: UUID | None,
) -> None:
    """Валидирует, что итоговое (kind, parent_id) для doc_id согласовано
    с правилами: website_base — child у project_root (max 1); типы из
    KIND_NO_CHILDREN не должны иметь активных потомков; project_root,
    превращающийся в иной тип, не должен иметь website_base-child.
    Вызывается ПОСЛЕ _validate_parent (если parent_id задан).
    """
    if kind not in KIND_VALUES:
        raise APIError(400, "invalid_kind", f"Unknown kind '{kind}'")

    if kind in KIND_NO_CHILDREN and await _has_active_children(db, doc_id):
        raise APIError(
            409, "kind_conflict",
            f"Doc has children — cannot set kind='{kind}'",
        )

    if kind == "website_base":
        if parent_id is None:
            raise APIError(
                400, "kind_conflict", "website_base must have a parent",
            )
        parent = await db.get(Doc, parent_id)
        if parent is None or parent.deleted_at is not None:
            raise APIError(400, "invalid_parent", "Parent does not exist")
        if parent.kind != "project_root":
            raise APIError(
                400, "kind_conflict",
                "website_base parent must be a project_root",
            )
        if await _has_website_base_child(db, parent_id, exclude_id=doc_id):
            raise APIError(
                409, "kind_conflict",
                "project_root already has a website_base child",
            )

    if kind != "project_root" and await _has_website_base_child(db, doc_id):
        raise APIError(
            409, "kind_conflict",
            "doc has a website_base child — keep kind='project_root' or "
            "remove/move the website_base first",
        )


async def _write_revision(
    db: AsyncSession, doc: Doc, author: str | None, ts: int
) -> None:
    rev = DocRevision(
        id=uuid.uuid4(),
        doc_id=doc.id,
        title=doc.title,
        body_md=doc.body_md,
        author=author,
        created_at=ts,
    )
    db.add(rev)


@router.get("/tree", response_model=list[DocTreeItem])
async def list_tree(
    workspace_id: UUID = Query(alias="workspaceId"),
    include_deleted: bool = Query(default=False, alias="includeDeleted"),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_token),
) -> list[Doc]:
    q = select(Doc).where(Doc.workspace_id == workspace_id)
    if not include_deleted:
        q = q.where(Doc.deleted_at.is_(None))
    q = q.order_by(Doc.position.asc(), Doc.updated_at.desc())
    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/search", response_model=list[DocSearchHit])
async def search_docs(
    q: str = Query(min_length=1),
    workspace_id: UUID | None = Query(default=None, alias="workspaceId"),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_token),
) -> list[DocSearchHit]:
    ws_filter = "AND d.workspace_id = :ws_id" if workspace_id is not None else ""
    # Postgres FTS: generated tsvector `search_tsv` + GIN индекс (см. миграцию).
    # Запрос — websearch_to_tsquery (юзерский синтаксис: "phrase", -minus, OR).
    sql = text(
        f"""
        SELECT d.id AS id,
               d.title AS title,
               d.kind AS kind,
               ts_headline('russian', coalesce(d.body_md, ''), q,
                   'StartSel=<mark>, StopSel=</mark>, MaxWords=16, MinWords=4, ShortWord=2'
               ) AS snippet,
               ts_rank_cd(d.search_tsv, q) AS rank
        FROM docs d, websearch_to_tsquery('russian', :q) q
        WHERE d.search_tsv @@ q AND d.deleted_at IS NULL {ws_filter}
        ORDER BY rank DESC
        LIMIT :limit
        """
    )
    params: dict = {"q": q, "limit": limit}
    if workspace_id is not None:
        params["ws_id"] = workspace_id
    rows = (await db.execute(sql, params)).mappings().all()
    return [
        DocSearchHit(
            id=UUID(r["id"]) if isinstance(r["id"], str) else r["id"],
            title=r["title"],
            kind=r["kind"],
            snippet=r["snippet"],
            rank=float(r["rank"]),
        )
        for r in rows
    ]


@router.post("", response_model=DocResponse, status_code=status.HTTP_201_CREATED)
async def create_doc(
    body: DocCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_token),
    x_user_email: str | None = Header(default=None, alias="X-User-Email"),
) -> Doc:
    if await db.get(Doc, body.id):
        raise APIError(409, "conflict", f"Doc with id '{body.id}' already exists")
    await _validate_workspace(db, body.workspace_id)
    if body.parent_id is not None:
        await _validate_parent(db, body.id, body.parent_id, body.workspace_id)
    await _validate_kind_state(
        db, doc_id=body.id, kind=body.kind, parent_id=body.parent_id,
    )
    _validate_slug(body.slug, body.kind)
    doc = Doc(**body.model_dump(), deleted_at=None)
    db.add(doc)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise APIError(409, "slug_conflict", f"slug '{body.slug}' is already taken")
    await _write_revision(db, doc, _author(x_user_email), body.updated_at)
    await db.commit()
    await db.refresh(doc)
    return doc


@router.get("/{doc_id}", response_model=DocResponse)
async def get_doc(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_token),
) -> Doc:
    doc = await db.get(Doc, doc_id)
    if not doc or doc.deleted_at is not None:
        raise APIError(404, "doc_not_found", f"Doc with id '{doc_id}' does not exist")
    return doc


@router.patch("/{doc_id}", response_model=DocResponse)
async def patch_doc(
    doc_id: UUID,
    body: DocPatch,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_token),
    x_user_email: str | None = Header(default=None, alias="X-User-Email"),
) -> Doc:
    doc = await db.get(Doc, doc_id)
    if not doc or doc.deleted_at is not None:
        raise APIError(404, "doc_not_found", f"Doc with id '{doc_id}' does not exist")
    if body.updated_at >= doc.updated_at:
        data = body.model_dump(exclude_unset=True)
        updated_at = data.pop("updated_at")
        if "parent_id" in data and data["parent_id"] is not None:
            await _validate_parent(db, doc_id, data["parent_id"], doc.workspace_id)
        final_kind = data.get("kind", doc.kind)
        if "kind" in data or "parent_id" in data:
            final_parent = data["parent_id"] if "parent_id" in data else doc.parent_id
            await _validate_kind_state(
                db, doc_id=doc_id, kind=final_kind, parent_id=final_parent,
            )
        if "slug" in data or "kind" in data:
            final_slug = data["slug"] if "slug" in data else doc.slug
            _validate_slug(final_slug, final_kind)
        for key, value in data.items():
            setattr(doc, key, value)
        doc.updated_at = updated_at
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            raise APIError(409, "slug_conflict", f"slug '{data.get('slug')}' is already taken")
        await _write_revision(db, doc, _author(x_user_email), updated_at)
        await db.commit()
        await db.refresh(doc)
    return doc


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_doc(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_token),
) -> None:
    doc = await db.get(Doc, doc_id)
    if not doc:
        raise APIError(404, "doc_not_found", f"Doc with id '{doc_id}' does not exist")
    ts = now_ms()
    doc.deleted_at = ts
    doc.updated_at = ts
    await db.commit()


SHARE_TTL_MS = 24 * 3600 * 1000


@router.post(
    "/{doc_id}/share",
    response_model=ShareCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_share(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_token),
    x_user_email: str | None = Header(default=None, alias="X-User-Email"),
) -> ShareCreateResponse:
    doc = await db.get(Doc, doc_id)
    if not doc or doc.deleted_at is not None:
        raise APIError(404, "doc_not_found", f"Doc with id '{doc_id}' does not exist")
    now = now_ms()
    share = ShareToken(
        token=uuid.uuid4(),
        doc_id=doc_id,
        expires_at=now + SHARE_TTL_MS,
        created_at=now,
        created_by_email=x_user_email,
    )
    db.add(share)
    await db.commit()
    return ShareCreateResponse(token=share.token, expires_at=share.expires_at)


@router.post("/{doc_id}/restore", response_model=DocResponse)
async def restore_doc(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_token),
) -> Doc:
    doc = await db.get(Doc, doc_id)
    if not doc:
        raise APIError(404, "doc_not_found", f"Doc with id '{doc_id}' does not exist")
    if doc.deleted_at is None:
        raise APIError(400, "not_deleted", f"Doc with id '{doc_id}' is not deleted")
    if doc.parent_id is not None:
        parent = await db.get(Doc, doc.parent_id)
        if not parent or parent.deleted_at is not None:
            doc.parent_id = None
    ts = now_ms()
    doc.deleted_at = None
    doc.updated_at = ts
    await db.commit()
    await db.refresh(doc)
    return doc


@router.get("/{doc_id}/revisions", response_model=list[DocRevisionMeta])
async def list_revisions(
    doc_id: UUID,
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_token),
) -> list[DocRevision]:
    if not await db.get(Doc, doc_id):
        raise APIError(404, "doc_not_found", f"Doc with id '{doc_id}' does not exist")
    q = (
        select(DocRevision)
        .where(DocRevision.doc_id == doc_id)
        .order_by(DocRevision.created_at.desc())
        .limit(limit)
    )
    return list((await db.execute(q)).scalars().all())


@router.get(
    "/{doc_id}/revisions/{revision_id}", response_model=DocRevisionFull
)
async def get_revision(
    doc_id: UUID,
    revision_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_token),
) -> DocRevision:
    rev = await db.get(DocRevision, revision_id)
    if not rev or rev.doc_id != doc_id:
        raise APIError(404, "revision_not_found", f"Revision '{revision_id}' does not exist")
    return rev
