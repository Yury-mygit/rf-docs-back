import uuid

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy import Uuid as UuidType
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Doc(Base):
    __tablename__ = "docs"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UuidType(), ForeignKey("workspaces.id"), nullable=False, index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType(), ForeignKey("docs.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    kind: Mapped[str] = mapped_column(
        Text, nullable=False, default="page", server_default="page"
    )
    slug: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class DocRevision(Base):
    __tablename__ = "doc_revisions"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UuidType(), ForeignKey("docs.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ShareToken(Base):
    __tablename__ = "share_tokens"

    token: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UuidType(),
        ForeignKey("docs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
