"""Offline integrity and semantic checks; not independent raw-source acceptance.

The reviewed external manifest digest is the trust anchor. All consumers use the
returned bytes/records, never reopen payload paths. Trusted local POSIX writers
are required (as for full audit publication); hostile concurrent parent-directory
replacement is outside this boundary.
"""

import hashlib
import json
import math
import os
import stat
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import unquote, urlsplit

from PIL import Image

from app.content.adapters.onthisday import (
    CATALOG_LICENSE,
    PROJECT_URL,
    TEXT_CREDIT,
    TEXT_LICENSE_URL,
)
from app.content.media import pipeline
from app.content.media.prepare import MAX_DIMENSION, MAX_PIXELS
from app.content.media.rights import LICENSES, PD_BASES, RISK, date_bearing
from app.content.publish import _beta, _safe_root, _unique, canonical
from app.content.runtime_models import BuildLock, DefaultPointer, RuntimeCatalogManifest
from app.content.schemas import (
    CategoryRecord,
    EventRecord,
    MediaCatalog,
    SourceSelection,
)
from app.content.validation import _answer_in_prompt, _http_url, validate_event

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
REQUIRED_FILES = frozenset(
    {
        "events.jsonl",
        "taxonomy.json",
        "media.json",
        "source-selection.json",
        "attribution.json",
        "build.lock.json",
        "LICENSE.catalog.txt",
        "NOTICE.catalog.md",
    }
)
PORTABLE_NOTICE = (
    "# Catalog text attribution\n\n" + TEXT_CREDIT + "\n\n"
    "Dataset author/project: " + PROJECT_URL + "\nLicense: " + TEXT_LICENSE_URL + "\n"
    "Source-input digests and historical origin are recorded in build.lock.json. "
    "Raw inputs and full audit evidence are not runtime dependencies. "
    "Citations link the source pages and their contributor histories. "
    "The dataset is pinned, not individual Wikipedia article revisions. "
    "Wikipedia does not endorse this project.\n"
)
ATTRIBUTION = {
    "schema_version": 1,
    "text_credit": TEXT_CREDIT,
    "project_url": PROJECT_URL,
    "license_url": TEXT_LICENSE_URL,
    "fallback_credit": "Historical Date Game original geometric illustrations; CC0 1.0",
}
SOURCE_RIGHTS = {
    "wikidata": "CC0 structured data",
    "wikipedia_en": "CC BY-SA 4.0 source attribution; original generated prompt, not copied extract",
    "wikipedia_onthisday": TEXT_CREDIT + " License: " + TEXT_LICENSE_URL,
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _nonfinite(value: str) -> Any:
    raise ValueError("nonfinite_json:" + value)


def _float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite_json:" + value)
    return result


def strict_json(data: bytes) -> Any:
    try:
        return json.loads(
            data,
            object_pairs_hook=_pairs,
            parse_constant=_nonfinite,
            parse_float=_float,
        )
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid_json") from exc


def _runtime_http_url(value: str) -> bool:
    """Check original spelling before URL parsing can discard controls."""
    try:
        if any(c.isspace() for c in value) or any(
            ord(c) < 32 or 127 <= ord(c) <= 159 for c in unquote(value)
        ):
            return False
        parsed = urlsplit(value)
        port = parsed.port  # Access validates numeric spelling and range.
        return (
            _http_url(value)
            and not parsed.netloc.endswith(":")
            and (port is None or port > 0)
        )
    except ValueError:
        return False


def read_checked(path: Path, *, limit: int = MAX_FILE_BYTES) -> bytes:
    """Reject links/special files before open; check the opened inode and size."""
    path = _safe_root(path)
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError("nonregular_or_linked_artifact")
        if before.st_size > limit:
            raise ValueError("artifact_size_limit")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            ):
                raise ValueError("artifact_changed_or_linked")
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        # Reads legitimately update atime; only content/identity metadata binds.
        if (
            len(data) > limit
            or len(data) != opened.st_size
            or opened.st_mtime_ns != after.st_mtime_ns
            or opened.st_ctime_ns != after.st_ctime_ns
            or opened.st_size != after.st_size
            or after.st_nlink != 1
        ):
            raise ValueError("artifact_size_or_change")
        return data
    except OSError as exc:
        raise ValueError("unreadable_artifact:" + path.name) from exc


