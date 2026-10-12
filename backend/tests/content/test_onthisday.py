"""Synthetic chronology envelopes; real pinned bytes are measured separately."""

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from app.content.adapters.base import RawCandidate
from app.content.importer import import_snapshot
from app.content.schemas import CategoryRecord, EventRecord, SourceSelection
from app.content.validation import validate_event
from tests.content.test_importer import active


def module() -> Any:
    assert importlib.util.find_spec("app.content.adapters.onthisday") is not None, (
        "The approved offline chronology adapter is missing"
    )
    return importlib.import_module("app.content.adapters.onthisday")


def row(**changes: Any) -> dict[str, Any]:
    return {
        "date": "1800-01-01",
        "year": 1800,
        "month": 1,
        "day": 1,
        "event": "Ada Example patents a mechanical calculator.",
        "category": "history",
        "source": "Wikipedia contributors",
        "source_url": "https://en.wikipedia.org/wiki/January_1",
        "license": "CC BY-SA 4.0",
        **changes,
    }


def fixture_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]
) -> tuple[Any, Path]:
    adapter_module = module()
    root = tmp_path / "chronology"
    root.mkdir(exist_ok=True)
    bodies = {
        "events.jsonl": b"".join(json.dumps(r).encode() + b"\n" for r in rows),
        "README.md": b"Synthetic attribution fixture only",
        "NOTICE.md": b"Synthetic CC BY-SA attribution fixture only",
    }
    pins = {name: hashlib.sha256(body).hexdigest() for name, body in bodies.items()}
    monkeypatch.setattr(adapter_module, "PINNED_FILES", pins)
    for name, body in bodies.items():
        (root / name).write_bytes(body)
    (root / "download-receipt.json").write_text(
        json.dumps(
            {
                "repository": adapter_module.REPOSITORY,
                "commit": adapter_module.COMMIT,
                "retrieved_at": "2026-10-12T13:17:41.583939+00:00",
                "files": {
                    name: {
                        "sha256": pins[name],
                        "bytes": len(body),
                        "status": 200,
                        "url": adapter_module.download_url(name),
                    }
                    for name, body in bodies.items()
                },
            }
        )
    )
    return adapter_module.OnThisDayAdapter(), root


