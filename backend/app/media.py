"""Serve only immutable, opaque game assets, never catalogs or directory indexes.

Provision this tree read-only. No symlinks (even in-tree aliases) are accepted.
The publisher retains each release's SVG fallbacks and sanitized WebP pictures.
"""

import os
import re
from pathlib import Path

from starlette.staticfiles import StaticFiles


class GameMediaFiles(StaticFiles):
    def __init__(self, directory: Path) -> None:
        super().__init__(directory=directory, check_dir=False, follow_symlink=False)

    async def check_config(self) -> None:
        # Missing local content is allowed at startup and simply returns 404.
        # lookup_path applies the security boundary on every request.
        return None

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        if not re.fullmatch(r"[^/\\\x00-\x20]+/[0-9a-f]{64}\.(?:svg|webp)", path):
            return "", None
        release_id, _ = path.split("/")
        if release_id in {".", ".."}:
            return "", None
        assert self.directory is not None
        target = Path(self.directory).absolute() / path
        # StaticFiles' containment check alone permits in-tree symlinks and a
        # symlink mount root. Refuse every component, including root ancestors.
        if any(component.is_symlink() for component in (target, *target.parents)):
            return "", None
        return super().lookup_path(path)
