from itertools import combinations, product
from uuid import UUID

import pytest

from app.game.ordering import seeded_order
from app.game.rules import eligible_ids, filter_pool, place, start_run
from app.game.types import EventKey, RuleError, RunRules
from app.game.years import from_year_index, to_year_index


def test_year_round_trips_across_civil_boundary() -> None:
    for index in range(-500, 501):
        civil = from_year_index(index)
        assert civil.value > 0
        assert to_year_index(civil.value, civil.era) == index


def test_seeded_frozen_pool_invariants() -> None:
    events = tuple(
        EventKey(UUID(int=n + 1), year, frozenset(categories))
        for n, (year, categories) in enumerate(
            [
                (-11, ("arts",)),
                (-5, ("science",)),
                (-1, ("arts", "science")),
                (0, ("arts",)),
                (1, ("science",)),
                (1, ("arts",)),
                (5, ("arts", "science")),
                (11, ("science",)),
                (20, ("arts",)),
            ]
        )
    )
    known = frozenset({"arts", "science"})
    global_events = {e.event_id: e for e in events}
    # An always-eligible global card is never allowed to extend a frozen run.
    outsider = EventKey(UUID(int=100), 1000, frozenset({"arts", "science"}))
    global_events[outsider.event_id] = outsider
    cases = product(
        (frozenset({"arts"}), frozenset({"science"}), known),
        ((-11, 20), (-5, 5), (0, 20)),
        (1, 2, 6, 12),
        range(5),
    )
    successful_runs = 0
    for categories, (start, end), gap, seed_number in cases:
        selection = RunRules(categories, start, end, gap)
        pool = filter_pool(events, selection, known)
        expected_pool = tuple(
            e
            for e in events
            if start <= e.year_index <= end and e.category_ids & categories
        )
        assert pool == expected_pool
        seed = seed_number.to_bytes(32)
        ids = tuple(e.event_id for e in pool)
        order = seeded_order(ids, seed)
        assert seeded_order(tuple(reversed(ids)), seed) == order
        assert seeded_order(ids[1:] + ids[:1], seed) == order
        has_pair = any(
            abs(a.year_index - b.year_index) >= gap for a, b in combinations(pool, 2)
        )
        if not has_pair:
            with pytest.raises(RuleError):
                start_run(global_events, selection, order)
            continue
        successful_runs += 1
        state = start_run(global_events, selection, order)
        assert state.streak == 0 and len(state.timeline) == 1
        assert state.correct_count == state.mistakes == 0
        permuted = dict(reversed(tuple(global_events.items())))
        assert start_run(permuted, selection, order) == state
        assert all(id_ in ids for id_ in state.timeline)
        while state.status == "active":
            eligible = tuple(
                id_
                for id_ in order
                if id_ not in state.timeline
                and all(
                    abs(
                        global_events[id_].year_index - global_events[placed].year_index
                    )
                    >= gap
                    for placed in state.timeline
                )
            )
            assert eligible_ids(state, global_events) == eligible
            assert state.pending_event_id == eligible[0]
            pending = state.pending_event_id
            slot = sum(
                global_events[id_].year_index < global_events[pending].year_index
                for id_ in state.timeline
            )
            wrong = place(
                state, global_events, pending, (slot + 1) % (len(state.timeline) + 1)
            )
            assert not wrong.correct and wrong.state.status in {"active", "won"}
            assert wrong.state.mistakes == state.mistakes + 1
            assert pending in wrong.state.timeline
            assert wrong.state.correct_count == state.correct_count
            outcome = place(state, global_events, pending, slot)
            assert outcome.correct and outcome.correct_slot == slot
            assert outcome.state.streak == state.streak + 1
            assert outcome.state.correct_count == state.correct_count + 1
            assert outcome.state.mistakes == state.mistakes
            assert outcome.state.revision == state.revision + 1
            assert place(state, permuted, pending, slot) == outcome
            state = outcome.state
            assert state.order == order and state.rules == selection
            assert state.generation_version == 1
            assert set(state.timeline) <= set(ids)
            years = [global_events[id_].year_index for id_ in state.timeline]
            assert years == sorted(years) and len(years) == len(set(years))
            assert len(state.timeline) == len(set(state.timeline))
            assert all(abs(a - b) >= gap for a, b in combinations(years, 2))
        assert state.status == "won" and state.pending_event_id is None
        assert eligible_ids(state, global_events) == ()
        assert not any(
            id_ not in state.timeline
            and all(
                abs(global_events[id_].year_index - global_events[placed].year_index)
                >= gap
                for placed in state.timeline
            )
            for id_ in order
        )
        assert outsider.event_id not in state.timeline
    assert successful_runs == 160


def test_run_has_no_hundred_placement_cap() -> None:
    events = {
        UUID(int=n + 1): EventKey(UUID(int=n + 1), n * 10 - 600, frozenset({"arts"}))
        for n in range(125)
    }
    selection = RunRules(frozenset({"arts"}), -600, 640, 10)
    order = seeded_order(tuple(events), bytes(32))
    state = start_run(events, selection, order)
    while state.status == "active":
        pending = state.pending_event_id
        assert pending is not None
        slot = sum(
            events[id_].year_index < events[pending].year_index
            for id_ in state.timeline
        )
        state = place(state, events, pending, slot).state
        if state.streak == 100:
            assert state.status == "active"
    assert state.status == "won" and state.streak == state.correct_count == state.revision == 124
    assert len(state.timeline) == 125
