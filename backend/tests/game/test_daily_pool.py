"""The runtime gate and Daily service share actual game gap semantics."""

from uuid import UUID

import pytest

from app.game.daily_config import DailyConfig
from app.game.types import EventKey


@pytest.mark.parametrize(
    "years,gap,playable",
    [
        ((100, 100), 1, False),
        ((100, 101), 2, False),
        ((100, 102), 2, True),
        ((0, 1), 1, True),
    ],
)
def test_daily_pool_uses_inclusive_min_gap(
    years: tuple[int, int], gap: int, playable: bool
) -> None:
    from app.game.daily_config import daily_pool
    from app.game.rules import start_run

    events = tuple(
        EventKey(UUID(int=i + 1), year, frozenset({"inventions"}))
        for i, year in enumerate(years)
    )
    events += (EventKey(UUID(int=3), 500, frozenset({"births"})),)
    config = DailyConfig(("inventions",), min_gap=gap)
    known = frozenset({"inventions", "births"})
    if not playable:
        with pytest.raises(ValueError):
            daily_pool(events, known, config)
    else:
        rules, pool = daily_pool(events, known, config)
        assert len(pool) == 2
        assert (
            start_run(
                {e.event_id: e for e in events}, rules, tuple(e.event_id for e in pool)
            ).status
            == "active"
        )
