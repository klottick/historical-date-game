"""One-shot migration/initialization and strictly read-only readiness."""

import hashlib
import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from app.distribution.config import validate_environment

if TYPE_CHECKING:
    from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[2]


def alembic_config() -> Config:
    from alembic.config import Config

    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "app/alembic"))
    return config


def initialize() -> int:
    try:
        validate_environment(os.environ)
        from alembic import command
        from sqlalchemy import text
        from sqlmodel import Session

        from app.backend_pre_start import main as wait_for_database
        from app.content.runtime import verify_default
        from app.core.config import settings
        from app.core.db import engine
        from app.game.runtime_catalog import (
            PACKAGED_CATALOGUE,
            install_runtime,
            provision_assets,
        )
        from app.initial_data import init

        snapshot = verify_default(PACKAGED_CATALOGUE)
        # Refuse unwritable storage before migration/admin creation. Never chown.
        with tempfile.TemporaryFile(dir=settings.GAME_DATA_DIR) as stream:
            stream.write(b"storage-check")
            stream.flush()
        provision_assets(snapshot, settings.GAME_DATA_DIR / "media")
        wait_for_database()
        # Session-scoped lock survives Alembic's separate transactions. Cooperative
        # initializers only; operators must stop consumers before an upgrade.
        with engine.connect() as lock:
            lock.execute(text("SELECT pg_advisory_lock(20261016, 1)"))
            try:
                command.upgrade(alembic_config(), "head")
                init()
                with Session(engine) as session:
                    selected = install_runtime(
                        session,
                        PACKAGED_CATALOGUE,
                        initialize_only=True,
                        media_root=settings.GAME_DATA_DIR / "media",
                    )
                    session.commit()
                sys.stdout.write(f"Initialized; selected catalogue: {selected}\n")
            finally:
                lock.execute(text("SELECT pg_advisory_unlock(20261016, 1)"))
    except Exception:
        # Settings/DB exceptions may contain secrets. Operators get a safe failure,
        # not an accidental credential dump into shared container logs.
        sys.stderr.write(
            "Initialization failed: check configuration, schema compatibility and storage; no reset was attempted.\n"
        )
        return 1
    return 0


def check_ready() -> None:
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlmodel import Session, select, text

    from app.content.runtime import read_checked
    from app.content.schemas import FallbackRecord, MediaRecord
    from app.core.config import settings
    from app.core.db import engine
    from app.game.catalog_repository import load_options
    from app.game.models import MediaAsset

    with Session(engine) as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        session.execute(text("SET LOCAL statement_timeout = '3s'"))
        heads = MigrationContext.configure(session.connection()).get_current_heads()
        if set(heads) != set(ScriptDirectory.from_config(alembic_config()).get_heads()):
            raise ValueError("schema_not_ready")
        options = load_options(session)
        if not options.categories:
            raise ValueError("catalogue_not_ready")
        media = session.exec(
            select(MediaAsset).where(MediaAsset.release_id == options.release_id)
        ).all()
        if not media:
            raise ValueError("media_not_ready")
        for row in media:
            record = (
                FallbackRecord if row.key.startswith("fallback:") else MediaRecord
            ).model_validate(row.snapshot)
            path = (
                settings.GAME_DATA_DIR
                / "media"
                / options.release_id
                / Path(record.filename).name
            )
            if hashlib.sha256(read_checked(path)).hexdigest() != record.sha256:
                raise ValueError("media_not_ready")
