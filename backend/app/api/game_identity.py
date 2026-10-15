"""Game-only authentication; context binding is not an authorization credential."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security.utils import get_authorization_scheme_param
from sqlmodel import Session

from app.api.deps import SessionDep, get_current_user
from app.core.config import settings
from app.game.guest_sessions import GamePlayer, account_player, resolve_guest_session
from app.game.models import utc_now
from app.game.run_service import GameServiceError


def require_guest_mutation(request: Request) -> None:
    if (
        request.headers.get("x-game-request") != "1"
        or request.headers.get("origin") not in settings.all_cors_origins
    ):
        raise GameServiceError(
            "game_request_rejected", 403, "Game request origin or header rejected"
        )


def resolve_game_player(
    request: Request, session: Session, *, require_context: bool
) -> GamePlayer:
    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, token = get_authorization_scheme_param(authorization)
        if scheme.lower() != "bearer" or not token:
            # Preserve OAuth2PasswordBearer's missing/malformed bearer behavior.
            raise HTTPException(
                status_code=401,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            user = get_current_user(session, token)
        except HTTPException as exc:
            # Only account resolution failures are session errors. Ordinary game
            # validation/ownership 400s and 404s retain their service contracts.
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": "invalid_account", "message": str(exc.detail)},
                headers=exc.headers,
            ) from exc
        player = account_player(user)
    else:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            require_guest_mutation(request)
        player = resolve_guest_session(
            session, request.cookies.get(settings.GAME_GUEST_COOKIE_NAME), utc_now()
        )
    context = request.headers.get("x-game-context")
    if require_context and (
        (player.kind == "guest" or context is not None) and context != player.context_id
    ):
        raise GameServiceError(
            "game_identity_changed", 409, "Game identity changed; confirm session setup"
        )
    return player


def get_current_game_player(request: Request, session: SessionDep) -> GamePlayer:
    return resolve_game_player(request, session, require_context=True)


CurrentGamePlayer = Annotated[GamePlayer, Depends(get_current_game_player)]
