import hashlib
import json
from datetime import date
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, select, text

from app.content.schemas import CategoryRecord, FallbackRecord, MediaRecord
from app.game.catalog_repository import CatalogError
from app.game.models import (
    CatalogCategory,
    DailyDefinition,
    GameOperation,
    GameRun,
    MediaAsset,
)
from app.models import User


def lock_run(session: Session, run_id: UUID, owner_id: UUID) -> GameRun:
    """Ownership-filtered row lock, held until the caller commits/rolls back.

    Missing and foreign-owned IDs are deliberately indistinguishable. Refresh
    existing identity-map state after waiting for another transaction's update.
    """
    run = session.exec(
        select(GameRun)
        .where(GameRun.id == run_id, GameRun.owner_id == owner_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if run is None:
        raise CatalogError("run_not_found")
    return run


def read_owned_run(session: Session, run_id: UUID, owner_id: UUID) -> GameRun:
    run = session.exec(
        select(GameRun)
        .where(GameRun.id == run_id, GameRun.owner_id == owner_id)
        .execution_options(populate_existing=True)
    ).first()
    if run is None:
        raise CatalogError("run_not_found")
    return run


def lock_owner(session: Session, owner_id: UUID) -> None:
    """Serialize starts without blocking placement's owner FK KEY SHARE check.

    NO KEY UPDATE is exclusive against another start (and owner deletion), but
    compatible with FK checks. FOR UPDATE would deadlock a new Daily operation
    on an existing attempt against a placement locking that attempt's run.
    """
    owner = session.exec(
        select(User).where(User.id == owner_id).with_for_update(key_share=True)
    ).first()
    if owner is None:
        raise CatalogError("run_not_found")


def lock_operation(session: Session, owner_id: UUID, operation_id: UUID) -> None:
    """Serialize the registry key across runs/scopes, even before a row exists.

    Collisions only serialize unrelated operations; the unique DB constraint is
    still authoritative. All mutators must acquire this before locking an owner
    or run row (including Daily start), so FK checks cannot invert lock order.
    """
    digest = hashlib.sha256(owner_id.bytes + operation_id.bytes).digest()
    key = int.from_bytes(digest[:8], "big", signed=True)
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def find_operation(
    session: Session, owner_id: UUID, operation_id: UUID
) -> GameOperation | None:
    return session.exec(
        select(GameOperation)
        .where(
            GameOperation.owner_id == owner_id,
            GameOperation.operation_id == operation_id,
        )
        .execution_options(populate_existing=True)
    ).first()


def load_categories(session: Session, release_id: str) -> tuple[CategoryRecord, ...]:
    rows = session.exec(
        select(CatalogCategory)
        .where(CatalogCategory.release_id == release_id)
        .order_by(CatalogCategory.category_id)
    ).all()
    if not rows:
        raise CatalogError("catalog_unavailable")
    return tuple(CategoryRecord.model_validate(row.snapshot) for row in rows)


def load_media(
    session: Session, release_id: str
) -> dict[str, MediaRecord | FallbackRecord]:
    rows = session.exec(
        select(MediaAsset).where(MediaAsset.release_id == release_id)
    ).all()
    return {
        row.key: (
            MediaRecord if row.key.startswith("asset:") else FallbackRecord
        ).model_validate_json(json.dumps(row.snapshot))
        for row in rows
    }


def latest_placement(session: Session, run: GameRun) -> GameOperation | None:
    # READ COMMITTED permits a move between the state and feedback queries. Select
    # this state's revision, not newer feedback from a concurrently committed move.
    return session.exec(
        select(GameOperation).where(
            GameOperation.run_id == run.id,
            GameOperation.owner_id == run.owner_id,
            GameOperation.scope == "placement",
            GameOperation.outcome["revision"].as_integer() == run.revision,
        )
    ).first()


def find_daily_definition(session: Session, day: date) -> DailyDefinition | None:
    return session.exec(
        select(DailyDefinition).where(DailyDefinition.day == day)
    ).first()


def insert_or_read_daily(
    session: Session, candidate: DailyDefinition
) -> DailyDefinition:
    """The unique UTC date chooses one winner without aborting a losing transaction.

    Under PostgreSQL READ COMMITTED, ON CONFLICT waits for the winning insert;
    the following statement sees that committed row (not our discarded seed).
    Neither this helper nor definition creation commits an attempt separately.
    """
    session.execute(
        insert(DailyDefinition)
        .values(**candidate.model_dump())
        .on_conflict_do_nothing(index_elements=["day"])
    )
    definition = find_daily_definition(session, candidate.day)
    if definition is None:
        raise CatalogError("catalog_unavailable")
    return definition


def find_daily_attempt(
    session: Session, owner_id: UUID, definition_id: UUID
) -> GameRun | None:
    # The revision-based B3 projection gives coherent state/feedback even if a
    # placement commits between this query and the projection's feedback query.
    return session.exec(
        select(GameRun)
        .where(
            GameRun.owner_id == owner_id, GameRun.daily_definition_id == definition_id
        )
        .execution_options(populate_existing=True)
    ).first()