def _entries(root: Path, expected: set[str]) -> None:
    root = _safe_root(root)
    if not root.is_dir() or {p.name for p in root.iterdir()} != expected:
        raise ValueError("unexpected_or_missing_runtime_artifact")


@dataclass(frozen=True)
class VerifiedRuntime:
    manifest_bytes: bytes
    categories: tuple[CategoryRecord, ...]
    events: tuple[EventRecord, ...]
    files: Mapping[str, bytes]
    assets: Mapping[str, bytes]

    @property
    def manifest(self) -> RuntimeCatalogManifest:
        # Frozen Pydantic models have mutable dict fields: return isolated views.
        return RuntimeCatalogManifest.model_validate_json(self.manifest_bytes)

    @property
    def media(self) -> MediaCatalog:
        return MediaCatalog.model_validate_json(self.files["media.json"])


def _media(catalog: MediaCatalog, assets: dict[str, bytes]) -> None:
    if set(catalog.fallbacks) != set(pipeline.FALLBACKS.values()):
        raise ValueError("incomplete_fallback_catalog")
    expected = {
        Path(r.filename).name: r.sha256 for r in pipeline._catalog_assets(catalog)
    }
    if {name: sha256(data) for name, data in assets.items()} != expected:
        raise ValueError("media_reference_or_integrity")
    for fallback in catalog.fallbacks.values():
        if pipeline.check_fallback(fallback, assets[Path(fallback.filename).name]):
            raise ValueError("unsafe_fallback")
    for record in catalog.records:
        if not _runtime_http_url(record.source_url) or (
            record.license_url is not None and not _runtime_http_url(record.license_url)
        ):
            raise ValueError("invalid_media_credit_url")
        source = urlsplit(record.source_url)
        if (
            source.scheme != "https"
            or source.hostname != "commons.wikimedia.org"
            or source.port not in (None, 443)
            or not source.path.startswith("/wiki/File:")
        ):
            raise ValueError("invalid_media_source_url")
        license_url = LICENSES.get(record.rights_basis)
        if (
            record.rights_basis not in PD_BASES
            and license_url is None
            or license_url
            and record.license_url != license_url
            or record.rights_basis in PD_BASES
            and record.license_url
            not in (None, "https://creativecommons.org/publicdomain/mark/1.0/")
            or not record.adaptation_allowed
            or record.fit != "contain"
        ):
            raise ValueError("unsupported_media_rights")
        visible = " ".join(
            (record.creator, record.attribution, record.alt_text, record.source_url)
        )
        screen = (
            visible.replace(record.rights_basis, "")
            if record.rights_basis in PD_BASES
            else visible
        )
        if (
            date_bearing(screen)
            or RISK.search(visible)
            or record.creator not in record.attribution
            or record.acquired_at > datetime.now(UTC)
        ):
            raise ValueError("unsafe_media_credit")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(assets[Path(record.filename).name])) as image:
                    if (
                        image.format != "WEBP"
                        or image.width * image.height > MAX_PIXELS
                        or max(image.size) > MAX_DIMENSION
                        or image.getexif()
                        or set(image.info) - {"loop", "background"}
                        or getattr(image, "n_frames", 1) != 1
                    ):
                        raise ValueError("unsafe_prepared_image")
                    image.load()
        except (
            OSError,
            Image.DecompressionBombWarning,
            Image.DecompressionBombError,
        ) as exc:
            raise ValueError("unsafe_prepared_image") from exc


