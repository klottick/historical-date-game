"""Real PostgreSQL persistence and the ordinary-account exclusion boundary."""

import hashlib
import hmac
import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select, text

from app import crud
from app.core.config import Settings, settings
from app.core.db import engine
from app.core.security import create_access_token, get_password_hash
from app.game.run_service import GameServiceError
from app.models import User, UserCreate, UserPublic
from app.utils import generate_password_reset_token

NOW = datetime(2026, 10, 13, tzinfo=UTC)


def test_bootstrap_stores_only_digest_and_reuses_owner(db: Session) -> None:
    from app.game.guest_models import GuestSession
    from app.game.guest_sessions import bootstrap_guest_session, resolve_guest_session

    first = bootstrap_guest_session(db, None, NOW)
    db.commit()
    second = bootstrap_guest_session(
        db, first.credential, datetime(2026, 10, 14, tzinfo=UTC)
    )
    assert second.player == first.player
    assert second.expires_at == datetime(2027, 1, 12, tzinfo=UTC)
    assert second.credential == first.credential
    assert first.player.kind == "guest"
    owner = db.get(User, first.player.owner_id)
    assert owner is not None
    assert owner.full_name == "Guest"
    assert owner.is_active and owner.is_guest
    assert owner.is_superuser is False
    assert owner.email.startswith("guest-") and owner.email.endswith(
        "@guests.example.com"
    )
    UserPublic.model_validate(owner)  # Placeholder satisfies the inherited EmailStr.
    stored = db.exec(
        select(GuestSession).where(GuestSession.owner_id == owner.id)
    ).one()
    assert stored.token_digest == hashlib.sha256(first.credential.encode()).hexdigest()
    assert first.player.context_id == f"g:{stored.public_id}"
    assert str(owner.id) not in first.player.context_id
    assert len(first.credential) == 43
    serialized_database_rows = json.dumps(
        [
            db.execute(
                text('SELECT row_to_json(u)::text FROM "user" u WHERE id = :id'),
                {"id": owner.id},
            ).scalar_one(),
            db.execute(
                text(
                    "SELECT row_to_json(g)::text FROM guestsession g WHERE owner_id = :id"
                ),
                {"id": owner.id},
            ).scalar_one(),
        ]
    )
    assert first.credential not in serialized_database_rows
    assert first.credential not in repr(first)
    db.commit()
    with Session(engine) as restarted:
        assert resolve_guest_session(restarted, first.credential, NOW) == first.player
    with pytest.raises(FrozenInstanceError):
        first.player.kind = "account"


def test_expiry_refresh_is_90_days(db: Session) -> None:
    from app.game.guest_models import GuestSession
    from app.game.guest_sessions import bootstrap_guest_session, resolve_guest_session

    first = bootstrap_guest_session(db, None, NOW)
    assert first.expires_at == datetime(2027, 1, 11, tzinfo=UTC)
    db.commit()
    stored = db.get(GuestSession, hashlib.sha256(first.credential.encode()).hexdigest())
    assert stored.created_at == NOW
    assert stored.expires_at.utcoffset() == timedelta(0)
    resolve_guest_session(db, first.credential, datetime(2026, 10, 14, tzinfo=UTC))
    assert stored.expires_at == datetime(
        2027, 1, 11, tzinfo=UTC
    )  # Inspection is read-only.
    refresh = bootstrap_guest_session(
        db,
        first.credential,
        datetime(2026, 10, 14, 2, tzinfo=timezone(timedelta(hours=2))),
    )
    assert refresh.expires_at == datetime(2027, 1, 12, tzinfo=UTC)
    assert stored.created_at == NOW
    db.commit()


