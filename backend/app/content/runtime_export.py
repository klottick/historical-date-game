"""Deterministic create-only export, gated by independent full audit verification."""

import fcntl
import os
import shutil
from pathlib import Path
from tempfile import mkdtemp

from app.content.adapters.onthisday import CATALOG_LICENSE
from app.content.build_context import locked_evaluation
from app.content.importer import _sync_directory
from app.content.media.pipeline import _catalog_assets
from app.content.publish import _safe_root, _write_bytes, canonical, verify_release
from app.content.runtime import (
    ATTRIBUTION,
    PORTABLE_NOTICE,
    read_checked,
    sha256,
    strict_json,
    verify_runtime,
)
from app.content.runtime_models import BuildLock, RuntimeCatalogManifest
from app.content.schemas import (
    CatalogManifest,
    CategoryRecord,
    EventRecord,
    MediaCatalog,
    SourceSelection,
)


def runtime_payloads(
    audit_release: Path,
    media_dir: Path,
) -> tuple[CatalogManifest, dict[str, bytes], dict[str, bytes]]:
    """Verify raw acceptance first; return portable final payloads, not evidence.

    Media keys are basenames; lock payload keys qualify them with ``media/``.
    The historical origin reference is supplied separately by the reviewed lock,
    never fabricated from a replay's fresh receipt timestamps or audit manifest.
    """
    manifest = verify_release(audit_release, media_dir)
    checked = {}
    for name in (
        "events.jsonl",
        "taxonomy.json",
        "media.json",
        "source-selection.json",
    ):
        data = read_checked(audit_release / name)
        if sha256(data) != manifest.files[name]:
            raise ValueError("audit_changed_after_verification")
        checked[name] = data
    events = [
        EventRecord.model_validate_json(line)
        for line in checked["events.jsonl"].splitlines()
    ]
    categories = [
        CategoryRecord.model_validate_json(canonical(row))
        for row in strict_json(checked["taxonomy.json"])
    ]
    catalog = MediaCatalog.model_validate_json(checked["media.json"])
    selection = SourceSelection.model_validate_json(checked["source-selection.json"])
    media_payload = catalog.model_dump(mode="json")
    media_payload["records"].sort(key=lambda r: r["asset_id"])
    files = {
        "events.jsonl": b"".join(
            canonical(e.model_dump(mode="json"))
            for e in sorted(events, key=lambda e: str(e.event_id))
        ),
        "taxonomy.json": canonical(
            [c.model_dump(mode="json") for c in sorted(categories, key=lambda c: c.id)]
        ),
        "media.json": canonical(media_payload),
        "source-selection.json": canonical(selection.model_dump(mode="json")),
        "attribution.json": canonical(ATTRIBUTION),
        "LICENSE.catalog.txt": CATALOG_LICENSE.encode(),
        "NOTICE.catalog.md": PORTABLE_NOTICE.encode(),
    }
    assets = {}
    for record in _catalog_assets(catalog):
        name = Path(record.filename).name
        data = read_checked(media_dir / name)
        if sha256(data) != record.sha256:
            raise ValueError("audit_asset_changed_after_verification")
        assets[name] = data
    return manifest, dict(sorted(files.items())), dict(sorted(assets.items()))


def export_runtime(
    audit_release: Path,
    media_dir: Path,
    catalogue_root: Path,
    lock: BuildLock,
) -> RuntimeCatalogManifest:
    # Revalidate even model_copy/constructed Python instances at the boundary.
    lock = BuildLock.model_validate_json(canonical(lock.model_dump(mode="json")))
    # The lock-bearing standalone API owns this scope too, not only replay.
    # Unrelated new acquisitions/audits retain their current-date default.
    with locked_evaluation(lock.evaluation_date):
        audit, files, assets = runtime_payloads(audit_release, media_dir)
    if lock.release_id in {audit.release_id, lock.origin_release_id}:
        raise ValueError("runtime_requires_new_release_id")
    digests = {name: sha256(data) for name, data in files.items()}
    digests.update({f"media/{name}": sha256(data) for name, data in assets.items()})
    if digests != lock.payload_sha256:
        raise ValueError("locked_payload_mismatch")
    files["build.lock.json"] = canonical(lock.model_dump(mode="json"))
    file_sha = {name: sha256(data) for name, data in sorted(files.items())}
    asset_sha = {name: sha256(data) for name, data in sorted(assets.items())}
    manifest = RuntimeCatalogManifest(
        release_id=lock.release_id,
        created_at=lock.created_at,
        fixture=audit.fixture,
        event_count=audit.event_count,
        files=file_sha,
        media=asset_sha,
        origin_release_id=lock.origin_release_id,
        origin_manifest_sha256=lock.origin_manifest_sha256,
        content_sha256=sha256(canonical({"files": file_sha, "media": asset_sha})),
    )
    root = _safe_root(catalogue_root)
    root.mkdir(parents=True, exist_ok=True)
    # Lock the root inode: no extra persistent lock artifact enters the bundle.
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        release = _safe_root(root / "releases" / lock.release_id)
        media = _safe_root(root / "media" / lock.release_id)
        if release.exists() or media.exists():
            raise ValueError("immutable_runtime_exists")
        temporary = Path(mkdtemp(prefix=".runtime-", dir=root))
        try:
            staged_release = temporary / "releases" / lock.release_id
            staged_media = temporary / "media" / lock.release_id
            for name, data in files.items():
                _write_bytes(staged_release / name, data)
            for name, data in assets.items():
                _write_bytes(staged_media / name, data)
            _write_bytes(
                staged_release / "runtime-manifest.json",
                canonical(manifest.model_dump(mode="json")),
            )
            verify_runtime(staged_release, staged_media)
            _sync_directory(staged_release)
            _sync_directory(staged_media)
            release.parent.mkdir(parents=True, exist_ok=True)
            media.parent.mkdir(parents=True, exist_ok=True)
            if release.exists() or media.exists():
                raise ValueError("immutable_runtime_exists")
            # Assets become visible first; a release is never exposed incomplete.
            # A failure between renames can leave harmless unselected assets.
            staged_media.rename(media)
            _sync_directory(media.parent)
            staged_release.rename(release)
            _sync_directory(release.parent)
            _sync_directory(root)
        finally:
            shutil.rmtree(temporary)
    finally:
        os.close(fd)
    return manifest