def test_civil_year_retains_date_and_licensed_description(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, root = fixture_snapshot(tmp_path, monkeypatch, [row()])
    raw = list(adapter.fetch(root))[0]
    event = adapter.normalize(raw)
    assert isinstance(event, EventRecord)
    assert (event.year_index, event.date_precision) == (1800, "year")
    assert event.prompt == row()["event"] and row()["event"] in event.explanation
    source = event.sources[0]
    assert source.raw_date == "1800-01-01"
    assert source.calendar == "historical-civil-year"
    assert (
        source.date_resolution
        == "source-resolved:historical-civil-year:year_index=1800"
    )
    assert source.url == row()["source_url"]
    assert "Wikipedia contributors" in source.rights_basis
    taxonomy = (CategoryRecord(id="inventions", label="Inventions"),)
    assert not validate_event(event, taxonomy, 2026)
    assert "unsupported_precision" in {
        i.code
        for i in validate_event(
            event.model_copy(update={"date_precision": "day"}), taxonomy, 2026
        )
    }


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"year": True}, "invalid_row"),
        ({"year": "1800"}, "invalid_row"),
        ({"year": 1800.0}, "invalid_row"),
        ({"month": 2}, "date_mismatch"),
        ({"day": 2}, "date_mismatch"),
        ({"year": 1801}, "date_mismatch"),
        ({"date": "0000-01-01", "year": 0}, "invalid_date"),
        ({"date": "1800-02-30", "month": 2, "day": 30}, "invalid_date"),
        ({"date": "1800–1801"}, "invalid_date"),
        ({"source": "synthetic"}, "excluded_source"),
        ({"source": "wikidata"}, "excluded_source"),
        ({"source": "unknown"}, "excluded_source"),
        ({"category": "milestone"}, "excluded_source"),
        ({"license": "CC0"}, "invalid_license"),
        ({"license": None}, "invalid_row"),
        (
            {"source_url": "https://en.wikipedia.org/wiki/January_2"},
            "source_url_mismatch",
        ),
        (
            {"source_url": "https://en.wikipedia.org.evil/wiki/January_1"},
            "source_url_mismatch",
        ),
        (
            {"source_url": "https://user@en.wikipedia.org/wiki/January_1"},
            "source_url_mismatch",
        ),
        ({"extra": "untrusted"}, "invalid_row"),
        (
            {"event": "Ada Example patents a calculator circa this date."},
            "uncertain_event",
        ),
        ({"event": "Ada Example allegedly patents a calculator."}, "uncertain_event"),
        (
            {"event": "Ada Example patents a calculator in 1801."},
            "contradictory_event_year",
        ),
        ({"event": "Ada Example patents a calculator c. 1799."}, "uncertain_event"),
        ({"event": "Ada Example patents a calculator in 1800."}, "answer_in_prompt"),
        (
            {"event": "<script>Ada Example patents a calculator.</script>"},
            "unsafe_prompt",
        ),
        (
            {"event": "Ada Example patents a calculator. https://example.org/1800"},
            "unsafe_prompt",
        ),
        ({"event": "A sports club opens."}, "unresolved_category"),
        ({"event": "Modern field hockey is born."}, "unresolved_category"),
        ({"event": "Years after Ada's death, a museum opens."}, "unresolved_category"),
        ({"event": "A book mentions an earlier battle."}, "unresolved_category"),
        (
            {"event": "The king signs letters patent for a title."},
            "unresolved_category",
        ),
        ({"date": "2030-01-01", "year": 2030}, "future_year"),
        ({"date": "2026-12-31", "year": 2026, "month": 12, "day": 31}, "future_event"),
    ],
)
def test_exclusions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any], code: str
) -> None:
    adapter, root = fixture_snapshot(tmp_path, monkeypatch, [row(**changes)])
    result = adapter.normalize(list(adapter.fetch(root))[0])
    assert isinstance(result, tuple)
    assert code in {i.code for i in result}


@pytest.mark.parametrize(
    "text,category",
    [
        ("The Battle of Example begins with a cavalry attack.", "battles"),
        ("Ada Example patents a mechanical calculator.", "inventions"),
        ("Ada Example publishes her first novel.", "literature"),
        ("An opera by Ada Example premieres in the capital.", "arts"),
        ("The Example spacecraft is launched toward the Moon.", "exploration"),
        ("The parliament ratifies the Example treaty.", "politics"),
        ("Ada Example is assassinated in the capital.", "deaths"),
    ],
)
def test_explainable_milestones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str, category: str
) -> None:
    adapter, root = fixture_snapshot(tmp_path, monkeypatch, [row(event=text)])
    result = adapter.normalize(list(adapter.fetch(root))[0])
    assert isinstance(result, EventRecord)
    assert result.category_ids == (category,)


def test_reimport_permutation_duplicate_and_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, root = fixture_snapshot(
        tmp_path,
        monkeypatch,
        [
            row(),
            row(
                date="1800-01-02",
                day=2,
                source_url="https://en.wikipedia.org/wiki/January_2",
            ),
            row(),
        ],
    )
    workspace = tmp_path / "work"
    first = import_snapshot(adapter, root, workspace)
    events = active(workspace, "candidates.jsonl")
    assert first.imported == 1 and first.duplicates == 1
    assert len(events[0]["sources"]) == 2
    assert import_snapshot(adapter, root, workspace).imported == 0
    adapter, root = fixture_snapshot(
        tmp_path,
        monkeypatch,
        [
            row(
                date="1800-01-02",
                day=2,
                source_url="https://en.wikipedia.org/wiki/January_2",
            ),
            row(),
            row(),
        ],
    )
    other = tmp_path / "permuted"
    import_snapshot(adapter, root, other)
    assert {e["event_id"] for e in active(other, "candidates.jsonl")} == {
        e["event_id"] for e in events
    }
    adapter, root = fixture_snapshot(
        tmp_path, monkeypatch, [row(date="1801-01-01", year=1801)]
    )
    import_snapshot(adapter, root, workspace)
    assert not active(workspace, "candidates.jsonl"), (
        "conflicting semantic year cannot leave old aliases accepted"
    )


