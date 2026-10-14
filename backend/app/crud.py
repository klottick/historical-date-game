import uuid
from typing import Any

from sqlalchemy import update
from sqlmodel import Session, col, select

from app.core.security import get_password_hash, verify_password_and_update
from app.models import Item, ItemCreate, User, UserCreate, UserUpdate


def create_user(*, session: Session, user_create: UserCreate) -> User:
    db_obj = User.model_validate(
        user_create, update={"hashed_password": get_password_hash(user_create.password)}
    )
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def update_user(*, session: Session, db_user: User, user_in: UserUpdate) -> Any:
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data = {}
    if "password" in user_data:
        password = user_data["password"]
        hashed_password = get_password_hash(password)
        extra_data["hashed_password"] = hashed_password
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def get_user_by_email(*, session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    session_user = session.exec(statement).first()
    return session_user


def authenticate(*, session: Session, email: str, password: str) -> User | None:
    db_user = get_user_by_email(session=session, email=email)
    if not db_user or db_user.is_guest:
        return None
    original_hash = db_user.hashed_password
    verified, updated_hash = verify_password_and_update(password, original_hash)
    if not verified:
        return None
    # Keep inactive-account rejection in the login route, without changing its hash.
    if updated_hash is not None and db_user.is_active:
        # A reset or eligibility change committed during verification must win.
        statement = (
            update(User)
            .where(
                col(User.id) == db_user.id,
                col(User.hashed_password) == original_hash,
                col(User.is_active).is_(True),
                col(User.is_guest).is_(False),
            )
            .values(hashed_password=updated_hash)
            .returning(col(User.id))
            .execution_options(synchronize_session=False)
        )
        if session.exec(statement).scalar_one_or_none() is None:
            # Rollback expires the stale snapshot. Fail closed, without retrying
            # authentication or an unconditional write using the old password.
            session.rollback()
            return None
        session.commit()
        session.refresh(db_user)
    return db_user


def create_item(*, session: Session, item_in: ItemCreate, owner_id: uuid.UUID) -> Item:
    db_item = Item.model_validate(item_in, update={"owner_id": owner_id})
    session.add(db_item)
    session.commit()
    session.refresh(db_item)
    return db_item
