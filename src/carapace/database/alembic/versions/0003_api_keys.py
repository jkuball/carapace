"""api keys

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-11 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

import carapace.database.base

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("secret_hash", sa.String(length=128), nullable=False),
        sa.Column("user", sa.String(length=256), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "scopes", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.Column("created_at", carapace.database.base.UtcDateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", carapace.database.base.UtcDateTime(timezone=True), nullable=True),
        sa.Column("expires_at", carapace.database.base.UtcDateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", carapace.database.base.UtcDateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user"], ["users.username"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_api_keys_prefix"), ["prefix"], unique=True)
        batch_op.create_index(batch_op.f("ix_api_keys_user"), ["user"], unique=False)
        batch_op.create_index(batch_op.f("ix_api_keys_expires_at"), ["expires_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_api_keys_expires_at"))
        batch_op.drop_index(batch_op.f("ix_api_keys_user"))
        batch_op.drop_index(batch_op.f("ix_api_keys_prefix"))

    op.drop_table("api_keys")
