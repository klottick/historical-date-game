from datetime import timedelta
from typing import cast

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.sql import Select
from sqlmodel import Session

from app import crud
from app.api.deps import get_current_user
from app.api.routes.login import login_access_token
from app.api.routes.users import update_password_me
from app.core import security
from app.core.config import settings
from app.models import UpdatePassword, User
from tests.utils.legacy_password import (
    INVALID_PASSWORD_HASHES,
    LEGACY_BCRYPT_HASH,
    LEGACY_PASSWORD,
)


class UserResult:
    def __init__(self, user: User | None) -> None:
        self.user = user

    def first(self) -> User | None:
        return self.user


class FakeSession:
    """Persist snapshots rather than references, so a missing commit is observable."""

    def __init__(self, user: User) -> None:
        self.user = user
        self.persisted_hash = user.hashed_password
        self.pending: User | None = None
        self.commits = 0

    def exec(self, statement: Select[tuple[User]]) -> UserResult:
        email = statement.compile().params["email_1"]
        return UserResult(self.user if email == self.user.email else None)

    def get(self, model: type[User], key: object) -> User | None:
        assert model is User
        return self.user if str(key) == str(self.user.id) else None

    def add(self, user: User) -> None:
        assert user is self.user
        self.pending = user

    def commit(self) -> None:
        assert self.pending is self.user
        self.persisted_hash = self.pending.hashed_password
        self.pending = None
        self.commits += 1

    def refresh(self, user: User) -> None:
        assert user is self.user
        user.hashed_password = self.persisted_hash

    @property
    def session(self) -> Session:
        return cast(Session, self)


def legacy_user(
    *, is_superuser: bool = False, is_guest: bool = False, is_active: bool = True
) -> User:
    return User(
        email="synthetic-legacy@example.com",
        hashed_password=LEGACY_BCRYPT_HASH,
        is_superuser=is_superuser,
        is_guest=is_guest,
        is_active=is_active,
    )


@pytest.mark.parametrize("prefix", ["2a", "2b", "2y"])
def test_known_legacy_hash_accepts_only_correct_password(prefix: str) -> None:
    hashed_password = LEGACY_BCRYPT_HASH.replace("$2b$", f"${prefix}$")
    assert security.verify_password(LEGACY_PASSWORD, hashed_password)
    assert not security.verify_password("incorrect-password", hashed_password)


@pytest.mark.parametrize(
    ("password", "stored_hash"),
    [
        (
            "a" * 127 + "1",
            "$2b$04$abcdefghijklmnopqrstuuBzzIgyKkz7xMWYSzkIjUSnxEQFQ0WNe",
        ),
        (
            "é" * 63 + "1",
            "$2b$04$abcdefghijklmnopqrstuuKiIlCeXB6chNXkLyAo8C7XcLPzh6zUe",
        ),
    ],
)
def test_long_legacy_password_upgrades_without_truncating_argon2(
    password: str, stored_hash: str
) -> None:
    # Passlib bcrypt accepted these inputs using the first 72 UTF-8 bytes.
    assert security.verify_password(password, stored_hash)
    assert not security.verify_password("incorrect-password", stored_hash)
    valid, upgraded = security.verify_password_and_update(password, stored_hash)
    assert valid
    assert upgraded is not None and upgraded.startswith("$argon2id$")
    assert security.verify_password(password, upgraded)
    assert not security.verify_password(password[:-1] + "2", upgraded)


@pytest.mark.parametrize("hashed_password", INVALID_PASSWORD_HASHES)
def test_invalid_stored_hash_fails_safely(hashed_password: str) -> None:
    assert not security.verify_password(LEGACY_PASSWORD, hashed_password)
    assert security.verify_password_and_update(LEGACY_PASSWORD, hashed_password) == (
        False,
        None,
    )


def test_verified_legacy_hash_gets_argon2_upgrade() -> None:
    valid, upgraded = security.verify_password_and_update(
        LEGACY_PASSWORD, LEGACY_BCRYPT_HASH
    )
    assert valid
    assert upgraded is not None and upgraded.startswith("$argon2id$")
    assert security.verify_password(LEGACY_PASSWORD, upgraded)
    assert not security.verify_password("incorrect-password", upgraded)


def test_wrong_password_never_gets_an_upgrade() -> None:
    assert security.verify_password_and_update(
        "incorrect-password", LEGACY_BCRYPT_HASH
    ) == (False, None)


def test_current_argon2_hash_needs_no_upgrade() -> None:
    hashed_password = security.get_password_hash(LEGACY_PASSWORD)
    assert hashed_password.startswith("$argon2id$")
    assert security.verify_password_and_update(LEGACY_PASSWORD, hashed_password) == (
        True,
        None,
    )


@pytest.mark.parametrize("is_superuser", [False, True])
def test_crud_authentication_persists_legacy_upgrade(is_superuser: bool) -> None:
    user = legacy_user(is_superuser=is_superuser)
    fake = FakeSession(user)
    authenticated = crud.authenticate(
        session=fake.session, email=user.email, password=LEGACY_PASSWORD
    )
    assert authenticated is user
    assert fake.persisted_hash.startswith("$argon2id$")
    assert security.verify_password(LEGACY_PASSWORD, fake.persisted_hash)
    assert user.is_superuser is is_superuser
    assert fake.commits == 1
    # A second successful authentication must not keep rewriting a current hash.
    assert (
        crud.authenticate(
            session=fake.session, email=user.email, password=LEGACY_PASSWORD
        )
        is user
    )
    assert fake.commits == 1


