"""Distribution regressions using only public, committed runtime files; no DB."""

import re
import shutil
import socket
from collections import Counter
from pathlib import Path

import pytest

from app.content.publish import canonical
from app.content.runtime import (
    REQUIRED_FILES,
    sha256,
    strict_json,
    verify_default,
    verify_runtime,
)
from app.content.runtime_models import BuildLock
from tests.content.test_runtime import reseal, rewrite

CATALOGUE = Path(__file__).resolve().parents[2] / "catalogue"
RELEASE_ID = "chronology-1276-runtime-v2"
# Independently recorded from the retained original's complete event payload.
EVENTS_SHA256 = "fe31289687a8ae1b1c34bd1ce034ca53f907c5e2d0d334214220578af74db13a"


@pytest.mark.parametrize("attack", ["empty", "all", "equal_year"])
@pytest.mark.parametrize("require_beta", [False, True])
def test_rehashed_nonfixture_requires_playable_daily_subset(
    tmp_path: Path, attack: str, require_beta: bool
) -> None:
    from app.content.runtime import verify_runtime

    snapshot = verify_default(CATALOGUE)
    rid = snapshot.manifest.release_id
    release, media = tmp_path / "releases" / rid, tmp_path / "media" / rid
    shutil.copytree(CATALOGUE / "releases" / rid, release)
    shutil.copytree(CATALOGUE / "media" / rid, media)
    rows = [strict_json(line) for line in snapshot.files["events.jsonl"].splitlines()]
    exemplar = next(
        row for row in rows if row["sources"][0]["source_id"] == "wikipedia_onthisday"
    )
    for index, row in enumerate(rows):
        if attack == "equal_year":
            row = {
                **exemplar,
                "event_id": row["event_id"],
                "identity_key": row["identity_key"],
            }
            rows[index] = row
        selected = attack == "all" or attack == "equal_year" and index != 0
        row["category_ids"] = ["inventions" if selected else "births"]
        row["fallback_key"] = "invention" if selected else "birth"
        row["identity_key"] = f"runtime-mutation:{row['event_id']}:event"
    (release / "events.jsonl").write_bytes(b"".join(canonical(row) for row in rows))
    reseal(release, media)
    with pytest.raises(ValueError, match="daily"):
        verify_runtime(release, media, require_beta=require_beta)
    # Explicit synthetic fixtures may intentionally not support Daily beta.
    rewrite(release / "runtime-manifest.json", lambda d: d.update(fixture=True))
    assert verify_runtime(release, media).manifest.fixture is True


def test_committed_default_is_offline_beta(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Runtime verification attempted network access")

    monkeypatch.setattr(socket, "socket", forbidden)
    snapshot = verify_default(CATALOGUE)
    assert snapshot.manifest.release_id == RELEASE_ID
    assert snapshot.manifest.event_count == 1276
    assert snapshot.manifest.fixture is False
    assert len(snapshot.assets) == 8
    assert snapshot.media.records == ()


def test_real_release_parity() -> None:
    snapshot = verify_default(CATALOGUE)
    assert sha256(snapshot.files["events.jsonl"]) == EVENTS_SHA256
    assert snapshot.manifest.content_sha256 == (
        "fdd5f09fc7dadc7eefb59ce60a36f3f3e8c1fbe53a0a703b7dd59da350dacc39"
    )
    assert snapshot.manifest.origin_manifest_sha256 == (
        "804ec52ccfc3e19cd955913b05cbfd59158f562408e45c1916fa8626d3ac50d3"
    )
    assert Counter(e.sources[0].source_id for e in snapshot.events) == {
        "wikipedia_onthisday": 1271,
        "wikidata": 5,
    }
    assert len({e.event_id for e in snapshot.events}) == 1276


def test_distribution_allowlist_and_licences() -> None:
    snapshot = verify_default(CATALOGUE)
    expected = {"README.md", "default.json"}
    expected.update(f"releases/{RELEASE_ID}/{name}" for name in REQUIRED_FILES)
    expected.add(f"releases/{RELEASE_ID}/runtime-manifest.json")
    expected.update(f"media/{RELEASE_ID}/{name}" for name in snapshot.assets)
    old_id = "chronology-1276-runtime-v1"
    old = verify_runtime(
        CATALOGUE / "releases" / old_id,
        CATALOGUE / "media" / old_id,
        expected_sha256="c8a071ed173092f2acd811c034f7e5edecffba2cc76863e571138c579727fe5d",
        require_beta=True,
    )
    expected.update(f"releases/{old_id}/{name}" for name in REQUIRED_FILES)
    expected.add(f"releases/{old_id}/runtime-manifest.json")
    expected.update(f"media/{old_id}/{name}" for name in old.assets)
    assert {
        p.relative_to(CATALOGUE).as_posix() for p in CATALOGUE.rglob("*") if p.is_file()
    } == expected
    assert all(not p.is_symlink() for p in CATALOGUE.rglob("*"))
    assert b"CC BY-SA 4.0" in snapshot.files["LICENSE.catalog.txt"]
    assert b"Wikipedia contributors" in snapshot.files["NOTICE.catalog.md"]
    assert b"CC0" in snapshot.files["attribution.json"]
    assert all(s.url and s.rights_basis for e in snapshot.events for s in e.sources)


def test_default_recipe_has_no_private_paths() -> None:
    snapshot = verify_default(CATALOGUE)
    lock = BuildLock.model_validate_json(snapshot.files["build.lock.json"])
    assert lock.evaluation_date.isoformat() == "2026-10-12"
    assert {s.path for s in lock.sources} == {
        "events.jsonl",
        "README.md",
        "NOTICE.md",
        "download-receipt.json",
        "supplements.jsonl",
    }
    assert {s.path for s in lock.sources if s.url is None} == {
        "download-receipt.json",
        "supplements.jsonl",
    }
    assert lock.code_sha256 and lock.dependencies and lock.payload_sha256
    # Historical immutable bundles pin their original recipe implementation.
    # New acquisition features must not reseal or rewrite these shipped bytes.
    # Current-code lock rejection is independently covered in test_rebuild.py;
    # fresh-build tests validate their new, current-code recipe at its boundary.
    assert all(
        not Path(p).is_absolute() and ".." not in Path(p).parts
        for p in lock.code_sha256
    )
    pointer = strict_json((CATALOGUE / "default.json").read_bytes())
    assert pointer["manifest_sha256"] == sha256(snapshot.manifest_bytes)
    # Host paths (not public HTTPS URL paths), operational secrets and raw outputs.
    private = re.compile(
        rb"(?:^|[\s\"'=])(?:/home/|/tmp/|/Users/|file://)|"
        rb"-----BEGIN [A-Z ]*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|"
        rb"github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|"
        rb"postgres(?:ql)?://|Bearer [A-Za-z0-9_.-]+"
    )
    for path in CATALOGUE.rglob("*"):
        if path.is_file():
            assert not private.search(path.read_bytes()), path.relative_to(CATALOGUE)
