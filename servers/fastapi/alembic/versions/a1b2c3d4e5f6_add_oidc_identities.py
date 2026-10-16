"""add oidc identities table

Revision ID: a1b2c3d4e5f6
Revises: 026c0ba8b35c
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "026c0ba8b35c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "oidc_identities" in inspector.get_table_names():
        return

    op.create_table(
        "oidc_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject", name="uq_oidc_identities_issuer_subject"),
    )
    op.create_index("ix_oidc_identities_issuer", "oidc_identities", ["issuer"])
    op.create_index("ix_oidc_identities_user_id", "oidc_identities", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_oidc_identities_user_id", table_name="oidc_identities")
    op.drop_index("ix_oidc_identities_issuer", table_name="oidc_identities")
    op.drop_table("oidc_identities")
