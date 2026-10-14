"""Owned, disposable guest-play verification databases; never live targets.

Run from this worktree's backend directory. Credentials stay in the private .env.
"""

import argparse
import hashlib
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Any
from urllib.request import urlopen
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
EVIDENCE = (
    WORKTREE
    / ".superpowers/sdd/2026-10-13-historical-date-game-guest-play/task-5-evidence"
)
NODE = Path("/tmp/opencode/node-v26.11.1-linux-x64/bin/node")
MANIFEST_SHA = "804ec52ccfc3e19cd955913b05cbfd59158f562408e45c1916fa8626d3ac50d3"


def browser_target(target: str) -> dict[str, Any]:
    if target not in {"real", "fixture"}:
        raise ValueError("Unknown owned browser target")
    real = target == "real"
    return {
        "database": "historical_date_game_guest_test"
        if real
        else "historical_date_game_guest_fixture_test",
        "backend_port": 8020 if real else 8021,
        "ui_port": 5184 if real else 5173,
        "cookie": "hdg_guest_verification" if real else "hdg_guest_fixture",
        "runtime": EVIDENCE / f"{target}-runtime",
    }


def verify_real_source(release: Path) -> Any:
    from app.content.publish import verify_release

    if (
        not release.is_absolute()
        or hashlib.sha256((release / "manifest.json").read_bytes()).hexdigest()
        != MANIFEST_SHA
    ):
        raise RuntimeError("Real source must match the absolute pinned manifest")
    manifest = verify_release(release, release / "media", require_beta=True)
    if manifest.fixture or manifest.event_count != 1276:
        raise RuntimeError("Reviewed real catalog identity changed")
    return manifest


def _project_media(release: Path, manifest: Any, runtime: Path) -> None:
    """Copy only verified manifest media, under the exact release-scoped prefix."""
    for name, digest in manifest.files.items():
        if not name.startswith("media/"):
            continue
        source = (release / name).resolve(strict=True)
        if (
            not source.is_relative_to(release.resolve())
            or hashlib.sha256(source.read_bytes()).hexdigest() != digest
        ):
            raise RuntimeError("Public media source failed integrity")
        destination = (
            runtime / "media" / manifest.release_id / name.removeprefix("media/")
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise RuntimeError("Existing public media differs; refusing overwrite")
        else:
            shutil.copyfile(source, destination)


def seed_browser(target: str, release: Path | None) -> None:
    from app.content.publish import verify_release
    from app.core.db import init_db
    from app.game.catalog_repository import activate_catalog
    from tests.api.routes.test_game_daily import release as build_fixture

    config = browser_target(target)
    require_owned_guest_database(config["database"])
    # Seeding is never coupled to pytest cleanup, nor allowed during browser use.
    for component in ("backend", "ui"):
        _require_free_port(config[f"{component}_port"])
    runtime = config["runtime"]
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    with _maintenance_connection() as connection:
        if connection.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = %s",
            (config["database"],),
        ).fetchone()[0]:
            raise RuntimeError("Refusing seed while the browser database is in use")
    proof_engine = create_engine(
        str(settings.SQLALCHEMY_DATABASE_URI).rsplit("/", 1)[0]
        + "/"
        + config["database"]
    )
    try:
        if target == "real":
            if release is None:
                raise RuntimeError("Absolute reviewed real release required")
            manifest = verify_real_source(release)
        with Session(proof_engine) as session:
            init_db(session)
            if target == "fixture":
                state = runtime / "fixture-state.json"
                if state.exists():
                    release = Path(json.loads(state.read_text())["release"])
                else:
                    build = runtime / ("fixture-build-" + uuid4().hex)
                    release_id = build_fixture(session, build)
                    release = build / "releases" / release_id
                    state.write_text(json.dumps({"release": str(release)}))
                    state.chmod(0o600)
                manifest = verify_release(
                    release, release / "media", require_beta=False
                )
                if not manifest.fixture or manifest.event_count != 8:
                    raise RuntimeError("Verified eight-event fixture required")
            _project_media(release, manifest, runtime)
            activate_catalog(
                session, release, release / "media", require_beta=target == "real"
            )
            session.commit()
        summary = {
            "target": target,
            "database": config["database"],
            "release_id": manifest.release_id,
            "events": manifest.event_count,
            "manifest_sha256": hashlib.sha256(
                (release / "manifest.json").read_bytes()
            ).hexdigest(),
            "files": dict(manifest.files),
        }
        (runtime / "seed.json").write_text(json.dumps(summary, indent=2))
        (runtime / "seed.json").chmod(0o600)
        sys.stdout.write(
            f"{target}: verified catalog activated; public media projected; no cleanup\n"
        )
    finally:
        proof_engine.dispose()


def _process_identity(pid: int) -> dict[str, Any]:
    root = Path(f"/proc/{pid}")
    return {
        "pid": pid,
        "cwd": str((root / "cwd").resolve(strict=True)),
        "command": (root / "cmdline").read_bytes().decode().rstrip("\0").split("\0"),
        "start_ticks": (root / "stat").read_text().rsplit(")", 1)[1].split()[19],
    }


def require_process_identity(record: dict[str, Any]) -> None:
    try:
        actual = _process_identity(record["pid"])
    except OSError, ValueError:
        raise RuntimeError("Owned process ownership is no longer proven")
    if actual != record or actual["cwd"] not in {
        str(WORKTREE / "backend"),
        str(WORKTREE / "frontend"),
    }:
        raise RuntimeError("Owned process ownership is not proven")


