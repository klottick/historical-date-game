"""Pure synthetic boundary tests; these make no historical acceptance claims."""

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from app.content.publish import canonical, publish_release, verify_release
from tests.content.test_publish import final_batch


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_checked_read_allows_access_time_update(tmp_path: Path) -> None:
    from app.content.runtime import read_checked

    path = tmp_path / "payload"
    path.write_bytes(b"unchanged content")
    os.utime(path, ns=(1, path.stat().st_mtime_ns))
    assert read_checked(path) == b"unchanged content"


def prepared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch | None = None
) -> tuple[Path, Path, Any]:
    from app.content.build_context import evaluation_date
    from app.content.runtime_export import runtime_payloads
    from app.content.runtime_models import BuildLock

    workspace, _ = final_batch(tmp_path, monkeypatch)
    audit = tmp_path / "audit/origin"
    publish_release(workspace, audit.parent, audit.name, fixture=True)
    _, files, assets = runtime_payloads(audit, audit / "media")
    lock = BuildLock(
        release_id="portable-v1",
        created_at=datetime(2026, 10, 16, tzinfo=UTC),
        evaluation_date=evaluation_date(),
        origin_release_id="historical-origin",
        origin_manifest_sha256="a" * 64,
        python="3.15",
        dependencies={"pydantic": "2.14.0"},
        code_sha256={"app/content/publish.py": "b" * 64},
        sources=(),
        payload_sha256={
            **{name: sha(data) for name, data in files.items()},
            **{f"media/{name}": sha(data) for name, data in assets.items()},
        },
    )
    return audit, tmp_path / "catalogue", lock


def exported(tmp_path: Path) -> tuple[Path, Path]:
    from app.content.runtime_export import export_runtime

    audit, root, lock = prepared(tmp_path)
    export_runtime(audit, audit / "media", root, lock)
    return root / "releases/portable-v1", root / "media/portable-v1"


def rewrite(path: Path, change: Any) -> None:
    value = json.loads(path.read_bytes())
    change(value)
    path.write_bytes(canonical(value))


def reseal(release: Path, media: Path) -> None:
    """Rehash attacker changes: hashes alone cannot satisfy semantic tests."""
    manifest = json.loads((release / "runtime-manifest.json").read_bytes())
    lock = json.loads((release / "build.lock.json").read_bytes())
    lock["payload_sha256"] = {
        **{
            name: sha((release / name).read_bytes())
            for name in manifest["files"]
            if name != "build.lock.json"
        },
        **{
            f"media/{name}": sha((media / name).read_bytes())
            for name in manifest["media"]
        },
    }
    (release / "build.lock.json").write_bytes(canonical(lock))
    manifest["files"] = {
        name: sha((release / name).read_bytes()) for name in manifest["files"]
    }
    manifest["media"] = {
        name: sha((media / name).read_bytes()) for name in manifest["media"]
    }
    manifest["content_sha256"] = sha(
        canonical({"files": manifest["files"], "media": manifest["media"]})
    )
    (release / "runtime-manifest.json").write_bytes(canonical(manifest))


def test_verified_runtime_round_trip(tmp_path: Path) -> None:
    from app.content.runtime import verify_runtime

    release, media = exported(tmp_path)
    snapshot = verify_runtime(
        release,
        media,
        expected_sha256=sha((release / "runtime-manifest.json").read_bytes()),
    )
    assert snapshot.manifest.event_count == 2
    assert snapshot.manifest.kind == "runtime-catalogue"
    assert len(snapshot.events) == 2 and len(snapshot.categories) == 8
    assert len(snapshot.media.fallbacks) == 8
    assert set(snapshot.files) == {
        "events.jsonl",
        "taxonomy.json",
        "media.json",
        "source-selection.json",
        "attribution.json",
        "build.lock.json",
        "LICENSE.catalog.txt",
        "NOTICE.catalog.md",
    }
    with pytest.raises(ValueError, match="beta"):
        verify_runtime(release, media, require_beta=True)
    saved = snapshot.files["events.jsonl"]
    (release / "events.jsonl").write_bytes(b"changed after verification")
    assert snapshot.files["events.jsonl"] == saved
    with pytest.raises(TypeError):
        snapshot.files["events.jsonl"] = b"mutated"  # type: ignore[index]  # deliberately test immutability
    snapshot.manifest.files.clear()
    snapshot.media.fallbacks.clear()
    assert len(snapshot.manifest.files) == 8 and len(snapshot.media.fallbacks) == 8


