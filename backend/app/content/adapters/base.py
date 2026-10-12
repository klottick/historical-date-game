"""Acquisition interfaces shared with the private importer workspace."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.content.schemas import EventRecord, ValidationIssue


@dataclass(frozen=True)
class RawCandidate:
    source_id: str
    record_id: str
    payload: dict[str, object]


class SourceAdapter(Protocol):
    def fetch(self, snapshot_dir: Path) -> Iterable[RawCandidate]: ...

    def normalize(
        self, raw: RawCandidate
    ) -> EventRecord | tuple[ValidationIssue, ...]: ...