def verify_runtime(
    release_dir: Path,
    media_dir: Path,
    *,
    expected_sha256: str | None = None,
    require_beta: bool = False,
) -> VerifiedRuntime:
    release_dir, media_dir = _safe_root(release_dir), _safe_root(media_dir)
    if media_dir.name != release_dir.name:
        raise ValueError("unqualified_media_directory")
    manifest_bytes = read_checked(
        release_dir / "runtime-manifest.json",
        limit=min(MAX_FILE_BYTES, MAX_MANIFEST_BYTES),
    )
    manifest_value = strict_json(manifest_bytes)
    if not isinstance(manifest_value, dict) or set(manifest_value) != set(
        RuntimeCatalogManifest.model_fields
    ):
        raise ValueError("incomplete_runtime_manifest")
    manifest = RuntimeCatalogManifest.model_validate_json(manifest_bytes)
    if expected_sha256 is not None and sha256(manifest_bytes) != expected_sha256:
        raise ValueError("manifest_integrity")
    if (
        manifest.release_id != release_dir.name
        or manifest.release_id == manifest.origin_release_id
    ):
        raise ValueError("manifest_identity_mismatch")
    if set(manifest.files) != REQUIRED_FILES:
        raise ValueError("runtime_file_allowlist")
    _entries(release_dir, set(REQUIRED_FILES) | {"runtime-manifest.json"})
    _entries(media_dir, set(manifest.media))
    if any("/" in name for name in manifest.media):
        raise ValueError("media_basename_required")
    total = len(manifest_bytes)
    files: dict[str, bytes] = {}
    assets: dict[str, bytes] = {}
    for root, expected, target in (
        (release_dir, manifest.files, files),
        (media_dir, manifest.media, assets),
    ):
        for name, digest in sorted(expected.items()):
            data = read_checked(
                root / name, limit=min(MAX_FILE_BYTES, max(0, MAX_TOTAL_BYTES - total))
            )
            total += len(data)
            if total > MAX_TOTAL_BYTES or sha256(data) != digest:
                raise ValueError("artifact_integrity_or_total_size")
            target[name] = data
    if manifest.content_sha256 != sha256(
        canonical({"files": manifest.files, "media": manifest.media})
    ):
        raise ValueError("content_digest_mismatch")
    for name in (
        "taxonomy.json",
        "media.json",
        "source-selection.json",
        "attribution.json",
        "build.lock.json",
    ):
        strict_json(files[name])
    lock = BuildLock.model_validate_json(files["build.lock.json"])
    if any(
        getattr(lock, field) != getattr(manifest, field)
        for field in (
            "release_id",
            "created_at",
            "origin_release_id",
            "origin_manifest_sha256",
        )
    ):
        raise ValueError("lock_metadata_mismatch")
    payload_sha = {
        name: digest
        for name, digest in manifest.files.items()
        if name != "build.lock.json"
    }
    payload_sha.update(
        {f"media/{name}": digest for name, digest in manifest.media.items()}
    )
    if lock.payload_sha256 != payload_sha:
        raise ValueError("lock_payload_mismatch")
    selection = SourceSelection.model_validate_json(files["source-selection.json"])
    if selection != SourceSelection.model_validate_json(
        Path(__file__).with_name("source-selection.json").read_bytes()
    ):
        raise ValueError("unsupported_source_selection")
    categories = tuple(
        CategoryRecord.model_validate_json(canonical(row))
        for row in strict_json(files["taxonomy.json"])
    )
    packaged = strict_json(Path(__file__).with_name("taxonomy.json").read_bytes())
    if sorted(
        (c.model_dump(mode="json") for c in categories), key=lambda c: c["id"]
    ) != sorted(packaged, key=lambda c: c["id"]):
        raise ValueError("taxonomy_mismatch")
    events = []
    for line in files["events.jsonl"].splitlines():
        strict_json(line)
        events.append(EventRecord.model_validate_json(line))
    _unique(events)
    if manifest.event_count != len(events):
        raise ValueError("runtime_count_mismatch")
    if require_beta:
        _beta(len(events), manifest.fixture)
    catalog = MediaCatalog.model_validate_json(files["media.json"])
    _media(catalog, assets)
    if {e.media_asset_id for e in events if e.media_asset_id is not None} != {
        r.asset_id for r in catalog.records
    }:
        raise ValueError("media_reference_closure")
    media_by_id = {record.asset_id: record for record in catalog.records}
    for event in events:
        issues = validate_event(event, categories, datetime.now(UTC).year)
        if issues or event.event_id.int == 0:
            raise ValueError("event_validation:" + ",".join(i.code for i in issues))
        if (
            event.fallback_key not in catalog.fallbacks
            or event.fallback_key != pipeline.fallback_key(event)
        ):
            raise ValueError("event_fallback_mapping")
        civil_year = event.year_index if event.year_index > 0 else 1 - event.year_index
        fallback = catalog.fallbacks[event.fallback_key]
        if _answer_in_prompt(
            event.model_copy(
                update={"prompt": fallback.alt_text + " " + fallback.creator}
            ),
            {civil_year},
        ):
            raise ValueError("date_bearing_fallback_metadata")
        if event.media_asset_id is not None:
            record = media_by_id[event.media_asset_id]
            visible = " ".join(
                (
                    record.creator,
                    record.attribution,
                    record.alt_text,
                    unquote(record.source_url),
                )
            )
            # Preserve the existing exemption for a PD template's legal duration.
            if record.rights_basis in PD_BASES:
                visible = visible.replace(record.rights_basis, "")
            if _answer_in_prompt(
                event.model_copy(update={"prompt": visible}), {civil_year}
            ):
                raise ValueError("date_bearing_event_credit_or_metadata")
        for source in event.sources:
            if not _runtime_http_url(source.url):
                raise ValueError("invalid_source_url")
            if (
                source.source_id not in selection.source_ids
                or source.rights_basis != SOURCE_RIGHTS[source.source_id]
            ):
                raise ValueError("source_selection_or_rights")
            snapshot, separator, download = source.snapshot_id.partition(";download=")
            if (
                snapshot.startswith(("/", ".", "file:"))
                or "\\" in snapshot
                or any(ord(c) < 32 for c in snapshot)
                or source.acquired_at > datetime.now(UTC)
            ):
                raise ValueError("nonportable_source_provenance")
            if separator and (
                not _runtime_http_url(download) or urlsplit(download).scheme != "https"
            ):
                raise ValueError("invalid_snapshot_download_url")
    if not manifest.fixture:
        # Fixtures can deliberately exercise non-Daily catalogues. Every
        # deployable release must satisfy the same pure gate as Daily creation.
        from app.game.daily_config import DailyConfig, daily_pool
        from app.game.types import EventKey

        try:
            daily_pool(
                tuple(
                    EventKey(e.event_id, e.year_index, frozenset(e.category_ids))
                    for e in events
                ),
                frozenset(c.id for c in categories),
                DailyConfig(tuple(selection.daily_category_ids)),
            )
        except ValueError as exc:
            raise ValueError("runtime_daily_pool_incompatible") from exc
    if (
        files["LICENSE.catalog.txt"] != CATALOG_LICENSE.encode()
        or files["NOTICE.catalog.md"] != PORTABLE_NOTICE.encode()
        or canonical(strict_json(files["attribution.json"])) != canonical(ATTRIBUTION)
    ):
        raise ValueError("catalog_text_attribution")
    return VerifiedRuntime(
        manifest_bytes,
        categories,
        tuple(events),
        MappingProxyType(files),
        MappingProxyType(assets),
    )


def verify_default(catalogue_root: Path) -> VerifiedRuntime:
    root = _safe_root(catalogue_root)
    data = read_checked(root / "default.json", limit=MAX_MANIFEST_BYTES)
    strict_json(data)
    pointer = DefaultPointer.model_validate_json(data)
    return verify_runtime(
        root / "releases" / pointer.release_id,
        root / "media" / pointer.release_id,
        expected_sha256=pointer.manifest_sha256,
        require_beta=True,
    )
