"""Pure whole-raw normalization shared by import and independent late gates.

No persisted dispositions, receipts or accepted-event lists establish eligibility.
Call once per batch, including individually invalid and quarantined raw aliases.
"""

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any

from app.content.adapters import router
from app.content.adapters.base import RawCandidate
from app.content.adapters.onthisday import SOURCE_ID, semantic_text
from app.content.adapters.selected import (
    MILESTONES,
    SelectedSourceAdapter,
    digest,
    issue,
)
from app.content.schemas import (
    CategoryRecord,
    EventRecord,
    SourceCitation,
    ValidationIssue,
)
from app.content.validation import validate_event

Normalized = EventRecord | tuple[ValidationIssue, ...]


def source_key(raw: RawCandidate) -> str:
    return json.dumps([raw.source_id, raw.record_id], separators=(",", ":"))


def raw_identity(raw: RawCandidate) -> str:
    chronology_identity = router.identity(raw)
    if chronology_identity is not None:
        return chronology_identity
    qid, milestone = raw.payload.get("entity_id"), raw.payload.get("milestone")
    if (
        isinstance(qid, str)
        and re.fullmatch(r"Q[1-9]\d*", qid)
        and isinstance(milestone, str)
        and milestone in MILESTONES
    ):
        return f"wikidata:{qid}:{milestone}"
    return "unresolved:" + source_key(raw)


@dataclass(frozen=True)
class CorpusResult:
    groups: dict[str, list[tuple[RawCandidate, Normalized]]]
    normalized: dict[str, EventRecord]
    failures: dict[str, list[ValidationIssue]]
    aliases: dict[str, Any]


