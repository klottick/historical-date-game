"""Synthetic private filesystem bindings for rollout tests, never live evidence."""

import hashlib
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app.core.config import settings
from tests.browser import three_lives_local_rollout as rollout


@contextmanager
def synthetic_rollout_sources() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="hdg-rollout-synthetic-") as temporary:
        root = Path(temporary)
        release = root / "data/game/releases/synthetic-rollout"
        runtime = root / "data/game/local-catalog-runtime"
        for directory in (release, runtime):
            directory.mkdir(parents=True, mode=0o700)
        files = {
            release / "catalog.json": b'{"fixture":true,"events":["synthetic"]}',
            runtime
            / "media.svg": b'<svg xmlns="http://www.w3.org/2000/svg"><title>Synthetic</title></svg>',
            root / "event-links.json": b'{"fixture":true,"links":[]}',
        }
        for path, content in files.items():
            path.write_bytes(content)
            path.chmod(0o600)
        for directory in root.rglob("*"):
            if directory.is_dir():
                directory.chmod(0o700)
        sidecar = root / "event-links.json"
        digest = hashlib.sha256(sidecar.read_bytes()).hexdigest()
        with (
            patch.multiple(
                rollout,
                ORIGINAL_LIVE=root,
                ORIGINAL_RELEASE_ID="synthetic-rollout",
                ORIGINAL_SIDECAR=sidecar,
                ORIGINAL_SIDECAR_SHA256=digest,
            ),
            patch.multiple(
                settings, GAME_EVENT_LINKS_FILE=sidecar, GAME_EVENT_LINKS_SHA256=digest
            ),
        ):
            yield root
