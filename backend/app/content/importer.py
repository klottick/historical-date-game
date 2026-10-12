"""Private, single-writer, generation-atomic resumable content imports.

The current.json pointer is the ONLY commit point. Readers must resolve it once
and read that immutable generation; never scan candidates from orphaned writes.
Content-only passes are not publication approval and contain no media digest.
"""

import fcntl
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.content.adapters.base import RawCandidate, SourceAdapter
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
    ValidationReceipt,
)
from app.content.validation import (
    VALIDATION_POLICY_VERSION,
    candidate_digest,
    validate_event,
)


@dataclass(frozen=True)
class ImportReport:
    imported: int
    quarantined: int
    duplicates: int


def _key(raw: RawCandidate) -> str:
    return json.dumps([raw.source_id, raw.record_id], separators=(",", ":"))


def _identity(raw: RawCandidate) -> str:
    qid, milestone = raw.payload.get("entity_id"), raw.payload.get("milestone")
    if (
        isinstance(qid, str)
        and re.fullmatch(r"Q[1-9]\d*", qid)
        and isinstance(milestone, str)
        and milestone in MILESTONES
    ):
        return f"wikidata:{qid}:{milestone}"
    return "unresolved:" + _key(raw)


def _write(path: Path, text: str) -> None:
    with path.open("w") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(
        json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows
    )


def _sources(raws: list[RawCandidate]) -> tuple[str, ...]:
    values: set[str] = set()
    for raw in raws:
        evidence = raw.payload.get("evidence", [])
        if not isinstance(evidence, list):
            continue
        for item in evidence:
            if isinstance(item, dict) and re.fullmatch(
                r"[0-9a-f]{64}", str(item.get("sha256", ""))
            ):
                values.add(str(item["sha256"]))
    # For general SourceAdapter implementations, bind preserved acquisition data.
    return tuple(sorted(values)) or tuple(sorted({digest(asdict(raw)) for raw in raws}))


