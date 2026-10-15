"""Hosted disposable Playwright provision only; never normal application startup.

Imports stay stdlib-only until the exact hosted endpoint guard succeeds. The
existing ownership-comment guard creates a new absent database, and the existing
fixture builder performs C3/C4/C5 verification and activation. No live catalog.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

DATABASE = "historical_date_game_guest_fixture_test"


def require_ci_target(environment: Mapping[str, str]) -> None:
    required = {
        "GITHUB_ACTIONS": "true",
        "HDG_CI_DISPOSABLE": "true",
        "POSTGRES_DB": DATABASE,
        "POSTGRES_SERVER": "127.0.0.1",
        "POSTGRES_PORT": "5433",
        "ENVIRONMENT": "local",
        "HDG_VERIFICATION_PROFILE": "guest",
    }
    if any(environment.get(key) != value for key, value in required.items()):
        raise RuntimeError("CI fixture requires the exact hosted disposable endpoint")


def compose_override(public_media: Path) -> dict:
    if not public_media.is_absolute() or public_media.name != "media":
        raise RuntimeError("Absolute public media directory required")
    if any(path.is_symlink() for path in (public_media, *public_media.parents)):
        raise RuntimeError("Public fixture mount must not traverse symlinks")
    return {
        "services": {
            # The official image creates only its maintenance DB. The fixture DB
            # must be absent until the ownership guard creates/comments it.
            "db": {
                "environment": {"POSTGRES_DB": "postgres"},
                "healthcheck": {
                    "test": ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d postgres"]
                },
            },
            "prestart": {"environment": {"POSTGRES_PORT": "5432"}},
            "backend": {
                "environment": {
                    "POSTGRES_PORT": "5432",
                    "GAME_DATA_DIR": "/browser-game",
                },
                "volumes": [
                    {
                        "type": "bind",
                        "source": str(public_media),
                        "target": "/browser-game/media",
                        "read_only": True,
                        "bind": {"create_host_path": False},
                    }
                ],
            },
        }
    }


def verify_public_media(
    public_media: Path, release_id: str, files: Mapping[str, str]
) -> int:
    expected = {
        name.removeprefix("media/"): digest
        for name, digest in files.items()
        if name.startswith("media/")
    }
    release = public_media / release_id
    if (
        not expected
        or any(path.is_symlink() for path in (public_media, *public_media.parents))
        or release.is_symlink()
        or not release.is_dir()
        or {path.name for path in public_media.iterdir()} != {release_id}
        or {path.name for path in release.iterdir()} != set(expected)
    ):
        raise RuntimeError("Unexpected public fixture projection")
    for name, digest in expected.items():
        asset = release / name
        if (
            not re.fullmatch(r"[0-9a-f]{64}\.(svg|webp)", name)
            or asset.is_symlink()
            or not asset.is_file()
            or asset.stem != digest
            or hashlib.sha256(asset.read_bytes()).hexdigest() != digest
        ):
            raise RuntimeError(
                "Public fixture asset failed opaque-name/hash verification"
            )
    return len(expected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["configure", "prepare"])
    parser.add_argument("--compose-override", type=Path)
    args = parser.parse_args()
    require_ci_target(os.environ)
    from tests.browser.guest_test_environment import (
        browser_target,
        prepare_database,
        require_owned_guest_database,
        run_migration,
        seed_browser,
    )

    runtime = browser_target("fixture")["runtime"]
    configuration = compose_override(runtime / "media")
    if args.command == "configure":
        if args.compose_override is None:
            raise RuntimeError("Runner-only Compose override path required")
        # Create-only, outside both build contexts. Only public media is mounted.
        with args.compose_override.open("x") as output:
            json.dump(configuration, output)
        return
    if runtime.exists():
        raise RuntimeError("Fresh CI runtime required; refusing existing fixture state")
    if not prepare_database(DATABASE):
        raise RuntimeError(
            "Fresh CI database required; refusing even an owned existing DB"
        )
    require_owned_guest_database(DATABASE)
    run_migration(DATABASE, "upgrade", "head")
    seed_browser("fixture", None)
    seed = json.loads((runtime / "seed.json").read_text())
    if seed["events"] != 8 or seed["database"] != DATABASE:
        raise RuntimeError("Eight-event owned synthetic fixture required")
    assets = verify_public_media(runtime / "media", seed["release_id"], seed["files"])
    require_owned_guest_database(DATABASE)
    sys.stdout.write(
        f"CI synthetic catalog verified/activated; {assets} matching public assets; owned DB\n"
    )


if __name__ == "__main__":
    main()