@pytest.mark.parametrize(
    "change",
    ["bytes", "commit", "notice", "symlink", "malformed", "line_limit", "row_limit"],
)
def test_bounded_fetch_failure_is_generation_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    adapter, root = fixture_snapshot(tmp_path, monkeypatch, [row()])
    workspace = tmp_path / "work"
    import_snapshot(adapter, root, workspace)
    before = (workspace / "current.json").read_bytes()
    if change in {"bytes", "malformed"}:
        (root / "events.jsonl").write_bytes(b"{bad json}\n")
        if change == "malformed":
            module().PINNED_FILES["events.jsonl"] = hashlib.sha256(
                b"{bad json}\n"
            ).hexdigest()
    elif change == "commit":
        receipt = json.loads((root / "download-receipt.json").read_text())
        receipt["commit"] = "0" * 40
        (root / "download-receipt.json").write_text(json.dumps(receipt))
    elif change == "notice":
        (root / "NOTICE.md").write_text("Missing attribution")
    elif change == "symlink":
        (root / "README.md").rename(root / "elsewhere")
        (root / "README.md").symlink_to(root / "elsewhere")
    elif change == "line_limit":
        monkeypatch.setattr(module(), "MAX_LINE_BYTES", 10)
    else:
        monkeypatch.setattr(module(), "MAX_ROWS", 0)
    with pytest.raises(ValueError):
        import_snapshot(adapter, root, workspace)
    assert (workspace / "current.json").read_bytes() == before


def test_router_finalization_verification_credits_and_source_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.content.cli import main
    from app.content.media import pipeline
    from app.content.publish import publish_release, verify_release
    from app.game.projections import pending_card, project_media, revealed_card

    adapter, root = fixture_snapshot(tmp_path, monkeypatch, [row()])
    workspace = tmp_path / "work"
    selection_path = Path(__file__).parents[3] / "docs/research/source-selection.json"
    selection = SourceSelection.model_validate_json(selection_path.read_bytes())
    assert "wikipedia_onthisday" in selection.source_ids
    assert (
        main(
            [
                "import",
                "--selection",
                str(selection_path),
                "--snapshot",
                str(root),
                "--workspace",
                str(workspace),
            ]
        )
        == 0
    )
    events = [
        EventRecord.model_validate_json(json.dumps(e))
        for e in active(workspace, "candidates.jsonl")
    ]
    assert len(events) == 1
    # A JSONL fallback path must never construct an HTTP client.
    import httpx

    monkeypatch.setattr(
        httpx, "Client", lambda **_: pytest.fail("offline chronology attempted network")
    )
    for event in events:
        assert (
            pipeline.assign_media(event, selection, workspace).reason
            == "no_source_image_metadata"
        )
    assert all(r.passed for r in pipeline.finalize_media_receipts(workspace))
    publish_release(workspace, tmp_path / "releases", "synthetic", fixture=True)
    release = tmp_path / "releases/synthetic"
    assert verify_release(release, release / "media").event_count == 1
    assert (release / "LICENSE.catalog.txt").exists()
    assert (release / "NOTICE.catalog.md").exists()
    catalog = pipeline.MediaCatalog.model_validate_json(
        (release / "media.json").read_bytes()
    )
    event = pipeline._inputs(workspace)[2][0]
    media = project_media(
        event.model_copy(update={"fallback_key": "invention"}),
        {"fallback:" + k: v for k, v in catalog.fallbacks.items()},
        "/media/synthetic",
    )
    pending = pending_card(event, media).model_dump_json()
    assert (
        "Wikipedia contributors" in pending
        and "creativecommons.org/licenses/by-sa/4.0/" in pending
    )
    assert (
        "January_1" not in pending
        and "1800" not in pending
        and "sha256=" not in pending
    )
    revealed = revealed_card(event, media).model_dump_json()
    assert "January_1" in revealed
    assert "raw.githubusercontent.com/mneedham/wikipedia-onthisday/" in revealed
    with pytest.raises(ValueError, match="beta_requires"):
        verify_release(release, release / "media", require_beta=True)
    (release / "NOTICE.catalog.md").write_text("Lost credit")
    with pytest.raises(ValueError, match="artifact_integrity"):
        verify_release(release, release / "media")