@pytest.mark.parametrize(
    "attack",
    [
        "year",
        "future",
        "pending",
        "precision",
        "source",
        "source_rights",
        "source_url",
        "category",
        "duplicate",
        "identity",
        "zero_id",
        "fallback",
        "media",
        "unknown",
        "count",
        "taxonomy",
        "selection",
        "daily",
        "license",
        "notice",
        "attribution",
        "fallback_rights",
        "fallback_missing",
    ],
)
def test_semantic_mutation_with_rehashed_manifest_rejected(
    tmp_path: Path, attack: str
) -> None:
    from app.content.runtime import verify_runtime

    release, media = exported(tmp_path)
    rows = [
        json.loads(line)
        for line in (release / "events.jsonl").read_bytes().splitlines()
    ]
    fields = {
        "year": ("year_index", 42),
        "future": ("year_index", 9000),
        "pending": ("review_status", "pending"),
        "precision": ("date_precision", "fuzzy"),
        "category": ("category_ids", ["unknown"]),
        "fallback": ("fallback_key", "absent"),
        "media": ("media_asset_id", "00000000-0000-0000-0000-000000000001"),
        "unknown": ("extra", True),
        "zero_id": ("event_id", "00000000-0000-0000-0000-000000000000"),
    }
    if attack in fields:
        key, value = fields[attack]
        rows[0][key] = value
    elif attack in {"source", "source_rights", "source_url"}:
        key, value = {
            "source": ("source_id", "unselected"),
            "source_rights": ("rights_basis", "Unknown rights"),
            "source_url": ("url", "file:///private"),
        }[attack]
        rows[0]["sources"][0][key] = value
    elif attack == "duplicate":
        rows.append(rows[0])
    elif attack == "identity":
        rows[1]["identity_key"] = rows[0]["identity_key"]
    elif attack == "count":
        rewrite(release / "runtime-manifest.json", lambda d: d.update(event_count=1000))
    elif attack == "taxonomy":
        rewrite(release / "taxonomy.json", lambda d: d.pop())
    elif attack in {"selection", "daily"}:
        rewrite(
            release / "source-selection.json",
            lambda d: d.update(
                **(
                    {"source_ids": ["unselected"]}
                    if attack == "selection"
                    else {"daily_category_ids": ["births"]}
                )
            ),
        )
    elif attack in {"license", "notice"}:
        (
            release
            / ("LICENSE.catalog.txt" if attack == "license" else "NOTICE.catalog.md")
        ).write_bytes(b"no attribution\n")
    elif attack == "attribution":
        rewrite(release / "attribution.json", lambda d: d.update(extra="private"))
    elif attack == "fallback_rights":
        rewrite(
            release / "media.json",
            lambda d: d["fallbacks"]["birth"].update(rights_basis="Unknown"),
        )
    elif attack == "fallback_missing":
        rewrite(release / "media.json", lambda d: d["fallbacks"].pop("politics"))
    (release / "events.jsonl").write_bytes(b"".join(canonical(row) for row in rows))
    reseal(release, media)
    with pytest.raises(ValueError):
        verify_runtime(release, media)


def test_runtime_is_not_audit_release(tmp_path: Path) -> None:
    release, media = exported(tmp_path)
    with pytest.raises((ValueError, OSError)):
        verify_release(release, media)


