"""B2 integration tests use the guarded PostgreSQL database and C5 fixtures."""

import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Session, delete, select, text

from app.content.adapters.selected import SelectedSourceAdapter
from app.content.cli import main
from app.content.importer import import_snapshot
from app.content.media import pipeline
from app.content.publish import publish_release
from app.core.config import settings
from app.core.db import engine
from app.game.catalog_repository import (
    CatalogError,
    activate_catalog,
    load_events,
    load_options,
)
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
from app.game.run_repository import lock_run
from app.models import User
from tests.browser.guest_test_environment import (
    ownership_comment,
    require_owned_guest_database,
    require_ownership,
)
from tests.content.test_importer import snapshot
from tests.content.test_media import SELECTION
from tests.content.test_publish import final_batch, rewrite
from tests.db_guard import require_test_database
from tests.utils.user import authentication_token_from_email


@pytest.fixture
def release(tmp_path: Path) -> Path:
    workspace, _ = final_batch(tmp_path)
    name = "b2-" + uuid4().hex
    publish_release(workspace, tmp_path / "releases", name, fixture=True)
    return tmp_path / "releases" / name


def activate(db: Session, release: Path) -> str:
    release_id = activate_catalog(db, release, release / "media", require_beta=False)
    db.commit()
    return release_id


def run_data(
    db: Session, release_id: str, owner: User
) -> tuple[DailyDefinition, GameRun, GameOperation]:
    ids = list(load_events(db, release_id))
    rules = {
        "category_ids": ["births", "deaths"],
        "start_year_index": -5000,
        "end_year_index": 2026,
        "min_gap": 1,
    }
    daily = DailyDefinition(
        day=date(2001, 1, 1),
        catalog_release_id=release_id,
        seed=b"d" * 32,
        rules=rules,
        pool=[str(i) for i in ids],
        order=[str(i) for i in ids],
        anchor_event_id=ids[0],
    )
    db.add(daily)
    db.flush()
    run = GameRun(
        owner_id=owner.id,
        mode="daily",
        daily_definition_id=daily.id,
        catalog_release_id=release_id,
        seed=daily.seed,
        rules=rules,
        pool=daily.pool,
        order=daily.order,
        timeline=[str(ids[0])],
        pending_event_id=ids[1],
        status="active",
        streak=0,
        revision=0,
    )
    db.add(run)
    db.flush()
    operation = GameOperation(
        owner_id=owner.id,
        operation_id=uuid4(),
        scope="daily",
        run_id=run.id,
        payload_digest="a" * 64,
        outcome={"run_id": str(run.id), "revision": 0},
    )
    db.add(operation)
    db.commit()
    # SQLAlchemy expires rows on commit; model_dump() does not lazy-load them.
    for row in (daily, run, operation):
        db.refresh(row)
    return daily, run, operation


def test_activate_is_idempotent_and_immutable(db: Session, release: Path) -> None:
    release_id = activate(db, release)
    frozen = db.get(CatalogRelease, release_id)
    assert frozen is not None
    before = frozen.manifest_bytes
    assert activate(db, release) == release_id
    assert db.get(CatalogRelease, release_id).manifest_bytes == before
    assert (
        len(
            db.exec(
                select(EventRevision).where(EventRevision.release_id == release_id)
            ).all()
        )
        == 2
    )
    # C5 accepts a changed manifest timestamp, but an already-used ID cannot change bytes.
    rewrite(
        release / "manifest.json", lambda d: d.update(created_at="2026-01-01T00:00:00Z")
    )
    with pytest.raises(CatalogError, match="immutable_release"):
        activate(db, release)
    assert db.get(CatalogRelease, release_id).manifest_bytes == before
    assert load_options(db).release_id == release_id


