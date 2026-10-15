from app.game.types import RuleError, YearInput, require_integer


def to_year_index(value: int, era: str) -> int:
    """Map positive civil years onto a continuous integer chronology."""
    magnitude = require_integer(value, "invalid_year")
    if magnitude <= 0:
        raise RuleError("invalid_year")
    if type(era) is not str or era not in ("BCE", "CE"):
        raise RuleError("invalid_era")
    return magnitude if era == "CE" else 1 - magnitude


def from_year_index(index: int) -> YearInput:
    year = require_integer(index, "invalid_year")
    return YearInput(year, "CE") if year >= 1 else YearInput(1 - year, "BCE")