@pytest.mark.parametrize(
    "attack",
    [
        "duplicate_json",
        "nonfinite",
        "traversal",
        "absolute",
        "symlink",
        "parent_symlink",
        "hardlink",
        "fifo",
        "missing",
        "extra",
        "extra_dir",
        "asset_extra",
        "asset_corrupt",
        "file_corrupt",
        "schema",
        "identity",
        "manifest_digest",
        "file_size",
        "total_size",
    ],
)
def test_runtime_rejects_duplicate_json_and_unsafe_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack: str
) -> None:
    from app.content import runtime

    release, media = exported(tmp_path)
    path = release / "events.jsonl"
    if attack in {"duplicate_json", "nonfinite"}:
        replacement = (
            b'"year_index":0,"year_index":'
            if attack == "duplicate_json"
            else b'"bad":NaN,"year_index":'
        )
        path.write_bytes(path.read_bytes().replace(b'"year_index":', replacement, 1))
        reseal(release, media)
    elif attack in {"traversal", "absolute"}:
        rewrite(
            release / "runtime-manifest.json",
            lambda d: d["files"].update(
                {"../escape" if attack == "traversal" else "/escape": "a" * 64}
            ),
        )
    elif attack in {"symlink", "hardlink", "fifo"}:
        copy = tmp_path / "saved"
        copy.write_bytes(path.read_bytes())
        path.unlink()
        if attack == "symlink":
            path.symlink_to(copy)
        elif attack == "hardlink":
            os.link(copy, path)
        else:
            os.mkfifo(path)
    elif attack == "parent_symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(release.parent, target_is_directory=True)
        release = alias / release.name
    elif attack == "missing":
        path.unlink()
    elif attack == "extra":
        (release / "raw.jsonl").write_bytes(b"private")
    elif attack == "extra_dir":
        (release / "private").mkdir()
    elif attack == "asset_extra":
        (media / "extra.svg").write_bytes(b"extra")
    elif attack == "asset_corrupt":
        next(media.iterdir()).write_bytes(b"changed")
    elif attack == "file_corrupt":
        path.write_bytes(b"changed")
    elif attack in {"schema", "identity"}:
        rewrite(
            release / "runtime-manifest.json",
            lambda d: d.update(
                **(
                    {"schema_version": 2}
                    if attack == "schema"
                    else {"release_id": "different"}
                )
            ),
        )
    elif attack == "file_size":
        monkeypatch.setattr(runtime, "MAX_FILE_BYTES", 100)
    elif attack == "total_size":
        monkeypatch.setattr(runtime, "MAX_TOTAL_BYTES", 100)
    with pytest.raises(ValueError):
        runtime.verify_runtime(
            release,
            media,
            expected_sha256="a" * 64 if attack == "manifest_digest" else None,
        )


def test_export_requires_full_verification(tmp_path: Path) -> None:
    from app.content.runtime_export import export_runtime, runtime_payloads

    audit, root, lock = prepared(tmp_path)
    (audit / "raw.jsonl").write_bytes(b"apparently approved is not proof")
    with pytest.raises(ValueError):
        runtime_payloads(audit, audit / "media")
    with pytest.raises(ValueError):
        export_runtime(audit, audit / "media", root, lock)
    assert not root.exists()


@pytest.mark.parametrize("interface", ["api", "cli"])
def test_standalone_export_uses_lock_date(tmp_path: Path, interface: str) -> None:
    from app.content.build_context import evaluation_date, locked_evaluation
    from app.content.runtime import verify_runtime
    from app.content.runtime_export import export_runtime

    today = evaluation_date()
    with locked_evaluation(date(2026, 10, 14)):
        audit, root, lock = prepared(tmp_path)
    assert evaluation_date() == today
    # No ambient locked context: the exporter must establish its own lock date.
    if interface == "api":
        export_runtime(audit, audit / "media", root, lock)
    else:
        path = tmp_path / "lock.json"
        path.write_bytes(canonical(lock.model_dump(mode="json")))
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.content.cli",
                "runtime-export",
                "--release",
                str(audit),
                "--media",
                str(audit / "media"),
                "--output",
                str(root),
                "--lock",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    assert evaluation_date() == today
    assert (
        verify_runtime(
            root / "releases/portable-v1", root / "media/portable-v1"
        ).manifest.event_count
        == 2
    )
    # Unlocked audit verification still uses today's rules, not the last export.
    with pytest.raises(ValueError, match="stale_media_rules"):
        verify_release(audit, audit / "media")


def test_export_lock_context_resets_after_failure(tmp_path: Path) -> None:
    from app.content.build_context import evaluation_date, locked_evaluation
    from app.content.runtime_export import export_runtime

    with locked_evaluation(date(2026, 10, 14)):
        audit, root, lock = prepared(tmp_path)
    # A different explicit date must fail full verification, not waive fingerprints.
    wrong = lock.model_copy(update={"evaluation_date": date(2026, 10, 13)})
    with locked_evaluation(date(2026, 10, 15)):
        with pytest.raises(ValueError, match="stale_media_rules"):
            export_runtime(audit, audit / "media", root, wrong)
        assert evaluation_date() == date(2026, 10, 15)
        assert not root.exists()
        export_runtime(audit, audit / "media", root, lock)
        assert evaluation_date() == date(2026, 10, 15)


