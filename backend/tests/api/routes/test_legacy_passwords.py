from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.api.routes.login import login_access_token, reset_password
from app.api.routes.users import update_password_me
from app.core.config import settings
from app.core.security import (
    create_access_token,
    verify_password,
    verify_password_and_update,
)
from app.models import NewPassword, UpdatePassword, User, UserUpdate
from app.utils import generate_password_reset_token
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


@pytest.mark.parametrize("entrypoint", ["crud", "route"])
@pytest.mark.parametrize(
    "event", ["reset", "change", "admin-password", "deactivate", "guest"]
)
def test_two_sessions_preserve_competing_password_or_policy_commit(
    db: Session,
    legacy_account: User,
    monkeypatch: pytest.MonkeyPatch,
    entrypoint: str,
    event: str,
) -> None:
    account_id = legacy_account.id
    email = legacy_account.email
    new_password = "synthetic-competing-password"
    reset_token = generate_password_reset_token(email=email)
    original_verify = verify_password_and_update
    competing_hash = LEGACY_BCRYPT_HASH
    calls = 0

    def verify_then_writer_commit(
        password: str, stored_hash: str
    ) -> tuple[bool, str | None]:
        nonlocal competing_hash, calls
        calls += 1
        assert stored_hash == LEGACY_BCRYPT_HASH
        result = original_verify(password, stored_hash)
        assert result[0] and result[1] is not None
        # B commits through unchanged writers while A still holds its loaded H0.
        with Session(db.get_bind()) as writer:
            competing_user = writer.get(User, account_id)
            assert competing_user is not None
            if event == "reset":
                reset_password(
                    session=writer,
                    body=NewPassword(token=reset_token, new_password=new_password),
                )
            elif event == "change":
                update_password_me(
                    session=writer,
                    current_user=competing_user,
                    body=UpdatePassword(
                        current_password=LEGACY_PASSWORD, new_password=new_password
                    ),
                )
            elif event in ("admin-password", "deactivate"):
                update = (
                    UserUpdate(password=new_password)
                    if event == "admin-password"
                    else UserUpdate(is_active=False)
                )
                crud.update_user(session=writer, db_user=competing_user, user_in=update)
            else:
                competing_user.is_guest = True
                writer.add(competing_user)
                writer.commit()
            writer.refresh(competing_user)
            competing_hash = competing_user.hashed_password
        return result

    with monkeypatch.context() as patch:
        patch.setattr(crud, "verify_password_and_update", verify_then_writer_commit)
        with Session(db.get_bind()) as login_session:
            if entrypoint == "crud":
                assert (
                    crud.authenticate(
                        session=login_session, email=email, password=LEGACY_PASSWORD
                    )
                    is None
                )
            else:
                with pytest.raises(HTTPException) as exc:
                    login_access_token(
                        login_session,
                        OAuth2PasswordRequestForm(
                            username=email, password=LEGACY_PASSWORD
                        ),
                    )
                assert exc.value.status_code == 400

            # A's identity map must not keep serving its pre-reset/policy snapshot.
            reloaded = login_session.get(User, account_id)
            assert reloaded is not None
            assert reloaded.hashed_password == competing_hash
            assert reloaded.is_active is (event != "deactivate")
            assert reloaded.is_guest is (event == "guest")

    assert calls == 1  # The loser fails closed, with no unconditional retry.
    assert persisted_hash(db, legacy_account) == competing_hash
    with Session(db.get_bind()) as reader:
        current_user = reader.get(User, account_id)
        assert current_user is not None
        assert current_user.is_active is (event != "deactivate")
        assert current_user.is_guest is (event == "guest")
        if event in ("reset", "change", "admin-password"):
            assert verify_password(new_password, current_user.hashed_password)
            assert not verify_password(LEGACY_PASSWORD, current_user.hashed_password)
            assert (
                crud.authenticate(session=reader, email=email, password=LEGACY_PASSWORD)
                is None
            )
            assert (
                crud.authenticate(session=reader, email=email, password=new_password)
                is current_user
            )
        else:
            assert current_user.hashed_password == LEGACY_BCRYPT_HASH
