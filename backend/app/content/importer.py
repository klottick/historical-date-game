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
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.content.adapters import router
from app.content.adapters.base import RawCandidate, SourceAdapter
from app.content.adapters.onthisday import (
    SNAPSHOT_PREFIX,
    SOURCE_ID,
    OnThisDayAdapter,
    snapshot_bytes,
)
from app.content.adapters.selected import SelectedSourceAdapter, digest
from app.content.corpus import normalize_corpus, raw_identity, source_key
from app.content.schemas import (
    CategoryRecord,
    ValidationReceipt,
)
from app.content.validation import (
    VALIDATION_POLICY_VERSION,
    candidate_digest,
)


@dataclass(frozen=True)
class ImportReport:
    imported: int
    quarantined: int
    duplicates: int


def _key(raw: RawCandidate) -> str:
    return source_key(raw)


def _identity(raw: RawCandidate) -> str:
    return raw_identity(raw)


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
    previous_generation = ""
    if pointer.exists():
        generation = json.loads(pointer.read_text())["generation"]
        previous_generation = generation
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
            "chronology_utc_date": datetime.now(UTC).date().isoformat()
            if any(data["source_id"] == SOURCE_ID for data in raw_state.values())
            else None,
            "policy": VALIDATION_POLICY_VERSION,
            # Bump with normalization fixes so unchanged snapshots are rechecked.
            "adapter_rules": router.rules_digest(),
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
    normalizer = (
        router.normalize
        if isinstance(
            adapter, (SelectedSourceAdapter, OnThisDayAdapter, router.AdapterRouter)
        )
        else adapter.normalize
    )
    corpus = normalize_corpus(
        [RawCandidate(**data) for data in raw_state.values()],
        taxonomy,
        datetime.now(UTC).year,
        aliases=previous["aliases"],
        normalize=normalizer,
    )
    groups, normalized, failures, aliases = (
        corpus.groups,
        corpus.normalized,
        corpus.failures,
        corpus.aliases,
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
    if any(raw.source_id == SOURCE_ID for raw in incoming):
        bodies = snapshot_bytes(snapshot_dir)
    elif any(data["source_id"] == SOURCE_ID for data in raw_state.values()):
        bodies = snapshot_bytes(workspace / previous_generation / SNAPSHOT_PREFIX)
    else:
        bodies = {}
    for name, body in bodies.items():
        destination = target / SNAPSHOT_PREFIX / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
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
