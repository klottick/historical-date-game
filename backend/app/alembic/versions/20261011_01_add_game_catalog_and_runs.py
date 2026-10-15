"""Persist immutable catalog releases and private game state.

Revision ID: 20261011_01
Revises: 1a31ce608336
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261011_01"
down_revision = "1a31ce608336"
branch_labels = None
depends_on = None


# Frozen migration definitions, deliberately independent of runtime models.
def _json(name):
    return sa.Column(name, postgresql.JSONB(), nullable=False)


def _time(name):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False)


def _rules(name):
    return sa.CheckConstraint(
        "(jsonb_typeof(rules) = 'object' AND rules ?& ARRAY['category_ids', "
        "'start_year_index', 'end_year_index', 'min_gap'] AND "
        "jsonb_typeof(rules->'category_ids') = 'array' AND "
        "jsonb_array_length(rules->'category_ids') > 0 AND "
        "jsonb_typeof(rules->'min_gap') = 'number' AND "
        "jsonb_typeof(rules->'start_year_index') = 'number' AND "
        "jsonb_typeof(rules->'end_year_index') = 'number' AND "
        "(rules->>'min_gap') ~ '^[1-9][0-9]*$' AND "
        "(rules->>'start_year_index') ~ '^-?[0-9]+$' AND "
        "(rules->>'end_year_index') ~ '^-?[0-9]+$' AND "
        "(rules->>'start_year_index')::bigint <= (rules->>'end_year_index')::bigint) IS TRUE",
        name=name,
    )


def _pool(name, timeline=False):
    condition = (
        "jsonb_typeof(pool) = 'array' AND jsonb_array_length(pool) > 0 AND "
        "jsonb_typeof(\"order\") = 'array' AND "
        "jsonb_array_length(\"order\") = jsonb_array_length(pool)"
    )
    if timeline:
        condition += " AND jsonb_typeof(timeline) = 'array' AND jsonb_array_length(timeline) > 0"
    return sa.CheckConstraint(condition, name=name)


def upgrade():
    op.create_table(
        "catalogrelease",
        sa.Column("id", sa.String(128), primary_key=True),
        _json("manifest"),
        sa.Column("manifest_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        _time("created_at"), _time("activated_at"),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("fixture", sa.Boolean(), nullable=False),
        sa.CheckConstraint("event_count > 0", name="ck_catalogrelease_count"),
        sa.CheckConstraint("manifest_sha256 ~ '^[0-9a-f]{64}$'", name="ck_catalogrelease_digest"),
    )
    op.create_table(
        "catalogselection",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("release_id", sa.String(), sa.ForeignKey("catalogrelease.id"), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_catalogselection_singleton"),
    )
    op.create_table(
        "catalogcategory",
        sa.Column("release_id", sa.String(), sa.ForeignKey("catalogrelease.id"), primary_key=True),
        sa.Column("category_id", sa.String(), primary_key=True), _json("snapshot"),
    )
    op.create_table(
        "eventrevision",
        sa.Column("release_id", sa.String(), sa.ForeignKey("catalogrelease.id"), primary_key=True),
        sa.Column("event_id", sa.Uuid(), primary_key=True), _json("snapshot"),
    )
    op.create_table(
        "mediaasset",
        sa.Column("release_id", sa.String(), sa.ForeignKey("catalogrelease.id"), primary_key=True),
        sa.Column("key", sa.String(), primary_key=True), _json("snapshot"),
    )
    op.create_table(
        "dailydefinition",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False, unique=True),
        sa.Column("catalog_release_id", sa.String(), sa.ForeignKey("catalogrelease.id"), nullable=False),
        sa.Column("seed", sa.LargeBinary(), nullable=False),
        sa.Column("generation_version", sa.Integer(), nullable=False),
        _json("rules"), _json("pool"), _json("order"),
        sa.Column("anchor_event_id", sa.Uuid(), nullable=False), _time("created_at"),
        sa.UniqueConstraint("id", "catalog_release_id", name="uq_dailydefinition_release"),
        sa.ForeignKeyConstraint(["catalog_release_id", "anchor_event_id"], ["eventrevision.release_id", "eventrevision.event_id"]),
        sa.CheckConstraint("octet_length(seed) = 32", name="ck_dailydefinition_seed"),
        sa.CheckConstraint("generation_version = 1", name="ck_dailydefinition_generation"),
        _rules("ck_dailydefinition_rules"), _pool("ck_dailydefinition_pool"),
    )
    op.create_table(
        "gamerun",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("daily_definition_id", sa.Uuid()),
        sa.Column("catalog_release_id", sa.String(), sa.ForeignKey("catalogrelease.id"), nullable=False),
        sa.Column("seed", sa.LargeBinary(), nullable=False),
        sa.Column("generation_version", sa.Integer(), nullable=False),
        _json("rules"), _json("pool"), _json("order"), _json("timeline"),
        sa.Column("pending_event_id", sa.Uuid()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("streak", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        _time("created_at"), _time("updated_at"),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("owner_id", "daily_definition_id", name="uq_gamerun_owner_daily"),
        sa.UniqueConstraint("id", "owner_id", name="uq_gamerun_owner"),
        sa.ForeignKeyConstraint(["daily_definition_id", "catalog_release_id"], ["dailydefinition.id", "dailydefinition.catalog_release_id"]),
        sa.ForeignKeyConstraint(["catalog_release_id", "pending_event_id"], ["eventrevision.release_id", "eventrevision.event_id"]),
        sa.CheckConstraint("(mode = 'daily' AND daily_definition_id IS NOT NULL) OR (mode = 'freeplay' AND daily_definition_id IS NULL)", name="ck_gamerun_mode"),
        sa.CheckConstraint("octet_length(seed) = 32", name="ck_gamerun_seed"),
        sa.CheckConstraint("generation_version = 1", name="ck_gamerun_generation"),
        sa.CheckConstraint("status IN ('active', 'lost', 'won')", name="ck_gamerun_status"),
        sa.CheckConstraint("streak >= 0 AND revision >= 0", name="ck_gamerun_counters"),
        sa.CheckConstraint("(status = 'active' AND pending_event_id IS NOT NULL) OR (status <> 'active' AND pending_event_id IS NULL)", name="ck_gamerun_pending"),
        _rules("ck_gamerun_rules"), _pool("ck_gamerun_pool", timeline=True),
    )
    op.create_index("ix_gamerun_owner_id", "gamerun", ["owner_id"])
    op.create_table(
        "gameoperation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False), _json("outcome"),
        _time("created_at"),
        sa.UniqueConstraint("owner_id", "operation_id", name="uq_gameoperation_owner_operation"),
        sa.ForeignKeyConstraint(["run_id", "owner_id"], ["gamerun.id", "gamerun.owner_id"], ondelete="CASCADE"),
        sa.CheckConstraint("scope IN ('freeplay', 'daily', 'placement')", name="ck_gameoperation_scope"),
        sa.CheckConstraint("payload_digest ~ '^[0-9a-f]{64}$'", name="ck_gameoperation_digest"),
        sa.CheckConstraint("jsonb_typeof(outcome) = 'object'", name="ck_gameoperation_outcome"),
    )
    op.create_index("ix_gameoperation_owner_id", "gameoperation", ["owner_id"])
    # Updates cannot silently rewrite frozen answers, provenance, daily generation,
    # or exact recorded responses. Deletes remain available for dependency-ordered
    # guarded test cleanup and owner cascades; FK restrictions retain shared rows.
    op.execute("""
        CREATE FUNCTION hdg_reject_frozen_update() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            IF NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'immutable_game_snapshot' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    for table in ("catalogrelease", "catalogcategory", "eventrevision", "mediaasset", "dailydefinition", "gameoperation"):
        op.execute(f"CREATE TRIGGER immutable_snapshot BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION hdg_reject_frozen_update()")


def downgrade():
    # Only run on disposable fixture databases, never a scored beta database.
    for table in ("gameoperation", "gamerun", "dailydefinition", "catalogselection", "mediaasset", "eventrevision", "catalogcategory", "catalogrelease"):
        op.drop_table(table)
    op.execute("DROP FUNCTION hdg_reject_frozen_update()")
