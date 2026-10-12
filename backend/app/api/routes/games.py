"""Authenticated HTTP boundary; rules and transactions belong to game services."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.game import daily_service, run_service
from app.game.catalog_repository import CatalogError, load_options
from app.game.projections import public_year
from app.game.schemas import (
    DailyOverview,
    DailyStart,
    FreeplayStart,
    GameOptions,
    LeaderboardPublic,
    PlaceCommand,
    RunPublic,
)

router = APIRouter(prefix="/games", tags=["games"])


@router.get("/options", response_model=GameOptions)
def read_options(session: SessionDep, _current_user: CurrentUser) -> GameOptions:
    try:
        options = load_options(session)
        return GameOptions(
            catalog_release_id=options.release_id,
            categories=list(options.categories),
            start=public_year(options.start_year_index),
            end=public_year(options.end_year_index),
            registration_open=settings.PUBLIC_REGISTRATION_ENABLED,
        )
    except CatalogError as exc:
        session.rollback()
        raise run_service.GameServiceError(
            "catalog_unavailable", 503, "Game catalog unavailable"
        ) from exc


@router.post("/freeplay", response_model=RunPublic)
def start_freeplay(
    session: SessionDep, current_user: CurrentUser, body: FreeplayStart
) -> RunPublic:
    return run_service.start_freeplay(session, current_user.id, body)


@router.get("/active-runs", response_model=list[RunPublic])
def read_active_runs(session: SessionDep, current_user: CurrentUser) -> list[RunPublic]:
    return run_service.list_active_runs(session, current_user.id)


@router.get("/runs/{run_id}", response_model=RunPublic)
def read_run(session: SessionDep, current_user: CurrentUser, run_id: UUID) -> RunPublic:
    return run_service.read_run(session, current_user.id, run_id)


@router.post("/runs/{run_id}/placements", response_model=RunPublic)
def place_card(
    session: SessionDep, current_user: CurrentUser, run_id: UUID, body: PlaceCommand
) -> RunPublic:
    return run_service.submit_placement(session, current_user.id, run_id, body)


@router.get("/daily", response_model=DailyOverview)
def read_daily(session: SessionDep, current_user: CurrentUser) -> DailyOverview:
    # The service owns the timezone-aware UTC clock, not any client day/seed.
    return daily_service.read_daily(session, current_user.id)


@router.post("/daily", response_model=RunPublic)
def start_daily(
    session: SessionDep, current_user: CurrentUser, body: DailyStart
) -> RunPublic:
    return daily_service.start_daily(session, current_user.id, body)


@router.get("/daily/{day}/leaderboard", response_model=LeaderboardPublic)
def read_leaderboard(
    session: SessionDep, _current_user: CurrentUser, day: date
) -> LeaderboardPublic:
    return daily_service.read_leaderboard(session, day)