def test_raw_forged_adapter_and_precomputed_year_are_not_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, root = fixture_snapshot(tmp_path, monkeypatch, [row()])
    raw = list(adapter.fetch(root))[0]
    for altered in (
        RawCandidate("wikidata", raw.record_id, raw.payload),
        RawCandidate(
            raw.source_id,
            raw.record_id,
            {**raw.payload, "year_index": 1900, "review_status": "approved"},
        ),
        RawCandidate(raw.source_id, "forged", raw.payload),
    ):
        assert isinstance(adapter.normalize(altered), tuple)


def test_bulk_no_image_assignments_use_real_current_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.content.media import pipeline

    assert hasattr(pipeline, "assign_chronology_media"), (
        "Bounded chronology needs one atomic fallback batch, not quadratic draft rewrites"
    )
    adapter, root = fixture_snapshot(
        tmp_path,
        monkeypatch,
        [row(), row(event="The parliament ratifies the Example treaty.")],
    )
    workspace = tmp_path / "work"
    import_snapshot(adapter, root, workspace)
    selection = SourceSelection.model_validate_json(
        (Path(__file__).parents[3] / "docs/research/source-selection.json").read_bytes()
    )
    pipeline.assign_chronology_media(selection, workspace)
    receipts = pipeline.finalize_media_receipts(workspace)
    assert len(receipts) == 2 and all(r.passed for r in receipts)


def test_frozen_source_membership_is_independently_rechecked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.content.media import pipeline

    adapter, root = fixture_snapshot(tmp_path, monkeypatch, [row()])
    raw = list(adapter.fetch(root))[0]
    assert hasattr(pipeline, "_recheck_chronology_snapshot"), (
        "Current normalization alone cannot prove original file membership"
    )
    assert not pipeline._recheck_chronology_snapshot(root, [raw], prefix="")
    forged = RawCandidate(
        raw.source_id,
        raw.record_id,
        {
            **raw.payload,
            "row": row(event="Ada Example patents a DIFFERENT calculator."),
        },
    )
    assert "source_integrity" in pipeline._recheck_chronology_snapshot(
        root, [forged], prefix=""
    )


def test_packaged_policy_matches_approved_selection_and_fixed_daily() -> None:
    root = Path(__file__).parents[3]
    approved = (root / "docs/research/source-selection.json").read_bytes()
    assert (root / "backend/app/game/source-selection.json").read_bytes() == approved
    selection = SourceSelection.model_validate_json(approved)
    assert selection.daily_category_ids == (
        "battles",
        "inventions",
        "exploration",
        "politics",
    )


def test_offline_selected_media_never_requests_missing_commons_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    from app.content.media import pipeline
    from tests.content.test_media import SELECTION, with_image

    workspace, events = with_image(tmp_path)
    for path in (workspace / "media-cache/commons").glob("*.json"):
        path.unlink()
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **_: pytest.fail("offline selected media attempted HTTP"),
    )
    assert (
        "offline" in __import__("inspect").signature(pipeline.assign_media).parameters
    ), "Offline mode must fail closed on absent snapshots"
    decision = pipeline.assign_media(events[0], SELECTION, workspace, offline=True)
    assert decision.media is None and "missing_commons_snapshot" in (
        decision.reason or ""
    )


def test_content_fingerprint_binds_validation_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.content.adapters import router

    before = router.rules_digest()
    original = Path.read_bytes

    def changed_validation(path: Path) -> bytes:
        body = original(path)
        return (
            body + b"\n# Changed acceptance rules\n"
            if path.name == "validation.py"
            else body
        )

    monkeypatch.setattr(Path, "read_bytes", changed_validation)
    assert router.rules_digest() != before


