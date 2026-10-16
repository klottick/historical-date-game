"""Fresh public-source builds use the real acceptance pipeline, never private data."""

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.content.adapters import onthisday
from app.content.publish import verify_release
from app.content.runtime import sha256, strict_json, verify_default
from tests.content.test_onthisday import fixture_snapshot, row
from tests.content.test_source_acquisition import transport, tree_state


def fresh() -> Any:
    assert importlib.util.find_spec("app.content.fresh"), "Missing fresh public build"
    return importlib.import_module("app.content.fresh")


def upstream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    # Only upstream bytes/pins/HTTP are substituted. Import, corpus conflict
    # checks, receipts, media, full audit and nonfixture >=1000 gate stay real.
    def name(number: int) -> str:
        return sha256(str(number).encode())[:40].translate(
            str.maketrans("0123456789", "ghijklmnop")
        )

    rows = [
        row(event=f"Inventor {name(n)} patents a mechanical calculator.")
        for n in range(1000)
    ]
    rows[0] = row(
        event=f"Inventor {name(0)} patents a mechanical calculator.",
        year=1799,
        date="1799-01-01",
    )
    rows += [row(event="Ada Example dies.")]
    rows += [row(event="Unclassified material remains accountable.")]
    rows += [
        row(event="Conflicted person patents a device.", year=y, date=f"{y}-01-01")
        for y in (1800, 1801)
    ]
    _, root = fixture_snapshot(tmp_path, monkeypatch, rows)
    bodies = {name: (root / name).read_bytes() for name in onthisday.PINNED_FILES}
    monkeypatch.setattr(fresh(), "SOURCE_SIZES", {n: len(b) for n, b in bodies.items()})
    return bodies


def serve(monkeypatch: pytest.MonkeyPatch, bodies: dict[str, bytes]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        for name, body in bodies.items():
            if str(request.url) == onthisday.download_url(name):
                return httpx.Response(200, content=body)
        raise AssertionError(f"Unexpected source lookup: {request.url}")

    transport(monkeypatch, handler)


def test_fresh_build_from_public_bytes_has_no_legacy_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = fresh()
    bodies = upstream(tmp_path, monkeypatch)
    serve(monkeypatch, bodies)
    destination = tmp_path / "new-dataset"
    result = module.build_fresh(destination, "public-new")
    checked = verify_default(destination / "catalogue")
    assert result["release_id"] == "public-new"
    assert result["event_count"] == 1001
    assert result["raw_count"] == 1004
    assert result["quarantined"] == 3
    assert result["coverage"]["categories"]["births"] == 0
    assert result["coverage"]["categories"]["inventions"] == 1000
    assert checked.manifest.fixture is False
    assert len(checked.events) == 1001 and len(checked.assets) == 8
    assert all(e.sources[0].source_id == "wikipedia_onthisday" for e in checked.events)
    lock = strict_json(checked.files["build.lock.json"])
    assert lock["recipe"] == "chronology-fresh-v1"
    assert {s["path"] for s in lock["sources"]} == set(onthisday.SNAPSHOT_FILES)
    assert not (destination / "inputs/supplements.jsonl").exists()
    assert lock["origin_release_id"] == "public-new-audit"
    assert lock["origin_manifest_sha256"] == sha256(
        (destination / "audit/public-new-audit/manifest.json").read_bytes()
    )
    receipt = strict_json((destination / "inputs/download-receipt.json").read_bytes())
    assert receipt["retrieved_at"].startswith(lock["evaluation_date"])
    assert all(
        receipt["files"][name]["sha256"] == sha256(body)
        for name, body in bodies.items()
    )
    report = strict_json((destination / "build-report.json").read_bytes())
    assert report == result
    from app.content.build_context import locked_evaluation
    from app.content.rebuild import load_lock, reproduce, validate_recipe

    recipe_path = destination / "catalogue/releases/public-new/build.lock.json"
    recipe = load_lock(recipe_path)
    validate_recipe(recipe)
    with locked_evaluation(recipe.evaluation_date):
        assert (
            verify_release(
                destination / "audit/public-new-audit",
                destination / "audit/public-new-audit/media",
                require_beta=True,
            ).event_count
            == 1001
        )
    # Optional exact replay of THIS generation needs no five legacy envelopes.
    replay = reproduce(
        recipe_path,
        destination / "inputs",
        tmp_path / "replay-new",
        expected_catalogue=destination / "catalogue",
    )
    assert replay["matches"] is True and replay["differing_files"] == []


@pytest.mark.parametrize("attack", ["corrupt", "redirect", "throttled"])
def test_fresh_download_failure_never_publishes_a_catalogue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack: str
) -> None:
    module = fresh()
    upstream(tmp_path, monkeypatch)
    status = {"corrupt": 200, "redirect": 302, "throttled": 429}[attack]
    transport(monkeypatch, lambda _: httpx.Response(status, content=b"not source data"))
    destination = tmp_path / "failed"
    with pytest.raises(ValueError, match="source_"):
        module.build_fresh(destination, "failed-new")
    assert not (destination / "catalogue").exists()
    assert not (destination / "build-report.json").exists()


@pytest.mark.parametrize("attack", ["existing", "unsafe-id", "nonignored", "symlink"])
def test_fresh_rejects_unsafe_outputs_before_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack: str
) -> None:
    module = fresh()
    destination, release = tmp_path / "safe", "fresh-new"
    if attack == "existing":
        destination.mkdir()
        (destination / "untouched").write_text("original")
    elif attack == "unsafe-id":
        release = "../escape"
    elif attack == "nonignored":
        from app.content.source_acquisition import REPOSITORY_ROOT

        destination = REPOSITORY_ROOT / "backend/untracked-fresh-output"
    else:
        destination.symlink_to(tmp_path / "target")
    before = tree_state(tmp_path)

    def forbidden(_: httpx.Request) -> httpx.Response:
        pytest.fail("Unsafe output made a network request")

    transport(monkeypatch, forbidden)
    with pytest.raises(ValueError):
        module.build_fresh(destination, release)
    assert tree_state(tmp_path) == before


def test_fresh_underfilled_source_fails_full_beta_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = fresh()
    _, root = fixture_snapshot(tmp_path, monkeypatch, [row()])
    bodies = {name: (root / name).read_bytes() for name in onthisday.PINNED_FILES}
    monkeypatch.setattr(module, "SOURCE_SIZES", {n: len(b) for n, b in bodies.items()})
    serve(monkeypatch, bodies)
    destination = tmp_path / "too-small"
    with pytest.raises(ValueError, match="beta"):
        module.build_fresh(destination, "underfilled")
    assert not (destination / "catalogue").exists()


def test_fresh_cli_reports_failure_without_database_or_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.content.rebuild_cli import main

    transport(monkeypatch, lambda _: httpx.Response(503))
    assert (
        main(["fresh", "--output", str(tmp_path / "out"), "--release-id", "new"]) == 1
    )
    assert "source_http_503" in json.loads(capsys.readouterr().err)["error"]
    # Imports in the existing pytest root are not evidence of a builder DB import;
    # subprocess coverage below tests the standalone command's actual import set.


def test_fresh_module_import_is_database_independent() -> None:
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.content.fresh, sys; "
            "assert 'app.core.config' not in sys.modules; "
            "assert 'app.core.db' not in sys.modules",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
