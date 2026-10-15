from dataclasses import FrozenInstanceError, replace
from typing import Any
from uuid import UUID

import pytest

from app.game.ordering import generate_seed, seeded_order
from app.game.rules import eligible_ids, filter_pool, place, start_run
from app.game.types import EventKey, RuleError, RunRules, YearInput
from app.game.years import from_year_index, to_year_index

CATEGORIES = frozenset({"arts", "science", "politics"})


def event(number: int, year: int, *categories: str) -> EventKey:
    return EventKey(UUID(int=number), year, frozenset(categories or ("arts",)))


def mapping(*events: EventKey) -> dict[UUID, EventKey]:
    return {item.event_id: item for item in events}


def rules(gap: int = 1) -> RunRules:
    return RunRules(frozenset({"arts"}), -10_000, 10_000, gap)


def test_civil_years_and_inclusive_union() -> None:
    assert to_year_index(1, "BCE") == 0
    assert to_year_index(1, "CE") - to_year_index(2, "BCE") == 2
    assert from_year_index(0).value == 1
    assert from_year_index(0).era == "BCE"
    assert from_year_index(-1) == YearInput(2, "BCE")
    assert from_year_index(1) == YearInput(1, "CE")
    items = (
        event(1, -1, "arts"),
        event(2, 0, "science"),
        event(3, 1, "arts", "science"),
        event(4, 2, "politics"),
        event(5, -2, "arts"),
        event(6, 3, "science"),
    )
    selection = RunRules(frozenset({"arts", "science"}), -1, 2, 1)
    assert filter_pool(items, selection, CATEGORIES) == items[:3]


def test_all_pairs_gap_and_viable_anchor() -> None:
    items = (event(1, 1800), event(2, 1810), event(3, 1805), event(4, 1800))
    events = mapping(*items)
    order = tuple(events)
    state = start_run(events, rules(10), order)
    assert state.timeline == (order[0],)
    assert state.streak == state.revision == 0
    assert state.generation_version == 1
    assert eligible_ids(state, events) == (order[1],)
    assert state.pending_event_id == order[1]
    outcome = place(state, events, order[1], 1)
    assert outcome.correct and outcome.correct_slot == 1
    assert outcome.state.status == "won"
    assert outcome.state.streak == outcome.state.revision == 1
    # Compatibility must hold against all placed cards, not just the anchor.
    events = mapping(event(10, 0), event(11, 20), event(12, 25), event(13, 40))
    state = start_run(events, rules(10), tuple(events))
    state = place(state, events, UUID(int=11), 1).state
    assert eligible_ids(state, events) == (UUID(int=13),)
    # The first card is isolated; the compatible pair follows it in full order.
    events = mapping(event(20, 5), event(21, 0), event(22, 10))
    state = start_run(events, rules(10), tuple(events))
    assert state.timeline == (UUID(int=21),)
    assert state.pending_event_id == UUID(int=22)


def test_wrong_place_loses_without_increment() -> None:
    events = mapping(event(1, 1800), event(2, 1810), event(3, 1790))
    before = start_run(events, rules(10), tuple(events))
    wrong_outcome = place(before, events, UUID(int=2), 0)
    assert not wrong_outcome.correct
    assert wrong_outcome.revealed_event_id == UUID(int=2)
    assert wrong_outcome.correct_slot == 1
    assert wrong_outcome.state.streak == before.streak
    assert wrong_outcome.state.status == "lost"
    assert wrong_outcome.state.timeline == before.timeline
    assert wrong_outcome.state.pending_event_id is None
    assert wrong_outcome.state.revision == before.revision + 1
    assert before.status == "active" and before.pending_event_id == UUID(int=2)
    assert before.timeline == (UUID(int=1),)


def test_scan_skips_incompatible_events_until_exhaustion() -> None:
    events = mapping(
        event(1, 1800),
        event(2, 1805),
        event(3, 1810),
        event(4, 1815),
        event(5, 1820),
        event(6, 1800),
        event(7, 1900),
    )
    # The unrelated globally eligible event must never widen the frozen pool.
    order = tuple(events)[:-1]
    state = start_run(events, rules(10), order)
    assert state.pending_event_id == UUID(int=3)
    state = place(state, events, UUID(int=3), 1).state
    assert state.pending_event_id == UUID(int=5)
    state = place(state, events, UUID(int=5), 2).state
    assert state.status == "won" and state.pending_event_id is None
    assert state.streak == 2 and eligible_ids(state, events) == ()
    assert state.order == order
    assert UUID(int=7) not in state.timeline


