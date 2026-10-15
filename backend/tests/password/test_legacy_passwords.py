from datetime import timedelta
from typing import cast
from uuid import UUID

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.sql import Select, operators
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.elements import (
    BinaryExpression,
    BindParameter,
    BooleanClauseList,
    ClauseElement,
    ColumnClause,
    False_,
    True_,
)
from sqlalchemy.sql.selectable import TableClause
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


class UpdateResult:
    def __init__(self, user_id: UUID | None) -> None:
        self.user_id = user_id

    def scalar_one_or_none(self) -> UUID | None:
        return self.user_id


class FakeSession:
    """Persist snapshots rather than references, so a missing commit is observable."""

    def __init__(self, user: User) -> None:
        self.user = user
        self.loaded_hash = user.hashed_password
        self.persisted = user.model_dump()
        self.pending: User | None = None
        self.pending_hash: str | None = None
        self.commits = 0
        self.rollbacks = 0
        self.updates = 0
        self.last_update: Update | None = None

    @property
    def persisted_hash(self) -> str:
        return cast(str, self.persisted["hashed_password"])

    def sql_value(self, expression: ClauseElement) -> object:
        if isinstance(expression, ColumnClause):
            return self.persisted[expression.name]
        if isinstance(expression, BindParameter):
            return expression.value
        if isinstance(expression, True_):
            return True
        if isinstance(expression, False_):
            return False
        raise AssertionError(f"Unsupported SQL value: {expression}")

    def matches(self, expression: ClauseElement | None) -> bool:
        if expression is None:
            return True
        if isinstance(expression, BooleanClauseList):
            assert expression.operator is operators.and_
            return all(self.matches(clause) for clause in expression.clauses)
        assert isinstance(expression, BinaryExpression)
        assert expression.operator in (operators.eq, operators.is_)
        left = self.sql_value(expression.left)
        right = self.sql_value(expression.right)
        if expression.operator is operators.is_:
            return left is right
        return left == right

    def execute(self, statement: Update) -> UpdateResult:
        # Evaluate the actual SQL predicate against the committed row. This is not
        # a preconfigured CAS result, and removing a guard changes its behavior.
        assert isinstance(statement.table, TableClause)
        assert statement.table.name == "user"
        assert [column.name for column in statement.exported_columns] == ["id"]
        assert self.user.hashed_password == self.loaded_hash
        self.updates += 1
        self.last_update = statement
        if not self.matches(statement.whereclause):
            return UpdateResult(None)
        self.pending_hash = statement.compile().params["hashed_password"]
        assert isinstance(self.pending_hash, str)
        return UpdateResult(self.user.id)

    def exec(
        self, statement: Select[tuple[User]] | Update
    ) -> UserResult | UpdateResult:
        if isinstance(statement, Update):
            return self.execute(statement)
        email = statement.compile().params["email_1"]
        return UserResult(self.user if email == self.user.email else None)

    def get(self, model: type[User], key: object) -> User | None:
        assert model is User
        return self.user if str(key) == str(self.user.id) else None

    def add(self, user: User) -> None:
        assert user is self.user
        self.pending = user

    def commit(self) -> None:
        assert self.pending is self.user or self.pending_hash is not None
        if self.pending is not None:
            self.persisted["hashed_password"] = self.pending.hashed_password
        else:
            self.persisted["hashed_password"] = self.pending_hash
        self.pending = None
        self.pending_hash = None
        self.commits += 1

    def rollback(self) -> None:
        self.pending = None
        self.pending_hash = None
        self.rollbacks += 1

    def refresh(self, user: User) -> None:
        assert user is self.user
        user.sqlmodel_update(self.persisted)

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


@pytest.mark.parametrize("entrypoint", ["crud", "login"])
@pytest.mark.parametrize("event", ["reset", "deactivate", "guest", "other-rehash"])
def test_concurrent_credential_or_policy_change_wins_over_legacy_login(
    monkeypatch: pytest.MonkeyPatch, entrypoint: str, event: str
) -> None:
    user = legacy_user()
    fake = FakeSession(user)
    original_verify = security.verify_password_and_update
    calls = 0
    competing_hash = security.get_password_hash(
        LEGACY_PASSWORD if event == "other-rehash" else "synthetic-reset-password"
    )

    def verify_then_competing_commit(
        password: str, stored_hash: str
    ) -> tuple[bool, str | None]:
        nonlocal calls
        calls += 1
        assert stored_hash == LEGACY_BCRYPT_HASH
        result = original_verify(password, stored_hash)
        assert result[0] and result[1] is not None
        # An independent writer commits, without updating A's loaded user snapshot.
        if event in ("reset", "other-rehash"):
            fake.persisted["hashed_password"] = competing_hash
        elif event == "deactivate":
            fake.persisted["is_active"] = False
        else:
            fake.persisted["is_guest"] = True
        assert user.hashed_password == LEGACY_BCRYPT_HASH
        assert user.is_active and not user.is_guest
        return result

    monkeypatch.setattr(
        crud, "verify_password_and_update", verify_then_competing_commit
    )
    if entrypoint == "crud":
        assert (
            crud.authenticate(
                session=fake.session, email=user.email, password=LEGACY_PASSWORD
            )
            is None
        )
    else:
        with pytest.raises(HTTPException) as exc:
            login_access_token(
                fake.session,
                OAuth2PasswordRequestForm(
                    username=user.email, password=LEGACY_PASSWORD
                ),
            )
        assert exc.value.status_code == 400
    expected_hash = (
        competing_hash if event in ("reset", "other-rehash") else LEGACY_BCRYPT_HASH
    )
    assert fake.persisted_hash == expected_hash
    assert fake.persisted["is_active"] is (event != "deactivate")
    assert fake.persisted["is_guest"] is (event == "guest")
    assert fake.commits == 0
    assert fake.rollbacks == 1
    assert fake.updates == 1
    assert calls == 1  # Fail closed: never retry a migration using a stale password.


def test_rehash_query_excludes_another_account_with_the_same_legacy_hash() -> None:
    user = legacy_user()
    fake = FakeSession(user)
    assert (
        crud.authenticate(
            session=fake.session, email=user.email, password=LEGACY_PASSWORD
        )
        is user
    )
    assert fake.last_update is not None
    another_account = FakeSession(legacy_user())
    assert another_account.user.id != user.id
    assert not another_account.matches(fake.last_update.whereclause)
    assert another_account.persisted_hash == LEGACY_BCRYPT_HASH