def test_frozen_revision_survives_activation(
    db: Session, release: Path, tmp_path: Path, client: TestClient
) -> None:
    old_id = activate(db, release)
    old_events = dict(load_events(db, old_id))
    old_categories = [
        r.snapshot
        for r in db.exec(
            select(CatalogCategory).where(CatalogCategory.release_id == old_id)
        ).all()
    ]
    old_media = [
        r.snapshot
        for r in db.exec(
            select(MediaAsset).where(MediaAsset.release_id == old_id)
        ).all()
    ]
    other = tmp_path / "other"
    other.mkdir()
    data = json.loads(Path("tests/fixtures/content/source-snapshot.json").read_text())
    # A genuine source correction retains identity but changes the frozen answer.
    data["entity"]["claims"]["P569"][0]["mainsnak"]["datavalue"]["value"]["time"] = (
        "+00000001801-00-00T00:00:00Z"
    )
    slot = data["page"]["revisions"][0]["slots"]["main"]
    slot["content"] = slot["content"].replace("birth_date = 1800", "birth_date = 1801")
    workspace = other / "work"
    import_snapshot(SelectedSourceAdapter(), snapshot(other, data), workspace)
    pointer = json.loads((workspace / "current.json").read_text())
    for line in (
        (workspace / pointer["generation"] / "candidates.jsonl")
        .read_text()
        .splitlines()
    ):
        pipeline.assign_media(
            pipeline.EventRecord.model_validate_json(line), SELECTION, workspace
        )
    assert all(r.passed for r in pipeline.finalize_media_receipts(workspace))
    email = uuid4().hex + "@example.com"
    authentication_token_from_email(client=client, email=email, db=db)
    owner = db.exec(select(User).where(User.email == email)).one()
    daily, run, _ = run_data(db, old_id, owner)
    new_id = "b2-" + uuid4().hex
    publish_release(workspace, other / "releases", new_id, fixture=True)
    activate(db, other / "releases" / new_id)
    assert load_options(db).release_id == new_id
    new_events = load_events(db, new_id)
    assert set(new_events) == set(old_events)
    assert any(e.year_index != new_events[i].year_index for i, e in old_events.items())
    assert run.catalog_release_id == old_id and daily.catalog_release_id == old_id
    assert dict(load_events(db, old_id)) == old_events
    assert [
        r.snapshot
        for r in db.exec(
            select(CatalogCategory).where(CatalogCategory.release_id == old_id)
        ).all()
    ] == old_categories
    assert [
        r.snapshot
        for r in db.exec(
            select(MediaAsset).where(MediaAsset.release_id == old_id)
        ).all()
    ] == old_media
    db.delete(owner)
    db.commit()
    db.delete(daily)
    db.commit()


@pytest.mark.parametrize("method", ["self", "admin", "orm_loaded", "sql"])
def test_account_deletion_cascades_owned_game_data(
    db: Session,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    release: Path,
    method: str,
) -> None:
    release_id = activate(db, release)
    email = uuid4().hex + "@example.com"
    headers = authentication_token_from_email(client=client, email=email, db=db)
    owner = db.exec(select(User).where(User.email == email)).one()
    daily, run, operation = run_data(db, release_id, owner)
    other_owner = User(email=uuid4().hex + "@example.com", hashed_password="unused")
    db.add(other_owner)
    db.flush()
    other_run = GameRun(
        **{**run.model_dump(), "id": uuid4(), "owner_id": other_owner.id}
    )
    db.add(other_run)
    db.flush()
    # UUID reuse is allowed across owners, never across one owner's scopes.
    other_operation = GameOperation(
        **{
            **operation.model_dump(),
            "id": uuid4(),
            "owner_id": other_owner.id,
            "run_id": other_run.id,
        }
    )
    db.add(other_operation)
    db.commit()
    ids = daily.id, run.id, operation.id, owner.id
    if method == "self":
        assert client.delete("/api/v1/users/me", headers=headers).status_code == 200
    elif method == "admin":
        assert (
            client.delete(
                f"/api/v1/users/{owner.id}", headers=superuser_token_headers
            ).status_code
            == 200
        )
    elif method == "orm_loaded":
        assert owner.game_runs and owner.game_operations
        db.delete(owner)
        db.commit()
    else:
        db.exec(delete(User).where(User.id == owner.id))
        db.commit()
    db.expire_all()
    assert db.get(User, ids[3]) is None
    assert db.get(GameRun, ids[1]) is None
    assert db.get(GameOperation, ids[2]) is None
    assert db.get(GameRun, other_run.id) is not None
    assert db.get(GameOperation, other_operation.id) is not None
    assert db.get(DailyDefinition, ids[0]) is not None
    assert len(load_events(db, release_id)) == 2
    db.delete(other_owner)
    db.commit()
    # Leave the globally unique test day available to the next parameter.
    db.delete(db.get(DailyDefinition, ids[0]))
    db.commit()


