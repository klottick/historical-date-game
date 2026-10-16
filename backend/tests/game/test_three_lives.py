from dataclasses import replace
from uuid import UUID

import pytest

from app.game.rules import place, start_run
from app.game.types import EventKey, RuleError, RunRules


@pytest.fixture
def pool() -> tuple[dict[UUID, EventKey], RunRules, tuple[UUID, ...]]:
    events = {
        UUID(int=n): EventKey(UUID(int=n), year, frozenset({"arts"}))
        for n, year in enumerate((-10, 0, 10, 20, 30, 40, 50, 60), start=1)
    }
    return events, RunRules(frozenset({"arts"}), -100, 100, 1), tuple(events)


def slot_for(state, events, event_id: UUID) -> int:
    return sum(events[id_].year_index < events[event_id].year_index for id_ in state.timeline)


@pytest.mark.parametrize(
    ("sequence", "correct_count", "mistakes", "lives", "streak", "status", "length"),
    [
        ("CWC", 2, 1, 2, 1, "active", 4),
        ("WW", 0, 2, 1, 0, "active", 3),
        ("WWW", 0, 3, 0, 0, "lost", 3),
    ],
)
def test_three_life_sequences(pool, sequence, correct_count, mistakes, lives, streak, status, length):
    events, rules, order = pool
    state = start_run(events, rules, order)
    final_miss = None
    for action in sequence:
        pending = state.pending_event_id
        assert pending is not None
        correct_slot = slot_for(state, events, pending)
        slot = correct_slot if action == "C" else (correct_slot + 1) % (len(state.timeline) + 1)
        if action == "W" and len(sequence) == 3 and state.mistakes == 2:
            final_miss = pending
        state = place(state, events, pending, slot).state
    assert state.correct_count == correct_count
    assert state.mistakes == mistakes
    assert state.lives_remaining == lives
    assert state.streak == streak
    assert state.status == status
    assert len(state.timeline) == length
    assert state.revision == len(sequence)
    years = [events[id_].year_index for id_ in state.timeline]
    assert years == sorted(years) and len(years) == len(set(years))
    if final_miss is not None:
        assert final_miss not in state.timeline


def test_last_eligible_miss_wins_with_life_remaining():
    events = {UUID(int=n): EventKey(UUID(int=n), n * 10, frozenset({"arts"})) for n in range(1, 3)}
    state = start_run(events, RunRules(frozenset({"arts"}), 0, 100, 1), tuple(events))
    pending = state.pending_event_id
    assert pending is not None
    result = place(state, events, pending, 0)
    assert result.state.status == "won"
    assert result.state.lives_remaining == 2
    assert result.state.timeline == (UUID(int=1), pending)
    assert result.state.correct_count == 0


def test_last_eligible_third_miss_loses():
    events = {UUID(int=n): EventKey(UUID(int=n), n * 10, frozenset({"arts"})) for n in range(1, 5)}
    state = start_run(events, RunRules(frozenset({"arts"}), 0, 100, 1), tuple(events))
    for _ in range(2):
        pending = state.pending_event_id
        assert pending is not None
        state = place(state, events, pending, 0).state
    pending = state.pending_event_id
    assert pending is not None
    state = place(state, events, pending, 0).state
    assert state.status == "lost" and state.lives_remaining == 0
    assert state.pending_event_id is None


def test_wrong_correction_participates_in_min_gap():
    events = {UUID(int=n): EventKey(UUID(int=n), year, frozenset({"arts"})) for n, year in enumerate((0, 20, 15, 30, 40), start=1)}
    rules = RunRules(frozenset({"arts"}), 0, 100, 10)
    state = start_run(events, rules, tuple(events))
    pending = state.pending_event_id
    assert pending is not None
    outcome = place(state, events, pending, 0)
    assert outcome.state.timeline == (UUID(int=1), pending)
    assert outcome.state.correct_count == 0
    assert outcome.state.pending_event_id == UUID(int=4)


def test_bce_ce_inclusive_rules_unchanged():
    events = {
        UUID(int=1): EventKey(UUID(int=1), -1, frozenset({"arts"})),
        UUID(int=2): EventKey(UUID(int=2), 0, frozenset({"arts"})),
        UUID(int=3): EventKey(UUID(int=3), 1, frozenset({"arts"})),
    }
    state = start_run(events, RunRules(frozenset({"arts"}), -1, 1, 1), tuple(events))
    assert state.timeline == (UUID(int=1),)
    assert state.pending_event_id == UUID(int=2)


def test_impossible_life_counters_rejected(pool):
    events, rules, order = pool
    state = start_run(events, rules, order)
    for changes in (
        {"mistakes": -1}, {"mistakes": True}, {"mistakes": 4},
        {"correct_count": -1}, {"correct_count": True},
        {"correct_count": 1},
        {"status": "lost", "pending_event_id": None, "mistakes": 3, "revision": 3},
    ):
        with pytest.raises(RuleError):
            replace(state, **changes)