def import_snapshot(
    adapter: SourceAdapter, snapshot_dir: Path, workspace: Path
) -> ImportReport:
    """Upsert persistent source keys, revalidate the whole active content workspace.

    Fetch failures never advance current.json. Removed source keys are not inferred
    from a partial batch; corrections upsert the same key, keeping canonical IDs.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    with (workspace / ".import.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _import_locked(adapter, snapshot_dir, workspace)


def _import_locked(
    adapter: SourceAdapter, snapshot_dir: Path, workspace: Path
) -> ImportReport:
    pointer = workspace / "current.json"
    previous: dict[str, Any] = {"raw": {}, "aliases": {}, "candidate_digests": {}}
    if pointer.exists():
        generation = json.loads(pointer.read_text())["generation"]
        previous = json.loads((workspace / generation / "state.json").read_text())
    raw_state = dict(previous["raw"])
    incoming = list(adapter.fetch(snapshot_dir))
    seen: dict[str, str] = {}
    for raw in incoming:
        key = _key(raw)
        raw_digest = digest(asdict(raw))
        if key in seen and seen[key] != raw_digest:
            raise ValueError("Conflicting records share a source key in the snapshot")
        seen[key] = raw_digest
        raw_state[key] = asdict(raw)
    taxonomy_data = json.loads(Path(__file__).with_name("taxonomy.json").read_text())
    input_digest = digest(
        {
            "raw": raw_state,
            "taxonomy": taxonomy_data,
            "current_year_index": datetime.now(UTC).year,
            "policy": VALIDATION_POLICY_VERSION,
            "adapter_rules": "selected-v6",
        }
    )
    if input_digest == previous.get("input_digest"):
        return ImportReport(
            imported=0,
            quarantined=previous["quarantined"],
            duplicates=previous["duplicates"],
        )
    taxonomy = tuple(
        CategoryRecord.model_validate_json(json.dumps(c)) for c in taxonomy_data
    )
    groups: dict[
        str, list[tuple[RawCandidate, EventRecord | tuple[ValidationIssue, ...]]]
    ] = {}
    # Migrate 618bca1 placeholders: an unresolved disposition was never proof
    # of canonical identity and must not prevent later machine-only recovery.
    aliases = {
        key: value
        for key, value in previous["aliases"].items()
        if not value["identity_key"].startswith("unresolved:")
    }
    alias_conflicts: set[str] = set()
    for key in sorted(raw_state):
        raw = RawCandidate(**raw_state[key])
        result = adapter.normalize(raw)
        identity = (
            result.identity_key if isinstance(result, EventRecord) else _identity(raw)
        )
        if key in aliases and aliases[key]["identity_key"] != identity:
            # Alias retargeting is not proof that two entities are identical.
            result = (
                issue(
                    "conflicting_identity",
                    "aliases",
                    "Source alias changed canonical identity",
                ),
            )
            alias_conflicts.update((identity, aliases[key]["identity_key"]))
        groups.setdefault(identity, []).append((raw, result))
        if isinstance(result, EventRecord):
            aliases.setdefault(
                key,
                {"identity_key": identity, "event_id": str(result.event_id)},
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
        if isinstance(adapter, SelectedSourceAdapter) and adapter.alias_dates_conflict(
            [raw for raw, result in members if isinstance(result, EventRecord)]
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
                    source_key = source.source_id, source.record_id
                    old = citations.get(source_key)
                    same_date = old is None or old.raw_date == source.raw_date
                    if old is not None and isinstance(adapter, SelectedSourceAdapter):
                        same_date = adapter.citation_dates_agree(
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
                    citations[source_key] = source
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
            errors.extend(validate_event(merged, taxonomy, datetime.now(UTC).year))
            normalized[identity] = merged
        failures[identity] = errors
    # Fuzzy similarity only detects suspicion; it never merges accepted facts.
    identities = sorted(normalized)
    for position, identity in enumerate(identities):
        left = normalized[identity]
        for other in identities[position + 1 :]:
            right = normalized[other]
            if identity.rsplit(":", 1)[-1] != other.rsplit(":", 1)[-1]:
                continue
            a = re.sub(r"\W+", " ", left.prompt.casefold()).strip()
            b = re.sub(r"\W+", " ", right.prompt.casefold()).strip()
            if SequenceMatcher(None, a, b).ratio() >= 0.90:
                for suspect in (identity, other):
                    failures[suspect].append(
                        issue(
                            "suspected_duplicate",
                            "identity_key",
                            "Similar wording without exact source identity is quarantined, not merged",
                        )
                    )
    candidates: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    candidate_digests = {}
    duplicates = 0
    quarantined = 0
    now = datetime.now(UTC)
    for identity in sorted(groups):
        members = groups[identity]
        event = normalized.get(identity)
        errors = failures[identity]
        codes = tuple(sorted({error.code for error in errors}))
        passed = event is not None and not codes
        raws = [raw for raw, _ in members]
        event_id = (
            event.event_id if event is not None else uuid5(NAMESPACE_URL, identity)
        )
        if event is not None and not passed:
            event = event.model_copy(update={"review_status": "quarantined"})
        bound_digest = (
            candidate_digest(event)
            if event is not None
            else digest([asdict(raw) for raw in raws])
        )
        if passed and event is not None:
            candidates.append(event.model_dump(mode="json"))
            candidate_digests[identity] = bound_digest
            duplicates += len(members) - 1
        else:
            quarantined += len(members)
            quarantine.append(
                {
                    "event_id": str(event_id),
                    "identity_key": identity,
                    "issue_codes": codes,
                    "issues": [error.model_dump(mode="json") for error in errors],
                    "raw": [asdict(raw) for raw in raws],
                    "candidate": event.model_dump(mode="json") if event else None,
                }
            )
        receipt = ValidationReceipt(
            event_id=event_id,
            candidate_sha256=bound_digest,
            source_sha256=_sources(raws),
            policy_version=VALIDATION_POLICY_VERSION,
            stage="content",
            media_catalog_sha256=None,
            passed=passed,
            checked_at=now,
            issue_codes=codes,
        )
        receipts.append(receipt.model_dump(mode="json"))
        for raw in raws:
            decisions.append(
                {
                    "source_id": raw.source_id,
                    "record_id": raw.record_id,
                    "event_id": str(event_id),
                    "identity_key": identity,
                    "raw_sha256": digest(asdict(raw)),
                    "candidate_sha256": bound_digest,
                    "source_sha256": receipt.source_sha256,
                    "policy_version": VALIDATION_POLICY_VERSION,
                    "passed": passed,
                    "issue_codes": codes,
                }
            )
    imported = sum(
        previous["candidate_digests"].get(identity) != value
        for identity, value in candidate_digests.items()
    )
    state = {
        "input_digest": input_digest,
        "raw": raw_state,
        "aliases": aliases,
        "candidate_digests": candidate_digests,
        "quarantined": quarantined,
        "duplicates": duplicates,
    }
    # Each generation is immutable; failed writes leave only unreferenced debris.
    generation = (
        Path("generations") / f"{input_digest}-{now.strftime('%Y%m%dT%H%M%S%f')}"
    )
    target = workspace / generation
    target.mkdir(parents=True)
    files = {
        "state.json": json.dumps(state, sort_keys=True),
        "aliases.json": json.dumps(aliases, sort_keys=True),
        "raw.jsonl": _jsonl(list(raw_state.values())),
        "candidates.jsonl": _jsonl(candidates),
        "quarantine.jsonl": _jsonl(quarantine),
        "decisions.jsonl": _jsonl(decisions),
        "receipts.jsonl": _jsonl(receipts),
        "sources.json": json.dumps(
            {
                "input_sha256": input_digest,
                "source_sha256": _sources(
                    [RawCandidate(**data) for data in raw_state.values()]
                ),
                "records": {
                    key: {
                        "raw_sha256": digest(data),
                        "evidence": data["payload"].get("evidence", []),
                    }
                    for key, data in raw_state.items()
                },
            },
            sort_keys=True,
        ),
    }
    for name, text in files.items():
        _write(target / name, text)
    _sync_directory(target)
    _sync_directory(target.parent)
    temporary = workspace / "current.json.tmp"
    _write(
        temporary,
        json.dumps(
            {"generation": str(generation), "input_sha256": input_digest},
            sort_keys=True,
        ),
    )
    temporary.replace(pointer)
    _sync_directory(workspace)
    return ImportReport(
        imported=imported, quarantined=quarantined, duplicates=duplicates
    )