@pytest.mark.parametrize("stored_hash", [LEGACY_BCRYPT_HASH, *INVALID_PASSWORD_HASHES])
def test_rejected_login_does_not_mutate_or_persist(stored_hash: str) -> None:
    user = legacy_user()
    user.hashed_password = stored_hash
    fake = FakeSession(user)
    with pytest.raises(HTTPException) as exc:
        login_access_token(
            fake.session,
            OAuth2PasswordRequestForm(
                username=user.email, password="incorrect-password"
            ),
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == "Incorrect email or password"
    assert user.hashed_password == fake.persisted_hash == stored_hash
    assert fake.commits == 0


def test_missing_email_does_not_mutate_legacy_user() -> None:
    fake = FakeSession(legacy_user())
    assert (
        crud.authenticate(
            session=fake.session, email="missing@example.com", password=LEGACY_PASSWORD
        )
        is None
    )
    assert fake.persisted_hash == LEGACY_BCRYPT_HASH
    assert fake.commits == 0


def test_login_route_issues_authorized_token_and_persists_upgrade() -> None:
    user = legacy_user(is_superuser=True)
    fake = FakeSession(user)
    token = login_access_token(
        fake.session,
        OAuth2PasswordRequestForm(username=user.email, password=LEGACY_PASSWORD),
    )
    payload = jwt.decode(
        token.access_token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
    )
    assert payload["sub"] == str(user.id)
    assert get_current_user(fake.session, token.access_token) is user
    assert user.is_superuser
    assert fake.persisted_hash.startswith("$argon2id$")
    assert fake.commits == 1


@pytest.mark.parametrize(
    ("flags", "detail"),
    [
        ({"is_guest": True}, "Incorrect email or password"),
        ({"is_active": False}, "Inactive user"),
    ],
)
def test_guest_and_inactive_login_policy_preserved(
    flags: dict[str, bool], detail: str
) -> None:
    user = legacy_user(**flags)
    fake = FakeSession(user)
    with pytest.raises(HTTPException) as exc:
        login_access_token(
            fake.session,
            OAuth2PasswordRequestForm(username=user.email, password=LEGACY_PASSWORD),
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == detail
    assert user.hashed_password == fake.persisted_hash == LEGACY_BCRYPT_HASH
    assert fake.commits == 0


@pytest.mark.parametrize(
    ("flags", "status_code", "detail"),
    [
        ({"is_guest": True}, 403, "Could not validate credentials"),
        ({"is_active": False}, 400, "Inactive user"),
    ],
)
def test_guest_and_inactive_tokens_remain_unauthorized(
    flags: dict[str, bool], status_code: int, detail: str
) -> None:
    user = legacy_user(**flags)
    fake = FakeSession(user)
    token = security.create_access_token(user.id, timedelta(minutes=5))
    with pytest.raises(HTTPException) as exc:
        get_current_user(fake.session, token)
    assert exc.value.status_code == status_code
    assert exc.value.detail == detail
    assert fake.persisted_hash == LEGACY_BCRYPT_HASH
    assert fake.commits == 0


def test_current_password_route_accepts_legacy_and_persists_new_argon2() -> None:
    user = legacy_user()
    fake = FakeSession(user)
    response = update_password_me(
        session=fake.session,
        current_user=user,
        body=UpdatePassword(
            current_password=LEGACY_PASSWORD, new_password="synthetic-new-password"
        ),
    )
    assert response.message == "Password updated successfully"
    assert fake.persisted_hash.startswith("$argon2id$")
    assert security.verify_password("synthetic-new-password", fake.persisted_hash)
    assert not security.verify_password(LEGACY_PASSWORD, fake.persisted_hash)
    assert fake.commits == 1


@pytest.mark.parametrize("stored_hash", [LEGACY_BCRYPT_HASH, *INVALID_PASSWORD_HASHES])
def test_current_password_rejection_leaves_hash_unchanged(stored_hash: str) -> None:
    user = legacy_user()
    user.hashed_password = stored_hash
    fake = FakeSession(user)
    with pytest.raises(HTTPException) as exc:
        update_password_me(
            session=fake.session,
            current_user=user,
            body=UpdatePassword(
                current_password="incorrect-password",
                new_password="synthetic-new-password",
            ),
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == "Incorrect password"
    assert user.hashed_password == fake.persisted_hash == stored_hash
    assert fake.commits == 0


def test_same_current_password_does_not_convert_legacy_hash() -> None:
    user = legacy_user()
    fake = FakeSession(user)
    with pytest.raises(HTTPException) as exc:
        update_password_me(
            session=fake.session,
            current_user=user,
            body=UpdatePassword(
                current_password=LEGACY_PASSWORD, new_password=LEGACY_PASSWORD
            ),
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == "New password cannot be the same as the current one"
    assert user.hashed_password == fake.persisted_hash == LEGACY_BCRYPT_HASH
    assert fake.commits == 0
