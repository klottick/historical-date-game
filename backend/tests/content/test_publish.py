"""Publication attacks use synthetic provider envelopes, never real beta claims."""

import copy
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.content.adapters.selected import SelectedSourceAdapter, digest
from app.content.importer import _sources
from app.content.media import pipeline
from app.content.publish import publish_release, verify_release
from app.content.schemas import EventRecord, MediaCatalog, ValidationReceipt
from app.content.validation import (
    candidate_digest,
    media_catalog_digest,
    validate_event,
)
from tests.content.test_importer import snapshot
from tests.content.test_media import SELECTION, batch, fake_download, with_image


def final_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch | None = None
) -> tuple[Path, Path]:
    if monkeypatch:
        workspace, events = with_image(tmp_path)
        monkeypatch.setattr(pipeline, "download_image", fake_download)
    else:
        workspace, events = batch(tmp_path)
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    assert all(r.passed for r in pipeline.finalize_media_receipts(workspace))
    pointer = json.loads((workspace / "media-current.json").read_text())
    return workspace, workspace / pointer["generation"]


def refresh(root: Path, filename: str = "manifest.json") -> None:
    """An attacker can rewrite unsigned hashes; semantic checks must still reject."""
    if filename == "manifest.json":
        refresh(root, "batch.json")
    data = json.loads((root / filename).read_text())
    for name in data["files"]:
        data["files"][name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    (root / filename).write_text(json.dumps(data))


def rewrite(path: Path, change: Any) -> None:
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def sync_receipts(root: Path) -> None:
    rows = json.loads((root / "validation.json").read_text())
    (root / "receipts.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )


def test_release_is_complete_and_immutable(tmp_path: Path) -> None:
    workspace, generation = final_batch(tmp_path)
    output = tmp_path / "releases"
    first = publish_release(workspace, output, "first", fixture=True)
    release = output / "first"
    assert first.event_count == 2 and first.fixture
    assert {
        "raw.jsonl",
        "sources.json",
        "decisions.json",
        "validation.json",
        "coverage.json",
    } <= set(first.files)
    assert verify_release(release, release / "media") == first
    with pytest.raises(ValueError, match="immutable"):
        publish_release(workspace, output, "first", fixture=True)
    for name in ("events.jsonl", "receipts.jsonl"):
        lines = (generation / name).read_text().splitlines()
        (generation / name).write_text("\n".join(reversed(lines)) + "\n")
    # Equivalent timestamp spelling must serialize through the typed contract.
    rows = [
        json.loads(line)
        for line in (generation / "events.jsonl").read_text().splitlines()
    ]
    for row in rows:
        for source in row["sources"]:
            source["acquired_at"] = source["acquired_at"].replace("Z", "+00:00")
    (generation / "events.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )
    rewrite(generation / "validation.json", lambda rows: rows.reverse())
    refresh(generation, "batch.json")
    second = publish_release(workspace, output, "second", fixture=True)
    assert first.files == second.files
    assert first.created_at != second.created_at
    coverage = json.loads((release / "coverage.json").read_text())
    assert coverage["distinct_years"] == 2
    assert coverage["images"] == 0 and coverage["fallback_events"] == 2
    assert coverage["categories"]["births"] == 1
    old = next((release / "media").glob("*.svg")).read_bytes()
    next((generation / "media").glob("*.svg")).write_bytes(b"changed source asset")
    with pytest.raises(ValueError, match="immutable"):
        publish_release(workspace, output, "first", fixture=True)
    assert next((release / "media").glob("*.svg")).read_bytes() == old


def test_complete_matching_machine_only_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, generation = final_batch(tmp_path, monkeypatch)
    # Independently rechecking rights must not depend on mutable C4 caches.
    assert list((generation / "media-cache" / "commons").glob("*.json"))
    release = tmp_path / "out" / "machine"
    manifest = publish_release(workspace, release.parent, release.name, fixture=True)
    assert verify_release(release, release / "media").files == manifest.files
    assert json.loads((release / "coverage.json").read_text())["images"] == 2


def test_publish_rejects_passed_content_only_receipt(tmp_path: Path) -> None:
    workspace, generation = final_batch(tmp_path)
    rewrite(
        generation / "validation.json",
        lambda rows: rows[0].update(stage="content", media_catalog_sha256=None),
    )
    sync_receipts(generation)
    refresh(generation, "batch.json")
    with pytest.raises(ValueError):
        publish_release(workspace, tmp_path / "out", "content", fixture=True)
    assert not (tmp_path / "out" / "content").exists()


@pytest.mark.parametrize("target", ["publish", "verify"])
@pytest.mark.parametrize(
    "kind,field,value",
    [
        ("records", "rights_basis", "GFDL"),
        ("records", "creator", "Changed photographer"),
        ("records", "attribution", "Missing credit"),
        ("records", "alt_text", "Changed alt"),
        ("records", "fit", "cover"),
        ("records", "source_revision", "Changed revision"),
        ("records", "filename", "../escape.webp"),
        ("records", "sha256", "b" * 64),
        ("fallbacks", "creator", "Changed provenance"),
        ("fallbacks", "rights_basis", "Unknown rights"),
        ("fallbacks", "alt_text", "Changed alt"),
        ("fallbacks", "filename", "/escape.svg"),
        ("fallbacks", "sha256", "c" * 64),
    ],
)
def test_changed_media_or_fallback_metadata_rejected_with_unchanged_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    kind: str,
    field: str,
    value: str,
) -> None:
    workspace, generation = final_batch(tmp_path, monkeypatch)
    root = generation
    if target == "verify":
        publish_release(workspace, tmp_path / "out", "changed", fixture=True)
        root = tmp_path / "out" / "changed"

    def change(data: dict[str, Any]) -> None:
        record = data["records"][0] if kind == "records" else data["fallbacks"]["birth"]
        record[field] = value

    rewrite(root / "media.json", change)
    refresh(root, "batch.json" if target == "publish" else "manifest.json")
    with pytest.raises(ValueError):
        if target == "publish":
            publish_release(workspace, tmp_path / "out", "changed", fixture=True)
        else:
            verify_release(root, root / "media")


@pytest.mark.parametrize("target", ["publish", "verify"])
@pytest.mark.parametrize("extension", ["webp", "svg"])
def test_altered_media_or_fallback_bytes_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str, extension: str
) -> None:
    workspace, generation = final_batch(tmp_path, monkeypatch)
    root = generation
    if target == "verify":
        publish_release(workspace, tmp_path / "out", "bytes", fixture=True)
        root = tmp_path / "out" / "bytes"
    next((root / "media").glob(f"*.{extension}")).write_bytes(b"altered real bytes")
    refresh(root, "batch.json" if target == "publish" else "manifest.json")
    with pytest.raises(ValueError):
        if target == "publish":
            publish_release(workspace, tmp_path / "out", "bytes", fixture=True)
        else:
            verify_release(root, root / "media")


@pytest.mark.parametrize(
    "attack",
    [
        "traversal",
        "absolute",
        "symlink",
        "parent_symlink",
        "identity",
        "missing",
        "count",
        "coverage",
    ],
)
def test_tampered_asset_or_path_escape_rejected(tmp_path: Path, attack: str) -> None:
    workspace, _ = final_batch(tmp_path)
    publish_release(workspace, tmp_path / "out", "secure", fixture=True)
    root = tmp_path / "out" / "secure"
    if attack in {"traversal", "absolute"}:
        rewrite(
            root / "manifest.json",
            lambda d: d["files"].update(
                {"../escape" if attack == "traversal" else "/escape": "a" * 64}
            ),
        )
    elif attack == "identity":
        rewrite(root / "manifest.json", lambda d: d.update(release_id="different"))
    elif attack == "count":
        rewrite(root / "manifest.json", lambda d: d.update(event_count=1000))
    elif attack == "coverage":
        rewrite(root / "coverage.json", lambda d: d.update(distinct_years=1000))
        refresh(root)
    elif attack == "missing":
        (root / "sources.json").unlink()
        rewrite(root / "manifest.json", lambda d: d["files"].pop("sources.json"))
    else:
        file = root / "events.jsonl"
        copy = tmp_path / "copy"
        copy.write_bytes(file.read_bytes())
        file.unlink()
        file.symlink_to(copy)
        if attack == "parent_symlink":
            linked = tmp_path / "linked"
            linked.symlink_to(root.parent, target_is_directory=True)
            root = linked / "secure"
    with pytest.raises(ValueError):
        verify_release(root, root / "media")


@pytest.mark.parametrize("target", ["publish", "verify"])
@pytest.mark.parametrize(
    "attack",
    [
        "rules",
        "decision_rules",
        "source",
        "raw",
        "taxonomy",
        "selection",
        "failed",
        "policy",
        "candidate",
        "missing_receipt",
        "pending",
        "duplicate",
        "identity_duplicate",
        "stale_content",
        "unlisted_asset",
        "public_raw",
    ],
)
def test_invalid_handoff_cannot_publish(
    tmp_path: Path, attack: str, target: str
) -> None:
    workspace, generation = final_batch(tmp_path)
    if target == "verify":
        publish_release(workspace, tmp_path / "out", "bad", fixture=True)
        generation = tmp_path / "out" / "bad"
    if attack == "rules":
        rewrite(
            generation / "batch.json", lambda d: d.update(media_rules_sha256="a" * 64)
        )
    elif attack == "decision_rules":
        rewrite(
            generation / "decisions.json",
            lambda d: next(iter(d.values())).update(media_rules_sha256="a" * 64),
        )
    elif attack == "source":
        rewrite(
            generation / "sources.json", lambda d: d.update(source_sha256=["a" * 64])
        )
    elif attack == "raw":
        rows = [
            json.loads(line)
            for line in (generation / "raw.jsonl").read_text().splitlines()
        ]
        rows[0]["payload"]["entity"]["labels"]["en"]["value"] = "Altered subject"
        (generation / "raw.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows)
        )
    elif attack == "taxonomy":
        rewrite(generation / "taxonomy.json", lambda d: d.pop())
    elif attack == "selection":
        rewrite(
            generation / "source-selection.json",
            lambda d: d.update(source_ids=["unselected"]),
        )
    elif attack == "stale_content":
        if target == "publish":
            rewrite(
                workspace / "current.json", lambda d: d.update(input_sha256="a" * 64)
            )
        else:
            rewrite(
                generation / "batch.json",
                lambda d: d.update(content_input_sha256="a" * 64),
            )
    elif attack in {"unlisted_asset", "public_raw"}:
        name = (
            "media/extra.svg"
            if attack == "unlisted_asset"
            else "media/encyclopedia.json"
        )
        (generation / name).write_text("private source prose must not be exposed")
        rewrite(
            generation / "batch.json",
            lambda d: d["files"].update(
                {name: hashlib.sha256((generation / name).read_bytes()).hexdigest()}
            ),
        )
        if target == "verify":
            rewrite(
                generation / "manifest.json",
                lambda d: d["files"].update(
                    {name: hashlib.sha256((generation / name).read_bytes()).hexdigest()}
                ),
            )
    elif attack in {"pending", "duplicate", "identity_duplicate"}:
        rows = [
            json.loads(line)
            for line in (generation / "events.jsonl").read_text().splitlines()
        ]
        if attack == "pending":
            rows[0]["review_status"] = "pending"
        elif attack == "duplicate":
            rows.append(rows[0])
        else:
            rows[1]["identity_key"] = rows[0]["identity_key"]
        (generation / "events.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows)
        )
    else:

        def change(rows: list[dict[str, Any]]) -> None:
            if attack == "missing_receipt":
                rows.pop()
            else:
                rows[0].update(
                    {
                        "failed": {"passed": False},
                        "policy": {"policy_version": "obsolete"},
                        "candidate": {"candidate_sha256": "a" * 64},
                    }[attack]
                )

        rewrite(generation / "validation.json", change)
        sync_receipts(generation)
    refresh(generation, "batch.json" if target == "publish" else "manifest.json")
    with pytest.raises(ValueError):
        if target == "publish":
            publish_release(workspace, tmp_path / "out", "bad", fixture=True)
        else:
            verify_release(generation, generation / "media")


def test_beta_gate_counts_approved_distinct_events(tmp_path: Path) -> None:
    workspace, _ = final_batch(tmp_path)
    publish_release(workspace, tmp_path / "out", "fixture", fixture=True)
    root = tmp_path / "out" / "fixture"
    with pytest.raises(ValueError, match="beta"):
        verify_release(root, root / "media", require_beta=True)
    with pytest.raises(ValueError, match="beta"):
        publish_release(workspace, tmp_path / "out", "small")


def test_cli_import_media_publish_verify_and_fail_closed(tmp_path: Path) -> None:
    root = snapshot(tmp_path)
    workspace = tmp_path / "cli-work"
    selection = "../docs/research/source-selection.json"

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "app.content.cli", *args],
            capture_output=True,
            text=True,
        )

    imported = run(
        "import",
        "--selection",
        selection,
        "--snapshot",
        str(root),
        "--workspace",
        str(workspace),
    )
    assert imported.returncode == 0, imported.stderr
    assert json.loads(imported.stdout)["quarantined"] == 0
    assert (
        run(
            "publish",
            "--workspace",
            str(workspace),
            "--output",
            str(tmp_path / "out"),
            "--release-id",
            "premature",
            "--fixture",
        ).returncode
        != 0
    )
    media = run("media", "--selection", selection, "--workspace", str(workspace))
    assert media.returncode == 0, media.stderr
    assert json.loads(media.stdout) == {"events": 2, "passed": 2, "failed": 0}
    result = run(
        "publish",
        "--workspace",
        str(workspace),
        "--output",
        str(tmp_path / "out"),
        "--release-id",
        "cli",
        "--fixture",
    )
    assert result.returncode == 0, result.stderr
    release = tmp_path / "out" / "cli"
    assert (
        run(
            "verify", "--release", str(release), "--media", str(release / "media")
        ).returncode
        == 0
    )
    assert (
        run(
            "verify",
            "--release",
            str(release),
            "--media",
            str(release / "media"),
            "--require-beta",
        ).returncode
        != 0
    )