def wait_process_identity(
    process: Any, cwd: Path, command: list[str]
) -> dict[str, Any]:
    """/proc/cmdline can be empty between spawn and exec; never ledger that race."""
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("Owned process exited before identity confirmation")
        record = _process_identity(process.pid)
        if record["cwd"] == str(cwd) and record["command"] == command:
            return record
        time.sleep(0.01)
    raise RuntimeError("Owned process command/cwd did not become verifiable")


def _require_free_port(port: int) -> None:
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))


def owned_process(target: str, component: str, stop: bool = False) -> None:
    config = browser_target(target)
    require_owned_guest_database(config["database"])
    EVIDENCE.mkdir(parents=True, exist_ok=True, mode=0o700)
    record_path = EVIDENCE / f"{target}-{component}-process.json"
    if stop:
        record = json.loads(record_path.read_text())
        require_process_identity(record)
        # Verify the exact cwd/command/start-time PID before signalling only it.
        os.kill(record["pid"], signal.SIGTERM)
        for _ in range(100):
            try:
                _require_free_port(config[f"{component}_port"])
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Owned process did not release its port")
        record_path.rename(
            EVIDENCE / f"{target}-{component}-stopped-{record['pid']}.json"
        )
        sys.stdout.write(f"{target} {component}: stopped owned PID {record['pid']}\n")
        return
    if record_path.exists():
        raise RuntimeError(
            "Process ledger exists; explicit ownership-checked stop required"
        )
    _require_free_port(config[f"{component}_port"])
    if not (config["runtime"] / "seed.json").exists():
        raise RuntimeError("Verified seed required before launch")
    ui_origin = f"http://localhost:{config['ui_port']}"
    env = dict(
        os.environ,
        POSTGRES_DB=config["database"],
        POSTGRES_SERVER="127.0.0.1",
        POSTGRES_PORT="5433",
        ENVIRONMENT="local",
        FRONTEND_HOST=ui_origin,
        BACKEND_CORS_ORIGINS=json.dumps(
            [ui_origin, "http://guest.test:5184"] if target == "real" else [ui_origin]
        ),
        GAME_GUEST_COOKIE_NAME=config["cookie"],
        GAME_DATA_DIR=str(config["runtime"]),
        PUBLIC_REGISTRATION_ENABLED="false" if target == "real" else "true",
        VITE_API_URL=f"http://localhost:{config['backend_port']}",
    )
    if target == "fixture":
        # Existing account password-recovery suite uses the owned local catcher.
        # Never send verification account mail through an external SMTP server.
        env.update(
            SMTP_HOST="127.0.0.1",
            SMTP_PORT="1025",
            SMTP_TLS="false",
            SMTP_SSL="false",
            SMTP_USER="",
            SMTP_PASSWORD="",
            EMAILS_FROM_EMAIL="guest-verification@example.com",
        )
    if component == "backend":
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(config["backend_port"]),
            "--no-access-log",
        ]
    else:
        command = [
            str(NODE),
            "node_modules/vite/bin/vite.js",
            "--config",
            "vite.guest-catalog.config.ts" if target == "real" else "vite.config.ts",
            "--host",
            "127.0.0.1",
            "--port",
            str(config["ui_port"]),
            "--strictPort",
        ]
    cwd = WORKTREE / ("backend" if component == "backend" else "frontend")
    with open(EVIDENCE / f"{target}-{component}.log", "ab") as output:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=output,
            stderr=output,
            start_new_session=True,
        )
    record = wait_process_identity(process, cwd, command)
    record_path.write_text(json.dumps(record, indent=2))
    record_path.chmod(0o600)
    url = f"http://127.0.0.1:{config[f'{component}_port']}" + (
        "/api/v1/utils/health-check/" if component == "backend" else "/"
    )
    for _ in range(200):
        if process.poll() is not None:
            raise RuntimeError("Owned process exited before readiness")
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    require_process_identity(record)
                    sys.stdout.write(
                        f"{target} {component}: ready loopback owned PID {process.pid}\n"
                    )
                    return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("Owned process readiness timed out")


def audit_browser(target: str) -> None:
    config = browser_target(target)
    require_owned_guest_database(config["database"])
    seed = json.loads((config["runtime"] / "seed.json").read_text())
    for name, digest in seed["files"].items():
        if name.startswith("media/"):
            asset = (
                config["runtime"]
                / "media"
                / seed["release_id"]
                / name.removeprefix("media/")
            )
            if hashlib.sha256(asset.read_bytes()).hexdigest() != digest:
                raise RuntimeError("Projected asset integrity failed")
    for component in ("backend", "ui"):
        record_path = EVIDENCE / f"{target}-{component}-process.json"
        if record_path.exists():
            require_process_identity(json.loads(record_path.read_text()))
    sys.stdout.write(
        f"{target}: exact DB/process ownership and all public media hashes verified\n"
    )


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
    real = subparsers.add_parser("seed-real")
    real.add_argument("--release", type=Path, required=True)
    subparsers.add_parser("seed-fixture")
    audit = subparsers.add_parser("audit")
    audit.add_argument("--target", choices=["real", "fixture"], required=True)
    for operation in ("launch", "stop"):
        process = subparsers.add_parser(operation)
        process.add_argument("--target", choices=["real", "fixture"], required=True)
        process.add_argument("--component", choices=["backend", "ui"], required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "migration-proof":
            evidence = migration_proof()
            sys.stdout.write(
                f"Migration preservation proof passed; owned DB removed; private evidence: {evidence}\n"
            )
        elif args.command == "seed-real":
            seed_browser("real", args.release)
        elif args.command == "seed-fixture":
            seed_browser("fixture", None)
        elif args.command == "audit":
            audit_browser(args.target)
        elif args.command in {"launch", "stop"}:
            owned_process(args.target, args.component, args.command == "stop")
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
