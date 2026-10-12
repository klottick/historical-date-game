"""Conservative per-file rights and metadata checks, not legal certification."""

import re
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AwareDatetime

from app.content.schemas import SHA256, ContentModel, NonEmpty

LICENSES = {
    f"CC {kind} {version}": f"https://creativecommons.org/licenses/{slug}/{version}/"
    for kind, slug in (("BY", "by"), ("BY-SA", "by-sa"))
    for version in ("2.0", "3.0", "4.0")
}
LICENSES["CC0"] = "https://creativecommons.org/publicdomain/zero/1.0/"
# These explicit worldwide bases are narrower than a generic 'Public domain'.
PD_BASES = {"PD-old-100-expired", "PD-self", "PD-author", "PD-Art (PD-old-100-expired)"}
RISK = re.compile(
    r"\b(map|document|title[ -]?page|titled|plaque|inscription|text|caption|poster|cover|"
    r"edition|logo|trademark|nasa|sensitiv(?:e|ity)|unresolved|nudity|nude|gore|blood|violence|"
    r"execution|racist|colonial|indigenous|privacy|personality|permission required|"
    r"unidentified|uncertain|fair use|non.?free|united states only|pd-us|gfdl)\b",
    re.I,
)


class MediaCandidate(ContentModel):
    asset_id: UUID
    source_url: NonEmpty
    creator: NonEmpty
    rights_basis: NonEmpty
    attribution: NonEmpty
    license_url: NonEmpty | None
    adaptation_allowed: bool
    alt_text: NonEmpty
    fit: Literal["contain", "cover"]
    acquired_at: AwareDatetime
    source_revision: NonEmpty
    repository: NonEmpty
    download_url: NonEmpty
    upstream_sha1: str
    metadata_sha256: SHA256
    title: NonEmpty
    description: NonEmpty
    categories: tuple[str, ...]
    entity_id: NonEmpty
    relevance: NonEmpty


def date_bearing(value: str) -> bool:
    """Reject date-like metadata broadly, not just the current event's year."""
    return bool(
        re.search(
            r"(?<!\d)\d{3,}(?!\d)|\b\d+\s*(?:BC|BCE|AD|CE)\b|\b(?:hundred|thousand)\b",
            value,
            re.I,
        )
    )


def check_candidate(candidate: MediaCandidate) -> tuple[str, ...]:
    codes: set[str] = set()
    parsed = urlsplit(candidate.source_url)
    if (
        candidate.repository != "commons"
        or parsed.scheme != "https"
        or parsed.hostname != "commons.wikimedia.org"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not parsed.path.startswith("/wiki/File:")
    ):
        codes.add("non_commons_origin")
    license_url = LICENSES.get(candidate.rights_basis)
    if candidate.rights_basis not in PD_BASES and license_url is None:
        codes.add("unsupported_rights")
    if license_url and candidate.license_url != license_url:
        codes.add("license_conflict")
    if candidate.rights_basis in PD_BASES and candidate.license_url not in (
        None,
        "https://creativecommons.org/publicdomain/mark/1.0/",
    ):
        codes.add("license_conflict")
    if not candidate.adaptation_allowed:
        codes.add("adaptation_not_allowed")
    origin = urlsplit(candidate.download_url)
    if (
        origin.scheme != "https"
        or origin.hostname != "upload.wikimedia.org"
        or origin.username
        or origin.password
        or origin.port not in (None, 443)
        or not origin.path.startswith("/wikipedia/commons/")
    ):
        codes.add("non_commons_download_origin")
    if candidate.acquired_at > datetime.now(UTC):
        codes.add("invalid_acquisition_time")
    if not re.fullmatch(r"[0-9a-f]{40}", candidate.upstream_sha1):
        codes.add("missing_upstream_digest")
    visible = " ".join(
        (
            candidate.creator,
            candidate.attribution,
            candidate.alt_text,
            candidate.source_url,
        )
    )
    # A supported template's '100' is a legal duration, not a source date.
    # Preserve it in actual credits; event-specific screening checks it too.
    date_screen = (
        visible.replace(candidate.rights_basis, "")
        if candidate.rights_basis in PD_BASES
        else visible
    )
    if date_bearing(date_screen):
        codes.add("date_bearing_required_credit")
    descriptive = " ".join(
        (candidate.title, candidate.description, *candidate.categories)
    )
    if date_bearing(descriptive):
        codes.add("date_bearing_metadata")
    if RISK.search(descriptive + " " + visible):
        codes.add("unsafe_or_unresolved_metadata")
    if candidate.relevance != "source-P18-subject-context":
        codes.add("unresolved_relevance")
    # No inferred pixel/OCR safety: a narrow positive photographic description
    # must explicitly establish a simple composition. Everything else falls back.
    if not re.fullmatch(
        r"(?:Portrait photograph|Object photograph|Ship photograph) of [^.]+ against a plain background\.",
        candidate.description,
    ):
        codes.add("unresolved_visual_safety")
    if candidate.fit != "contain":
        codes.add("composition_not_preserved")
    return tuple(sorted(codes))