@pytest.mark.parametrize(
    "credential", [None, "", "bad", "x" * 42, "x" * 44, "!" * 43, "x" * 10000, "a" * 43]
)
def test_invalid_session_reads_never_allocate(
    db: Session, credential: str | None
) -> None:
    from app.game.guest_models import GuestSession
    from app.game.guest_sessions import resolve_guest_session

    before = (
        db.exec(select(func.count()).select_from(User)).one(),
        db.exec(select(func.count()).select_from(GuestSession)).one(),
    )
    with pytest.raises(GameServiceError) as exc:
        resolve_guest_session(db, credential, NOW)
    assert exc.value.status_code == 401
    assert (
        db.exec(select(func.count()).select_from(User)).one(),
        db.exec(select(func.count()).select_from(GuestSession)).one(),
    ) == before
    assert not db.new and not db.dirty


@pytest.mark.parametrize("kind", ["expired", "revoked", "inactive", "account", "admin"])
def test_invalid_owner_or_session_requires_explicit_replacement(
    db: Session, kind: str
) -> None:
    from app.game.guest_models import GuestSession
    from app.game.guest_sessions import bootstrap_guest_session, resolve_guest_session

    first = bootstrap_guest_session(db, None, NOW)
    db.commit()
    owner = db.get(User, first.player.owner_id)
    stored = db.get(GuestSession, hashlib.sha256(first.credential.encode()).hexdigest())
    if kind == "revoked":
        db.delete(stored)
    elif kind == "expired":
        stored.expires_at = NOW + timedelta(days=1)
        db.add(stored)
    elif kind == "inactive":
        owner.is_active = False
        db.add(owner)
    else:
        owner.is_guest = False
        owner.is_superuser = kind == "admin"
        db.add(owner)
    db.commit()
    later = datetime(2026, 10, 14, tzinfo=UTC)
    with pytest.raises(GameServiceError):
        resolve_guest_session(db, first.credential, later)
    replacement = bootstrap_guest_session(db, first.credential, later)
    assert replacement.player.owner_id != first.player.owner_id
    assert replacement.credential != first.credential
    db.commit()
    # The old owner is retained; bootstrap never deletes progress.
    assert db.get(User, first.player.owner_id) is not None


def test_naive_clocks_are_rejected_without_allocation(db: Session) -> None:
    from app.game.guest_sessions import bootstrap_guest_session, resolve_guest_session

    before = db.exec(select(func.count()).select_from(User)).one()
    for helper in (bootstrap_guest_session, resolve_guest_session):
        with pytest.raises(ValueError):
            helper(db, None, datetime(2026, 10, 13))
    assert db.exec(select(func.count()).select_from(User)).one() == before


def test_bootstrap_is_atomic_and_caller_owns_commit(db: Session) -> None:
    from app.game.guest_models import GuestSession
    from app.game.guest_sessions import bootstrap_guest_session

    db.rollback()
    with Session(engine) as writer:
        first = bootstrap_guest_session(writer, None, NOW)
        digest = hashlib.sha256(first.credential.encode()).hexdigest()
        with Session(engine) as observer:
            assert observer.get(User, first.player.owner_id) is None
            assert observer.get(GuestSession, digest) is None
        writer.rollback()
    with Session(engine) as observer:
        assert observer.get(User, first.player.owner_id) is None
        assert observer.get(GuestSession, digest) is None


