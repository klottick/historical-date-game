"""Fixed, machine-approved Daily selection; never infer an all-category default."""

from dataclasses import dataclass
from importlib.resources import files

from app.content.schemas import CATEGORY_IDS, SourceSelection
from app.game.rules import filter_pool, start_run
from app.game.types import EventKey, RunRules


@dataclass(frozen=True)
class DailyConfig:
    category_ids: tuple[str, ...]
    min_gap: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.category_ids) is not tuple
            or not self.category_ids
            or any(
                type(value) is not str or value not in CATEGORY_IDS
                for value in self.category_ids
            )
            or len(set(self.category_ids)) != len(self.category_ids)
            or type(self.min_gap) is not int
            or self.min_gap < 1
        ):
            raise ValueError("Invalid Daily configuration")


def load_daily_config() -> DailyConfig:
    selection = SourceSelection.model_validate_json(
        files("app.game").joinpath("source-selection.json").read_bytes()
    )
    return DailyConfig(tuple(selection.daily_category_ids), min_gap=1)


def daily_pool(
    events: tuple[EventKey, ...], known: frozenset[str], config: DailyConfig
) -> tuple[RunRules, tuple[EventKey, ...]]:
    """Pure deployability gate shared by runtime verification and Daily creation.

    Exercise the game rules themselves: a proper category selection alone does
    not imply a nonempty proper event subset or an anchor with a playable pair.
    """
    config = DailyConfig(config.category_ids, config.min_gap)
    categories = frozenset(config.category_ids)
    selected = tuple(event for event in events if event.category_ids & categories)
    if not categories < known or not selected or len(selected) == len(events):
        raise ValueError("invalid_daily_pool")
    rules = RunRules(
        categories,
        min(event.year_index for event in selected),
        max(event.year_index for event in selected),
        config.min_gap,
    )
    pool = filter_pool(events, rules, known)
    start_run(
        {event.event_id: event for event in events},
        rules,
        tuple(event.event_id for event in pool),
    )
    return rules, pool
