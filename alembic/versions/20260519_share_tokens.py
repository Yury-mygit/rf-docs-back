"""share tokens for docs

Revision ID: c3f2b1a8e5d4
Revises: 01f91c75b9cf
Create Date: 2026-05-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3f2b1a8e5d4"
down_revision: Union[str, None] = "01f91c75b9cf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "share_tokens",
        sa.Column("token", sa.Uuid(), nullable=False),
        sa.Column("doc_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("created_by_email", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["doc_id"], ["docs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token"),
    )
    op.create_index(
        op.f("ix_share_tokens_doc_id"), "share_tokens", ["doc_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_share_tokens_doc_id"), table_name="share_tokens")
    op.drop_table("share_tokens")
