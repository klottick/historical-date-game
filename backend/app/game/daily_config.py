"""Fixed, machine-approved Daily selection; never infer an all-category default."""

from dataclasses import dataclass
from importlib.resources import files

from app.content.schemas import CATEGORY_IDS, SourceSelection


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