@pytest.mark.parametrize(
    "body", [b'{"year":1800,"year":1801}\n', b"NaN\n", b"[]\n", b"{bad}\n"]
)
def test_malformed_pinned_json_cannot_partly_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    adapter, root = fixture_snapshot(tmp_path, monkeypatch, [row()])
    workspace = tmp_path / "work"
    import_snapshot(adapter, root, workspace)
    before = (workspace / "current.json").read_bytes()
    (root / "events.jsonl").write_bytes(body)
    sha = hashlib.sha256(body).hexdigest()
    module().PINNED_FILES["events.jsonl"] = sha
    receipt = json.loads((root / "download-receipt.json").read_text())
    receipt["files"]["events.jsonl"].update(sha256=sha, bytes=len(body))
    (root / "download-receipt.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        import_snapshot(adapter, root, workspace)
    assert (workspace / "current.json").read_bytes() == before


def test_semantic_alias_wording_variants_are_quarantined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, root = fixture_snapshot(
        tmp_path,
        monkeypatch,
        [row(), row(event="Ada Example patents a mechanical calculator!")],
    )
    workspace = tmp_path / "work"
    report = import_snapshot(adapter, root, workspace)
    assert report.imported == 0 and report.quarantined == 2
    assert (
        "suspected_duplicate" in active(workspace, "quarantine.jsonl")[0]["issue_codes"]
    )


@pytest.mark.parametrize(
    "attack,expected",
    [
        ("source", "source_integrity"),
        ("notice", "catalog_text_attribution"),
        ("prompt", "current_content_mismatch"),
    ],
)
def test_standalone_verifier_rechecks_resealed_source_text_and_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack: str, expected: str
) -> None:
    from app.content.media import pipeline
    from app.content.publish import publish_release, verify_release
    from app.content.validation import candidate_digest

    adapter, root = fixture_snapshot(tmp_path, monkeypatch, [row()])
    workspace = tmp_path / "work"
    import_snapshot(adapter, root, workspace)
    selection = SourceSelection.model_validate_json(
        (Path(__file__).parents[3] / "docs/research/source-selection.json").read_bytes()
    )
    pipeline.assign_chronology_media(selection, workspace)
    assert all(r.passed for r in pipeline.finalize_media_receipts(workspace))
    publish_release(workspace, tmp_path / "releases", "synthetic", fixture=True)
    release = tmp_path / "releases/synthetic"
    if attack == "source":
        (release / "source-snapshots/onthisday/events.jsonl").write_text(
            json.dumps(row(year=1801, date="1801-01-01")) + "\n"
        )
    elif attack == "notice":
        (release / "NOTICE.catalog.md").write_text("Missing text attribution\n")
    else:
        event = EventRecord.model_validate_json(
            (release / "events.jsonl").read_text().strip()
        )
        event = event.model_copy(
            update={"prompt": "Ada Example patents an electrical calculator."}
        )
        sha = candidate_digest(event)
        for name in ("events.jsonl", "candidates.jsonl"):
            (release / name).write_text(event.model_dump_json() + "\n")
        receipts = json.loads((release / "validation.json").read_text())
        receipts[0]["candidate_sha256"] = sha
        (release / "validation.json").write_text(json.dumps(receipts))
        (release / "receipts.jsonl").write_text(json.dumps(receipts[0]) + "\n")
        decisions = json.loads((release / "decisions.json").read_text())
        decisions[str(event.event_id)].update(
            input_candidate_sha256=sha, candidate_sha256=sha
        )
        (release / "decisions.json").write_text(json.dumps(decisions))
    # Integrity hashes alone are not the acceptance boundary: reseal them all.
    batch = json.loads((release / "batch.json").read_text())
    batch["files"] = {
        name: hashlib.sha256((release / name).read_bytes()).hexdigest()
        for name in batch["files"]
    }
    (release / "batch.json").write_text(json.dumps(batch))
    manifest = json.loads((release / "manifest.json").read_text())
    manifest["files"] = {
        name: hashlib.sha256((release / name).read_bytes()).hexdigest()
        for name in manifest["files"]
    }
    (release / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match=expected):
        verify_release(release, release / "media")