def test_export_is_create_only(tmp_path: Path) -> None:
    from app.content.runtime_export import export_runtime

    audit, root, lock = prepared(tmp_path)
    export_runtime(audit, audit / "media", root, lock)
    release = root / "releases/portable-v1"
    before = (release / "runtime-manifest.json").read_bytes()
    with pytest.raises(ValueError, match="exists"):
        export_runtime(audit, audit / "media", root, lock)
    assert (release / "runtime-manifest.json").read_bytes() == before
    assert not (root / "default.json").exists()


def test_origin_reference_and_timestamp_are_locked(tmp_path: Path) -> None:
    from app.content.runtime import verify_runtime
    from app.content.runtime_export import export_runtime

    audit, root, lock = prepared(tmp_path)
    export_runtime(audit, audit / "media", root, lock)
    snapshot = verify_runtime(root / "releases/portable-v1", root / "media/portable-v1")
    assert snapshot.manifest.created_at == datetime(2026, 10, 16, tzinfo=UTC)
    assert snapshot.manifest.origin_release_id == "historical-origin"
    assert snapshot.manifest.origin_manifest_sha256 == "a" * 64
    second = tmp_path / "second"
    rewrite(
        audit / "manifest.json", lambda d: d.update(created_at="2026-10-17T00:00:00Z")
    )
    export_runtime(audit, audit / "media", second, lock)
    for path in root.rglob("*"):
        if path.is_file() and not path.name.startswith("."):
            assert path.read_bytes() == (second / path.relative_to(root)).read_bytes()


@pytest.mark.parametrize("attack", ["digest", "missing", "extra", "same_id"])
def test_export_rejects_bad_lock(tmp_path: Path, attack: str) -> None:
    from app.content.runtime_export import export_runtime

    audit, root, lock = prepared(tmp_path)
    value = lock.model_dump(mode="json")
    if attack == "same_id":
        value["release_id"] = audit.name
    elif attack == "digest":
        value["payload_sha256"]["events.jsonl"] = "0" * 64
    elif attack == "missing":
        value["payload_sha256"].pop("events.jsonl")
    else:
        value["payload_sha256"]["extra.json"] = "0" * 64
    with pytest.raises(ValueError):
        export_runtime(
            audit,
            audit / "media",
            root,
            type(lock).model_validate_json(json.dumps(value)),
        )
    assert not root.exists()


@pytest.mark.parametrize(
    "pointer",
    [
        {},
        {"release_id": "../escape", "manifest_sha256": "a" * 64},
        {"release_id": "portable-v1", "manifest_sha256": "a" * 64},
        {"release_id": "portable-v1", "manifest_sha256": "a" * 64, "extra": 1},
    ],
)
def test_default_pointer_fails_closed(tmp_path: Path, pointer: dict[str, Any]) -> None:
    from app.content.runtime import verify_default

    release, _ = exported(tmp_path)
    root = release.parents[1]
    (root / "default.json").write_bytes(canonical(pointer))
    with pytest.raises(ValueError):
        verify_default(root)


def test_default_requires_beta(tmp_path: Path) -> None:
    from app.content.runtime import verify_default

    release, _ = exported(tmp_path)
    root = release.parents[1]
    (root / "default.json").write_bytes(
        canonical(
            {
                "release_id": release.name,
                "manifest_sha256": sha(
                    (release / "runtime-manifest.json").read_bytes()
                ),
            }
        )
    )
    with pytest.raises(ValueError, match="beta"):
        verify_default(root)


def test_packaged_source_policy_matches_reviewed_docs() -> None:
    assert (
        Path("app/content/source-selection.json").read_bytes()
        == Path("../docs/research/source-selection.json").read_bytes()
    )
    assert (
        Path("app/content/source-selection.json").read_bytes()
        == Path("app/game/source-selection.json").read_bytes()
    )


