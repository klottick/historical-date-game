"""Offline packaged catalogue installation; never acquire or rebuild content."""

import argparse
import fcntl
import json
import os
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.content.publish import _safe_root
from app.content.runtime import VerifiedRuntime, read_checked, verify_default
from app.game.catalog_repository import CatalogError, install_snapshot

PACKAGED_CATALOGUE = Path(__file__).resolve().parents[2] / "catalogue"


def provision_assets(snapshot: VerifiedRuntime, media_root: Path) -> None:
    """Create real release-scoped files, or require identical existing bytes.

    Cooperating installers serialize on the directory inode, without needing a
    writable packaged tree or a lock file. Failed provisioning may leave new,
    unselected files; never overwrite/remove old files or follow symlinks.
    """
    root = _safe_root(media_root)
    root.mkdir(parents=True, exist_ok=True)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        destination = _safe_root(root / snapshot.manifest.release_id)
        destination.mkdir(exist_ok=True)
        for name, data in snapshot.assets.items():
            path = _safe_root(destination / name)
            if not path.exists():
                with path.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            if read_checked(path) != data:
                raise CatalogError("immutable_media_asset:" + name)
    finally:
        os.close(fd)


def install_runtime(
    session: Session,
    catalogue_root: Path,
    *,
    initialize_only: bool,
    media_root: Path,
) -> str:
    """Verify all bytes and provision readable assets before any DB access.

    media_root is the actual public media directory (GAME_DATA_DIR / 'media'),
    not the data-directory parent. No payload paths are reopened after checking.
    The caller must commit; provisioning failure never changes DB selection.
    """
    snapshot = verify_default(catalogue_root)
    provision_assets(snapshot, media_root)
    return install_snapshot(session, snapshot, initialize_only=initialize_only)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("initialize", "install"))
    parser.add_argument("--catalogue", type=Path, default=PACKAGED_CATALOGUE)
    args = parser.parse_args(argv)
    # Settings preserve explicit external media roots. The package location is
    # independent: an old GAME_DATA_DIR is not a replacement default catalogue.
    from app.core.config import settings
    from app.core.db import engine

    try:
        with Session(engine) as session:
            selected = install_runtime(
                session,
                args.catalogue,
                initialize_only=args.command == "initialize",
                media_root=settings.GAME_DATA_DIR / "media",
            )
            session.commit()
        sys.stdout.write(json.dumps({"release_id": selected}) + "\n")
        if args.command == "initialize":
            sys.stderr.write(
                f"Selected catalogue: {selected}. Initialization never replaces an "
                "existing selection; use 'install' for an explicit change.\n"
            )
    except (ValueError, OSError, SQLAlchemyError) as exc:
        sys.stderr.write("Runtime catalogue installation failed: " + str(exc) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
