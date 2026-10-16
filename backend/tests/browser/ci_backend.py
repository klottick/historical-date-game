"""Prepare only the exact owned, idle lives-profile backend CI databases.

No application startup, real catalogue acquisition, or gameplay reset is invoked.
Imports stay stdlib-only until the explicit environment guard has succeeded.
"""

import argparse
import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

DATABASE = "historical_date_game_lives_backend_test"
MIGRATION_DATABASE = "historical_date_game_lives_migration_test"
DATABASES = (DATABASE, MIGRATION_DATABASE)


def require_ci_target(environment: Mapping[str, str]) -> None:
    required = {
        "HDG_VERIFICATION_PROFILE": "lives",
        "POSTGRES_DB": DATABASE,
        "POSTGRES_SERVER": "127.0.0.1",
        "POSTGRES_PORT": "5433",
        "ENVIRONMENT": "local",
    }
    if any(environment.get(key) != value for key, value in required.items()):
        raise RuntimeError(
            "CI preparation requires the exact lives backend disposable endpoint"
        )


def require_idle_owned(database: str, *, allow_absent: bool = False) -> None:
    from app.core.config import settings
    from tests.browser import guest_test_environment as environment

    if database not in DATABASES:
        raise RuntimeError("Unexpected backend CI database")
    environment.require_guest_test_target(
        database, settings.POSTGRES_SERVER, settings.ENVIRONMENT
    )
    with environment._maintenance_connection() as connection:
        identity = environment._database_identity(connection, database)
        if identity is None:
            if allow_absent:
                return
            raise RuntimeError("Backend CI database is absent")
        environment.require_ownership(database, *identity)
        active = connection.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname=%s", (database,)
        ).fetchone()
        if active is None or active[0] != 0:
            raise RuntimeError(
                "Backend CI database has active consumers (including idle pools)"
            )


def _seed_migration_catalogue() -> None:
    from sqlalchemy import create_engine, text
    from sqlmodel import Session

    from app.core.config import settings
    from tests.api.routes.test_game_daily import release

    require_idle_owned(MIGRATION_DATABASE)
    engine = create_engine(
        str(settings.SQLALCHEMY_DATABASE_URI).rsplit("/", 1)[0]
        + "/"
        + MIGRATION_DATABASE
    )
    try:
        with Session(engine) as session:
            selected = session.execute(
                text(
                    "SELECT r.fixture,r.event_count,(SELECT count(*) FROM eventrevision e "
                    "WHERE e.release_id=r.id) FROM catalogselection s "
                    "JOIN catalogrelease r ON r.id=s.release_id WHERE s.id=1"
                )
            ).one_or_none()
            if selected is not None:
                if tuple(selected) != (True, 8, 8):
                    raise RuntimeError(
                        "Refusing to replace a non-synthetic selected migration catalogue"
                    )
                return
            # TemporaryDirectory creates its own private scratch on empty runners.
            with tempfile.TemporaryDirectory(prefix="hdg-ci-migration-") as temporary:
                release(session, Path(temporary) / "synthetic")
    finally:
        engine.dispose()


def prepare() -> None:
    require_ci_target(os.environ)
    from app.core.config import settings
    from tests.browser import guest_test_environment as environment

    if (
        settings.POSTGRES_DB,
        settings.POSTGRES_SERVER,
        settings.POSTGRES_PORT,
        settings.ENVIRONMENT,
    ) != (DATABASE, "127.0.0.1", 5433, "local"):
        raise RuntimeError(
            "Loaded settings differ from the exact lives backend disposable endpoint"
        )
    # Preflight BOTH targets before the first creation/migration. Never relabel or
    # terminate connections, and do not partially prepare an unsafe second target.
    for database in DATABASES:
        require_idle_owned(database, allow_absent=True)
    for database in DATABASES:
        environment.prepare_database(database)
        require_idle_owned(database)
    environment.run_migration(MIGRATION_DATABASE, "upgrade", "head")
    _seed_migration_catalogue()
    for database in DATABASES:
        require_idle_owned(database)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare"])
    parser.parse_args()
    prepare()
    sys.stdout.write(
        "Owned idle backend databases prepared; synthetic eight-event migration catalogue selected\n"
    )


if __name__ == "__main__":
    main()
