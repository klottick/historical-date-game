"""Offline, create-only private releases from the current frozen C4 batch.

Hashes detect corruption, not malicious replacement of an entire unsigned corpus.
Trusted local POSIX writers are required. Only media/ is public-serving eligible.
"""

import fcntl
import hashlib
import json
import os
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

from app.content.adapters.base import RawCandidate
from app.content.adapters.onthisday import (
    CATALOG_LICENSE,
    CATALOG_NOTICE,
    SNAPSHOT_FILES,
    SNAPSHOT_PREFIX,
    SOURCE_ID,
)
from app.content.adapters.selected import digest
from app.content.importer import _sources, _sync_directory
from app.content.media import pipeline
from app.content.media.rights import MediaCandidate
from app.content.schemas import (
    CATEGORY_IDS,
    CatalogManifest,
    CategoryRecord,
    EventRecord,
    MediaCatalog,
    SourceSelection,
    ValidationReceipt,
    _relative_path,
)
from app.content.validation import (
    media_catalog_digest,
    validate_event,
    validate_receipt,
)

REQUIRED = {
    "events.jsonl",
    "candidates.jsonl",
    "media.json",
    "validation.json",
    "receipts.jsonl",
    "raw.jsonl",
    "sources.json",
    "aliases.json",
    "taxonomy.json",
    "source-selection.json",
    "decisions.json",
}


def canonical(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        + b"\n"
    )


def _safe_root(path: Path) -> Path:
    path = path.absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlink_path")
    return path


def _path(root: Path, name: str) -> Path:
    _relative_path(name)
    target = _safe_root(root / name)
    if not target.is_relative_to(root.absolute()):
        raise ValueError("path_escape")
    return target


def _json(root: Path, name: str) -> Any:
    try:
        return json.loads(_path(root, name).read_bytes())
    except FileNotFoundError as exc:
        raise ValueError(f"missing_artifact:{name}") from exc


def _rows(root: Path, name: str) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in _path(root, name).read_bytes().splitlines()
        if line.strip()
    ]


