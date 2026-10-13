from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.config import settings
from app.core.db import engine, init_db
from app.game.models import (
    CatalogCategory,
    CatalogRelease,
    CatalogSelection,
    DailyDefinition,
    EventRevision,
    GameOperation,
    GameRun,
    MediaAsset,
)
from app.main import app
from app.models import Item, User
from tests.browser.guest_test_environment import require_owned_guest_database
from tests.db_guard import require_test_database
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session]:
    require_test_database(settings.POSTGRES_DB)
    require_owned_guest_database()
    with Session(engine) as session:
        init_db(session)
        yield session
        # A failed integrity test must not prevent dependency-ordered cleanup.
        session.rollback()
        require_owned_guest_database()
        for model in (
            GameOperation,
            GameRun,
            DailyDefinition,
            CatalogSelection,
            MediaAsset,
            EventRevision,
            CatalogCategory,
            CatalogRelease,
        ):
            session.execute(delete(model))
        statement = delete(Item)
        session.execute(statement)
        statement = delete(User)
        session.execute(statement)
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
