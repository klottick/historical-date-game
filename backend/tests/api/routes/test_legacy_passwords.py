from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.core.security import create_access_token, verify_password
from app.models import User
from tests.utils.legacy_password import (
    INVALID_PASSWORD_HASHES,
    LEGACY_BCRYPT_HASH,
    LEGACY_PASSWORD,
)
from tests.utils.utils import random_email


@pytest.fixture
def legacy_account(db: Session) -> Iterator[User]:
    user = User(email=random_email(), hashed_password=LEGACY_BCRYPT_HASH)
    db.add(user)
    db.commit()
    db.refresh(user)
    yield user
    db.rollback()
    db.delete(user)
    db.commit()


def persisted_hash(db: Session, user: User) -> str:
    # An independent session must see the committed value, not an ORM identity cache.
    with Session(db.get_bind()) as reader:
        stored_user = reader.get(User, user.id)
        assert stored_user is not None
        return stored_user.hashed_password


@pytest.mark.parametrize("is_superuser", [False, True])
def test_legacy_login_commits_argon2_and_preserves_authorization(
    client: TestClient, db: Session, legacy_account: User, is_superuser: bool
) -> None:
    legacy_account.is_superuser = is_superuser
    db.add(legacy_account)
    db.commit()
    response = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": legacy_account.email, "password": LEGACY_PASSWORD},
    )
    assert response.status_code == 200
    upgraded = persisted_hash(db, legacy_account)
    assert upgraded.startswith("$argon2id$")
    assert verify_password(LEGACY_PASSWORD, upgraded)
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    me = client.get(f"{settings.API_V1_STR}/users/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["id"] == str(legacy_account.id)
    assert me.json()["is_superuser"] is is_superuser
    # Ordinary users must not gain administrator authorization via migration.
    users = client.get(f"{settings.API_V1_STR}/users/", headers=headers)
    assert users.status_code == (200 if is_superuser else 403)
    again = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": legacy_account.email, "password": LEGACY_PASSWORD},
    )
    assert again.status_code == 200
    assert persisted_hash(db, legacy_account) == upgraded


def test_legacy_crud_authentication_commits_upgrade(
    db: Session, legacy_account: User
) -> None:
    assert (
        crud.authenticate(
            session=db, email=legacy_account.email, password=LEGACY_PASSWORD
        )
        is legacy_account
    )
    upgraded = persisted_hash(db, legacy_account)
    assert upgraded.startswith("$argon2id$")
    assert verify_password(LEGACY_PASSWORD, upgraded)


@pytest.mark.parametrize("stored_hash", [LEGACY_BCRYPT_HASH, *INVALID_PASSWORD_HASHES])
def test_bad_password_or_stored_hash_does_not_change_database(
    client: TestClient, db: Session, legacy_account: User, stored_hash: str
) -> None:
    legacy_account.hashed_password = stored_hash
    db.add(legacy_account)
    db.commit()
    response = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": legacy_account.email, "password": "incorrect-password"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Incorrect email or password"
    assert persisted_hash(db, legacy_account) == stored_hash


@pytest.mark.parametrize(
    ("is_guest", "is_active", "detail"),
    [(True, True, "Incorrect email or password"), (False, False, "Inactive user")],
)
def test_legacy_guest_and_inactive_accounts_stay_locked_out(
    client: TestClient,
    db: Session,
    legacy_account: User,
    is_guest: bool,
    is_active: bool,
    detail: str,
) -> None:
    legacy_account.is_guest = is_guest
    legacy_account.is_active = is_active
    db.add(legacy_account)
    db.commit()
    response = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": legacy_account.email, "password": LEGACY_PASSWORD},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == detail
    assert persisted_hash(db, legacy_account) == LEGACY_BCRYPT_HASH


def test_legacy_current_password_change_commits_new_argon2(
    client: TestClient, db: Session, legacy_account: User
) -> None:
    # Issue a token without password login, which would already migrate this fixture.
    token = create_access_token(legacy_account.id, timedelta(minutes=5))
    response = client.patch(
        f"{settings.API_V1_STR}/users/me/password",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": LEGACY_PASSWORD,
            "new_password": "synthetic-new-password",
        },
    )
    assert response.status_code == 200
    upgraded = persisted_hash(db, legacy_account)
    assert upgraded.startswith("$argon2id$")
    assert verify_password("synthetic-new-password", upgraded)
    assert not verify_password(LEGACY_PASSWORD, upgraded)


@pytest.mark.parametrize("stored_hash", [LEGACY_BCRYPT_HASH, *INVALID_PASSWORD_HASHES])
def test_rejected_current_password_change_keeps_database_hash(
    client: TestClient, db: Session, legacy_account: User, stored_hash: str
) -> None:
    legacy_account.hashed_password = stored_hash
    db.add(legacy_account)
    db.commit()
    token = create_access_token(legacy_account.id, timedelta(minutes=5))
    response = client.patch(
        f"{settings.API_V1_STR}/users/me/password",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "incorrect-password",
            "new_password": "synthetic-new-password",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Incorrect password"
    assert persisted_hash(db, legacy_account) == stored_hash


@pytest.mark.parametrize(
    ("is_guest", "is_active", "status_code"),
    [(True, True, 403), (False, False, 400)],
)
def test_guest_and_inactive_current_password_changes_are_forbidden(
    client: TestClient,
    db: Session,
    legacy_account: User,
    is_guest: bool,
    is_active: bool,
    status_code: int,
) -> None:
    legacy_account.is_guest = is_guest
    legacy_account.is_active = is_active
    db.add(legacy_account)
    db.commit()
    token = create_access_token(legacy_account.id, timedelta(minutes=5))
    response = client.patch(
        f"{settings.API_V1_STR}/users/me/password",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": LEGACY_PASSWORD,
            "new_password": "synthetic-new-password",
        },
    )
    assert response.status_code == status_code
    assert persisted_hash(db, legacy_account) == LEGACY_BCRYPT_HASH


def test_same_legacy_current_password_leaves_database_hash_unchanged(
    client: TestClient, db: Session, legacy_account: User
) -> None:
    token = create_access_token(legacy_account.id, timedelta(minutes=5))
    response = client.patch(
        f"{settings.API_V1_STR}/users/me/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": LEGACY_PASSWORD, "new_password": LEGACY_PASSWORD},
    )
    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "New password cannot be the same as the current one"
    )
    assert persisted_hash(db, legacy_account) == LEGACY_BCRYPT_HASH
