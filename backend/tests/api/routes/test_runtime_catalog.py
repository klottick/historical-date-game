"""Checked snapshot installation on the explicitly owned disposable target only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest
from sqlalchemy import event
from sqlmodel import Session, delete, select, text

from app.core.config import settings
from app.core.db import engine
from app.game.catalog_repository import CatalogError, load_events, load_options
from app.game.models import CatalogRelease, CatalogSelection, EventRevision
from app.models import User
from tests.api.routes.test_game_catalog import run_data
from tests.browser.guest_test_environment import require_owned_guest_database
from tests.content.test_runtime_catalog import runtime_snapshot


@pytest.fixture(scope="session")
def _runtime_target_safety(_verification_database_safety: None) -> None:
    assert settings.POSTGRES_DB == "historical_date_game_lives_backend_test"
    assert settings.POSTGRES_SERVER == "127.0.0.1" and settings.POSTGRES_PORT == 5433
    require_owned_guest_database()
    # The shared session preflight ran before any suite-owned pools were opened.
    # Rechecking idleness here would misidentify earlier tests' pools as foreign.


@pytest.fixture(scope="session", autouse=True)
def db(_runtime_target_safety: None, db: Session) -> Session:
    """Run safety before the inherited fixture can initialize or later clean up."""
    return db


def test_fresh_initialize_is_immutable_idempotent_and_uses_checked_records(
    db: Session, tmp_path: Path
) -> None:
    from app.game.catalog_repository import install_snapshot

    root, snapshot = runtime_snapshot(tmp_path)
    db.exec(delete(CatalogSelection))
    db.commit()
    # The checked snapshot, not these now-corrupt source files, is the input.
    for path in (root / "releases" / snapshot.manifest.release_id).iterdir():
        path.write_bytes(b"untrusted after check")
    name = install_snapshot(db, snapshot, initialize_only=True)
    db.commit()
    assert name == snapshot.manifest.release_id == load_options(db).release_id
    before = db.get(CatalogRelease, name).model_dump()
    assert install_snapshot(db, snapshot, initialize_only=True) == name
    db.commit()
    assert db.get(CatalogRelease, name).model_dump() == before
    assert len(load_events(db, name)) == 2
    assert db.get(CatalogRelease, name).manifest["kind"] == "runtime-catalogue"


def test_initialize_keeps_different_selection_and_explicit_install_preserves_history(
    db: Session, tmp_path: Path
) -> None:
    from app.game.catalog_repository import install_snapshot

    _, old = runtime_snapshot(tmp_path / "old")
    _, new = runtime_snapshot(tmp_path / "new")
    old_id = install_snapshot(db, old)
    owner = User(
        email=new.manifest.release_id + "@example.com", hashed_password="retained-hash"
    )
    db.add(owner)
    db.commit()
    daily, run, operation = run_data(db, old_id, owner)
    rows = (owner, daily, run, operation)
    for row in rows:
        db.refresh(row)
    before = [row.model_dump() for row in rows]
    old_events = dict(load_events(db, old_id))
    assert install_snapshot(db, new, initialize_only=True) == old_id
    assert db.get(CatalogRelease, new.manifest.release_id) is None
    assert install_snapshot(db, new) == new.manifest.release_id
    db.commit()
    assert load_options(db).release_id == new.manifest.release_id
    assert dict(load_events(db, old_id)) == old_events
    for row, saved in zip(rows, before, strict=True):
        db.refresh(row)
        assert row.model_dump() == saved
    db.delete(owner)
    db.commit()
    db.delete(daily)
    db.commit()


def test_conflicting_manifest_leaves_selection_and_rows_unchanged(
    db: Session, tmp_path: Path
) -> None:
    from app.game.catalog_repository import install_snapshot

    _, snapshot = runtime_snapshot(tmp_path / "first")
    name = install_snapshot(db, snapshot)
    db.commit()
    _, conflict = runtime_snapshot(
        tmp_path / "conflict",
        release_id=name,
        created_at=datetime(2026, 10, 15, tzinfo=UTC),
    )
    with pytest.raises(CatalogError, match="immutable_release"):
        install_snapshot(db, conflict)
    assert load_options(db).release_id == name
    assert db.get(CatalogRelease, name).manifest_bytes == snapshot.manifest_bytes
    assert len(load_events(db, name)) == 2


def test_snapshot_transaction_rollback_does_not_leave_partial_rows(
    db: Session, tmp_path: Path
) -> None:
    from app.game.catalog_repository import install_snapshot

    _, snapshot = runtime_snapshot(tmp_path / "new")
    _, old = runtime_snapshot(tmp_path / "old")
    previous = install_snapshot(db, old)
    db.commit()
    with Session(engine) as writer:
        install_snapshot(writer, snapshot)
        assert load_options(writer).release_id == snapshot.manifest.release_id
        with Session(engine) as observer:
            assert observer.get(CatalogRelease, snapshot.manifest.release_id) is None
            assert load_options(observer).release_id == previous
        writer.rollback()
    assert db.get(CatalogRelease, snapshot.manifest.release_id) is None
    assert not db.exec(
        select(EventRevision).where(
            EventRevision.release_id == snapshot.manifest.release_id
        )
    ).all()
    assert load_options(db).release_id == previous


def test_initialize_checks_selection_after_acquiring_shared_lock(
    db: Session, tmp_path: Path
) -> None:
    from app.game.catalog_repository import install_snapshot

    _, startup = runtime_snapshot(tmp_path / "startup")
    _, explicit = runtime_snapshot(tmp_path / "explicit")
    db.commit()
    attempted_lock = Event()

    def initialize() -> str:
        with Session(engine) as session:

            def before_execute(
                _connection, _cursor, statement, _parameters, _context, _many
            ):
                if "pg_advisory_xact_lock" in statement:
                    attempted_lock.set()

            event.listen(session.connection(), "before_cursor_execute", before_execute)
            result = install_snapshot(session, startup, initialize_only=True)
            session.commit()
            return result

    with ThreadPoolExecutor(max_workers=1) as pool:
        with Session(engine) as installer:
            installer.execute(text("SELECT pg_advisory_xact_lock(20261011, 2)"))
            installer.exec(delete(CatalogSelection))
            future = pool.submit(initialize)
            assert attempted_lock.wait(5)
            assert not future.done()
            selected = install_snapshot(installer, explicit)
            installer.commit()
            assert future.result(timeout=10) == selected
    db.expire_all()
    assert load_options(db).release_id == selected
    assert db.get(CatalogRelease, startup.manifest.release_id) is None


def test_external_asset_conflict_does_not_switch_selected_release(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.game import runtime_catalog
    from app.game.catalog_repository import install_snapshot

    root, snapshot = runtime_snapshot(tmp_path / "new")
    _, old = runtime_snapshot(tmp_path / "old")
    previous = install_snapshot(db, old)
    db.commit()
    # Composition only: the small verified snapshot does NOT pass verify_default's
    # >=1000 beta gate (tested separately in the pure suite).
    monkeypatch.setattr(runtime_catalog, "verify_default", lambda root: snapshot)
    target = tmp_path / "external/media" / snapshot.manifest.release_id
    target.mkdir(parents=True)
    path = target / next(iter(snapshot.assets))
    path.write_bytes(b"retained conflict")
    with pytest.raises(ValueError):
        runtime_catalog.install_runtime(
            db, root, initialize_only=False, media_root=target.parent
        )
    assert path.read_bytes() == b"retained conflict"
    assert load_options(db).release_id == previous
    assert db.get(CatalogRelease, snapshot.manifest.release_id) is None


def test_runtime_cli_initializes_then_requires_explicit_install_for_change(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json

    from app.game import runtime_catalog

    root, first = runtime_snapshot(tmp_path / "first")
    other, second = runtime_snapshot(tmp_path / "second")
    checked = {root: first, other: second}
    # Composition test, not a synthetic beta acceptance claim.
    monkeypatch.setattr(runtime_catalog, "verify_default", checked.__getitem__)
    monkeypatch.setattr(settings, "GAME_DATA_DIR", tmp_path / "external")
    db.exec(delete(CatalogSelection))
    db.commit()
    for command, bundle, expected in (
        ("initialize", root, first.manifest.release_id),
        ("initialize", root, first.manifest.release_id),
        ("initialize", other, first.manifest.release_id),
        ("install", other, second.manifest.release_id),
    ):
        assert runtime_catalog.main([command, "--catalogue", str(bundle)]) == 0
        output = capsys.readouterr()
        assert json.loads(output.out) == {"release_id": expected}
        if command == "initialize":
            assert "use 'install'" in output.err and expected in output.err
        db.expire_all()
        assert load_options(db).release_id == expected
        db.commit()
    for snapshot in (first, second):
        for name, data in snapshot.assets.items():
            path = (
                settings.GAME_DATA_DIR / "media" / snapshot.manifest.release_id / name
            )
            assert not path.is_symlink() and path.read_bytes() == data


def test_database_failure_rolls_back_snapshot_insertion(
    db: Session, tmp_path: Path
) -> None:
    from sqlalchemy.exc import DBAPIError

    from app.game.catalog_repository import install_snapshot

    _, old = runtime_snapshot(tmp_path / "old")
    _, new = runtime_snapshot(tmp_path / "new")
    previous = install_snapshot(db, old)
    db.commit()

    def fail_events(connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO eventrevision"):
            connection.exec_driver_sql("SELECT 1 / 0")

    connection = db.connection()
    event.listen(connection, "before_cursor_execute", fail_events)
    try:
        with pytest.raises(DBAPIError):
            install_snapshot(db, new)
    finally:
        event.remove(connection, "before_cursor_execute", fail_events)
    assert load_options(db).release_id == previous
    assert db.get(CatalogRelease, new.manifest.release_id) is None
    assert not db.exec(
        select(EventRevision).where(EventRevision.release_id == new.manifest.release_id)
    ).all()
