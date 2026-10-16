"""Strict portable artifact contracts, distinct from full audit releases."""

from datetime import date
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.content.schemas import SHA256, ContentModel, NonEmpty, _relative_path


def release_component(value: str) -> str:
    _relative_path(value)
    if "/" in value or value.startswith("."):
        raise ValueError("release_id_must_be_single_component")
    return value


def paths(value: dict[str, str]) -> dict[str, str]:
    for path in value:
        _relative_path(path)
    return value


class LockedSource(ContentModel):
    path: NonEmpty
    sha256: SHA256
    size: Annotated[int, Field(ge=0)]
    url: str | None
    role: Literal["chronology", "supplements"]

    _path = field_validator("path")(_relative_path)

    @field_validator("url")
    @classmethod
    def _https(cls, value: str | None) -> str | None:
        if value is not None:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 443)
                or any(c.isspace() or ord(c) < 32 for c in value)
                or parsed.fragment
            ):
                raise ValueError("locked_source_requires_https")
        return value


class BuildLock(ContentModel):
    schema_version: Annotated[int, Field(ge=1, le=1)] = 1
    recipe: Literal["catalogue-v1", "chronology-fresh-v1"] = "catalogue-v1"
    release_id: NonEmpty
    created_at: AwareDatetime
    evaluation_date: date
    origin_release_id: NonEmpty
    origin_manifest_sha256: SHA256
    python: NonEmpty
    dependencies: dict[NonEmpty, NonEmpty]
    code_sha256: dict[str, SHA256]
    sources: tuple[LockedSource, ...]
    payload_sha256: dict[str, SHA256]

    _release = field_validator("release_id", "origin_release_id")(release_component)
    _paths = field_validator("code_sha256", "payload_sha256")(paths)

    @model_validator(mode="after")
    def _closure(self) -> Self:
        if len({s.path for s in self.sources}) != len(self.sources):
            raise ValueError("duplicate_locked_source")
        if {"build.lock.json", "runtime-manifest.json"} & set(self.payload_sha256):
            raise ValueError("circular_lock_digest")
        return self


class RuntimeCatalogManifest(ContentModel):
    kind: Literal["runtime-catalogue"] = "runtime-catalogue"
    schema_version: Annotated[int, Field(ge=1, le=1)] = 1
    release_id: NonEmpty
    created_at: AwareDatetime
    fixture: bool
    event_count: Annotated[int, Field(gt=0)]
    files: dict[str, SHA256]
    media: dict[str, SHA256]
    origin_release_id: NonEmpty
    origin_manifest_sha256: SHA256
    content_sha256: SHA256

    _release = field_validator("release_id", "origin_release_id")(release_component)
    _paths = field_validator("files", "media")(paths)


class DefaultPointer(ContentModel):
    release_id: NonEmpty
    manifest_sha256: SHA256

    _release = field_validator("release_id")(release_component)
