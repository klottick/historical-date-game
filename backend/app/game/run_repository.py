from uuid import UUID

from sqlmodel import Session, select

from app.game.catalog_repository import CatalogError
from app.game.models import GameRun


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
