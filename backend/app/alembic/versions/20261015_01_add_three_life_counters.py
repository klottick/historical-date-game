"""Add three-life counters only across an empty gameplay boundary.

Revision ID: 20261015_01
Revises: 20261013_01
"""

import sqlalchemy as sa
from alembic import op

revision = "20261015_01"
down_revision = "20261013_01"
branch_labels = None
depends_on = None


def _require_empty_gameplay() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        'LOCK TABLE "gameoperation", "gamerun", "dailydefinition" IN ACCESS EXCLUSIVE MODE'
    )
    for table in ("gameoperation", "gamerun", "dailydefinition"):
        count = bind.execute(sa.text(f'SELECT count(*) FROM "{table}"')).scalar_one()
        if count:
            raise RuntimeError(f"Cannot change three-life persistence while {table} is nonempty")


def upgrade() -> None:
    _require_empty_gameplay()
    op.add_column("gamerun", sa.Column("mistakes", sa.Integer(), nullable=False))
    op.add_column("gamerun", sa.Column("correct_count", sa.Integer(), nullable=False))
    op.create_check_constraint("ck_gamerun_mistakes", "gamerun", "mistakes BETWEEN 0 AND 3")
    op.create_check_constraint("ck_gamerun_correct_count", "gamerun", "correct_count >= 0")
    op.create_check_constraint(
        "ck_gamerun_state_invariant",
        "gamerun",
        "streak <= correct_count AND revision = correct_count + mistakes AND "
        "jsonb_array_length(timeline) = 1 + revision - CASE WHEN status = 'lost' THEN 1 ELSE 0 END AND "
        "((status = 'lost' AND mistakes = 3 AND streak = 0) OR "
        "(status <> 'lost' AND mistakes < 3)) AND "
        "(mistakes <> 0 OR streak = correct_count)",
    )


def downgrade() -> None:
    _require_empty_gameplay()
    op.drop_constraint("ck_gamerun_state_invariant", "gamerun", type_="check")
    op.drop_constraint("ck_gamerun_correct_count", "gamerun", type_="check")
    op.drop_constraint("ck_gamerun_mistakes", "gamerun", type_="check")
    op.drop_column("gamerun", "correct_count")
    op.drop_column("gamerun", "mistakes")