def test_activation_verifies_before_writing(
    db: Session, release: Path, tmp_path: Path
) -> None:
    other = tmp_path / "baseline"
    other.mkdir()
    workspace, _ = final_batch(other)
    baseline = "baseline-" + uuid4().hex
    publish_release(workspace, other / "releases", baseline, fixture=True)
    active = activate(db, other / "releases" / baseline)
    with pytest.raises(CatalogError):
        activate_catalog(db, release, release / "media", require_beta=True)
    assert db.get(CatalogRelease, release.name) is None
    assert load_options(db).release_id == active
    (release / "events.jsonl").write_text("tampered\n")
    with pytest.raises(CatalogError):
        activate(db, release)
    assert db.get(CatalogRelease, release.name) is None


def test_persisted_state_constraints_and_owner_lock(
    db: Session, client: TestClient, release: Path
) -> None:
    release_id = activate(db, release)
    email = uuid4().hex + "@example.com"
    authentication_token_from_email(client=client, email=email, db=db)
    owner = db.exec(select(User).where(User.email == email)).one()
    daily, run, operation = run_data(db, release_id, owner)
    assert lock_run(db, run.id, owner.id).id == run.id
    with Session(engine) as competing:
        competing.execute(text("SET LOCAL lock_timeout = '50ms'"))
        with pytest.raises(OperationalError) as locked:
            lock_run(competing, run.id, owner.id)
        assert locked.value.orig.sqlstate == "55P03"
        competing.rollback()
    with pytest.raises(CatalogError, match="run_not_found"):
        lock_run(db, run.id, uuid4())
    db.commit()
    with Session(db.bind) as fresh:
        saved = fresh.get(GameRun, run.id)
        assert saved.seed == b"d" * 32 and saved.generation_version == 1
        assert saved.rules == daily.rules and saved.pool == daily.pool
        assert saved.order == daily.order and saved.timeline == run.timeline
        assert saved.pending_event_id == run.pending_event_id
        assert saved.created_at.tzinfo and saved.updated_at.tzinfo
        saved_operation = fresh.get(GameOperation, operation.id)
        assert saved_operation.payload_digest == "a" * 64
        assert saved_operation.outcome == operation.outcome
    attacks = [
        "UPDATE gamerun SET seed = decode('00', 'hex') WHERE id = :id",
        "UPDATE gamerun SET status = 'invalid' WHERE id = :id",
        "UPDATE gamerun SET revision = -1 WHERE id = :id",
        "UPDATE gamerun SET generation_version = 2 WHERE id = :id",
        "UPDATE gamerun SET mode = 'freeplay' WHERE id = :id",
        "UPDATE gamerun SET rules = '{}'::jsonb WHERE id = :id",
    ]
    for sql in attacks:
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(text(sql), {"id": run.id})
    with pytest.raises(IntegrityError) as duplicate_operation, db.begin_nested():
        db.add(
            GameOperation(
                owner_id=owner.id,
                operation_id=operation.operation_id,
                scope="placement",
                run_id=run.id,
                payload_digest="b" * 64,
                outcome={},
            )
        )
        db.flush()
    assert (
        duplicate_operation.value.orig.diag.constraint_name
        == "uq_gameoperation_owner_operation"
    )
    with pytest.raises(IntegrityError) as duplicate_run, db.begin_nested():
        db.add(GameRun(**{**run.model_dump(), "id": uuid4()}))
        db.flush()
    assert duplicate_run.value.orig.diag.constraint_name == "uq_gamerun_owner_daily"
    with pytest.raises(IntegrityError) as duplicate_day, db.begin_nested():
        db.add(DailyDefinition(**{**daily.model_dump(), "id": uuid4()}))
        db.flush()
    assert duplicate_day.value.orig.diag.constraint_name == "dailydefinition_day_key"
    for invalid_rules in (
        {**run.rules, "min_gap": None},
        {**run.rules, "min_gap": "1"},
        {**run.rules, "start_year_index": None},
    ):
        with pytest.raises(IntegrityError) as bad_rules, db.begin_nested():
            db.add(
                GameRun(
                    **{
                        **run.model_dump(),
                        "id": uuid4(),
                        "mode": "freeplay",
                        "daily_definition_id": None,
                        "rules": invalid_rules,
                    }
                )
            )
            db.flush()
        assert bad_rules.value.orig.diag.constraint_name == "ck_gamerun_rules"
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(CatalogSelection(id=2, release_id=release_id))
        db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            text(
                "UPDATE eventrevision SET snapshot = '{}'::jsonb WHERE release_id = :id"
            ),
            {"id": release_id},
        )
    # A real state transition is persisted without losing any frozen generation fields.
    run.status = "lost"
    run.pending_event_id = None
    run.revision = 1
    run.updated_at = datetime.now(UTC)
    run.finished_at = run.updated_at
    db.add(run)
    db.commit()
    with Session(engine) as after_move:
        moved = lock_run(after_move, run.id, owner.id)
        assert moved.status == "lost" and moved.revision == 1
        assert moved.pending_event_id is None and moved.finished_at == moved.updated_at
        assert moved.seed == daily.seed and moved.rules == daily.rules
    db.delete(owner)
    db.commit()
    db.delete(daily)
    db.commit()


