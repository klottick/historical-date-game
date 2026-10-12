from dataclasses import dataclass
from typing import Literal
from uuid import UUID


class RuleError(ValueError):
    """A rejected setting or command; callers may safely expose its code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def require_integer(value: object, code: str) -> int:
    if type(value) is not int:
        raise RuleError(code)
    return value


def require_categories(value: object, code: str) -> None:
    if not isinstance(value, frozenset) or not value:
        raise RuleError(code)
    if any(type(item) is not str or not item or item.strip() != item for item in value):
        raise RuleError(code)


def require_ids(value: object, code: str) -> None:
    if not isinstance(value, tuple) or any(not isinstance(id_, UUID) for id_ in value):
        raise RuleError(code)
    if len(set(value)) != len(value):
        raise RuleError(code)


@dataclass(frozen=True)
class YearInput:
    value: int
    era: Literal["BCE", "CE"]

    def __post_init__(self) -> None:
        if require_integer(self.value, "invalid_year") <= 0:
            raise RuleError("invalid_year")
        if type(self.era) is not str or self.era not in ("BCE", "CE"):
            raise RuleError("invalid_era")


@dataclass(frozen=True)
class EventKey:
    event_id: UUID
    year_index: int
    category_ids: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, UUID):
            raise RuleError("invalid_event")
        require_integer(self.year_index, "invalid_event")
        require_categories(self.category_ids, "invalid_event")


@dataclass(frozen=True)
class RunRules:
    category_ids: frozenset[str]
    start_year_index: int
    end_year_index: int
    min_gap: int

    def __post_init__(self) -> None:
        require_categories(self.category_ids, "invalid_rules")
        start = require_integer(self.start_year_index, "invalid_rules")
        end = require_integer(self.end_year_index, "invalid_rules")
        gap = require_integer(self.min_gap, "invalid_rules")
        if start > end or gap < 1:
            raise RuleError("invalid_rules")


@dataclass(frozen=True)
class RunState:
    rules: RunRules
    order: tuple[UUID, ...]
    timeline: tuple[UUID, ...]
    pending_event_id: UUID | None
    streak: int
    status: Literal["active", "lost", "won"]
    revision: int
    generation_version: Literal[1] = 1

    def __post_init__(self) -> None:
        if not isinstance(self.rules, RunRules):
            raise RuleError("invalid_state")
        require_ids(self.order, "invalid_state")
        require_ids(self.timeline, "invalid_state")
        if not self.timeline or not set(self.timeline) <= set(self.order):
            raise RuleError("invalid_state")
        streak = require_integer(self.streak, "invalid_state")
        revision = require_integer(self.revision, "invalid_state")
        if streak != len(self.timeline) - 1 or self.status not in (
            "active",
            "lost",
            "won",
        ):
            raise RuleError("invalid_state")
        if revision != streak + (self.status == "lost"):
            raise RuleError("invalid_state")
        if require_integer(self.generation_version, "invalid_generation") != 1:
            raise RuleError("invalid_generation")
        if self.status == "active":
            if (
                not isinstance(self.pending_event_id, UUID)
                or self.pending_event_id not in self.order
                or self.pending_event_id in self.timeline
            ):
                raise RuleError("invalid_state")
        elif self.pending_event_id is not None:
            raise RuleError("invalid_state")


@dataclass(frozen=True)
class PlacementOutcome:
    state: RunState
    correct: bool
    revealed_event_id: UUID
    correct_slot: int
