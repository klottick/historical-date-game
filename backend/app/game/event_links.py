"""Process-cached supplemental metadata. No request-path reads or acquisition."""

import hashlib
import json
from pathlib import Path

from sqlmodel import Session

from app.content.adapters.onthisday import _json
from app.content.event_links import EventLinksFile, source_link
from app.content.schemas import EventRecord
from app.core.config import settings
from app.game.models import CatalogRelease, GameRun
from app.game.schemas import EventLinkPublic


def load_event_links(file: Path | None, sha256: str | None) -> EventLinksFile | None:
    if file is None or sha256 is None:
        return None
    try:
        if (
            any(p.is_symlink() for p in (file, *file.parents))
            or file.stat().st_size > 32 * 1024 * 1024
        ):
            return None
        body = file.read_bytes()
        if hashlib.sha256(body).hexdigest() != sha256:
            return None
        # Reject duplicate keys before Pydantic's JSON decoder can collapse them.
        value = _json(body)
        return EventLinksFile.model_validate_json(json.dumps(value))
    except ValueError, OSError, TypeError, RecursionError:
        return None


_links = load_event_links(
    settings.GAME_EVENT_LINKS_FILE, settings.GAME_EVENT_LINKS_SHA256
)


def link_for_event(
    event: EventRecord, release_id: str, manifest_sha256: str
) -> EventLinkPublic | None:
    record = None
    if (
        _links is not None
        and _links.release_id == release_id
        and _links.manifest_sha256 == manifest_sha256
    ):
        record = _links.records.get(event.event_id)
        if record is not None and record.source_url not in {
            source.url for source in event.sources
        }:
            record = None
    if record is None:
        record = source_link(event, "enrichment_unavailable")
    if record is None:
        return None
    return EventLinkPublic(kind=record.kind, label=record.label, url=record.url)


def event_link_for_run(
    session: Session, run: GameRun, event: EventRecord
) -> EventLinkPublic | None:
    release = session.get(CatalogRelease, run.catalog_release_id)
    return link_for_event(
        event, run.catalog_release_id, release.manifest_sha256 if release else ""
    )