@pytest.mark.parametrize("value", [True, False, 1.0, 0, -1, "1", None])
def test_invalid_civil_magnitude(value: Any) -> None:
    with pytest.raises(RuleError):
        to_year_index(value, "CE")
    with pytest.raises(RuleError):
        YearInput(value, "BCE")


@pytest.mark.parametrize("era", ["ce", "BC", "AD", "", 1, True, None])
def test_invalid_era(era: Any) -> None:
    with pytest.raises(RuleError):
        to_year_index(1, era)
    with pytest.raises(RuleError):
        YearInput(1, era)


@pytest.mark.parametrize("index", [True, False, 0.0, "0", None])
def test_invalid_year_index(index: Any) -> None:
    with pytest.raises(RuleError):
        from_year_index(index)


@pytest.mark.parametrize(
    "changes",
    [
        {"min_gap": True},
        {"min_gap": 1.0},
        {"min_gap": 0},
        {"min_gap": -1},
        {"start_year_index": False},
        {"end_year_index": 1.0},
        {"start_year_index": 11_000},
        {"category_ids": frozenset()},
        {"category_ids": {"arts"}},
        {"category_ids": frozenset({""})},
        {"category_ids": frozenset({1})},
    ],
)
def test_invalid_rules(changes: dict[str, Any]) -> None:
    with pytest.raises(RuleError):
        replace(rules(), **changes)


def test_filter_rejects_unknown_categories_and_malformed_pool() -> None:
    item = event(1, 1)
    for items, selection, known in (
        ((item,), replace(rules(), category_ids=frozenset({"unknown"})), CATEGORIES),
        ((event(2, 2, "unknown"),), rules(), CATEGORIES),
        ((item, item), rules(), CATEGORIES),
        ((item, event(1, 2)), rules(), CATEGORIES),
        (("not an event",), rules(), CATEGORIES),
        ([item], rules(), CATEGORIES),
        ((item,), "not rules", CATEGORIES),
        ((item,), rules(), {"arts"}),
    ):
        with pytest.raises(RuleError):
            filter_pool(items, selection, known)  # type: ignore[arg-type]
    # Same-year distinct events may be in the pool, never both in a timeline.
    assert filter_pool((item, event(2, 1)), rules(), CATEGORIES) == (item, event(2, 1))


@pytest.mark.parametrize(
    "changes",
    [
        {"event_id": "bad"},
        {"year_index": True},
        {"year_index": 1.0},
        {"category_ids": {"arts"}},
        {"category_ids": frozenset()},
    ],
)
def test_invalid_event_keys(changes: dict[str, Any]) -> None:
    with pytest.raises(RuleError):
        replace(event(1, 1), **changes)


def test_start_rejects_bad_pool_order_and_insufficient_pairs() -> None:
    a, b = event(1, 1), event(2, 2)
    events = mapping(a, b)
    for pool, selection, order in (
        (events, rules(), (a.event_id, a.event_id)),
        (events, rules(), (a.event_id, UUID(int=99))),
        (events, rules(), [a.event_id, b.event_id]),
        (events, rules(), (a.event_id, "bad")),
        ({a.event_id: b}, rules(), (a.event_id,)),
        ({a.event_id: "bad"}, rules(), (a.event_id,)),
        (events, "bad", tuple(events)),
        ("bad", rules(), (a.event_id,)),
        (events, rules(), ()),
        (events, rules(), (a.event_id,)),
        (events, rules(2), tuple(events)),
        (mapping(a, event(2, 1)), rules(), tuple(events)),
        (mapping(a, event(2, 2, "politics")), rules(), tuple(events)),
        (events, RunRules(frozenset({"arts"}), 1, 1, 1), tuple(events)),
    ):
        with pytest.raises(RuleError) as error:
            start_run(pool, selection, order)  # type: ignore[arg-type]
        assert error.value.code


@pytest.mark.parametrize("slot", [True, False, 1.0, "1", None, -1, 2])
def test_invalid_commands_leave_state_unchanged(slot: Any) -> None:
    events = mapping(event(1, 1), event(2, 2))
    state = start_run(events, rules(), tuple(events))
    before = replace(state)
    with pytest.raises(RuleError):
        place(state, events, UUID(int=2), slot)
    assert state == before


