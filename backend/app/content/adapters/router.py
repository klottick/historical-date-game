"""Private dispatch: acquired source IDs determine normalization at every stage."""

import hashlib
from collections.abc import Iterable
from pathlib import Path

from app.content.adapters.base import RawCandidate, SourceAdapter
from app.content.adapters.onthisday import SOURCE_ID, OnThisDayAdapter, raw_identity
from app.content.adapters.selected import SelectedSourceAdapter, digest, issue
from app.content.schemas import EventRecord, ValidationIssue


def for_raw(raw: RawCandidate) -> SourceAdapter:
    if raw.source_id == SOURCE_ID:
        return OnThisDayAdapter()
    return SelectedSourceAdapter()


def normalize(raw: RawCandidate) -> EventRecord | tuple[ValidationIssue, ...]:
    if raw.source_id not in {SOURCE_ID, "wikidata", "wikipedia_en"}:
        return (
            issue(
                "adapter_mismatch", "source_id", "No approved adapter for this source"
            ),
        )
    return for_raw(raw).normalize(raw)


def identity(raw: RawCandidate) -> str | None:
    return raw_identity(raw) if raw.source_id == SOURCE_ID else None


def rules_digest() -> str:
    content_root = Path(__file__).parent.parent
    paths = (
        *sorted(Path(__file__).parent.glob("*.py")),
        content_root / "validation.py",
        content_root / "importer.py",
        content_root / "schemas.py",
    )
    return digest(
        {
            str(p.relative_to(content_root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths
        }
    )


class AdapterRouter:
    def fetch(self, snapshot_dir: Path) -> Iterable[RawCandidate]:
        if (snapshot_dir / "events.jsonl").exists():
            yield from OnThisDayAdapter().fetch(snapshot_dir)
        else:
            yield from SelectedSourceAdapter().fetch(snapshot_dir)

    def normalize(self, raw: RawCandidate) -> EventRecord | tuple[ValidationIssue, ...]:
        return normalize(raw)
