"""Game-player HTTP boundary; rules and transactions belong to game services."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.deps import SessionDep
from app.api.game_identity import (
    CurrentGamePlayer,
    require_guest_mutation,
    resolve_game_player,
)
from app.core.config import settings
from app.game import daily_service, run_service
from app.game.catalog_repository import CatalogError, load_options
from app.game.guest_sessions import bootstrap_guest_session
from app.game.models import utc_now
from app.game.projections import public_year
from app.game.protocol import GAME_PROTOCOL_VERSION
from app.game.schemas import (
    DailyOverview,
    DailyStart,
    FreeplayStart,
    GameOptions,
    GameSessionPublic,
    LeaderboardPublic,
    PlaceCommand,
    RunPublic,
)

router = APIRouter(prefix="/games", tags=["games"])
# Reuse the account scheme so generated clients still attach configured bearers.
# The empty alternative represents cookie identity, validated by CurrentGamePlayer.
GAME_PLAYER_SECURITY: dict[str, list[dict[str, list[str]]]] = {
    "security": [{"OAuth2PasswordBearer": []}, {}]
}
SESSION_RESPONSE_HEADERS = {
    "Cache-Control": "no-store",
    "Vary": "Cookie, Authorization",
}


def _session_error(
    error: run_service.GameServiceError | HTTPException,
) -> HTTPException:
    if isinstance(error, HTTPException):
        return HTTPException(
            status_code=error.status_code,
            detail=error.detail,
            headers={**(error.headers or {}), **SESSION_RESPONSE_HEADERS},
        )
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
        headers=SESSION_RESPONSE_HEADERS,
    )


@router.get(
    "/session", response_model=GameSessionPublic, openapi_extra=GAME_PLAYER_SECURITY
)
def read_game_session(
    request: Request, response: Response, session: SessionDep
) -> GameSessionPublic:
    try:
        player = resolve_game_player(request, session, require_context=False)
    except (run_service.GameServiceError, HTTPException) as exc:
        raise _session_error(exc) from exc
    response.headers.update(SESSION_RESPONSE_HEADERS)
    return GameSessionPublic(
        kind=player.kind,
        context_id=player.context_id,
        protocol_version=GAME_PROTOCOL_VERSION,
    )


@router.post(
    "/session", response_model=GameSessionPublic, openapi_extra=GAME_PLAYER_SECURITY
)
def bootstrap_game_session(
    request: Request, response: Response, session: SessionDep
) -> GameSessionPublic:
    try:
        if request.headers.get("authorization") is not None:
            player = resolve_game_player(request, session, require_context=False)
        else:
            require_guest_mutation(request)
            bootstrap = bootstrap_guest_session(
                session, request.cookies.get(settings.GAME_GUEST_COOKIE_NAME), utc_now()
            )
            session.commit()
            player = bootstrap.player
            response.set_cookie(
                key=settings.GAME_GUEST_COOKIE_NAME,
                value=bootstrap.credential,
                max_age=90 * 24 * 60 * 60,
                path=f"{settings.API_V1_STR}/games",
                secure=settings.ENVIRONMENT != "local",
                httponly=True,
                samesite="lax",
            )
    except (run_service.GameServiceError, HTTPException) as exc:
        session.rollback()
        raise _session_error(exc) from exc
    except Exception:
        session.rollback()
        raise
    response.headers.update(SESSION_RESPONSE_HEADERS)
    return GameSessionPublic(
        kind=player.kind,
        context_id=player.context_id,
        protocol_version=GAME_PROTOCOL_VERSION,
    )


@router.get("/options", response_model=GameOptions)
def read_options(session: SessionDep) -> GameOptions:
    try:
        options = load_options(session)
        return GameOptions(
            protocol_version=GAME_PROTOCOL_VERSION,
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


@router.post("/freeplay", response_model=RunPublic, openapi_extra=GAME_PLAYER_SECURITY)
def start_freeplay(
    session: SessionDep, current_player: CurrentGamePlayer, body: FreeplayStart
) -> RunPublic:
    return run_service.start_freeplay(session, current_player.owner_id, body)


@router.get(
    "/active-runs", response_model=list[RunPublic], openapi_extra=GAME_PLAYER_SECURITY
)
def read_active_runs(
    session: SessionDep, current_player: CurrentGamePlayer
) -> list[RunPublic]:
    return run_service.list_active_runs(session, current_player.owner_id)


@router.get(
    "/runs/{run_id}", response_model=RunPublic, openapi_extra=GAME_PLAYER_SECURITY
)
def read_run(
    session: SessionDep, current_player: CurrentGamePlayer, run_id: UUID
) -> RunPublic:
    return run_service.read_run(session, current_player.owner_id, run_id)


@router.post(
    "/runs/{run_id}/placements",
    response_model=RunPublic,
    openapi_extra=GAME_PLAYER_SECURITY,
)
def place_card(
    session: SessionDep,
    current_player: CurrentGamePlayer,
    run_id: UUID,
    body: PlaceCommand,
) -> RunPublic:
    return run_service.submit_placement(session, current_player.owner_id, run_id, body)


@router.get("/daily", response_model=DailyOverview, openapi_extra=GAME_PLAYER_SECURITY)
def read_daily(session: SessionDep, current_player: CurrentGamePlayer) -> DailyOverview:
    # The service owns the timezone-aware UTC clock, not any client day/seed.
    return daily_service.read_daily(session, current_player.owner_id)


@router.post("/daily", response_model=RunPublic, openapi_extra=GAME_PLAYER_SECURITY)
def start_daily(
    session: SessionDep, current_player: CurrentGamePlayer, body: DailyStart
) -> RunPublic:
    return daily_service.start_daily(session, current_player.owner_id, body)


@router.get(
    "/daily/{day}/leaderboard",
    response_model=LeaderboardPublic,
    openapi_extra=GAME_PLAYER_SECURITY,
)
def read_leaderboard(
    session: SessionDep, _current_player: CurrentGamePlayer, day: date
) -> LeaderboardPublic:
    return daily_service.read_leaderboard(session, day)
