"""Scoped content eligibility date; never a clock for retrieval/audit evidence."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime

_evaluation: ContextVar[date | None] = ContextVar("catalogue_evaluation", default=None)


def evaluation_date() -> date:
    return _evaluation.get() or datetime.now(UTC).date()


@contextmanager
def locked_evaluation(day: date) -> Iterator[None]:
    if type(day) is not date:
        raise ValueError("evaluation_requires_date")
    token = _evaluation.set(day)
    try:
        yield
    finally:
        _evaluation.reset(token)
