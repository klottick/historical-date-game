"""Private artifact contracts; approved means machine-validated, never human review.

Use ``model_validate_json`` at artifact boundaries. Python inputs remain strict
(UUID/datetime/tuple instances, not coercible strings/lists). Model copies are
not a validation boundary; callers must validate newly acquired data explicitly.
"""

import re
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonEmpty = Annotated[str, Field(min_length=1, pattern=r"\S")]
CATEGORY_IDS = (
    "births",
    "deaths",
    "battles",
    "inventions",
    "literature",
    "arts",
    "exploration",
    "politics",
)


def _relative_path(value: str) -> str:
    if (
        not value
        or PurePosixPath(value).is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(character in value for character in ("\\", ":"))
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("Expected a canonical relative artifact path")
    return value


class ContentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SourceCitation(ContentModel):
    source_id: str
    record_id: str
    url: str
    rights_basis: str
    raw_date: str
    calendar: str
    acquired_at: AwareDatetime
    snapshot_id: str
    date_resolution: str


class CategoryRecord(ContentModel):
    id: NonEmpty
    label: NonEmpty


class MediaRecord(ContentModel):
    asset_id: UUID
    sha256: SHA256
    filename: str
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

    @model_validator(mode="after")
    def _digest_filename(self) -> Self:
        if self.filename != f"media/{self.sha256}.webp":
            raise ValueError("Media filename must be media/<sha256>.webp")
        return self


class FallbackRecord(ContentModel):
    key: NonEmpty
    filename: str
    sha256: SHA256
    alt_text: NonEmpty
    creator: NonEmpty
    rights_basis: NonEmpty

    @model_validator(mode="after")
    def _digest_filename(self) -> Self:
        if self.filename != f"media/{self.sha256}.svg":
            raise ValueError("Fallback filename must be media/<sha256>.svg")
        return self


class MediaCatalog(ContentModel):
    records: tuple[MediaRecord, ...]
    fallbacks: dict[str, FallbackRecord]

    @model_validator(mode="after")
    def _unique_keys(self) -> Self:
        ids = [record.asset_id for record in self.records]
        if len(set(ids)) != len(ids):
            raise ValueError("Media asset IDs must be unique")
        if any(key != record.key for key, record in self.fallbacks.items()):
            raise ValueError("Fallback mapping keys must match record keys")
        return self


class EventRecord(ContentModel):
    event_id: UUID
    identity_key: str
    prompt: str
    year_index: int
    category_ids: tuple[str, ...]
    region_ids: tuple[str, ...]
    explanation: str
    sources: tuple[SourceCitation, ...]
    date_precision: Literal["year", "month", "day"]
    review_status: Literal["pending", "quarantined", "approved"]
    media_asset_id: UUID | None
    fallback_key: str


class ValidationReceipt(ContentModel):
    event_id: UUID
    candidate_sha256: SHA256
    source_sha256: tuple[SHA256, ...]
    policy_version: NonEmpty
    stage: Literal["content", "content_media"]
    media_catalog_sha256: SHA256 | None
    passed: bool
    checked_at: AwareDatetime
    issue_codes: tuple[NonEmpty, ...]


class ValidationIssue(ContentModel):
    code: str
    field: str
    message: str


class SourceSelection(ContentModel):
    source_ids: tuple[NonEmpty, ...]
    allowed_media_hosts: tuple[NonEmpty, ...]
    decision_report: NonEmpty
    daily_category_ids: tuple[NonEmpty, ...]

    @field_validator("decision_report")
    @classmethod
    def _report_path(cls, value: str) -> str:
        return _relative_path(value)

    @model_validator(mode="after")
    def _selection(self) -> Self:
        for values in (
            self.source_ids,
            self.allowed_media_hosts,
            self.daily_category_ids,
        ):
            if not values or len(set(values)) != len(values):
                raise ValueError("Source selection lists must be nonempty and unique")
        if not set(self.daily_category_ids) <= set(CATEGORY_IDS):
            raise ValueError("Unknown daily category")
        for host in self.allowed_media_hosts:
            if len(host) > 253 or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in host.split(".")
            ):
                raise ValueError("Media allowlist requires exact lowercase DNS hosts")
        return self


class CatalogManifest(ContentModel):
    schema_version: Annotated[int, Field(ge=1, le=1)] = 1
    release_id: NonEmpty
    created_at: AwareDatetime
    event_count: Annotated[int, Field(ge=0)]
    fixture: bool
    files: dict[str, SHA256]

    @field_validator("release_id")
    @classmethod
    def _release_path(cls, value: str) -> str:
        _relative_path(value)
        if "/" in value:
            raise ValueError("Release ID must be a single path component")
        return value

    @field_validator("files")
    @classmethod
    def _artifact_paths(cls, value: dict[str, str]) -> dict[str, str]:
        for path in value:
            _relative_path(path)
        return value