def test_runtime_cli_is_database_independent(tmp_path: Path) -> None:
    release, media = exported(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.content.cli",
            "runtime-verify",
            "--release",
            str(release),
            "--media",
            str(media),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "POSTGRES_SERVER": "unreachable.invalid"},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["event_count"] == 2


@pytest.mark.parametrize(
    "data", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}']
)
def test_strict_json_rejects_ambiguous_numbers_and_keys(data: bytes) -> None:
    from app.content.runtime import strict_json

    with pytest.raises(ValueError):
        strict_json(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("recipe", "other"),
        ("release_id", "../escape"),
        ("release_id", "nested/id"),
        ("origin_manifest_sha256", "bad"),
        ("evaluation_date", "not-a-date"),
        ("created_at", "2026-10-16T00:00:00"),
        ("extra", True),
        ("code_sha256", {"../private": "a" * 64}),
        ("payload_sha256", {"runtime-manifest.json": "a" * 64}),
        ("payload_sha256", {"build.lock.json": "a" * 64}),
    ],
)
def test_build_lock_contract_rejects_invalid_inputs(
    tmp_path: Path, field: str, value: Any
) -> None:
    _, _, lock = prepared(tmp_path)
    data = lock.model_dump(mode="json")
    data[field] = value
    with pytest.raises(ValueError):
        type(lock).model_validate_json(json.dumps(data))


@pytest.mark.parametrize(
    "field,value",
    [
        ("path", "../escape"),
        ("path", "/absolute"),
        ("path", "x//y"),
        ("sha256", "wrong"),
        ("size", -1),
        ("size", "1"),
        ("url", "http://example.org/file"),
        ("url", "https://user@example.org/file"),
        ("url", "https://example.org/file#fragment"),
        ("role", "accepted-events"),
    ],
)
def test_locked_source_contract(field: str, value: Any) -> None:
    from app.content.runtime_models import LockedSource

    source = {
        "path": "snapshots/raw.jsonl",
        "sha256": "a" * 64,
        "size": 10,
        "url": None,
        "role": "supplements",
    }
    source[field] = value
    with pytest.raises(ValueError):
        LockedSource.model_validate_json(json.dumps(source))


@pytest.mark.parametrize(
    "attack",
    [
        None,
        "rights",
        "license_url",
        "source_url",
        "creator",
        "credit",
        "adaptation",
        "fit",
        "bytes",
    ],
)
def test_runtime_photo_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack: str | None
) -> None:
    from app.content.runtime import verify_runtime
    from app.content.runtime_export import export_runtime

    audit, root, lock = prepared(tmp_path, monkeypatch)
    export_runtime(audit, audit / "media", root, lock)
    release, media = root / "releases/portable-v1", root / "media/portable-v1"
    if attack is None:
        assert len(verify_runtime(release, media).media.records) == 1
        return
    fields = {
        "rights": ("rights_basis", "GFDL"),
        "license_url": ("license_url", "javascript:alert(1)"),
        "source_url": ("source_url", "https://evil.example/image"),
        "creator": ("creator", " "),
        "credit": ("attribution", "Missing credit"),
        "adaptation": ("adaptation_allowed", False),
        "fit": ("fit", "cover"),
    }
    if attack == "bytes":
        record = json.loads((release / "media.json").read_bytes())["records"][0]
        (media / Path(record["filename"]).name).write_bytes(b"not a WebP")
        # Digest/name matching is also forged: actual decoding must reject it.
        new_name = sha(b"not a WebP") + ".webp"
        (media / Path(record["filename"]).name).rename(media / new_name)
        rewrite(
            release / "media.json",
            lambda d: d["records"][0].update(
                sha256=sha(b"not a WebP"), filename="media/" + new_name
            ),
        )
        rewrite(
            release / "runtime-manifest.json",
            lambda d: d.update(
                media={p.name: sha(p.read_bytes()) for p in media.iterdir()}
            ),
        )
    else:
        key, value = fields[attack]
        rewrite(release / "media.json", lambda d: d["records"][0].update({key: value}))
    reseal(release, media)
    with pytest.raises(ValueError):
        verify_runtime(release, media)