def synthetic_gate_batch(tmp_path: Path, count: int) -> Path:
    """Build typed frozen shapes for gate tests, NOT a real beta corpus/C4 load test.

    Every synthetic event is independently normalized from cached provider-shaped
    bytes. No monkeypatch skips C5 validators; only the large C4 staging loop is
    represented by its persisted handoff shape.
    """
    workspace, generation = final_batch(tmp_path)
    seed = json.loads(Path("tests/fixtures/content/source-snapshot.json").read_text())
    entities, pages, records = {}, [], []
    for i in range(count):
        qid = f"Q{910000 + i}"
        # Long unrelated alphabetic names avoid fuzzy duplicates and year leaks.
        name = "Synthetic " + "".join(
            chr(65 + int(c, 16))
            for c in hashlib.sha256(str(i).encode()).hexdigest()[:48]
        )
        entity = copy.deepcopy(seed["entity"])
        entity["id"] = qid
        entity["labels"]["en"]["value"] = name
        entity["claims"]["P569"][0]["id"] = qid + "$birth"
        entities[qid] = entity
        page = copy.deepcopy(seed["page"])
        page.update(pageid=910000 + i, title=name, pageprops={"wikibase_item": qid})
        pages.append(page)
        records.append(
            {
                "source_id": "wikidata",
                "record_id": f"synthetic-{i}",
                "entity_id": qid,
                "milestone": "birth",
                "category_ids": ["births"],
                "region_ids": ["synthetic"],
            }
        )
    root = tmp_path / "gate-snapshot"
    root.mkdir()
    requests = []
    specs = json.loads((tmp_path / "snapshot" / "snapshot.json").read_text())[
        "requests"
    ]
    for spec, body in zip(
        specs, ({"entities": entities}, {"query": {"pages": pages}}), strict=True
    ):
        data = json.dumps(body).encode()
        (root / spec["file"]).write_bytes(data)
        requests.append({**spec, "sha256": hashlib.sha256(data).hexdigest()})
    (root / "snapshot.json").write_text(
        json.dumps(
            {
                "snapshot_id": "synthetic-gate-only",
                "requests": requests,
                "records": records,
            }
        )
    )
    adapter = SelectedSourceAdapter()
    raws = list(adapter.fetch(root))
    originals = []
    for raw in raws:
        event = adapter.normalize(raw)
        assert isinstance(event, EventRecord)
        taxonomy = tuple(
            pipeline.CategoryRecord.model_validate_json(json.dumps(row))
            for row in json.loads((generation / "taxonomy.json").read_text())
        )
        assert not validate_event(event, taxonomy, 2026)
        originals.append(event)
    events = [e.model_copy(update={"fallback_key": "birth"}) for e in originals]
    catalog = MediaCatalog.model_validate_json((generation / "media.json").read_bytes())
    source_data = {
        "input_sha256": digest([r.payload for r in raws]),
        "source_sha256": _sources(raws),
        "records": {
            json.dumps([r.source_id, r.record_id], separators=(",", ":")): {
                "raw_sha256": digest(
                    {
                        "source_id": r.source_id,
                        "record_id": r.record_id,
                        "payload": r.payload,
                    }
                ),
                "evidence": r.payload["evidence"],
            }
            for r in raws
        },
    }
    aliases = {
        json.dumps([r.source_id, r.record_id], separators=(",", ":")): {
            "identity_key": e.identity_key,
            "event_id": str(e.event_id),
        }
        for r, e in zip(raws, events, strict=True)
    }
    receipts = [
        ValidationReceipt(
            event_id=e.event_id,
            candidate_sha256=candidate_digest(e),
            source_sha256=_sources([raw]),
            policy_version="automated-v1",
            stage="content_media",
            media_catalog_sha256=media_catalog_digest(catalog),
            passed=True,
            checked_at=datetime.now(UTC),
            issue_codes=(),
        )
        for e, raw in zip(events, raws, strict=True)
    ]
    template = next(
        iter(json.loads((generation / "decisions.json").read_text()).values())
    )
    decisions = {
        str(e.event_id): {
            **template,
            "event_id": str(e.event_id),
            "input_candidate_sha256": candidate_digest(original),
            "candidate_sha256": candidate_digest(e),
            "source_sha256": _sources([raw]),
            "fallback_key": "birth",
        }
        for e, original, raw in zip(events, originals, raws, strict=True)
    }
    payloads = {
        "raw.jsonl": "".join(
            json.dumps(
                {
                    "source_id": r.source_id,
                    "record_id": r.record_id,
                    "payload": r.payload,
                }
            )
            + "\n"
            for r in raws
        ),
        "candidates.jsonl": "".join(e.model_dump_json() + "\n" for e in originals),
        "events.jsonl": "".join(e.model_dump_json() + "\n" for e in events),
        "sources.json": json.dumps(source_data),
        "aliases.json": json.dumps(aliases),
        "validation.json": json.dumps([r.model_dump(mode="json") for r in receipts]),
        "receipts.jsonl": "".join(r.model_dump_json() + "\n" for r in receipts),
        "decisions.json": json.dumps(decisions),
    }
    current = json.loads((workspace / "current.json").read_text())
    for name, text in payloads.items():
        (generation / name).write_text(text)
        if name in {"raw.jsonl", "candidates.jsonl", "sources.json", "aliases.json"}:
            (workspace / current["generation"] / name).write_text(text)
    rewrite(
        workspace / "current.json",
        lambda d: d.update(input_sha256=source_data["input_sha256"]),
    )
    rewrite(
        workspace / "media-current.json",
        lambda d: d.update(content_input_sha256=source_data["input_sha256"]),
    )
    rewrite(
        generation / "batch.json",
        lambda d: d.update(
            content_input_sha256=source_data["input_sha256"], event_count=count
        ),
    )
    refresh(generation, "batch.json")
    return workspace