def test_stale_terminal_and_missing_event_commands() -> None:
    events = mapping(event(1, 1), event(2, 2), event(3, 3))
    state = start_run(events, rules(), tuple(events))
    for event_id in (UUID(int=1), UUID(int=3), UUID(int=99), "bad"):
        with pytest.raises(RuleError):
            place(state, events, event_id, 1)  # type: ignore[arg-type]
    for pool in ({}, {UUID(int=1): event(1, 1)}, {**events, UUID(int=2): "bad"}):
        with pytest.raises(RuleError):
            eligible_ids(state, pool)  # type: ignore[arg-type]
        with pytest.raises(RuleError):
            place(state, pool, UUID(int=2), 1)  # type: ignore[arg-type]
    lost = place(state, events, UUID(int=2), 0).state
    won = place(
        place(state, events, UUID(int=2), 1).state, events, UUID(int=3), 2
    ).state
    for terminal in (lost, won):
        before = replace(terminal)
        with pytest.raises(RuleError):
            place(terminal, events, UUID(int=2), 1)
        assert terminal == before


def test_domain_values_are_frozen() -> None:
    events = mapping(event(1, 1), event(2, 2))
    state = start_run(events, rules(), tuple(events))
    outcome = place(state, events, UUID(int=2), 1)
    for value, attribute in (
        (YearInput(1, "CE"), "value"),
        (event(1, 1), "year_index"),
        (rules(), "min_gap"),
        (state, "streak"),
        (outcome, "correct"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(value, attribute, 999)
    assert state.order == outcome.state.order
    assert outcome.state.rules == state.rules
    assert outcome.state.generation_version == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"rules": "bad"},
        {"order": [UUID(int=1), UUID(int=2)]},
        {"order": (UUID(int=1), UUID(int=1))},
        {"order": ()},
        {"timeline": ()},
        {"timeline": (UUID(int=99),)},
        {"timeline": [UUID(int=1)]},
        {"streak": True},
        {"streak": 1},
        {"status": "unknown"},
        {"revision": False},
        {"revision": 1},
        {"generation_version": 2},
        {"generation_version": True},
        {"pending_event_id": None},
        {"pending_event_id": UUID(int=1)},
        {"pending_event_id": UUID(int=99)},
        {"status": "won"},
        {"status": "lost", "revision": 1},
    ],
)
def test_malformed_state_values_are_rejected(changes: dict[str, Any]) -> None:
    events = mapping(event(1, 1), event(2, 2))
    state = start_run(events, rules(), tuple(events))
    with pytest.raises(RuleError):
        replace(state, **changes)
    assert state.status == "active" and state.streak == state.revision == 0


def test_rehydrated_state_requires_correct_timeline_and_pending_card() -> None:
    events = mapping(event(1, 1), event(2, 2), event(3, 3))
    state = start_run(events, rules(), tuple(events))
    after = place(state, events, UUID(int=2), 1).state
    malformed = (
        replace(state, pending_event_id=UUID(int=3)),
        replace(state, status="won", pending_event_id=None),
        replace(after, timeline=tuple(reversed(after.timeline))),
        "not a state",
    )
    for invalid in malformed:
        with pytest.raises(RuleError):
            eligible_ids(invalid, events)  # type: ignore[arg-type]
        with pytest.raises(RuleError):
            place(invalid, events, UUID(int=3), 2)  # type: ignore[arg-type]
    same_year = {**events, UUID(int=2): event(2, 1)}
    with pytest.raises(RuleError):
        eligible_ids(after, same_year)
    assert after.timeline == (UUID(int=1), UUID(int=2))
    assert after.streak == after.revision == 1


def test_seeded_order_known_vector_and_crypto_seed() -> None:
    ids = tuple(UUID(int=number) for number in (1, 2, 3, 4))
    assert seeded_order(ids, bytes(32)) == tuple(UUID(int=n) for n in (4, 1, 2, 3))
    first, second = generate_seed(), generate_seed()
    assert type(first) is bytes and len(first) == 32
    assert type(second) is bytes and len(second) == 32
    assert first != second


def test_uuid_bytes_break_hash_ties(monkeypatch: pytest.MonkeyPatch) -> None:
    class TiedDigest:
        def digest(self) -> bytes:
            return bytes(32)

    monkeypatch.setattr("app.game.ordering.sha256", lambda _: TiedDigest())
    ids = tuple(UUID(int=n) for n in (3, 1, 2))
    assert seeded_order(ids, bytes(32)) == tuple(UUID(int=n) for n in (1, 2, 3))


@pytest.mark.parametrize(
    ("ids", "seed"),
    [
        ((UUID(int=1), UUID(int=1)), bytes(32)),
        (("bad",), bytes(32)),
        ([UUID(int=1)], bytes(32)),
        ((), "seed"),
        ((), bytearray(32)),
        ((), b""),
    ],
)
def test_ordering_rejects_malformed_inputs(ids: Any, seed: Any) -> None:
    with pytest.raises(RuleError):
        seeded_order(ids, seed)
