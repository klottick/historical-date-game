"""Owned, disposable guest-play verification databases; never live targets.

Run from this worktree's backend directory. Credentials stay in the private .env.
"""

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from sqlmodel import Session, create_engine, text

from app.core.config import settings

WORKTREE = Path(__file__).resolve().parents[3]
GUEST_DATABASES = frozenset(
    {
        "historical_date_game_guest_test",
        "historical_date_game_guest_migration_test",
        "historical_date_game_guest_fixture_test",
    }
)
MIGRATION_DATABASE = "historical_date_game_guest_migration_test"


def require_guest_test_target(database: str, host: str, environment: str) -> None:
    if (
        database not in GUEST_DATABASES
        or host not in {"127.0.0.1", "localhost", "::1"}
        or environment != "local"
    ):
        raise RuntimeError(
            "Guest verification requires a named local disposable database"
        )


def ownership_comment(database: str) -> str:
    return f"historical-date-game guest-play verification; worktree={WORKTREE}; database={database}"


def require_ownership(database: str, comment: str | None, owner: str) -> None:
    if comment != ownership_comment(database) or owner != settings.POSTGRES_USER:
        raise RuntimeError("Guest verification database ownership is not proven")


def _maintenance_connection() -> psycopg.Connection[Any]:
    return psycopg.connect(
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        dbname="postgres",
        autocommit=True,
        connect_timeout=5,
    )


def _database_identity(
    connection: psycopg.Connection[Any], database: str
) -> tuple[str | None, str] | None:
    return connection.execute(
        "SELECT shobj_description(oid, 'pg_database'), pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s",
        (database,),
    ).fetchone()


def require_owned_guest_database(database: str | None = None) -> None:
    database = database if database is not None else settings.POSTGRES_DB
    require_guest_test_target(database, settings.POSTGRES_SERVER, settings.ENVIRONMENT)
    with _maintenance_connection() as connection:
        identity = _database_identity(connection, database)
        if identity is None:
            raise RuntimeError("Guest verification database is absent")
        require_ownership(database, *identity)


def prepare_database(database: str) -> bool:
    """Create only absent targets. Never relabel an existing unowned database."""
    require_guest_test_target(database, settings.POSTGRES_SERVER, settings.ENVIRONMENT)
    with _maintenance_connection() as connection:
        identity = _database_identity(connection, database)
        if identity is not None:
            require_ownership(database, *identity)
            return False
        connection.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(database), sql.Identifier(settings.POSTGRES_USER)
            )
        )
        connection.execute(
            sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                sql.Identifier(database), sql.Literal(ownership_comment(database))
            )
        )
        identity = _database_identity(connection, database)
        if identity is None:
            raise RuntimeError("Guest database creation was not verified")
        require_ownership(database, *identity)
    return True


def run_migration(database: str, direction: str, revision: str) -> None:
    require_owned_guest_database(database)
    environment = dict(
        os.environ,
        POSTGRES_DB=database,
        POSTGRES_SERVER=settings.POSTGRES_SERVER,
        POSTGRES_PORT=str(settings.POSTGRES_PORT),
        ENVIRONMENT="local",
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", direction, revision],
        cwd=WORKTREE / "backend",
        env=environment,
        check=True,
    )


def _private_row_digests(session: Session) -> dict[str, dict[str, str | int]]:
    """Compare complete old rows, omitting only the newly added account marker."""
    result: dict[str, dict[str, str | int]] = {}
    for table in (
        "user",
        "item",
        "catalogrelease",
        "catalogselection",
        "catalogcategory",
        "eventrevision",
        "mediaasset",
        "dailydefinition",
        "gamerun",
        "gameoperation",
    ):
        projection = "to_jsonb(t) - 'is_guest'" if table == "user" else "to_jsonb(t)"
        rows = (
            session.execute(
                text(
                    f'SELECT ({projection})::text FROM "{table}" t ORDER BY ({projection})::text'
                )
            )
            .scalars()
            .all()
        )
        result[table] = {
            "count": len(rows),
            "sha256": hashlib.sha256(json.dumps(rows).encode()).hexdigest(),
        }
    return result


def _seed_legacy_progress(session: Session, root: Path) -> None:
    """Use the verified synthetic catalog and frozen v1 service projections."""
    from app.core.security import get_password_hash
    from app.game.daily_service import _definition
    from app.game.models import GameRun
    from app.game.run_service import _digest, _project, _record
    from tests.api.routes.test_game_daily import release

    release_id = release(session, root / "fixture")
    owner_id = uuid4()
    session.execute(
        text(
            'INSERT INTO "user" (id, email, hashed_password, full_name, is_active, is_superuser) VALUES (:id, :email, :password, :name, true, false)'
        ),
        {
            "id": owner_id,
            "email": f"migration-{owner_id}@example.com",
            "password": get_password_hash(secrets.token_urlsafe(32)),
            "name": "Migration account",
        },
    )
    definition = _definition(session, datetime(2401, 1, 1, tzinfo=UTC).date())
    assert definition.catalog_release_id == release_id
    run = GameRun(
        owner_id=owner_id,
        mode="daily",
        daily_definition_id=definition.id,
        catalog_release_id=release_id,
        seed=definition.seed,
        generation_version=definition.generation_version,
        rules=dict(definition.rules),
        pool=list(definition.pool),
        order=list(definition.order),
        timeline=[str(definition.anchor_event_id)],
        pending_event_id=UUID(definition.order[1]),
        status="active",
        streak=0,
        revision=0,
    )
    session.add(run)
    session.flush()
    _record(
        session,
        owner_id,
        uuid4(),
        "daily",
        _digest("daily", {}),
        _project(session, run),
    )
    session.commit()