@pytest.mark.parametrize("count", [999, 1000])
def test_beta_boundary_independently_validates_synthetic_shapes(
    tmp_path: Path, count: int
) -> None:
    workspace = synthetic_gate_batch(tmp_path, count)
    output = tmp_path / "out"
    if count == 999:
        with pytest.raises(ValueError, match="beta"):
            publish_release(workspace, output, "nonfixture")
        publish_release(workspace, output, "fixture", fixture=True)
        # Even falsely claiming nonfixture cannot get 999 accepted events through.
        rewrite(output / "fixture" / "manifest.json", lambda d: d.update(fixture=False))
        with pytest.raises(ValueError, match="beta"):
            verify_release(
                output / "fixture", output / "fixture" / "media", require_beta=True
            )
    else:
        manifest = publish_release(workspace, output, "synthetic-test-only")
        release = output / "synthetic-test-only"
        assert (
            verify_release(release, release / "media", require_beta=True).event_count
            == 1000
        )
        assert manifest.event_count == 1000
        rewrite(release / "manifest.json", lambda d: d.update(fixture=True))
        with pytest.raises(ValueError, match="beta"):
            verify_release(release, release / "media", require_beta=True)


@pytest.mark.parametrize(
    "attack", ["absolute", "traversal", "parent_symlink", "workspace_symlink"]
)
def test_cli_import_rejects_noncanonical_snapshot_paths(
    tmp_path: Path, attack: str
) -> None:
    from app.content.cli import main

    root = snapshot(tmp_path)
    workspace = tmp_path / "unsafe-work"
    if attack == "workspace_symlink":
        real = tmp_path / "real-work"
        real.mkdir()
        workspace.mkdir()
        (workspace / ".import.lock").symlink_to(real / "lock")
    elif attack == "parent_symlink":
        (root / "alias").symlink_to(root, target_is_directory=True)
        rewrite(
            root / "snapshot.json",
            lambda d: d["requests"][0].update(file="alias/wikidata.json"),
        )
    else:
        value = (
            str(root / "wikidata.json")
            if attack == "absolute"
            else "../snapshot/wikidata.json"
        )
        rewrite(root / "snapshot.json", lambda d: d["requests"][0].update(file=value))
    assert (
        main(
            [
                "import",
                "--selection",
                "../docs/research/source-selection.json",
                "--snapshot",
                str(root),
                "--workspace",
                str(workspace),
            ]
        )
        == 1
    )
    assert not (workspace / "current.json").exists()