def normalize_corpus(
    raws: list[RawCandidate],
    taxonomy: tuple[CategoryRecord, ...],
    current_year_index: int,
    *,
    aliases: dict[str, Any] | None = None,
    normalize: Callable[[RawCandidate], Normalized] = router.normalize,
) -> CorpusResult:
    """Recompute the importer's deterministic constraints from the whole corpus.

    Aliases retain identity history only; never consume stored pass/quarantine
    decisions. A custom normalizer is for the existing SourceAdapter API only.
    """
    raw_state: dict[str, RawCandidate] = {}
    for raw in raws:
        key = source_key(raw)
        if key in raw_state and digest(asdict(raw_state[key])) != digest(asdict(raw)):
            raise ValueError("Conflicting records share a source key in the snapshot")
        raw_state[key] = raw
    groups: dict[str, list[tuple[RawCandidate, Normalized]]] = {}
    # Unresolved dispositions are not proof of a canonical identity.
    current_aliases = {
        key: value
        for key, value in (aliases or {}).items()
        if not value["identity_key"].startswith("unresolved:")
    }
    alias_conflicts: set[str] = set()
    semantic_years: dict[str, set[int]] = {}
    for raw in raw_state.values():
        source_row = raw.payload.get("row")
        if (
            raw.source_id == SOURCE_ID
            and isinstance(source_row, dict)
            and isinstance(source_row.get("event"), str)
            and type(source_row.get("year")) is int
        ):
            semantic_years.setdefault(semantic_text(source_row["event"]), set()).add(
                source_row["year"]
            )
    for key in sorted(raw_state):
        raw = raw_state[key]
        result = normalize(raw)
        identity = (
            result.identity_key
            if isinstance(result, EventRecord)
            else raw_identity(raw)
        )
        source_row = raw.payload.get("row")
        if (
            raw.source_id == SOURCE_ID
            and isinstance(source_row, dict)
            and isinstance(source_row.get("event"), str)
            and len(semantic_years.get(semantic_text(source_row["event"]), set())) > 1
        ):
            result = (
                issue(
                    "conflicting_dates",
                    "row.year",
                    "Repeated chronology semantics disagree on reported year",
                ),
            )
        if key in current_aliases and current_aliases[key]["identity_key"] != identity:
            result = (
                issue(
                    "conflicting_identity",
                    "aliases",
                    "Source alias changed canonical identity",
                ),
            )
            alias_conflicts.update((identity, current_aliases[key]["identity_key"]))
        groups.setdefault(identity, []).append((raw, result))
        if isinstance(result, EventRecord):
            current_aliases.setdefault(
                key, {"identity_key": identity, "event_id": str(result.event_id)}
            )
    normalized: dict[str, EventRecord] = {}
    failures: dict[str, list[ValidationIssue]] = {}
    for identity, members in groups.items():
        events = [result for _, result in members if isinstance(result, EventRecord)]
        errors = [
            error
            for _, result in members
            if isinstance(result, tuple)
            for error in result
        ]
        if identity in alias_conflicts:
            errors.append(
                issue(
                    "conflicting_identity",
                    "aliases",
                    "A persistent source alias ambiguously retargeted this identity",
                )
            )
        if len({event.year_index for event in events}) > 1:
            errors.append(
                issue(
                    "conflicting_dates",
                    "year_index",
                    "Exact identity aliases disagree on year",
                )
            )
        if (
            identity.startswith("onthisday:")
            and len({event.prompt for event in events}) > 1
        ):
            errors.append(
                issue(
                    "suspected_duplicate",
                    "prompt",
                    "Normalized chronology aliases have different original wording; do not silently choose one",
                )
            )
        if SelectedSourceAdapter().alias_dates_conflict(
            [
                raw
                for raw, result in members
                if isinstance(result, EventRecord) and raw.source_id != SOURCE_ID
            ]
        ):
            errors.append(
                issue(
                    "conflicting_dates",
                    "sources",
                    "Exact source aliases disagree at common supported date precision",
                )
            )
        if events:
            base = events[0]
            ranks = {"year": 1, "month": 2, "day": 3}
            common_precision = min(
                (event.date_precision for event in events), key=ranks.__getitem__
            )
            citations: dict[tuple[str, str], SourceCitation] = {}
            for source_event in events:
                for source in source_event.sources:
                    source_key_pair = source.source_id, source.record_id
                    old = citations.get(source_key_pair)
                    same_date = old is None or old.raw_date == source.raw_date
                    if old is not None and source.source_id in {
                        "wikidata",
                        "wikipedia_en",
                    }:
                        same_date = SelectedSourceAdapter.citation_dates_agree(
                            old, source, common_precision
                        )
                    if old is not None and (
                        not same_date
                        or old.calendar != source.calendar
                        or old.date_resolution != source.date_resolution
                    ):
                        errors.append(
                            issue(
                                "conflicting_dates",
                                "sources",
                                "Repeated source identity has conflicting date evidence",
                            )
                        )
                    citations[source_key_pair] = source
            merged = base.model_copy(
                update={
                    "date_precision": common_precision,
                    "sources": tuple(citations[k] for k in sorted(citations)),
                    "category_ids": tuple(
                        sorted({c for e in events for c in e.category_ids})
                    ),
                    "region_ids": tuple(
                        sorted({r for e in events for r in e.region_ids})
                    ),
                }
            )
            errors.extend(validate_event(merged, taxonomy, current_year_index))
            normalized[identity] = merged
        failures[identity] = errors
    # Suspects include individually normalized groups with OTHER failures too,
    # exactly as at import; never restrict this scan to an accepted-event subset.
    identities = sorted(normalized)
    prompts = {
        key: re.sub(r"\W+", " ", event.prompt.casefold()).strip()
        for key, event in normalized.items()
    }
    for position, identity in enumerate(identities):
        for other in identities[position + 1 :]:
            if identity.rsplit(":", 1)[-1] != other.rsplit(":", 1)[-1]:
                continue
            matcher = SequenceMatcher(None, prompts[identity], prompts[other])
            if (
                matcher.real_quick_ratio() >= 0.90
                and matcher.quick_ratio() >= 0.90
                and matcher.ratio() >= 0.90
            ):
                for suspect in (identity, other):
                    failures[suspect].append(
                        issue(
                            "suspected_duplicate",
                            "identity_key",
                            "Similar wording without exact source identity is quarantined, not merged",
                        )
                    )
    return CorpusResult(groups, normalized, failures, current_aliases)
