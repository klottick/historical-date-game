"""Pinned source-to-runtime replay, with no database imports or activation.

Recipe v1 retains the entire chronology plus five original source envelopes.
Update seals new payload digests only after actual full pipeline verification;
reproduce never repairs a stale lock. Every output is create-only scratch.
"""

import re
import tomllib
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from platform import python_version
from typing import Any

from app.content.adapters import router
from app.content.adapters.base import RawCandidate
from app.content.adapters.onthisday import SNAPSHOT_FILES, OnThisDayAdapter
from app.content.build_context import locked_evaluation
from app.content.importer import import_snapshot
from app.content.media import pipeline
from app.content.publish import canonical, publish_release, verify_release
from app.content.runtime import (
    REQUIRED_FILES,
    read_checked,
    sha256,
    strict_json,
    verify_runtime,
)
from app.content.runtime_export import export_runtime, runtime_payloads
from app.content.runtime_models import BuildLock
from app.content.schemas import EventRecord, SourceSelection, ValidationIssue
from app.content.source_acquisition import (
    acquire_sources,
    check_source_directory,
    safe_output,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
CHRONOLOGY_ROWS = 19860
SUPPLEMENT_ROWS = 5
SUPPLEMENTS = "supplements.jsonl"


def code_fingerprints() -> dict[str, str]:
    """Complete recipe code/config, never generated catalogue/lock payloads."""
    content = BACKEND_ROOT / "app/content"
    paths = [p for p in content.rglob("*") if p.suffix in {".py", ".json", ".svg"}]
    paths += [BACKEND_ROOT / "pyproject.toml", BACKEND_ROOT / "uv.lock"]
    paths += [
        BACKEND_ROOT / "app/game" / name
        for name in (
            "daily_config.py",
            "rules.py",
            "types.py",
            "source-selection.json",
        )
    ]
    return {
        p.relative_to(BACKEND_ROOT).as_posix(): sha256(read_checked(p))
        for p in sorted(paths)
    }


def dependency_versions() -> dict[str, str]:
    """Pin every installed package in uv.lock, including transitive decoders."""
    data = tomllib.loads(read_checked(BACKEND_ROOT / "uv.lock").decode())
    installed = {}
    for package in data["package"]:
        name = package["name"]
        if name == "app":
            continue
        try:
            installed[name] = version(name)
        except PackageNotFoundError:
            # uv's platform/extra alternatives need not be installed here.
            continue
    return dict(sorted(installed.items()))


def load_lock(path: Path) -> BuildLock:
    return BuildLock.model_validate_json(
        canonical(strict_json(read_checked(path, limit=1024 * 1024)))
    )


def validate_recipe(lock: BuildLock, *, require_payloads: bool = True) -> None:
    """Check environment/source pins before any acquisition or build mutation.

    Acquisition and new candidate recipes may omit generated payload hashes;
    strict reproduction must require them. Other recipe checks are identical.
    """
    if lock.python != python_version():
        raise ValueError("locked_python_mismatch")
    dependencies = dependency_versions()
    if (
        not {"httpx", "pydantic", "pillow", "mwparserfromhell"} <= set(dependencies)
        or lock.dependencies != dependencies
    ):
        raise ValueError("locked_dependencies_mismatch_or_incomplete")
    if not lock.code_sha256 or lock.code_sha256 != code_fingerprints():
        raise ValueError("locked_code_mismatch_or_incomplete")
    expected = dict.fromkeys(SNAPSHOT_FILES, "chronology")
    if lock.recipe == "catalogue-v1":
        expected[SUPPLEMENTS] = "supplements"
    if {s.path: s.role for s in lock.sources} != expected:
        raise ValueError("locked_source_scope_mismatch")
    if require_payloads and not REQUIRED_FILES - {"build.lock.json"} <= set(
        lock.payload_sha256
    ):
        raise ValueError("locked_payloads_incomplete")


def _supplements(root: Path) -> list[RawCandidate]:
    lines = read_checked(root / SUPPLEMENTS, limit=8 * 1024 * 1024).splitlines()
    if len(lines) != SUPPLEMENT_ROWS:
        raise ValueError("supplement_scope_mismatch")
    raws = []
    allowed = {
        "entity_id",
        "milestone",
        "category_ids",
        "region_ids",
        "entity",
        "page",
        "evidence",
        "snapshot_id",
        "source_id",
        "record_id",
    }
    required = {"entity_id", "milestone", "entity", "page", "evidence"}
    for line in lines:
        item = strict_json(line)
        if not isinstance(item, dict) or set(item) != {
            "source_id",
            "record_id",
            "payload",
        }:
            raise ValueError("source_only_envelope_required")
        payload = item["payload"]
        if (
            not isinstance(item["source_id"], str)
            or item["source_id"] not in {"wikidata", "wikipedia_en"}
            or not isinstance(item["record_id"], str)
            or not item["record_id"]
            or not isinstance(payload, dict)
            or not required <= set(payload) <= allowed
            or not isinstance(payload["entity"], dict)
            or not isinstance(payload["page"], dict)
            or not isinstance(payload["evidence"], list)
            or len(payload["evidence"]) != 2
            or not all(isinstance(e, dict) and e for e in payload["evidence"])
            or not isinstance(payload["entity_id"], str)
            or not re.fullmatch(r"Q[1-9]\d*", payload["entity_id"])
            or not isinstance(payload["milestone"], str)
        ):
            raise ValueError("source_only_envelope_with_evidence_required")
        for evidence in payload["evidence"]:
            fields = {
                "source_id",
                "sha256",
                "acquired_at",
                "snapshot_id",
                "url",
                "revision",
            }
            if (
                set(evidence) != fields
                or not all(isinstance(value, str) for value in evidence.values())
                or evidence["source_id"] not in {"wikidata", "wikipedia_en"}
                or not re.fullmatch(r"[0-9a-f]{64}", evidence["sha256"])
                or not evidence["snapshot_id"]
                or not evidence["url"]
            ):
                raise ValueError("source_only_evidence_fields_required")
            try:
                observed = datetime.fromisoformat(
                    evidence["acquired_at"].replace("Z", "+00:00")
                )
                if observed.utcoffset() is None:
                    raise ValueError("naive_source_observation")
            except ValueError as exc:
                raise ValueError("source_only_evidence_observation_required") from exc
        raws.append(RawCandidate(**item))
    if len({(r.source_id, r.record_id) for r in raws}) != len(raws):
        raise ValueError("duplicate_supplement_source_key")
    return raws


class _WholeInputAdapter:
    def __init__(self, raws: list[RawCandidate]) -> None:
        self.raws = tuple(raws)

    def fetch(self, snapshot_dir: Path) -> Iterable[RawCandidate]:
        return iter(self.raws)

    def normalize(self, raw: RawCandidate) -> EventRecord | tuple[ValidationIssue, ...]:
        return router.normalize(raw)


def compare_payloads(
    expected: Mapping[str, bytes], actual: Mapping[str, bytes]
) -> dict[str, object]:
    differing = sorted(
        name
        for name in expected.keys() | actual.keys()
        if expected.get(name) != actual.get(name)
    )

    def records(payloads: Mapping[str, bytes]) -> dict[str, Any]:
        return {
            row["event_id"]: row
            for line in payloads.get("events.jsonl", b"").splitlines()
            if (row := strict_json(line))
        }

    old, new = records(expected), records(actual)
    return {
        "matches": not differing,
        "differing_files": differing,
        "added_event_ids": sorted(new.keys() - old.keys()),
        "removed_event_ids": sorted(old.keys() - new.keys()),
        "changed_event_ids": sorted(
            key for key in old.keys() & new.keys() if old[key] != new[key]
        ),
    }


def _bundle(root: Path, release_id: str) -> dict[str, bytes]:
    if (root / "runtime-manifest.json").is_file():
        release, media = root, root.parent.parent / "media" / root.name
    else:
        release, media = root / "releases" / release_id, root / "media" / release_id
    checked = verify_runtime(release, media)
    return {
        **checked.files,
        "runtime-manifest.json": checked.manifest_bytes,
        **{f"media/{name}": data for name, data in checked.assets.items()},
    }


def _run(
    lock_path: Path,
    source_dir: Path,
    output: Path,
    *,
    expected_catalogue: Path | None,
    update: bool,
) -> dict[str, object]:
    lock = load_lock(lock_path)
    # All code/toolchain/recipe failures precede acquisition and workspace writes.
    validate_recipe(lock, require_payloads=not update)
    output = safe_output(output)
    # Check spelling BEFORE resolution, which would erase a symlink boundary.
    check_source_directory(lock, source_dir)
    source_dir = source_dir.resolve()
    if output.is_relative_to(source_dir):
        raise ValueError("output_inside_source_dir")
    if expected_catalogue is not None and output.is_relative_to(
        expected_catalogue.resolve()
    ):
        raise ValueError("output_inside_expected_catalogue")
    expected = (
        _bundle(expected_catalogue, lock.release_id)
        if expected_catalogue is not None
        else None
    )
    # Validate the complete raw scope before opening an importer workspace.
    chronology = list(OnThisDayAdapter().fetch(source_dir))
    if lock.recipe == "catalogue-v1" and len(chronology) != CHRONOLOGY_ROWS:
        raise ValueError("chronology_scope_mismatch")
    raws = chronology
    if lock.recipe == "catalogue-v1":
        raws += _supplements(source_dir)
    output.mkdir(parents=True)
    inputs = acquire_sources(lock, output / "inputs", source_dir=source_dir)
    workspace = output / "workspace"
    with locked_evaluation(lock.evaluation_date):
        imported = import_snapshot(_WholeInputAdapter(raws), inputs, workspace)
        selection = SourceSelection.model_validate_json(
            Path(__file__).with_name("source-selection.json").read_bytes()
        )
        pipeline.assign_chronology_media(selection, workspace)
        _, _, events, _ = pipeline._inputs(workspace)
        for event in events:
            if not event.identity_key.startswith("onthisday:"):
                pipeline.assign_media(event, selection, workspace, offline=True)
        receipts = pipeline.finalize_media_receipts(workspace)
        if not receipts or not all(receipt.passed for receipt in receipts):
            raise ValueError("replay_full_media_validation_failed")
        audit_id = "replay-audit"
        if lock.release_id == audit_id:
            raise ValueError("runtime_requires_new_release_id")
        publish_release(workspace, output / "audit", audit_id)
        audit = output / "audit" / audit_id
        verify_release(audit, audit / "media", require_beta=True)
        _, files, assets = runtime_payloads(audit, audit / "media")
        generated = {
            **files,
            **{f"media/{name}": body for name, body in assets.items()},
        }
        digests = {name: sha256(body) for name, body in generated.items()}
        if update:
            lock = lock.model_copy(update={"payload_sha256": digests})
        mismatched = sorted(
            name
            for name in digests.keys() | lock.payload_sha256.keys()
            if digests.get(name) != lock.payload_sha256.get(name)
        )
        if mismatched:
            result = (
                compare_payloads(expected, generated)
                if expected is not None
                else {
                    "matches": False,
                    "differing_files": mismatched,
                    "added_event_ids": [],
                    "removed_event_ids": [],
                    "changed_event_ids": [],
                }
            )
            result.update(
                {
                    "matches": False,
                    "locked_payload_mismatches": mismatched,
                    "error": "locked_payload_mismatch; runtime export refused",
                }
            )
        else:
            export_runtime(audit, audit / "media", output / "catalogue", lock)
            actual = _bundle(output / "catalogue", lock.release_id)
            result = compare_payloads(
                expected if expected is not None else actual, actual
            )
    result.update(
        {
            "release_id": lock.release_id,
            "audit_manifest_sha256": sha256(read_checked(audit / "manifest.json")),
            "audit_verified": True,
            "generated_at": datetime.now(UTC).isoformat(),
            "imported": imported.imported,
            "quarantined": imported.quarantined,
            "mode": "update-candidate" if update else "reproduce",
        }
    )
    with (output / "replay-report.json").open("xb") as stream:
        stream.write(canonical(result))
    return result


def reproduce(
    lock_path: Path,
    source_dir: Path,
    output: Path,
    *,
    expected_catalogue: Path | None,
) -> dict[str, object]:
    return _run(
        lock_path,
        source_dir,
        output,
        expected_catalogue=expected_catalogue,
        update=False,
    )


def update_candidate(
    lock_path: Path, source_dir: Path, output: Path
) -> dict[str, object]:
    """Explicit new recipe: seal actual verified payloads, never edit the input lock."""
    return _run(lock_path, source_dir, output, expected_catalogue=None, update=True)
