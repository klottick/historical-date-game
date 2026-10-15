"""Prepare real C5-verified browser fixtures; never run pytest DB cleanup.

From backend/, with the explicit local test DB/port environment:
python -m tests.utils.browser_catalog --data-dir ../data/game/browser-tests
The existing B4 builder starts from retained synthetic provider snapshots and
runs C3 import, C4 whole-media validation and C5 publication, not pass receipts.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlmodel import Session, select

from app.content.publish import verify_release
from app.content.schemas import MediaCatalog
from app.core.config import settings
from app.core.db import engine
from app.game.models import CatalogSelection, DailyDefinition, GameRun, MediaAsset


def safe_path(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlink_fixture_path")


def copy_assets(source: Path, target: Path) -> int:
    """Create-only public bytes; identical existing assets can be reused."""
    safe_path(source)
    safe_path(target)
    assets = []
    for item in sorted(source.iterdir()):
        safe_path(item)
        if not re.fullmatch(r"[0-9a-f]{64}\.(svg|webp)", item.name):
            raise ValueError("invalid_public_asset")
        payload = item.read_bytes()
        if hashlib.sha256(payload).hexdigest() != item.stem:
            raise ValueError("asset_digest_mismatch")
        dest = target / item.name
        safe_path(dest)
        if dest.exists() and dest.read_bytes() != payload:
            raise ValueError("immutable_asset_conflict")
        assets.append((dest, payload))
    target.mkdir(parents=True, exist_ok=True)
    for dest, payload in assets:
        if not dest.exists():
            with dest.open("xb") as file:
                file.write(payload)
            dest.chmod(0o444)
    return len(assets)


def frozen_runs(session: Session) -> list[tuple[Any, ...]]:
    return sorted(
        (
            str(run.id),
            run.catalog_release_id,
            run.revision,
            run.status,
            run.streak,
            tuple(run.timeline),
            str(run.pending_event_id),
        )
        for run in session.exec(
            select(GameRun).execution_options(populate_existing=True)
        ).all()
    )


def prepare(data_dir: Path) -> dict[str, Any]:
    if (
        settings.POSTGRES_DB != "historical_date_game_test"
        or settings.POSTGRES_PORT != 5433
    ):
        raise RuntimeError(
            "Browser fixtures require historical_date_game_test on port 5433"
        )
    data_dir = data_dir.absolute()
    safe_path(data_dir)
    data_dir = data_dir.resolve()
    build = data_dir / "builds" / uuid4().hex
    build.parent.mkdir(parents=True, exist_ok=True)
    # The builder commits its Session. A joined savepoint keeps those commits
    # inside this outer transaction until copying/reverification has succeeded.
    with engine.begin() as connection:
        if (
            connection.execute(text("SELECT current_database()")).scalar_one()
            != "historical_date_game_test"
        ):
            raise RuntimeError("Connected database must be historical_date_game_test")
        with Session(
            bind=connection, join_transaction_mode="create_savepoint"
        ) as session:
            from tests.api.routes.test_game_daily import release

            before = frozen_runs(session)
            pointer = session.get(CatalogSelection, 1)
            retained = {pointer.release_id} if pointer else set()
            retained.update(
                session.exec(
                    select(DailyDefinition.catalog_release_id).where(
                        DailyDefinition.day == datetime.now(UTC).date()
                    )
                ).all()
            )
            release_id = release(session, build)
            published = build / "releases" / release_id
            manifest = verify_release(published, published / "media")
            assert manifest.fixture and manifest.event_count == 8
            assets = copy_assets(published / "media", data_dir / "media" / release_id)
            assert (
                verify_release(published, data_dir / "media" / release_id) == manifest
            )
            media = MediaCatalog.model_validate_json(
                (published / "media.json").read_bytes()
            )
            hashes = {r.sha256 for r in media.fallbacks.values()}
            restored = []
            # Existing frozen Daily/run URLs may refer to the prior release.
            # Restore only identical authored fallback hashes recorded in that
            # immutable DB snapshot; never rewrite a run, manifest or receipt.
            for prior in sorted(retained):
                records = session.exec(
                    select(MediaAsset).where(MediaAsset.release_id == prior)
                ).all()
                expected = {
                    r.snapshot["sha256"]
                    for r in records
                    if r.key.startswith("fallback:")
                }
                if expected == hashes:
                    copy_assets(published / "media", data_dir / "media" / prior)
                    restored.append(prior)
            assert frozen_runs(session) == before, "Existing frozen runs changed"
    return {
        "release_id": release_id,
        "fixture": manifest.fixture,
        "event_count": manifest.event_count,
        "fallbacks": len(media.fallbacks),
        "public_assets": assets,
        "release_dir": str(published),
        "data_dir": str(data_dir),
        "restored_fallback_release_ids": restored,
        "existing_frozen_runs_unchanged": len(before),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    sys.stdout.write(
        json.dumps(prepare(parser.parse_args().data_dir), sort_keys=True) + "\n"
    )