def test_activation_cli(
    db: Session, release: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["activate", "--release", str(release), "--media", str(release / "media")]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == {"release_id": release.name}
    db.expire_all()
    assert load_options(db).release_id == release.name
    assert main([*args, "--require-beta"]) == 1
    assert "beta" in capsys.readouterr().err


def test_activation_rollback_is_atomic(db: Session, release: Path) -> None:
    db.commit()
    with Session(engine) as writer:
        activate_catalog(writer, release, release / "media", require_beta=False)
        assert writer.get(CatalogRelease, release.name)
        with Session(engine) as observer:
            assert observer.get(CatalogRelease, release.name) is None
            pointer = observer.get(CatalogSelection, 1)
            assert pointer is None or pointer.release_id != release.name
        writer.rollback()
    assert db.get(CatalogRelease, release.name) is None
    assert not db.exec(
        select(EventRevision).where(EventRevision.release_id == release.name)
    ).all()


@pytest.mark.parametrize("reactivate", [False, True])
def test_cached_pointer_tracks_committed_activation(
    db: Session, release: Path, reactivate: bool
) -> None:
    first_id = activate(db, release)
    # Generate a different verified release from the same C5 fixture workspace.
    workspace = release.parents[1] / "work"
    next_id = "b2-" + uuid4().hex
    publish_release(workspace, release.parent, next_id, fixture=True)
    with Session(engine) as cached:
        pointer = cached.get(CatalogSelection, 1)
        assert pointer.release_id == first_id
        with Session(engine) as activator:
            activate_catalog(
                activator,
                release.parent / next_id,
                release.parent / next_id / "media",
                require_beta=False,
            )
            activator.commit()
        if reactivate:
            activate_catalog(cached, release, release / "media", require_beta=False)
            cached.commit()
            with Session(engine) as observer:
                assert load_options(observer).release_id == first_id
        else:
            assert load_options(cached).release_id == next_id


def test_catalog_unavailable_without_pointer(db: Session) -> None:
    db.commit()
    with Session(engine) as isolated:
        isolated.exec(delete(CatalogSelection))
        with pytest.raises(CatalogError, match="catalog_unavailable"):
            load_options(isolated)
        with pytest.raises(CatalogError, match="catalog_unavailable"):
            load_events(isolated, "missing-" + uuid4().hex)
        isolated.rollback()


def test_migration_round_trip_on_owned_fixture_database(
    release: Path, request: pytest.FixtureRequest
) -> None:
    """Authorized exception: this test owns one absent random child DB.

    Primary verification targets remain fixed-name and comment-verified. This
    round trip separately creates/comments/verifies/drops only its exact child.
    """
    require_test_database(settings.POSTGRES_DB)
    require_owned_guest_database()
    name = "hdg_b2_fixture_" + uuid4().hex[:12] + "_test"
    request.node.user_properties.append(("owned_fixture_database", name))
    require_test_database(name)
    env = {**os.environ, "POSTGRES_DB": name, "POSTGRES_PORT": "5433"}
    from psycopg import sql
    from sqlalchemy import Connection, create_engine, inspect

    def verify_child_ownership(connection: Connection) -> None:
        identity = connection.execute(
            text(
                "SELECT shobj_description(oid, 'pg_database'), pg_get_userbyid(datdba) "
                "FROM pg_database WHERE datname = :name"
            ),
            {"name": name},
        ).one()
        require_ownership(name, identity[0], identity[1])

    child = create_engine(
        str(settings.SQLALCHEMY_DATABASE_URI).rsplit("/", 1)[0] + "/" + name
    )
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM pg_database WHERE datname = :name"),
                {"name": name},
            ).scalar_one()
            == 0
        )
        # CREATE must succeed before entering any cleanup path; never adopt a DB.
        connection.execute(text(f'CREATE DATABASE "{name}"'))
        try:
            connection.exec_driver_sql(
                sql.SQL("COMMENT ON DATABASE {} IS {}")
                .format(sql.Identifier(name), sql.Literal(ownership_comment(name)))
                .as_string()
            )
            verify_child_ownership(connection)
            request.node.user_properties.append(
                ("owned_fixture_comment", ownership_comment(name))
            )
            for step, revision in enumerate(("head", "1a31ce608336", "head")):
                verify_child_ownership(connection)
                action = "downgrade" if revision == "1a31ce608336" else "upgrade"
                result = subprocess.run(
                    [sys.executable, "-m", "alembic", action, revision],
                    env=env,
                    text=True,
                    capture_output=True,
                )
                assert result.returncode == 0, result.stderr
                if step == 0:
                    # Exercise downgrade with real synthetic C5 snapshots and owned
                    # run/operation rows, not a scored production database.
                    verify_child_ownership(connection)
                    with Session(child) as fixture_db:
                        owner = User(
                            email="migration-fixture@example.com",
                            hashed_password="unused",
                        )
                        fixture_db.add(owner)
                        fixture_db.commit()
                        release_id = activate(fixture_db, release)
                        run_data(fixture_db, release_id, owner)
                elif step == 1:
                    verify_child_ownership(connection)
                    with child.connect() as previous:
                        assert "gamerun" not in inspect(previous).get_table_names()
                        assert (
                            previous.execute(
                                text('SELECT count(*) FROM "user"')
                            ).scalar_one()
                            == 1
                        )
                        assert (
                            previous.execute(
                                text(
                                    "SELECT count(*) FROM pg_proc WHERE proname = 'hdg_reject_frozen_update'"
                                )
                            ).scalar_one()
                            == 0
                        )
            # Verify the re-upgraded schema and exact revision, then drop only this DB.
            verify_child_ownership(connection)
            with child.connect() as migrated:
                assert (
                    migrated.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one()
                    == "20261013_01"
                )
                assert set(inspect(migrated).get_table_names()) >= {
                    "catalogrelease",
                    "catalogselection",
                    "catalogcategory",
                    "eventrevision",
                    "mediaasset",
                    "dailydefinition",
                    "gamerun",
                    "gameoperation",
                }
                assert (
                    migrated.execute(
                        text(
                            "SELECT count(*) FROM pg_trigger WHERE tgname = 'immutable_snapshot'"
                        )
                    ).scalar_one()
                    == 6
                )
        finally:
            child.dispose()
            verify_child_ownership(connection)
            assert (
                connection.execute(
                    text("SELECT count(*) FROM pg_stat_activity WHERE datname = :name"),
                    {"name": name},
                ).scalar_one()
                == 0
            )
            connection.execute(text(f'DROP DATABASE "{name}"'))
            assert (
                connection.execute(
                    text("SELECT count(*) FROM pg_database WHERE datname = :name"),
                    {"name": name},
                ).scalar_one()
                == 0
            )
