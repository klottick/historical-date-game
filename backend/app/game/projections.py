"""Construct public fields explicitly; never dump EventRecord into a card."""

import json
from collections.abc import Mapping
from urllib.parse import quote, urlsplit
from uuid import UUID

from sqlalchemy.orm import object_session
from sqlmodel import Session

from app.content.adapters.onthisday import (
    PROJECT_URL,
    SOURCE_ID,
    TEXT_CREDIT,
    TEXT_LICENSE_URL,
    download_url,
)
from app.content.schemas import CategoryRecord, EventRecord, FallbackRecord, MediaRecord
from app.game.catalog_repository import CatalogError
from app.game.event_links import event_link_for_run
from app.game.models import DailyDefinition, GameRun
from app.game.run_repository import latest_placement, load_media
from app.game.schemas import (
    CreditPublic,
    EventLinkPublic,
    GameConfig,
    MediaPublic,
    PendingCard,
    RevealedCard,
    RunPublic,
    SourcePublic,
    YearInput,
)
from app.game.years import from_year_index


def public_year(index: int) -> YearInput:
    civil = from_year_index(index)
    return YearInput(value=civil.value, era=civil.era)


def safe_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        # Parsing alone does not validate the port, and malformed IPv6 raises.
        _ = parts.port
    except ValueError:
        raise CatalogError("catalog_unavailable")
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or any(ord(char) < 33 for char in value)
        or "\\" in value
    ):
        raise CatalogError("catalog_unavailable")
    return value


def _asset_url(base: str, filename: str) -> str:
    # Only digest-named media filenames from the typed frozen snapshots enter here.
    if base.startswith("/") and not base.startswith("//"):
        if any(char in base for char in ("\\", "?", "#")) or any(
            ord(c) < 33 for c in base
        ):
            raise CatalogError("catalog_unavailable")
    else:
        safe_url(base)
    return base.rstrip("/") + "/" + filename.removeprefix("media/")


def project_media(
    event: EventRecord,
    assets: Mapping[str, MediaRecord | FallbackRecord],
    media_base_url: str,
) -> MediaPublic:
    fallback = assets.get("fallback:" + event.fallback_key)
    if not isinstance(fallback, FallbackRecord):
        raise CatalogError("catalog_unavailable")
    fallback_url = _asset_url(media_base_url, fallback.filename)
    text_credits = (
        [
            CreditPublic(label=TEXT_CREDIT, url=PROJECT_URL),
            CreditPublic(
                label="Catalog text license: CC BY-SA 4.0", url=TEXT_LICENSE_URL
            ),
        ]
        if any(source.source_id == SOURCE_ID for source in event.sources)
        else []
    )
    if event.media_asset_id is None:
        return MediaPublic(
            url=fallback_url,
            fallback_url=fallback_url,
            alt_text=fallback.alt_text,
            fit="contain",
            credits=text_credits
            + [
                CreditPublic(
                    label=f"{fallback.creator} / {fallback.rights_basis}", url=None
                )
            ],
        )
    asset = assets.get("asset:" + str(event.media_asset_id))
    if not isinstance(asset, MediaRecord):
        raise CatalogError("catalog_unavailable")
    credits = text_credits + [
        CreditPublic(label=asset.attribution, url=safe_url(asset.source_url))
    ]
    if asset.license_url is not None:
        credits.append(
            CreditPublic(label=asset.rights_basis, url=safe_url(asset.license_url))
        )
    # Fallback artwork has its own mandatory credits, including when an image fails.
    credits.append(
        CreditPublic(label=f"{fallback.creator} / {fallback.rights_basis}", url=None)
    )
    return MediaPublic(
        url=_asset_url(media_base_url, asset.filename),
        fallback_url=fallback_url,
        alt_text=asset.alt_text,
        fit=asset.fit,
        credits=credits,
    )


def pending_card(event: EventRecord, media: MediaPublic) -> PendingCard:
    return PendingCard(
        event_id=event.event_id,
        prompt=event.prompt,
        category_ids=list(event.category_ids),
        media=media,
    )


def revealed_card(
    event: EventRecord, media: MediaPublic, *, learn_more: EventLinkPublic | None = None
) -> RevealedCard:
    return RevealedCard(
        event_id=event.event_id,
        prompt=event.prompt,
        category_ids=list(event.category_ids),
        media=media,
        year=public_year(event.year_index),
        explanation=event.explanation,
        learn_more=learn_more,
        sources=[
            SourcePublic(label=source.source_id, url=safe_url(source.url))
            for source in event.sources
        ]
        + (
            [
                SourcePublic(
                    label="Pinned chronology dataset download; original lineage retained",
                    url=download_url("events.jsonl"),
                )
            ]
            if any(source.source_id == SOURCE_ID for source in event.sources)
            else []
        ),
    )


def project_run(
    run: GameRun,
    events: Mapping[UUID, EventRecord],
    categories: tuple[CategoryRecord, ...],
    media_base_url: str,
) -> RunPublic:
    """Project an attached run using only its release-scoped frozen media.

    The exact public feedback is stored in the operation registry, not rebuilt
    from today's active release. No private generation fields leave this boundary.
    media_base_url names this run's public release media directory (not artifacts).
    """
    session = object_session(run)
    if not isinstance(session, Session):
        raise CatalogError("catalog_unavailable")
    assets = load_media(session, run.catalog_release_id)
    operation = latest_placement(session, run)
    feedback = None
    if operation is not None:
        feedback = RunPublic.model_validate_json(json.dumps(operation.outcome)).feedback
    daily_date = None
    if run.daily_definition_id is not None:
        definition = session.get(DailyDefinition, run.daily_definition_id)
        if definition is None:
            raise CatalogError("catalog_unavailable")
        daily_date = definition.day
    try:
        timeline = [
            revealed_card(
                events[UUID(id_)],
                project_media(events[UUID(id_)], assets, media_base_url),
                learn_more=event_link_for_run(session, run, events[UUID(id_)]),
            )
            for id_ in run.timeline
        ]
        pending = None
        if run.status == "active" and run.pending_event_id is not None:
            event = events[run.pending_event_id]
            pending = pending_card(event, project_media(event, assets, media_base_url))
    except KeyError:
        raise CatalogError("catalog_unavailable")
    return RunPublic(
        run_id=run.id,
        mode=run.mode,  # type: ignore[arg-type]
        daily_date=daily_date,
        catalog_release_id=run.catalog_release_id,
        config=GameConfig(
            category_ids=run.rules["category_ids"],
            start=public_year(run.rules["start_year_index"]),
            end=public_year(run.rules["end_year_index"]),
            min_gap=run.rules["min_gap"],
        ),
        categories=list(categories),
        status=run.status,  # type: ignore[arg-type]
        streak=run.streak,
        revision=run.revision,
        timeline=timeline,
        pending=pending,
        feedback=feedback,
    )


def release_media_base(release_id: str) -> str:
    return "/media/" + quote(release_id, safe="")
