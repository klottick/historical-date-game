"""Add private game-only guest owners and digest sessions.

Revision ID: 20261013_01
Revises: 20261011_01
"""

from alembic import op
import sqlalchemy as sa

revision = "20261013_01"
down_revision = "20261011_01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user", sa.Column("is_guest", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_check_constraint("ck_user_guest_not_superuser", "user", "NOT (is_guest AND is_superuser)")
    op.create_table(
        "guestsession",
        sa.Column("token_digest", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("public_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("expires_at > created_at", name="ck_guestsession_expiry"),
        sa.CheckConstraint("token_digest ~ '^[0-9a-f]{64}$'", name="ck_guestsession_digest"),
    )


def downgrade():
    op.drop_table("guestsession")
    op.drop_constraint("ck_user_guest_not_superuser", "user", type_="check")
    op.drop_column("user", "is_guest")
