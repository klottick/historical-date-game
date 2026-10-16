from collections.abc import Mapping
from itertools import pairwise
from uuid import UUID

from app.game.types import (
    EventKey,
    PlacementOutcome,
    RuleError,
    RunRules,
    RunState,
    require_categories,
    require_ids,
    require_integer,
)


def _require_rules(rules: RunRules) -> None:
    if not isinstance(rules, RunRules):
        raise RuleError("invalid_rules")


def _require_events(events: Mapping[UUID, EventKey]) -> None:
    if not isinstance(events, Mapping):
        raise RuleError("invalid_pool")
    for id_, event in events.items():
        if not isinstance(event, EventKey) or id_ != event.event_id:
            raise RuleError("invalid_pool")


def _matches(event: EventKey, rules: RunRules) -> bool:
    return rules.start_year_index <= event.year_index <= rules.end_year_index and bool(
        event.category_ids & rules.category_ids
    )


def filter_pool(
    events: tuple[EventKey, ...],
    rules: RunRules,
    known_categories: frozenset[str],
) -> tuple[EventKey, ...]:
    _require_rules(rules)
    require_categories(known_categories, "invalid_categories")
    if not rules.category_ids <= known_categories:
        raise RuleError("unknown_category")
    if not isinstance(events, tuple):
        raise RuleError("invalid_pool")
    seen: set[UUID] = set()
    for event in events:
        if not isinstance(event, EventKey) or event.event_id in seen:
            raise RuleError("invalid_pool")
        if not event.category_ids <= known_categories:
            raise RuleError("unknown_category")
        seen.add(event.event_id)
    return tuple(event for event in events if _matches(event, rules))


def _require_pool(
    events: Mapping[UUID, EventKey], rules: RunRules, order: tuple[UUID, ...]
) -> None:
    _require_rules(rules)
    _require_events(events)
    require_ids(order, "invalid_order")
    for id_ in order:
        if id_ not in events or not _matches(events[id_], rules):
            raise RuleError("invalid_pool")


def _eligible(
    order: tuple[UUID, ...],
    timeline: tuple[UUID, ...],
    events: Mapping[UUID, EventKey],
    gap: int,
) -> tuple[UUID, ...]:
    used = set(timeline)
    return tuple(
        id_
        for id_ in order
        if id_ not in used
        and all(
            abs(events[id_].year_index - events[placed].year_index) >= gap
            for placed in timeline
        )
    )


def start_run(
    events: Mapping[UUID, EventKey], rules: RunRules, order: tuple[UUID, ...]
) -> RunState:
    """Freeze exactly this prefiltered pool and choose its first viable anchor."""
    _require_pool(events, rules, order)
    for anchor in order:
        timeline = (anchor,)
        eligible = _eligible(order, timeline, events, rules.min_gap)
        if eligible:
            return RunState(rules, order, timeline, eligible[0], 0, 0, 0, "active", 0)
    raise RuleError("insufficient_pool")


def eligible_ids(state: RunState, events: Mapping[UUID, EventKey]) -> tuple[UUID, ...]:
    if not isinstance(state, RunState):
        raise RuleError("invalid_state")
    _require_pool(events, state.rules, state.order)
    years = tuple(events[id_].year_index for id_ in state.timeline)
    # In a sorted timeline, adjacent gaps imply the required all-pairs gap.
    if any(right - left < state.rules.min_gap for left, right in pairwise(years)):
        raise RuleError("invalid_state")
    eligible = _eligible(state.order, state.timeline, events, state.rules.min_gap)
    if state.status == "active" and (
        not eligible or state.pending_event_id != eligible[0]
    ):
        raise RuleError("invalid_state")
    if state.status == "won" and eligible:
        raise RuleError("invalid_state")
    return eligible


def place(
    state: RunState, events: Mapping[UUID, EventKey], event_id: UUID, slot: int
) -> PlacementOutcome:
    if not isinstance(state, RunState):
        raise RuleError("invalid_state")
    if state.status != "active":
        raise RuleError("terminal_state")
    eligible_ids(state, events)
    if not isinstance(event_id, UUID) or event_id != state.pending_event_id:
        raise RuleError("stale_event")
    position = require_integer(slot, "invalid_slot")
    if not 0 <= position <= len(state.timeline):
        raise RuleError("invalid_slot")
    correct_slot = sum(
        events[placed].year_index < events[event_id].year_index
        for placed in state.timeline
    )
    if position != correct_slot:
        mistakes = state.mistakes + 1
        if mistakes == 3:
            lost = RunState(
                state.rules,
                state.order,
                state.timeline,
                None,
                0,
                mistakes,
                state.correct_count,
                "lost",
                state.revision + 1,
                state.generation_version,
            )
            return PlacementOutcome(lost, False, event_id, correct_slot)
        corrected = (
            state.timeline[:correct_slot] + (event_id,) + state.timeline[correct_slot:]
        )
        eligible = _eligible(state.order, corrected, events, state.rules.min_gap)
        corrected_state = RunState(
            state.rules,
            state.order,
            corrected,
            eligible[0] if eligible else None,
            0,
            mistakes,
            state.correct_count,
            "active" if eligible else "won",
            state.revision + 1,
            state.generation_version,
        )
        return PlacementOutcome(corrected_state, False, event_id, correct_slot)
    timeline = state.timeline[:position] + (event_id,) + state.timeline[position:]
    eligible = _eligible(state.order, timeline, events, state.rules.min_gap)
    next_state = RunState(
        state.rules,
        state.order,
        timeline,
        eligible[0] if eligible else None,
        state.streak + 1,
        state.mistakes,
        state.correct_count + 1,
        "active" if eligible else "won",
        state.revision + 1,
        state.generation_version,
    )
    return PlacementOutcome(next_state, True, event_id, correct_slot)
