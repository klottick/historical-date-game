"""Validate the packaged Vite entry and complete static/dynamic asset closure."""

import json
from pathlib import Path

from app.content.runtime import read_checked


def check_frontend(root: Path) -> None:
    html = read_checked(root / "index.html").decode()
    manifest = json.loads(read_checked(root / ".vite/manifest.json"))
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError("frontend_manifest_not_ready")
    entry = manifest.get("index.html")
    if not isinstance(entry, dict) or entry.get("isEntry") is not True:
        raise ValueError("frontend_entry_not_ready")
    files = set()
    for record in manifest.values():
        if not isinstance(record, dict) or not isinstance(record.get("file"), str):
            raise ValueError("frontend_manifest_not_ready")
        files.add(record["file"])
        for field in ("imports", "dynamicImports", "css", "assets"):
            values = record.get(field, [])
            if not isinstance(values, list) or not all(
                isinstance(item, str) for item in values
            ):
                raise ValueError("frontend_manifest_not_ready")
            if field in {"imports", "dynamicImports"}:
                if any(item not in manifest for item in values):
                    raise ValueError("frontend_dependency_not_ready")
            else:
                files.update(values)
    if entry["file"] not in html:
        raise ValueError("frontend_entry_not_ready")
    for name in files:
        if (
            not name.startswith("assets/")
            or any(part in {"", ".", ".."} for part in name.split("/"))
            or "\\" in name
        ):
            raise ValueError("frontend_asset_path_not_ready")
        if not read_checked(root / name):
            raise ValueError("frontend_asset_not_ready")
