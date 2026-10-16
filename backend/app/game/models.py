"""Private persistence models. Never serialize these as public game responses.

Imported by app.models to register all tables; this module must not import it back.
"""

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    LargeBinary,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models import User


def utc_now() -> datetime:
    return datetime.now(UTC)


def json_column() -> Column[Any]:
    return Column(JSONB, nullable=False)


def timestamp_column() -> Column[Any]:
    return Column(DateTime(timezone=True), nullable=False)


def rules_constraint(name: str) -> CheckConstraint:
    return CheckConstraint(
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


class CatalogRelease(SQLModel, table=True):
    id: str = Field(primary_key=True, max_length=128)
    manifest: dict[str, Any] = Field(sa_column=json_column())
    manifest_bytes: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    manifest_sha256: str = Field(max_length=64)
    created_at: datetime = Field(sa_column=timestamp_column())
    activated_at: datetime = Field(
        default_factory=utc_now, sa_column=timestamp_column()
    )
    event_count: int
    fixture: bool
    __table_args__ = (
        CheckConstraint("event_count > 0", name="ck_catalogrelease_count"),
        CheckConstraint(
            "manifest_sha256 ~ '^[0-9a-f]{64}$'", name="ck_catalogrelease_digest"
        ),
    )


class CatalogSelection(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    release_id: str = Field(foreign_key="catalogrelease.id", nullable=False)
    __table_args__ = (CheckConstraint("id = 1", name="ck_catalogselection_singleton"),)


class CatalogCategory(SQLModel, table=True):
    release_id: str = Field(foreign_key="catalogrelease.id", primary_key=True)
    category_id: str = Field(primary_key=True)
    snapshot: dict[str, Any] = Field(sa_column=json_column())


class EventRevision(SQLModel, table=True):
    release_id: str = Field(foreign_key="catalogrelease.id", primary_key=True)
    event_id: UUID = Field(primary_key=True)
    snapshot: dict[str, Any] = Field(sa_column=json_column())


class MediaAsset(SQLModel, table=True):
    # Keys are 'asset:<UUID>' or 'fallback:<key>', preserving both C2 shapes.
    release_id: str = Field(foreign_key="catalogrelease.id", primary_key=True)
    key: str = Field(primary_key=True)
    snapshot: dict[str, Any] = Field(sa_column=json_column())


class DailyDefinition(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    day: date = Field(unique=True)
    catalog_release_id: str = Field(foreign_key="catalogrelease.id", nullable=False)
    seed: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    generation_version: int = 1
    rules: dict[str, Any] = Field(sa_column=json_column())
    pool: list[str] = Field(sa_column=json_column())
    order: list[str] = Field(sa_column=json_column())
    anchor_event_id: UUID
    created_at: datetime = Field(default_factory=utc_now, sa_column=timestamp_column())
    __table_args__ = (
        UniqueConstraint("id", "catalog_release_id", name="uq_dailydefinition_release"),
        ForeignKeyConstraint(
            ["catalog_release_id", "anchor_event_id"],
            ["eventrevision.release_id", "eventrevision.event_id"],
        ),
        CheckConstraint("octet_length(seed) = 32", name="ck_dailydefinition_seed"),
        CheckConstraint("generation_version = 1", name="ck_dailydefinition_generation"),
        CheckConstraint(
            "jsonb_typeof(pool) = 'array' AND jsonb_array_length(pool) > 0 AND jsonb_typeof(\"order\") = 'array' AND jsonb_array_length(\"order\") = jsonb_array_length(pool)",
            name="ck_dailydefinition_pool",
        ),
        rules_constraint("ck_dailydefinition_rules"),
    )


class GameRun(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    owner_id: UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    owner: User = Relationship(back_populates="game_runs")
    mode: str
    daily_definition_id: UUID | None = Field(default=None)
    catalog_release_id: str = Field(foreign_key="catalogrelease.id", nullable=False)
    seed: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    generation_version: int = 1
    rules: dict[str, Any] = Field(sa_column=json_column())
    pool: list[str] = Field(sa_column=json_column())
    order: list[str] = Field(sa_column=json_column())
    timeline: list[str] = Field(sa_column=json_column())
    pending_event_id: UUID | None = None
    status: str
    streak: int
    mistakes: int = Field(default=0)
    correct_count: int = Field(default=0)
    revision: int
    created_at: datetime = Field(default_factory=utc_now, sa_column=timestamp_column())
    updated_at: datetime = Field(default_factory=utc_now, sa_column=timestamp_column())
    finished_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "daily_definition_id", name="uq_gamerun_owner_daily"
        ),
        UniqueConstraint("id", "owner_id", name="uq_gamerun_owner"),
        ForeignKeyConstraint(
            ["daily_definition_id", "catalog_release_id"],
            ["dailydefinition.id", "dailydefinition.catalog_release_id"],
        ),
        ForeignKeyConstraint(
            ["catalog_release_id", "pending_event_id"],
            ["eventrevision.release_id", "eventrevision.event_id"],
        ),
        CheckConstraint(
            "(mode = 'daily' AND daily_definition_id IS NOT NULL) OR (mode = 'freeplay' AND daily_definition_id IS NULL)",
            name="ck_gamerun_mode",
        ),
        CheckConstraint("octet_length(seed) = 32", name="ck_gamerun_seed"),
        CheckConstraint("generation_version = 1", name="ck_gamerun_generation"),
        CheckConstraint(
            "status IN ('active', 'lost', 'won')", name="ck_gamerun_status"
        ),
        CheckConstraint("streak >= 0 AND revision >= 0", name="ck_gamerun_counters"),
        CheckConstraint("mistakes BETWEEN 0 AND 3", name="ck_gamerun_mistakes"),
        CheckConstraint("correct_count >= 0", name="ck_gamerun_correct_count"),
        CheckConstraint(
            "streak <= correct_count AND revision = correct_count + mistakes AND "
            "jsonb_array_length(timeline) = 1 + revision - CASE WHEN status = 'lost' THEN 1 ELSE 0 END AND "
            "((status = 'lost' AND mistakes = 3 AND streak = 0) OR "
            "(status <> 'lost' AND mistakes < 3)) AND "
            "(mistakes <> 0 OR streak = correct_count)",
            name="ck_gamerun_state_invariant",
        ),
        CheckConstraint(
            "(status = 'active' AND pending_event_id IS NOT NULL) OR (status <> 'active' AND pending_event_id IS NULL)",
            name="ck_gamerun_pending",
        ),
        CheckConstraint(
            "jsonb_typeof(pool) = 'array' AND jsonb_array_length(pool) > 0 AND jsonb_typeof(\"order\") = 'array' AND jsonb_array_length(\"order\") = jsonb_array_length(pool) AND jsonb_typeof(timeline) = 'array' AND jsonb_array_length(timeline) > 0",
            name="ck_gamerun_pool",
        ),
        rules_constraint("ck_gamerun_rules"),
    )


class GameOperation(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    owner_id: UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    owner: User = Relationship(back_populates="game_operations")
    operation_id: UUID
    scope: str
    run_id: UUID
    payload_digest: str = Field(max_length=64)
    outcome: dict[str, Any] = Field(sa_column=json_column())
    created_at: datetime = Field(default_factory=utc_now, sa_column=timestamp_column())
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "operation_id", name="uq_gameoperation_owner_operation"
        ),
        ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["gamerun.id", "gamerun.owner_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "scope IN ('freeplay', 'daily', 'placement')", name="ck_gameoperation_scope"
        ),
        CheckConstraint(
            "payload_digest ~ '^[0-9a-f]{64}$'", name="ck_gameoperation_digest"
        ),
        CheckConstraint(
            "jsonb_typeof(outcome) = 'object'", name="ck_gameoperation_outcome"
        ),
    )