def test_export_rechecks_rehashed_raw_acceptance(tmp_path: Path) -> None:
    from app.content.runtime_export import export_runtime
    from tests.content.test_publish import refresh

    audit, root, lock = prepared(tmp_path)
    rows = [
        json.loads(line) for line in (audit / "events.jsonl").read_bytes().splitlines()
    ]
    rows[0]["review_status"] = "pending"
    (audit / "events.jsonl").write_bytes(b"".join(canonical(row) for row in rows))
    refresh(audit)
    with pytest.raises(ValueError):
        export_runtime(audit, audit / "media", root, lock)
    assert not root.exists()


def test_export_atomic_failure_never_exposes_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.content import runtime_export
    from app.content.publish import _write_bytes

    audit, root, lock = prepared(tmp_path)
    writer = _write_bytes

    def fail(path: Path, data: bytes) -> None:
        if path.name == "runtime-manifest.json":
            raise OSError("synthetic write failure")
        writer(path, data)

    monkeypatch.setattr(runtime_export, "_write_bytes", fail)
    with pytest.raises(OSError, match="synthetic"):
        runtime_export.export_runtime(audit, audit / "media", root, lock)
    assert not (root / "releases/portable-v1").exists()
    assert not (root / "media/portable-v1").exists()
    assert not list(root.glob(".runtime-*"))


def test_cli_runtime_export(tmp_path: Path) -> None:
    audit, root, lock = prepared(tmp_path)
    lock_path = tmp_path / "lock.json"
    lock_path.write_bytes(canonical(lock.model_dump(mode="json")))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.content.cli",
            "runtime-export",
            "--release",
            str(audit),
            "--media",
            str(audit / "media"),
            "--output",
            str(root),
            "--lock",
            str(lock_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["release_id"] == "portable-v1"


@pytest.mark.parametrize(
    "attack",
    [
        "private_snapshot",
        "snapshot_download",
        "future_acquisition",
        "attribution_bool",
        "missing_kind",
        "missing_schema",
    ],
)
def test_runtime_rejects_nonportable_provenance_and_format(
    tmp_path: Path, attack: str
) -> None:
    from app.content.runtime import verify_runtime

    release, media = exported(tmp_path)
    if attack in {"missing_kind", "missing_schema"}:
        rewrite(
            release / "runtime-manifest.json",
            lambda d: d.pop("kind" if attack == "missing_kind" else "schema_version"),
        )
    elif attack == "attribution_bool":
        rewrite(release / "attribution.json", lambda d: d.update(schema_version=True))
    else:
        rows = [
            json.loads(line)
            for line in (release / "events.jsonl").read_bytes().splitlines()
        ]
        field, value = {
            "private_snapshot": ("snapshot_id", "/home/private/source-cache"),
            "snapshot_download": (
                "snapshot_id",
                "snapshot;download=file:///home/private",
            ),
            "future_acquisition": ("acquired_at", "2999-01-01T00:00:00Z"),
        }[attack]
        rows[0]["sources"][0][field] = value
        (release / "events.jsonl").write_bytes(b"".join(canonical(row) for row in rows))
    reseal(release, media)
    with pytest.raises(ValueError):
        verify_runtime(release, media)


def test_runtime_verification_does_not_rebuild_or_connect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    from app.content import publish
    from app.content.media import pipeline
    from app.content.runtime import verify_runtime

    release, media = exported(tmp_path)

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("runtime must not connect, acquire or audit")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(publish, "verify_release", forbidden)
    monkeypatch.setattr(pipeline, "_recheck_content", forbidden)
    monkeypatch.setattr(pipeline, "_recheck_chronology_snapshot", forbidden)
    monkeypatch.setattr(pipeline, "download_image", forbidden)
    assert verify_runtime(release, media).manifest.event_count == 2


def set_event_civil_year(release: Path, year: int, *, bce: bool = False) -> None:
    rows = [
        json.loads(line)
        for line in (release / "events.jsonl").read_bytes().splitlines()
    ]
    event = rows[0]
    event["year_index"] = 1 - year if bce else year
    event["date_precision"] = "year"
    for source in event["sources"]:
        source["raw_date"] = f"{year} BCE" if bce else str(year)
        source["calendar"] = "proleptic-gregorian" if bce else "gregorian"
        source["date_resolution"] = (
            f"source-resolved:{source['calendar']}:year_index={event['year_index']}"
        )
    (release / "events.jsonl").write_bytes(b"".join(canonical(row) for row in rows))


@pytest.mark.parametrize(
    "field",
    [
        "fallback_creator",
        "photo_fallback_creator",
        "creator",
        "attribution",
        "alt_text",
        "source_url",
        "encoded_source_url",
    ],
)
@pytest.mark.parametrize("bce", [False, True])
def test_rehashed_event_specific_media_answer_leak_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    bce: bool,
) -> None:
    from app.content.runtime import verify_runtime
    from app.content.runtime_export import export_runtime

    audit, root, lock = prepared(
        tmp_path, None if field == "fallback_creator" else monkeypatch
    )
    export_runtime(audit, audit / "media", root, lock)
    release, media = root / "releases/portable-v1", root / "media/portable-v1"
    set_event_civil_year(release, 44, bce=bce)
    # The year itself remains valid and consistent with all retained citations.
    reseal(release, media)
    assert verify_runtime(release, media).events[0].year_index == (-43 if bce else 44)
    event = json.loads((release / "events.jsonl").read_bytes().splitlines()[0])

    def leak(catalog: dict[str, Any]) -> None:
        if field.endswith("fallback_creator"):
            catalog["fallbacks"][event["fallback_key"]]["creator"] += " 44"
        else:
            record = next(
                r
                for r in catalog["records"]
                if r["asset_id"] == event["media_asset_id"]
            )
            key = "source_url" if field == "encoded_source_url" else field
            old = record[key]
            record[key] += (
                "%34%34"
                if field == "encoded_source_url"
                else " 44"
                if field != "source_url"
                else "_44"
            )
            if field == "creator":
                record["attribution"] = record["attribution"].replace(old, record[key])

    rewrite(release / "media.json", leak)
    reseal(release, media)
    with pytest.raises(ValueError, match="date_bearing_.*metadata"):
        verify_runtime(release, media)


