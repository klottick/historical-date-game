"""Game-only identities. Bootstrap participates in the caller's transaction."""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlmodel import Session

from app.core.config import settings
from app.core.security import get_password_hash
from app.game.guest_models import GuestSession
from app.game.run_service import GameServiceError
from app.models import User


@dataclass(frozen=True)
class GamePlayer:
    owner_id: UUID
    kind: Literal["guest", "account"]
    context_id: str


@dataclass(frozen=True)
class GuestBootstrap:
    player: GamePlayer
    credential: str = field(repr=False)
    expires_at: datetime


def _utc(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Guest sessions require a timezone-aware clock")
    return now.astimezone(UTC)


def _valid_session(
    session: Session, credential: str | None, now: datetime
) -> GuestSession | None:
    if credential is None or re.fullmatch(r"[A-Za-z0-9_-]{43}", credential) is None:
        return None
    digest = hashlib.sha256(credential.encode()).hexdigest()
    stored = session.get(GuestSession, digest)
    if stored is None or stored.expires_at <= now:
        return None
    owner = session.get(User, stored.owner_id)
    if owner is None or not owner.is_active or not owner.is_guest or owner.is_superuser:
        return None
    return stored


def _guest_player(stored: GuestSession) -> GamePlayer:
    return GamePlayer(stored.owner_id, "guest", f"g:{stored.public_id}")


def bootstrap_guest_session(
    session: Session, credential: str | None, now: datetime
) -> GuestBootstrap:
    now = _utc(now)
    stored = _valid_session(session, credential, now)
    if stored is not None:
        stored.expires_at = now + timedelta(days=90)
        session.add(stored)
        session.flush()
        # _valid_session cannot succeed without a credential.
        assert credential is not None
        return GuestBootstrap(_guest_player(stored), credential, stored.expires_at)

    credential = secrets.token_urlsafe(32)
    owner_id = uuid4()
    owner = User(
        id=owner_id,
        email=f"guest-{owner_id}@guests.example.com",
        hashed_password=get_password_hash(secrets.token_urlsafe(32)),
        full_name="Guest",
        is_active=True,
        is_superuser=False,
        is_guest=True,
    )
    session.add(owner)
    session.flush()
    stored = GuestSession(
        token_digest=hashlib.sha256(credential.encode()).hexdigest(),
        owner_id=owner_id,
        created_at=now,
        expires_at=now + timedelta(days=90),
    )
    session.add(stored)
    session.flush()
    return GuestBootstrap(_guest_player(stored), credential, stored.expires_at)


def resolve_guest_session(
    session: Session, credential: str | None, now: datetime
) -> GamePlayer:
    with session.no_autoflush:
        stored = _valid_session(session, credential, _utc(now))
    if stored is None:
        raise GameServiceError(
            "game_session_required",
            401,
            "Game session unavailable; retry session setup",
        )
    return _guest_player(stored)


def account_player(user: User) -> GamePlayer:
    if user.is_guest or not user.is_active:
        raise GameServiceError(
            "invalid_account", 403, "Account authentication required"
        )
    digest = hmac.new(
        settings.SECRET_KEY.encode(),
        f"hdg:game-account-context:v1:{user.id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return GamePlayer(user.id, "account", f"a:{digest}")
