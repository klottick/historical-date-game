"""Install format-specifically verified, immutable private database snapshots."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from uuid import UUID

from sqlmodel import Session, select, text

from app.content.publish import verify_release
from app.content.runtime import VerifiedRuntime
from app.content.schemas import (
    CatalogManifest,
    CategoryRecord,
    EventRecord,
    MediaCatalog,
)
from app.game.models import (
    CatalogCategory,
    CatalogRelease,
    CatalogSelection,
    EventRevision,
    MediaAsset,
)


class CatalogError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CatalogOptions:
    release_id: str
    categories: tuple[CategoryRecord, ...]
    start_year_index: int
    end_year_index: int


@dataclass(frozen=True)
class _VerifiedAudit:
    manifest: CatalogManifest
    manifest_bytes: bytes
    categories: tuple[CategoryRecord, ...]
    events: tuple[EventRecord, ...]
    media: MediaCatalog


def activate_catalog(
    session: Session, release_dir: Path, media_dir: Path, *, require_beta: bool
) -> str:
    """Flush activation atomically; the caller commits its transaction.

    A transaction-scoped advisory lock serializes even the first singleton insert.
    Reuse compares exact manifest bytes, not merely release identity or row counts.
    C5 is always called, including idempotent activations and beta upgrades.
    """
    try:
        manifest = verify_release(release_dir, media_dir, require_beta=require_beta)
        manifest_bytes = (release_dir / "manifest.json").read_bytes()
        if type(manifest).model_validate_json(manifest_bytes) != manifest:
            raise CatalogError("release_changed_during_activation")
        payloads = {}
        for name in ("taxonomy.json", "events.jsonl", "media.json"):
            payload = (release_dir / name).read_bytes()
            if hashlib.sha256(payload).hexdigest() != manifest.files[name]:
                raise CatalogError("release_changed_during_activation")
            payloads[name] = payload
        categories = tuple(
            CategoryRecord.model_validate(row)
            for row in json.loads(payloads["taxonomy.json"])
        )
        events = tuple(
            EventRecord.model_validate_json(line)
            for line in payloads["events.jsonl"].splitlines()
            if line.strip()
        )
        media = MediaCatalog.model_validate_json(payloads["media.json"])
    except (ValueError, OSError, KeyError, TypeError) as exc:
        if isinstance(exc, CatalogError):
            raise
        raise CatalogError("catalog_verification_failed:" + str(exc)) from exc

    return install_snapshot(
        session, _VerifiedAudit(manifest, manifest_bytes, categories, events, media)
    )


def install_snapshot(
    session: Session,
    snapshot: VerifiedRuntime | _VerifiedAudit,
    *,
    initialize_only: bool = False,
) -> str:
    """Flush a checked snapshot atomically; caller owns commit/rollback.

    This is an internal checked-record boundary, not a file-format validator.
    Both public file installers must run their respective full verifier first.
    Return the actual selection: initialization never replaces another release.
    """
    manifest = snapshot.manifest
    manifest_bytes = snapshot.manifest_bytes
    media = snapshot.media
    with session.begin_nested():
        session.execute(text("SELECT pg_advisory_xact_lock(20261011, 2)"))
        # Serialize the empty singleton case too. Never check initialization's
        # selection before the shared advisory lock, including cached sessions.
        pointer = session.get(
            CatalogSelection, 1, populate_existing=True, with_for_update=True
        )
        existing = session.get(
            CatalogRelease, manifest.release_id, populate_existing=True
        )
        if existing is not None:
            if existing.manifest_bytes != manifest_bytes:
                raise CatalogError("immutable_release")
        if initialize_only and pointer is not None:
            return pointer.release_id
        if existing is None:
            session.add(
                CatalogRelease(
                    id=manifest.release_id,
                    manifest=manifest.model_dump(mode="json"),
                    manifest_bytes=manifest_bytes,
                    manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                    created_at=manifest.created_at,
                    event_count=manifest.event_count,
                    fixture=manifest.fixture,
                )
            )
            session.flush()
            session.add_all(
                [
                    CatalogCategory(
                        release_id=manifest.release_id,
                        category_id=r.id,
                        snapshot=r.model_dump(mode="json"),
                    )
                    for r in snapshot.categories
                ]
            )
            session.add_all(
                [
                    EventRevision(
                        release_id=manifest.release_id,
                        event_id=r.event_id,
                        snapshot=r.model_dump(mode="json"),
                    )
                    for r in snapshot.events
                ]
            )
            session.add_all(
                [
                    MediaAsset(
                        release_id=manifest.release_id,
                        key="asset:" + str(r.asset_id),
                        snapshot=r.model_dump(mode="json"),
                    )
                    for r in media.records
                ]
            )
            session.add_all(
                [
                    MediaAsset(
                        release_id=manifest.release_id,
                        key="fallback:" + key,
                        snapshot=r.model_dump(mode="json"),
                    )
                    for key, r in media.fallbacks.items()
                ]
            )
            session.flush()
        if pointer is None:
            session.add(CatalogSelection(release_id=manifest.release_id))
        else:
            pointer.release_id = manifest.release_id
            session.add(pointer)
        session.flush()
    return manifest.release_id


def load_events(session: Session, release_id: str) -> Mapping[UUID, EventRecord]:
    if session.get(CatalogRelease, release_id) is None:
        raise CatalogError("catalog_unavailable")
    rows = session.exec(
        select(EventRevision).where(EventRevision.release_id == release_id)
    ).all()
    return MappingProxyType(
        {
            r.event_id: EventRecord.model_validate_json(json.dumps(r.snapshot))
            for r in rows
        }
    )


def load_options(session: Session) -> CatalogOptions:
    pointer = session.get(CatalogSelection, 1, populate_existing=True)
    if pointer is None:
        raise CatalogError("catalog_unavailable")
    events = load_events(session, pointer.release_id)
    if not events:
        raise CatalogError("catalog_unavailable")
    categories = session.exec(
        select(CatalogCategory)
        .where(CatalogCategory.release_id == pointer.release_id)
        .order_by(CatalogCategory.category_id)
    ).all()
    years = [e.year_index for e in events.values()]
    return CatalogOptions(
        pointer.release_id,
        tuple(CategoryRecord.model_validate(r.snapshot) for r in categories),
        min(years),
        max(years),
    )