def test_event_credit_screen_preserves_public_domain_duration_exemption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.content.runtime import verify_runtime
    from app.content.runtime_export import export_runtime

    audit, root, lock = prepared(tmp_path, monkeypatch)
    export_runtime(audit, audit / "media", root, lock)
    release, media = root / "releases/portable-v1", root / "media/portable-v1"
    set_event_civil_year(release, 100)

    def public_domain(catalog: dict[str, Any]) -> None:
        record = catalog["records"][0]
        record["attribution"] = record["attribution"].replace(
            record["rights_basis"], "PD-old-100-expired"
        )
        record["rights_basis"] = "PD-old-100-expired"
        record["license_url"] = "https://creativecommons.org/publicdomain/mark/1.0/"

    rewrite(release / "media.json", public_domain)
    reseal(release, media)
    assert verify_runtime(release, media).events[0].year_index == 100


@pytest.mark.parametrize(
    "target", ["citation", "download", "media_source", "license_url"]
)
@pytest.mark.parametrize(
    "suffix",
    [
        ":invalid/wiki/Example",
        ":65536/wiki/Example",
        "/wiki/Ex\x00ample",
        "/wiki/Ex\nample",
        "/wiki/Ex\x7fample",
    ],
)
def test_rehashed_malformed_runtime_url_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    suffix: str,
) -> None:
    from app.content.runtime import verify_runtime
    from app.content.runtime_export import export_runtime

    audit, root, lock = prepared(
        tmp_path, monkeypatch if target in {"media_source", "license_url"} else None
    )
    export_runtime(audit, audit / "media", root, lock)
    release, media = root / "releases/portable-v1", root / "media/portable-v1"
    if target in {"citation", "download"}:
        rows = [
            json.loads(line)
            for line in (release / "events.jsonl").read_bytes().splitlines()
        ]
        source = rows[0]["sources"][0]
        url = "https://en.wikipedia.org" + suffix
        if target == "citation":
            source["url"] = url
        else:
            source["snapshot_id"] += ";download=" + url
        (release / "events.jsonl").write_bytes(b"".join(canonical(row) for row in rows))
    else:
        key = "source_url" if target == "media_source" else "license_url"
        url = "https://commons.wikimedia.org" + suffix.replace("/wiki/", "/wiki/File:")
        rewrite(release / "media.json", lambda d: d["records"][0].update({key: url}))
    reseal(release, media)
    with pytest.raises(ValueError):
        verify_runtime(release, media)
