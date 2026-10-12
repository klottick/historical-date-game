"""Allowlisted wire contracts, separate from private catalog and run models."""

from datetime import date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.content.schemas import CategoryRecord
from app.game.years import to_year_index


class PublicModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, revalidate_instances="always"
    )


class YearInput(PublicModel):
    value: Annotated[int, Field(gt=0)]
    era: Literal["BCE", "CE"]

    @model_validator(mode="after")
    def persistable_year_index(self) -> Self:
        # Persisted rule constraints cast indexes to PostgreSQL bigint. Bound the
        # canonical index, not the civil magnitude: BCE 2**63 + 1 is still valid.
        # This is a storage boundary, not an historical range limit on B1 math.
        index = to_year_index(self.value, self.era)
        if not -(2**63) <= index <= 2**63 - 1:
            raise ValueError("Year index must fit signed 64-bit storage")
        return self


class GameConfig(PublicModel):
    category_ids: Annotated[list[str], Field(min_length=1)]
    start: YearInput
    end: YearInput
    min_gap: Annotated[int, Field(ge=1)]

    @field_validator("category_ids")
    @classmethod
    def canonical_categories(cls, values: list[str]) -> list[str]:
        if any(not value or value.strip() != value for value in values):
            raise ValueError("Category IDs must be nonempty canonical strings")
        # Selections are sets (union), so ordering/duplicates are not new payloads.
        return sorted(set(values))


# Wire UUID strings must also validate when FastAPI has already decoded JSON.
WireUUID = Annotated[UUID, Field(strict=False)]


class FreeplayStart(PublicModel):
    operation_id: WireUUID
    catalog_release_id: Annotated[str, Field(min_length=1, max_length=128)]
    config: GameConfig


class DailyStart(PublicModel):
    operation_id: WireUUID


class PlaceCommand(PublicModel):
    operation_id: WireUUID
    expected_revision: Annotated[int, Field(ge=0)]
    event_id: WireUUID
    # Bounds depend on the frozen timeline and are checked by the engine.
    slot: int


class CreditPublic(PublicModel):
    label: str
    url: str | None


class MediaPublic(PublicModel):
    url: str
    fallback_url: str
    alt_text: str
    fit: str
    credits: list[CreditPublic]


class PendingCard(PublicModel):
    event_id: UUID
    prompt: str
    category_ids: list[str]
    media: MediaPublic


class SourcePublic(PublicModel):
    label: str
    url: str


class RevealedCard(PendingCard):
    year: YearInput
    explanation: str
    sources: list[SourcePublic]


class MoveFeedback(PublicModel):
    correct: bool
    card: RevealedCard
    correct_slot: int


class RunPublic(PublicModel):
    run_id: UUID
    mode: Literal["daily", "freeplay"]
    daily_date: date | None
    catalog_release_id: str
    config: GameConfig
    categories: list[CategoryRecord]
    status: Literal["active", "lost", "won"]
    streak: int
    revision: int
    timeline: list[RevealedCard]
    pending: PendingCard | None
    feedback: MoveFeedback | None


class GameOptions(PublicModel):
    catalog_release_id: str
    categories: list[CategoryRecord]
    start: YearInput
    end: YearInput
    registration_open: bool


class PublicConfig(PublicModel):
    registration_open: bool


class DailyOverview(PublicModel):
    day: date
    reset_at: datetime
    category_ids: list[str]
    attempt_run_id: UUID | None


class LeaderboardEntry(PublicModel):
    display_name: str
    streak: int
    status: Literal["lost", "won"]
    rank: int


class LeaderboardPublic(PublicModel):
    day: date
    entries: list[LeaderboardEntry]