def test_guest_cannot_use_account_auth_or_recovery(
    db: Session,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.game.guest_sessions import bootstrap_guest_session

    first = bootstrap_guest_session(db, None, NOW)
    owner = db.get(User, first.player.owner_id)
    owner.hashed_password = get_password_hash("known-test-password")
    db.add(owner)
    db.commit()

    def no_email(*_args: object, **_kwargs: object) -> None:
        pytest.fail("internal guest was sent an account email")

    monkeypatch.setattr("app.api.routes.login.send_email", no_email)
    assert (
        crud.authenticate(session=db, email=owner.email, password="known-test-password")
        is None
    )
    login = client.post(
        "/api/v1/login/access-token",
        data={"username": owner.email, "password": "known-test-password"},
    )
    assert login.status_code == 400 and "access_token" not in login.json()
    forged = {
        "Authorization": f"Bearer {create_access_token(owner.id, timedelta(days=1))}"
    }
    for path in ("/users/me", "/users/", "/items/"):
        assert client.get("/api/v1" + path, headers=forged).status_code == 403
        assert (
            client.get(
                "/api/v1" + path,
                headers={
                    "Cookie": f"{settings.GAME_GUEST_COOKIE_NAME}={first.credential}"
                },
            ).status_code
            == 401
        )
    assert client.post("/api/v1/login/test-token", headers=forged).status_code == 403
    assert (
        client.patch(
            "/api/v1/users/me", headers=forged, json={"full_name": "Account"}
        ).status_code
        == 403
    )
    assert client.delete("/api/v1/users/me", headers=forged).status_code == 403
    assert client.post(f"/api/v1/password-recovery/{owner.email}").status_code == 404
    assert (
        client.post(
            f"/api/v1/password-recovery-html-content/{owner.email}",
            headers=superuser_token_headers,
        ).status_code
        == 404
    )
    token = generate_password_reset_token(owner.email)
    assert (
        client.post(
            "/api/v1/reset-password/",
            json={"token": token, "new_password": "new-test-password"},
        ).status_code
        == 404
    )
    db.refresh(owner)
    assert owner.is_guest and owner.full_name == "Guest"


def test_admin_cannot_convert_or_list_internal_guests(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    from app.game.guest_sessions import bootstrap_guest_session

    before = client.get(
        "/api/v1/users/?limit=10000", headers=superuser_token_headers
    ).json()
    first = bootstrap_guest_session(db, None, NOW)
    db.commit()
    after = client.get(
        "/api/v1/users/?limit=10000", headers=superuser_token_headers
    ).json()
    assert after == before
    assert str(first.player.owner_id) not in json.dumps(after)
    path = f"/api/v1/users/{first.player.owner_id}"
    assert client.get(path, headers=superuser_token_headers).status_code == 404
    assert (
        client.patch(
            path,
            headers=superuser_token_headers,
            json={"is_guest": False, "is_superuser": True, "password": "new-password"},
        ).status_code
        == 404
    )
    assert client.delete(path, headers=superuser_token_headers).status_code == 404
    db.refresh(db.get(User, first.player.owner_id))
    assert db.get(User, first.player.owner_id).is_guest


def test_request_guest_marker_is_not_an_account_field(
    db: Session,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "PUBLIC_REGISTRATION_ENABLED", True)
    for route, headers in (("/users/", superuser_token_headers), ("/users/signup", {})):
        data = {
            "email": uuid4().hex + "@example.com",
            "password": "test-password",
            "is_guest": True,
        }
        created = client.post("/api/v1" + route, headers=headers, json=data)
        assert created.status_code == 200 and "is_guest" not in created.json()
        owner = crud.get_user_by_email(session=db, email=data["email"])
        assert owner.is_guest is False
        changed = client.patch(
            f"/api/v1/users/{owner.id}",
            headers=superuser_token_headers,
            json={"is_guest": True, "full_name": "Updated account"},
        )
        assert changed.status_code == 200 and "is_guest" not in changed.json()
        db.refresh(owner)
        assert not owner.is_guest


def test_account_context_is_stable_keyed_and_not_owner_uuid(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.game.guest_sessions import account_player

    account = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=uuid4().hex + "@example.com", password="test-password"
        ),
    )
    monkeypatch.setattr(settings, "SECRET_KEY", "test-context-key")
    player = account_player(account)
    expected = hmac.new(
        b"test-context-key",
        f"hdg:game-account-context:v1:{account.id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    assert player.owner_id == account.id and player.kind == "account"
    assert player.context_id == "a:" + expected
    assert str(account.id) not in player.context_id
    assert account_player(account) == player
    monkeypatch.setattr(settings, "SECRET_KEY", "another-test-key")
    assert account_player(account).context_id != player.context_id
    account.is_guest = True
    with pytest.raises(GameServiceError):
        account_player(account)


@pytest.mark.parametrize(
    "name", ["", "space name", "bad;cookie", "bad=cookie", "bad\nname", "café"]
)
def test_cookie_configuration_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(ValidationError):
        Settings(GAME_GUEST_COOKIE_NAME=name)


@pytest.mark.parametrize(
    "name",
    ["hdg_guest", "hdg_guest_verification", "hdg_guest_fixture", "hdg_guest_real"],
)
def test_cookie_configuration_accepts_isolated_names(name: str) -> None:
    assert Settings(GAME_GUEST_COOKIE_NAME=name).GAME_GUEST_COOKIE_NAME == name


def test_database_forbids_guest_admins_and_cascades_sessions(db: Session) -> None:
    from app.game.guest_models import GuestSession
    from app.game.guest_sessions import bootstrap_guest_session

    first = bootstrap_guest_session(db, None, NOW)
    db.commit()
    owner = db.get(User, first.player.owner_id)
    with pytest.raises(IntegrityError), db.begin_nested():
        owner.is_superuser = True
        db.add(owner)
        db.flush()
    db.refresh(owner)
    digest = hashlib.sha256(first.credential.encode()).hexdigest()
    db.delete(owner)
    db.commit()
    db.expire_all()
    assert db.get(GuestSession, digest) is None


@pytest.mark.parametrize("mutation", ["expiry", "digest", "owner", "public_id"])
def test_database_enforces_guest_session_constraints(
    db: Session, mutation: str
) -> None:
    from app.game.guest_models import GuestSession
    from app.game.guest_sessions import bootstrap_guest_session

    first = bootstrap_guest_session(db, None, NOW)
    second = bootstrap_guest_session(db, None, NOW)
    db.commit()
    stored = db.get(
        GuestSession, hashlib.sha256(second.credential.encode()).hexdigest()
    )
    original = db.get(
        GuestSession, hashlib.sha256(first.credential.encode()).hexdigest()
    )
    with pytest.raises(IntegrityError), db.begin_nested():
        if mutation == "expiry":
            stored.expires_at = stored.created_at
        elif mutation == "digest":
            stored.token_digest = "raw-credential"
        elif mutation == "owner":
            stored.owner_id = original.owner_id
        else:
            stored.public_id = original.public_id
        db.add(stored)
        db.flush()
    db.rollback()


def test_guest_owner_deletion_cascades_existing_game_progress(
    db: Session, tmp_path: Path
) -> None:
    from app.game.daily_service import start_daily
    from app.game.guest_models import GuestSession
    from app.game.guest_sessions import bootstrap_guest_session
    from app.game.models import DailyDefinition, GameOperation, GameRun
    from app.game.schemas import DailyStart
    from tests.api.routes.test_game_daily import release

    release(db, tmp_path / "fixture")
    guest = bootstrap_guest_session(db, None, NOW)
    db.commit()
    run = start_daily(
        db,
        guest.player.owner_id,
        DailyStart(protocol_version=2, operation_id=uuid4()),
        datetime(2400, 1, 1, tzinfo=UTC),
    )
    definition_id = db.get(GameRun, run.run_id).daily_definition_id
    operation_id = (
        db.exec(select(GameOperation).where(GameOperation.run_id == run.run_id))
        .one()
        .id
    )
    db.delete(db.get(User, guest.player.owner_id))
    db.commit()
    db.expire_all()
    assert db.get(GameRun, run.run_id) is None
    assert db.get(GameOperation, operation_id) is None
    assert (
        db.get(GuestSession, hashlib.sha256(guest.credential.encode()).hexdigest())
        is None
    )
    assert db.get(DailyDefinition, definition_id) is not None


def test_session_resolution_never_autoflushes_caller_work(db: Session) -> None:
    from app.game.guest_sessions import bootstrap_guest_session, resolve_guest_session

    guest = bootstrap_guest_session(db, None, NOW)
    db.commit()
    db.expunge_all()
    pending = User(email=uuid4().hex + "@example.com", hashed_password="unused")
    db.add(pending)

    def no_flush(_session: Session, _context: object, _instances: object) -> None:
        pytest.fail("read-only session inspection flushed caller work")

    event.listen(db, "before_flush", no_flush)
    try:
        assert resolve_guest_session(db, guest.credential, NOW) == guest.player
        assert pending in db.new
    finally:
        event.remove(db, "before_flush", no_flush)
        db.rollback()