@pytest.mark.parametrize("target", ["publish", "verify"])
@pytest.mark.parametrize(
    "attack",
    [
        "unused_fallback",
        "rights_snapshot",
        "original_snapshot",
        "source_receipt",
        "content_receipt",
        "source_rights",
        "alias",
    ],
)
def test_independent_private_provenance_and_all_fallback_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str, attack: str
) -> None:
    workspace, root = final_batch(tmp_path, monkeypatch)
    if target == "verify":
        publish_release(workspace, tmp_path / "out", "evidence", fixture=True)
        root = tmp_path / "out" / "evidence"
    if attack == "unused_fallback":
        catalog = json.loads((root / "media.json").read_text())
        name = catalog["fallbacks"]["politics"]["filename"]
        (root / name).unlink()
        rewrite(root / "batch.json", lambda d: d["files"].pop(name))
        if target == "verify":
            rewrite(root / "manifest.json", lambda d: d["files"].pop(name))
    elif attack == "rights_snapshot":
        path = next((root / "media-cache/commons").glob("*.json"))
        path.write_text("{}")
    elif attack == "original_snapshot":
        next((root / "media-cache/originals").glob("*.bin")).write_bytes(b"new bytes")
    elif attack == "source_receipt":
        rewrite(
            root / "validation.json", lambda d: d[0].update(source_sha256=["a" * 64])
        )
        sync_receipts(root)
    elif attack == "content_receipt":
        rewrite(
            root / "validation.json",
            lambda d: d[0].update(stage="content", media_catalog_sha256=None),
        )
        sync_receipts(root)
    elif attack == "source_rights":
        rows = [
            json.loads(line)
            for line in (root / "events.jsonl").read_text().splitlines()
        ]
        rows[0]["sources"][0]["rights_basis"] = "No attribution obligations"
        (root / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    else:
        rewrite(
            root / "aliases.json",
            lambda d: next(iter(d.values())).update(
                event_id="00000000-0000-0000-0000-000000000000"
            ),
        )
    refresh(root, "batch.json" if target == "publish" else "manifest.json")
    with pytest.raises(ValueError):
        if target == "publish":
            publish_release(workspace, tmp_path / "out", "evidence", fixture=True)
        else:
            verify_release(root, root / "media")


def test_atomic_failure_never_exposes_partial_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.content import publish

    workspace, _ = final_batch(tmp_path)
    writer = publish._write_bytes

    def fail(path: Path, data: bytes) -> None:
        if path.name == "manifest.json":
            raise OSError("synthetic write failure")
        writer(path, data)

    monkeypatch.setattr(publish, "_write_bytes", fail)
    output = tmp_path / "atomic"
    with pytest.raises(OSError, match="synthetic"):
        publish_release(workspace, output, "incomplete", fixture=True)
    assert not (output / "incomplete").exists()
    assert not list(output.glob(".release-*"))
