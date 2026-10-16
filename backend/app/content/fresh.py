"""Public chronology to a new playable catalogue; no historical/private inputs.

The upstream snapshot is pinned for integrity, not to require equality with an
old game release. New observations, code and eligibility dates create new data.
Raw downloads and full audit evidence stay in caller-owned scratch, outside Git.
"""

from datetime import UTC, datetime
from pathlib import Path
from platform import python_version
from typing import Any

from app.content.adapters import onthisday
from app.content.build_context import locked_evaluation
from app.content.importer import import_snapshot
from app.content.media import pipeline
from app.content.publish import canonical, publish_release, verify_release
from app.content.rebuild import code_fingerprints, dependency_versions
from app.content.runtime import (
    read_checked,
    sha256,
    strict_json,
    verify_default,
    verify_runtime,
)
from app.content.runtime_export import export_runtime, runtime_payloads
from app.content.runtime_models import (
    BuildLock,
    DefaultPointer,
    LockedSource,
    release_component,
)
from app.content.schemas import SourceSelection
from app.content.source_acquisition import _download, safe_output

# Metadata of the three approved public objects; not a required accepted-row count.
SOURCE_SIZES = {"events.jsonl": 6626097, "README.md": 2279, "NOTICE.md": 17663}


def build_fresh(output: Path, release_id: str) -> dict[str, Any]:
    """Download public sources and build a new isolated, verified runtime root.

    Always downloads; no old catalogue, source cache, .env or database is read.
    The only default pointer written belongs to the newly created output root.
    Never activate it or overwrite another build, release or installation.
    """
    release_id = release_component(release_id)
    output = safe_output(output)
    bodies = {}
    retrieved = {}
    for name, digest in onthisday.PINNED_FILES.items():
        source = LockedSource(
            path=name,
            sha256=digest,
            size=SOURCE_SIZES[name],
            url=onthisday.download_url(name),
            role="chronology",
        )
        bodies[name] = _download(source)
        retrieved[name] = {
            "sha256": digest,
            "bytes": len(bodies[name]),
            "status": 200,
            "url": source.url,
        }
    now = datetime.now(UTC)
    bodies["download-receipt.json"] = canonical(
        {
            "repository": onthisday.REPOSITORY,
            "commit": onthisday.COMMIT,
            "retrieved_at": now.isoformat(),
            "files": retrieved,
        }
    )
    # Create-only even if another writer appeared during the network requests.
    output.mkdir(parents=True)
    inputs = output / "inputs"
    inputs.mkdir()
    for name, body in bodies.items():
        with (inputs / name).open("xb") as stream:
            stream.write(body)
    audit_id = release_id + "-audit"
    audit = output / "audit" / audit_id
    with locked_evaluation(now.date()):
        imported = import_snapshot(
            onthisday.OnThisDayAdapter(), inputs, output / "workspace"
        )
        selection = SourceSelection.model_validate_json(
            Path(__file__).with_name("source-selection.json").read_bytes()
        )
        pipeline.assign_chronology_media(selection, output / "workspace")
        receipts = pipeline.finalize_media_receipts(output / "workspace")
        if not receipts or not all(receipt.passed for receipt in receipts):
            raise ValueError("fresh_full_media_validation_failed")
        publish_release(output / "workspace", output / "audit", audit_id)
        verify_release(audit, audit / "media", require_beta=True)
        _, files, assets = runtime_payloads(audit, audit / "media")
        lock = BuildLock(
            recipe="chronology-fresh-v1",
            release_id=release_id,
            created_at=now,
            evaluation_date=now.date(),
            origin_release_id=audit_id,
            origin_manifest_sha256=sha256(read_checked(audit / "manifest.json")),
            python=python_version(),
            dependencies=dependency_versions(),
            code_sha256=code_fingerprints(),
            sources=tuple(
                LockedSource(
                    path=name,
                    sha256=sha256(body),
                    size=len(body),
                    url=onthisday.download_url(name)
                    if name in onthisday.PINNED_FILES
                    else None,
                    role="chronology",
                )
                for name, body in sorted(bodies.items())
            ),
            payload_sha256={
                **{name: sha256(body) for name, body in files.items()},
                **{f"media/{name}": sha256(body) for name, body in assets.items()},
            },
        )
        manifest = export_runtime(audit, audit / "media", output / "catalogue", lock)
    manifest_bytes = read_checked(
        output / "catalogue/releases" / release_id / "runtime-manifest.json"
    )
    # Verify before exposing even this output-local install pointer.
    verify_runtime(
        output / "catalogue/releases" / release_id,
        output / "catalogue/media" / release_id,
        require_beta=True,
    )
    pointer = DefaultPointer(
        release_id=release_id, manifest_sha256=sha256(manifest_bytes)
    )
    with (output / "catalogue/default.json").open("xb") as stream:
        stream.write(canonical(pointer.model_dump(mode="json")))
    verify_default(output / "catalogue")
    coverage = strict_json(read_checked(audit / "coverage.json"))
    report = {
        "mode": "fresh",
        "recipe": lock.recipe,
        "release_id": release_id,
        "event_count": manifest.event_count,
        "raw_count": len(
            read_checked(audit / "raw.jsonl", limit=64 * 1024 * 1024).splitlines()
        ),
        "quarantined": imported.quarantined,
        "coverage": coverage,
        "source_repository": onthisday.REPOSITORY,
        "source_commit": onthisday.COMMIT,
        "retrieved_at": now.isoformat(),
        "manifest_sha256": pointer.manifest_sha256,
        "catalogue": "catalogue",
        "limitations": [
            "Chronology only; no legacy birth supplements or photographs.",
            "Automatic category heuristics; not historical or legal clearance.",
        ],
    }
    with (output / "build-report.json").open("xb") as stream:
        stream.write(canonical(report))
    return report
