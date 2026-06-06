"""models and platform settings

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-06 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "models",
        sa.Column("id", sa.String(length=256), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "data", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("models", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_models_provider"), ["provider"], unique=False)

    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column(
            "data", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
    with op.batch_alter_table("models", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_models_provider"))

    op.drop_table("models")