def _files(root: Path) -> set[str]:
    found = set()
    for path in root.rglob("*"):
        _safe_root(path)
        if path.is_file():
            found.add(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise ValueError("nonregular_artifact")
    return found


def _sha(root: Path, name: str) -> str:
    path = _path(root, name)
    if not path.is_file():
        raise ValueError("missing_artifact")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hashes(root: Path, expected: dict[str, str]) -> None:
    for name, sha in expected.items():
        if _sha(root, name) != sha:
            raise ValueError(f"artifact_integrity:{name}")


def _pointer(workspace: Path, name: str, prefix: str) -> tuple[Path, dict[str, Any]]:
    pointer = _json(workspace, name)
    relative = pointer["generation"]
    _relative_path(relative)
    if len(relative.split("/")) != 2 or relative.split("/")[0] != prefix:
        raise ValueError("unsafe_workspace_pointer")
    return _path(workspace, relative), pointer


def _events(root: Path, name: str) -> list[EventRecord]:
    return [
        EventRecord.model_validate_json(json.dumps(row)) for row in _rows(root, name)
    ]


def _unique(events: list[EventRecord]) -> None:
    if (
        not events
        or len({e.event_id for e in events}) != len(events)
        or len({e.identity_key for e in events}) != len(events)
    ):
        raise ValueError("empty_or_duplicate_events")


def _coverage(events: list[EventRecord], catalog: MediaCatalog) -> dict[str, Any]:
    categories = Counter(c for e in events for c in e.category_ids)
    return {
        "event_count": len(events),
        "review_status": dict(sorted(Counter(e.review_status for e in events).items())),
        "eras": {
            "BCE": sum(e.year_index <= 0 for e in events),
            "CE": sum(e.year_index > 0 for e in events),
        },
        "regions": dict(
            sorted(Counter(r for e in events for r in e.region_ids).items())
        ),
        "without_region": sum(not e.region_ids for e in events),
        "categories": {key: categories[key] for key in CATEGORY_IDS},
        "distinct_years": len({e.year_index for e in events}),
        "year_min": min(e.year_index for e in events),
        "year_max": max(e.year_index for e in events),
        "images": sum(e.media_asset_id is not None for e in events),
        "distinct_images": len(catalog.records),
        "fallback_events": sum(e.media_asset_id is None for e in events),
        "fallback_coverage": dict(
            sorted(Counter(e.fallback_key for e in events).items())
        ),
        "fallback_assets": len(catalog.fallbacks),
    }


def _check(
    root: Path, media_dir: Path
) -> tuple[list[EventRecord], MediaCatalog, dict[str, Any]]:
    """Recompute acceptance, never trust batch/report flags or supplied counts."""
    summary = _json(root, "batch.json")
    rules_sha = pipeline.media_rules_digest()
    if summary.get("media_rules_sha256") != rules_sha:
        raise ValueError("stale_media_rules")
    events = _events(root, "events.jsonl")
    originals = _events(root, "candidates.jsonl")
    _unique(events)
    _unique(originals)
    by_id = {e.event_id: e for e in originals}
    if set(by_id) != {e.event_id for e in events}:
        raise ValueError("incomplete_current_batch")
    catalog = MediaCatalog.model_validate_json(_path(root, "media.json").read_bytes())
    if summary.get("media_catalog_sha256") != media_catalog_digest(catalog):
        raise ValueError("stale_media_catalog")
    if {e.media_asset_id for e in events if e.media_asset_id is not None} != {
        r.asset_id for r in catalog.records
    }:
        raise ValueError("unreferenced_or_missing_media")
    taxonomy = tuple(
        CategoryRecord.model_validate_json(json.dumps(row))
        for row in _json(root, "taxonomy.json")
    )
    packaged = json.loads(Path(__file__).with_name("taxonomy.json").read_bytes())
    if sorted(
        (r.model_dump(mode="json") for r in taxonomy), key=lambda r: r["id"]
    ) != sorted(packaged, key=lambda r: r["id"]):
        raise ValueError("taxonomy_mismatch")
    selection = SourceSelection.model_validate_json(
        _path(root, "source-selection.json").read_bytes()
    )
    approved = SourceSelection.model_validate_json(
        Path(__file__)
        .parents[3]
        .joinpath("docs/research/source-selection.json")
        .read_bytes()
    )
    if selection != approved:
        raise ValueError("unsupported_source_selection")
    sources = _json(root, "sources.json")
    raws = [RawCandidate(**row) for row in _rows(root, "raw.jsonl")]
    keys = [json.dumps([r.source_id, r.record_id], separators=(",", ":")) for r in raws]
    if len(set(keys)) != len(keys) or set(keys) != set(sources["records"]):
        raise ValueError("source_record_set")
    if sources.get("input_sha256") != summary.get("content_input_sha256") or tuple(
        sources.get("source_sha256", [])
    ) != _sources(raws):
        raise ValueError("source_integrity")
    for raw, key in zip(raws, keys, strict=True):
        record = sources["records"][key]
        if (
            raw.source_id not in selection.source_ids
            or record["raw_sha256"]
            != digest(
                {
                    "source_id": raw.source_id,
                    "record_id": raw.record_id,
                    "payload": raw.payload,
                }
            )
            or record["evidence"] != raw.payload.get("evidence", [])
        ):
            raise ValueError("source_integrity")
    receipts = [
        ValidationReceipt.model_validate_json(json.dumps(row))
        for row in _json(root, "validation.json")
    ]
    jsonl_receipts = [
        ValidationReceipt.model_validate_json(json.dumps(row))
        for row in _rows(root, "receipts.jsonl")
    ]
    if (
        sorted(receipts, key=lambda r: str(r.event_id))
        != sorted(jsonl_receipts, key=lambda r: str(r.event_id))
        or len({r.event_id for r in receipts}) != len(receipts)
        or {r.event_id for r in receipts} != {e.event_id for e in events}
    ):
        raise ValueError("missing_duplicate_or_inconsistent_receipts")
    receipt_by_id = {r.event_id: r for r in receipts}
    decisions = _json(root, "decisions.json")
    if set(decisions) != {str(e.event_id) for e in events}:
        raise ValueError("incomplete_decisions")
    aliases = _json(root, "aliases.json")
    # Safe path checks precede C4 readers/decoders, including private snapshots.
    actual_files = _files(root)
    expected_files = (
        REQUIRED
        | {"batch.json"}
        | {r.filename for r in pipeline._catalog_assets(catalog)}
    )
    if any(raw.source_id == SOURCE_ID for raw in raws):
        expected_files |= {SNAPSHOT_PREFIX + name for name in SNAPSHOT_FILES} | {
            "LICENSE.catalog.txt",
            "NOTICE.catalog.md",
        }
        if pipeline._recheck_chronology_snapshot(root, raws):
            raise ValueError("source_integrity")
        if (
            _path(root, "LICENSE.catalog.txt").read_bytes() != CATALOG_LICENSE.encode()
            or _path(root, "NOTICE.catalog.md").read_bytes() != CATALOG_NOTICE.encode()
        ):
            raise ValueError("catalog_text_attribution")
    for decision in decisions.values():
        if decision.get("candidate"):
            evidence = MediaCandidate.model_validate_json(
                json.dumps(decision["candidate"])
            )
            stem = hashlib.sha256(evidence.title.encode()).hexdigest()
            expected_files.update(
                {
                    f"media-cache/commons/{stem}.json",
                    f"media-cache/commons/{stem}.meta.json",
                    f"media-cache/originals/{evidence.upstream_sha1}.bin",
                    f"media-cache/originals/{evidence.upstream_sha1}.meta.json",
                }
            )
    expected_files |= actual_files & {"coverage.json", "manifest.json"}
    if actual_files != expected_files:
        raise ValueError("unexpected_or_missing_artifact")
    media_dir = _safe_root(media_dir)
    for record in pipeline._catalog_assets(catalog):
        path = _path(media_dir, Path(record.filename).name)
        if _sha(media_dir, path.name) != record.sha256:
            raise ValueError("asset_integrity")
    # C4 expects an asset root containing media/, so use the frozen release root
    # as well as the explicitly supplied public-store directory above.
    codes = pipeline._check_assets(catalog, root)
    if codes:
        raise ValueError("asset_validation:" + ",".join(sorted(codes)))
    raw_index = pipeline._raw_index(raws)
    for event in events:
        original = by_id[event.event_id]
        if (
            event.model_copy(
                update={
                    "media_asset_id": original.media_asset_id,
                    "fallback_key": original.fallback_key,
                }
            )
            != original
        ):
            raise ValueError("assignment_content_changed")
        decision = decisions[str(event.event_id)]
        if (
            decision.get("event_id") != str(event.event_id)
            or decision.get("media_rules_sha256") != rules_sha
            or decision.get("selection") != selection.model_dump(mode="json")
        ):
            raise ValueError("stale_media_decision")
        event_raws = raw_index.get(event.identity_key, [])
        current_digests = _sources(event_raws)
        issues = validate_event(event, taxonomy, datetime.now(UTC).year)
        issues += validate_receipt(
            event, receipt_by_id[event.event_id], current_digests, catalog
        )
        codes = {issue.code for issue in issues}
        codes |= pipeline._recheck_content(event, event_raws, sources)
        codes |= pipeline._recheck_media(
            root, event, original, event_raws, decision, catalog
        )
        for raw in event_raws:
            key = json.dumps([raw.source_id, raw.record_id], separators=(",", ":"))
            alias = aliases.get(key, {})
            if alias.get("identity_key") != event.identity_key or alias.get(
                "event_id"
            ) != str(event.event_id):
                codes.add("source_alias_mismatch")
        if codes:
            raise ValueError("event_validation:" + ",".join(sorted(codes)))
    # Counts in the batch are checked but never used to establish the beta gate.
    if summary.get("event_count") != len(events):
        raise ValueError("batch_count_mismatch")
    return events, catalog, _coverage(events, catalog)


def _beta(count: int, fixture: bool) -> None:
    if fixture or count < 1000:
        raise ValueError("beta_requires_1000_distinct_accepted_nonfixture_events")


def _canonical_files(root: Path) -> dict[str, bytes]:
    files = {}
    for name in sorted(_files(root) - {"batch.json"}):
        if name.startswith(SNAPSHOT_PREFIX):
            files[name] = _path(root, name).read_bytes()
        elif name.endswith(".jsonl"):
            rows = _rows(root, name)
            if name in {"events.jsonl", "candidates.jsonl"}:
                rows = [
                    EventRecord.model_validate_json(json.dumps(row)).model_dump(
                        mode="json"
                    )
                    for row in rows
                ]
            elif name == "receipts.jsonl":
                rows = [
                    ValidationReceipt.model_validate_json(json.dumps(row)).model_dump(
                        mode="json"
                    )
                    for row in rows
                ]
            key = (
                (lambda r: (r["source_id"], r["record_id"]))
                if name == "raw.jsonl"
                else (lambda r: r["event_id"])
            )
            files[name] = b"".join(canonical(row) for row in sorted(rows, key=key))
        elif name.endswith(".json"):
            value = _json(root, name)
            if name == "media.json":
                value = MediaCatalog.model_validate_json(json.dumps(value)).model_dump(
                    mode="json"
                )
                value["records"].sort(key=lambda r: r["asset_id"])
            elif name == "validation.json":
                value = [
                    ValidationReceipt.model_validate_json(json.dumps(row)).model_dump(
                        mode="json"
                    )
                    for row in value
                ]
                value.sort(key=lambda r: r["event_id"])
            elif name == "taxonomy.json":
                value = [
                    CategoryRecord.model_validate_json(json.dumps(row)).model_dump(
                        mode="json"
                    )
                    for row in value
                ]
                value.sort(key=lambda r: r["id"])
            elif name == "source-selection.json":
                value = SourceSelection.model_validate_json(
                    json.dumps(value)
                ).model_dump(mode="json")
            # Provider snapshot bytes must preserve their acquisition digests.
            files[name] = (
                _path(root, name).read_bytes()
                if name.startswith("media-cache/")
                else canonical(value)
            )
        else:
            files[name] = _path(root, name).read_bytes()
    return files


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def publish_release(
    workspace: Path, output_root: Path, release_id: str, *, fixture: bool = False
) -> CatalogManifest:
    # Typed identity validation before any directory creation.
    CatalogManifest(
        release_id=release_id,
        created_at=datetime.now(UTC),
        event_count=0,
        fixture=fixture,
        files={},
    )
    workspace, output_root = _safe_root(workspace), _safe_root(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    with (
        _path(output_root, ".publish.lock").open("a") as output_lock,
        _path(workspace, ".import.lock").open("a") as content_lock,
        _path(workspace, ".media.lock").open("a") as media_lock,
    ):
        fcntl.flock(output_lock, fcntl.LOCK_EX)
        fcntl.flock(content_lock, fcntl.LOCK_SH)
        fcntl.flock(media_lock, fcntl.LOCK_SH)
        destination = _path(output_root, release_id)
        if destination.exists():
            raise ValueError("immutable_release_exists")
        content, content_pointer = _pointer(workspace, "current.json", "generations")
        root, pointer = _pointer(workspace, "media-current.json", "media-generations")
        summary = _json(root, "batch.json")
        for key, expected in {
            "content_generation": content_pointer["generation"],
            "content_input_sha256": content_pointer["input_sha256"],
            "media_rules_sha256": pipeline.media_rules_digest(),
            "media_catalog_sha256": summary.get("media_catalog_sha256"),
        }.items():
            if summary.get(key) != expected or pointer.get(key) != expected:
                raise ValueError("stale_current_batch:" + key)
        files = summary["files"]
        if not REQUIRED <= set(files) or _files(root) != set(files) | {"batch.json"}:
            raise ValueError("incomplete_batch_artifacts")
        _hashes(root, files)
        for name in ("raw.jsonl", "sources.json", "aliases.json", "candidates.jsonl"):
            if _sha(root, name) != _sha(content, name):
                raise ValueError("stale_content_snapshot")
        events, _, coverage = _check(root, root / "media")
        if not fixture:
            _beta(len(events), fixture)
        payloads = _canonical_files(root)
        payloads["coverage.json"] = canonical(coverage)
        summary["files"] = {
            name: hashlib.sha256(data).hexdigest()
            for name, data in sorted(payloads.items())
        }
        payloads["batch.json"] = canonical(summary)
        manifest = CatalogManifest(
            release_id=release_id,
            created_at=datetime.now(UTC),
            event_count=len(events),
            fixture=fixture,
            files={
                name: hashlib.sha256(data).hexdigest()
                for name, data in sorted(payloads.items())
            },
        )
        temporary = Path(mkdtemp(prefix=".release-", dir=output_root))
        try:
            for name, data in payloads.items():
                _write_bytes(_path(temporary, name), data)
            _write_bytes(
                temporary / "manifest.json", canonical(manifest.model_dump(mode="json"))
            )
            for directory in sorted(
                (p for p in temporary.rglob("*") if p.is_dir()),
                key=lambda p: len(p.parts),
                reverse=True,
            ):
                _sync_directory(directory)
            _sync_directory(temporary)
            # Serialized cooperating writers; rename never targets an existing ID.
            if destination.exists():
                raise ValueError("immutable_release_exists")
            temporary.rename(destination)
            _sync_directory(output_root)
        except BaseException:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise
        return manifest


def verify_release(
    release_dir: Path, media_dir: Path, *, require_beta: bool = False
) -> CatalogManifest:
    release_dir = _safe_root(release_dir)
    manifest = CatalogManifest.model_validate_json(
        _path(release_dir, "manifest.json").read_bytes()
    )
    if manifest.release_id != release_dir.name:
        raise ValueError("manifest_identity_mismatch")
    if not REQUIRED | {"batch.json", "coverage.json"} <= set(manifest.files) or _files(
        release_dir
    ) != set(manifest.files) | {"manifest.json"}:
        raise ValueError("incomplete_release_artifacts")
    _hashes(release_dir, manifest.files)
    summary = _json(release_dir, "batch.json")
    if set(summary["files"]) != set(manifest.files) - {"batch.json"}:
        raise ValueError("incomplete_batch_artifacts")
    _hashes(release_dir, summary["files"])
    events, _, coverage = _check(release_dir, media_dir)
    if (
        manifest.event_count != len(events)
        or _json(release_dir, "coverage.json") != coverage
    ):
        raise ValueError("manifest_count_or_coverage_mismatch")
    if require_beta:
        _beta(len(events), manifest.fixture)
    return manifest