def _remove_created_migration_database() -> None:
    """No force/termination: refuse if any connection still uses this target."""
    database = MIGRATION_DATABASE
    require_guest_test_target(database, settings.POSTGRES_SERVER, settings.ENVIRONMENT)
    with _maintenance_connection() as connection:
        identity = _database_identity(connection, database)
        if identity is None:
            raise RuntimeError("Migration proof database disappeared")
        require_ownership(database, *identity)
        active = connection.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = %s", (database,)
        ).fetchone()
        if active is None or active[0] != 0:
            raise RuntimeError("Migration proof database still has connections")
        connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
        if _database_identity(connection, database) is not None:
            raise RuntimeError("Migration proof database removal was not verified")


def migration_proof() -> Path:
    """Legacy rows survive additive upgrade and an EMPTY guest-schema round trip."""
    if not __debug__:
        raise RuntimeError("Migration proof requires enabled verification assertions")
    database = settings.POSTGRES_DB
    require_guest_test_target(database, settings.POSTGRES_SERVER, settings.ENVIRONMENT)
    if database != MIGRATION_DATABASE:
        raise RuntimeError("Migration proof requires its dedicated disposable database")
    if not prepare_database(database):
        raise RuntimeError("Migration proof must create a new absent database")
    proof_engine = None
    evidence: dict[str, Any] = {}
    try:
        run_migration(database, "upgrade", "20261011_01")
        require_owned_guest_database(database)
        proof_engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
        with TemporaryDirectory(
            prefix="hdg-guest-migration-", dir="/tmp/opencode"
        ) as temporary:
            with Session(proof_engine) as session:
                _seed_legacy_progress(session, Path(temporary))
                before = _private_row_digests(session)
                assert (
                    before["user"]["count"]
                    == before["gamerun"]["count"]
                    == before["gameoperation"]["count"]
                    == before["dailydefinition"]["count"]
                    == 1
                )
        proof_engine.dispose()
        evidence["before"] = before
        for direction, revision, label in (
            ("upgrade", "20261013_01", "upgraded"),
            ("downgrade", "20261011_01", "downgraded_empty_guest_schema"),
            ("upgrade", "20261013_01", "reupgraded"),
        ):
            # Never downgrade nonempty guest state, even in this owned DB.
            require_owned_guest_database(database)
            if direction == "downgrade":
                with Session(proof_engine) as session:
                    assert (
                        session.execute(
                            text("SELECT count(*) FROM guestsession")
                        ).scalar_one()
                        == 0
                    )
                    assert (
                        session.execute(
                            text('SELECT count(*) FROM "user" WHERE is_guest')
                        ).scalar_one()
                        == 0
                    )
                proof_engine.dispose()
            run_migration(database, direction, revision)
            require_owned_guest_database(database)
            with Session(proof_engine) as session:
                after = _private_row_digests(session)
                assert after == before
                if direction == "upgrade":
                    assert (
                        session.execute(
                            text('SELECT bool_and(is_guest = false) FROM "user"')
                        ).scalar_one()
                        is True
                    )
                assert (
                    session.execute(
                        text(
                            "SELECT count(*) FROM gamerun r JOIN dailydefinition d ON r.daily_definition_id = d.id AND r.catalog_release_id = d.catalog_release_id JOIN gameoperation o ON o.run_id = r.id AND o.owner_id = r.owner_id"
                        )
                    ).scalar_one()
                    == 1
                )
                evidence[label] = after
            proof_engine.dispose()
    finally:
        if proof_engine is not None:
            proof_engine.dispose()
        # This invocation created it, and removal re-verifies its exact comment.
        _remove_created_migration_database()
    evidence.update(
        passed=True,
        database=database,
        ownership_comment=ownership_comment(database),
        removed=True,
    )
    directory = WORKTREE / ".superpowers/sdd/2026-10-13-historical-date-game-guest-play"
    directory.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w", prefix="migration-proof-", suffix=".json", dir=directory, delete=False
    ) as handle:
        json.dump(evidence, handle, indent=2)
        return Path(handle.name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare-db")
    prepare.add_argument("--database", required=True)
    subparsers.add_parser("migration-proof")
    args = parser.parse_args(argv)
    try:
        if args.command == "migration-proof":
            evidence = migration_proof()
            sys.stdout.write(
                f"Migration preservation proof passed; owned DB removed; private evidence: {evidence}\n"
            )
        else:
            created = prepare_database(args.database)
            run_migration(args.database, "upgrade", "head")
            sys.stdout.write(
                f"{args.database}: {'created' if created else 'reused'}; ownership verified; migrated\n"
            )
    except Exception:
        sys.stderr.write(
            "Guest verification setup failed; no unverified target permitted\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
