import os
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
from tests.browser.ci_backend import require_ci_target
from tests.browser.guest_test_environment import (
    _maintenance_connection,
    require_owned_guest_database,
)
from tests.db_guard import require_test_database
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers


def _require_backend_verification_target() -> None:
    """Refuse browser/migration or wrong-profile targets even when exactly owned."""
    require_test_database(settings.POSTGRES_DB)
    require_ci_target(
        {
            "HDG_VERIFICATION_PROFILE": os.environ.get("HDG_VERIFICATION_PROFILE", ""),
            "POSTGRES_DB": settings.POSTGRES_DB,
            "POSTGRES_SERVER": settings.POSTGRES_SERVER,
            "POSTGRES_PORT": str(settings.POSTGRES_PORT),
            "ENVIRONMENT": settings.ENVIRONMENT,
        }
    )


@pytest.fixture(scope="session", autouse=True)
def _verification_database_safety() -> None:
    """Check exact target and consumers before the suite opens connection pools."""
    _require_backend_verification_target()
    require_owned_guest_database()
    with _maintenance_connection() as connection:
        assert connection.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = %s",
            (settings.POSTGRES_DB,),
        ).fetchone() == (0,), "Refusing test setup while target has consumers"


@pytest.fixture(scope="session", autouse=True)
def db(_verification_database_safety: None) -> Generator[Session]:
    # Preserve the direct-call boundary as well as pytest's session preflight.
    _require_backend_verification_target()
    require_owned_guest_database()
    with Session(engine) as session:
        init_db(session)
        yield session
        # A failed integrity test must not prevent dependency-ordered cleanup.
        session.rollback()
        _require_backend_verification_target()
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
