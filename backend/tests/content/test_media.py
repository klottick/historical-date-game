"""Synthetic Commons metadata and pixels; no live acquisitions or manual gates."""

import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx
import pytest

from app.content.adapters.selected import SelectedSourceAdapter
from app.content.importer import import_snapshot
from app.content.media import download, pipeline
from app.content.media.prepare import prepare_image
from app.content.media.rights import MediaCandidate, check_candidate
from app.content.schemas import EventRecord, MediaCatalog, SourceSelection
from app.content.validation import (
    candidate_digest,
    media_catalog_digest,
    validate_receipt,
)
from tests.content.test_importer import active, snapshot

SELECTION = SourceSelection.model_validate_json(
    Path("../docs/research/source-selection.json").read_text()
)


def pixels() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (100, 80), "#426d73").save(out, format="PNG")
    return out.getvalue()


def candidate(**changes: Any) -> MediaCandidate:
    values = {
        "asset_id": uuid5(NAMESPACE_URL, "synthetic-photo"),
        "source_url": "https://commons.wikimedia.org/wiki/File:Synthetic_Ada.png",
        "creator": "Synthetic photographer",
        "rights_basis": "CC BY-SA 4.0",
        "attribution": "Synthetic photographer / Wikimedia Commons / CC BY-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "adaptation_allowed": True,
        "alt_text": "Subject-context portrait photograph",
        "fit": "contain",
        "acquired_at": datetime.now(UTC),
        "source_revision": "2026-10-12T00:00:00Z",
        "repository": "commons",
        "download_url": "https://upload.wikimedia.org/wikipedia/commons/a/ab/Synthetic_Ada.png",
        "upstream_sha1": hashlib.sha1(pixels()).hexdigest(),
        "metadata_sha256": "a" * 64,
        "title": "File:Synthetic Ada.png",
        "subject_name": "Synthetic Ada",
        "description": "Portrait photograph of Synthetic Ada against a plain background.",
        "categories": ("Portrait photographs",),
        "entity_id": "Q900001",
        "relevance": "source-P18-subject-context",
    }
    values.update(changes)
    return MediaCandidate(**values)


def batch(tmp_path: Path) -> tuple[Path, list[EventRecord]]:
    workspace = tmp_path / "work"
    import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path), workspace)
    return workspace, [
        EventRecord.model_validate_json(json.dumps(e))
        for e in active(workspace, "candidates.jsonl")
    ]


def cache(workspace: Path, title: str, body: dict[str, Any]) -> None:
    root = workspace / "media-cache" / "commons"
    root.mkdir(parents=True, exist_ok=True)
    data = json.dumps(body).encode()
    stem = hashlib.sha256(title.encode()).hexdigest()
    (root / f"{stem}.json").write_bytes(data)
    (root / f"{stem}.meta.json").write_text(
        json.dumps(
            {
                "sha256": hashlib.sha256(data).hexdigest(),
                "acquired_at": "2026-10-12T00:00:00Z",
                "endpoint": "https://commons.wikimedia.org/w/api.php",
            }
        )
    )


def commons(**metadata: str) -> dict[str, Any]:
    fields = {
        "Artist": "Synthetic photographer",
        "Credit": "Own work",
        "LicenseShortName": "CC BY-SA 4.0",
        "LicenseUrl": "https://creativecommons.org/licenses/by-sa/4.0/",
        "UsageTerms": "Creative Commons Attribution-Share Alike 4.0",
        "Copyrighted": "True",
        "AttributionRequired": "True",
        "ImageDescription": "Portrait photograph of Synthetic Ada against a plain background.",
        "Categories": "Portrait photographs",
        "ObjectName": "Synthetic Ada",
    }
    fields.update(metadata)
    return {
        "query": {
            "pages": [
                {
                    "title": "File:Synthetic Ada.png",
                    "imagerepository": "local",
                    "imageinfo": [
                        {
                            "url": candidate().download_url,
                            "descriptionurl": candidate().source_url,
                            "timestamp": "2026-10-12T00:00:00Z",
                            "sha1": candidate().upstream_sha1,
                            "mime": "image/png",
                            "extmetadata": {k: {"value": v} for k, v in fields.items()},
                        }
                    ],
                }
            ]
        }
    }


def with_image(tmp_path: Path) -> tuple[Path, list[EventRecord]]:
    data = json.loads(Path("tests/fixtures/content/source-snapshot.json").read_text())
    data["entity"]["claims"]["P18"] = [
        {
            "rank": "normal",
            "mainsnak": {
                "snaktype": "value",
                "datavalue": {"type": "string", "value": "Synthetic Ada.png"},
            },
        }
    ]
    workspace = tmp_path / "work"
    import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), workspace)
    cache(workspace, "File:Synthetic Ada.png", commons())
    return workspace, [
        EventRecord.model_validate_json(json.dumps(e))
        for e in active(workspace, "candidates.jsonl")
    ]


def fake_download(url: str, destination: Path, allowed_hosts: tuple[str, ...]) -> Path:
    assert url.startswith("https://upload.wikimedia.org/")
    assert allowed_hosts == ("upload.wikimedia.org",)
    destination.write_bytes(pixels())
    return destination


def test_date_bearing_required_credit_uses_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, events = with_image(tmp_path)
    cache(workspace, "File:Synthetic Ada.png", commons(Credit="Photographed in 1800"))
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    result = pipeline.assign_media(events[0], SELECTION, workspace)
    assert result.media is None
    assert "date_bearing" in str(result.reason)
    assert (
        "Photographed in 1800"
        in (
            workspace
            / json.loads((workspace / "media-staging.json").read_text())["generation"]
            / "decisions.json"
        ).read_text()
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"rights_basis": "GFDL"},
        {"adaptation_allowed": False},
        {"repository": "wikipedia_en"},
        {"rights_basis": "PD-US"},
        {"attribution": "credit 1800"},
        {"description": "Title page with inscriptions"},
        {"categories": ("Violence",)},
        {"license_url": "https://creativecommons.org/licenses/by/3.0/"},
    ],
)
def test_unlicensed_or_nonadaptable_media_not_transformed(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    item = candidate(**changes)
    assert check_candidate(item)
    source = tmp_path / "source.png"
    source.write_bytes(pixels())
    with pytest.raises(ValueError):
        prepare_image(source, tmp_path, item)
    assert not list(tmp_path.glob("media/*.webp"))


def test_prepare_opaque_credit_and_contain(tmp_path: Path) -> None:
    from PIL import Image

    source = tmp_path / "source.png"
    source.write_bytes(pixels())
    result = prepare_image(source, tmp_path, candidate())
    assert result.fit == "contain"
    assert result.filename == f"media/{result.sha256}.webp"
    assert "CC BY-SA 4.0" in result.attribution and "Converted" in result.attribution
    assert result.source_revision == candidate().source_revision
    with Image.open(tmp_path / result.filename) as image:
        assert image.size == (100, 80) and not image.getexif()
    (tmp_path / result.filename).write_bytes(b"different")
    with pytest.raises(ValueError, match="immutable"):
        prepare_image(source, tmp_path, candidate())


@pytest.mark.parametrize(
    "url",
    [
        "http://upload.wikimedia.org/x",
        "https://user@upload.wikimedia.org/x",
        "https://upload.wikimedia.org:444/x",
        "https://127.0.0.1/x",
        "https://[::ffff:127.0.0.1]/x",
        "https://upload.wikimedia.org.evil/x",
    ],
)
def test_download_rejects_unapproved_destinations(tmp_path: Path, url: str) -> None:
    with pytest.raises(ValueError):
        download.download_image(url, tmp_path / "image", ("upload.wikimedia.org",))


def test_unsafe_redirect_and_oversized_decode_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PIL import Image

    monkeypatch.setattr(download, "_resolve", lambda host: ("8.8.8.8",))

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://127.0.0.1/secret"})

    monkeypatch.setattr(
        download,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ValueError):
        download.download_image(
            candidate().download_url, tmp_path / "image", ("upload.wikimedia.org",)
        )
    assert not (tmp_path / "image").exists()
    source = tmp_path / "source.png"
    source.write_bytes(pixels())
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 5000)
    with pytest.raises(ValueError, match="decode"):
        prepare_image(source, tmp_path, candidate())


def test_original_fallbacks_cover_every_event_type(tmp_path: Path) -> None:
    catalog = pipeline.install_fallbacks(tmp_path)
    assert set(catalog) == {
        "birth",
        "death",
        "battle",
        "invention",
        "book",
        "art",
        "exploration",
        "politics",
    }
    assert len({v.sha256 for v in catalog.values()}) == 8
    for key, record in catalog.items():
        blob = (tmp_path / record.filename).read_bytes()
        assert hashlib.sha256(blob).hexdigest() == record.sha256
        assert key in record.alt_text.lower()
        assert b"<script" not in blob and b"href=" not in blob and b"<text" not in blob
        assert pipeline.check_fallback(record, blob) == ()


def test_per_event_commons_lookup_and_safe_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, events = with_image(tmp_path)
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    decisions = [pipeline.assign_media(e, SELECTION, workspace) for e in events]
    assert all(d.media is not None for d in decisions)
    receipts = pipeline.finalize_media_receipts(workspace)
    assert len(receipts) == 2 and all(r.passed for r in receipts)
    generation = (
        workspace
        / json.loads((workspace / "media-current.json").read_text())["generation"]
    )
    evidence = json.loads((generation / "decisions.json").read_text())
    assert len(evidence) == 2 and all(d["attempts"] for d in evidence.values())
    assert (
        len(
            MediaCatalog.model_validate_json(
                (generation / "media.json").read_text()
            ).records
        )
        == 1
    )


def test_failed_download_has_reasoned_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, events = with_image(tmp_path)

    def fail(*_args: Any) -> Path:
        raise ValueError("network_failure")

    monkeypatch.setattr(pipeline, "download_image", fail)
    decision = pipeline.assign_media(events[0], SELECTION, workspace)
    assert decision.media is None and "network_failure" in str(decision.reason)


def test_finalize_media_receipts_refreezes_and_revalidates_all_events(
    tmp_path: Path,
) -> None:
    workspace, events = batch(tmp_path)
    content_pointer = (workspace / "current.json").read_bytes()
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    first = pipeline.finalize_media_receipts(workspace)
    assert len(first) == 2 and all(r.passed for r in first)
    stage = (
        workspace
        / json.loads((workspace / "media-staging.json").read_text())["generation"]
    )
    catalog = MediaCatalog.model_validate_json((stage / "media.json").read_text())
    fallback = catalog.fallbacks["birth"].model_copy(
        update={"creator": "Updated original provenance"}
    )
    catalog = catalog.model_copy(
        update={"fallbacks": {**catalog.fallbacks, "birth": fallback}}
    )
    (stage / "media.json").write_text(catalog.model_dump_json())
    assert all(
        validate_receipt(
            e.model_copy(update={"fallback_key": pipeline.fallback_key(e)}),
            r,
            r.source_sha256,
            catalog,
        )
        for e, r in zip(events, first, strict=True)
    )
    second = pipeline.finalize_media_receipts(workspace)
    assert all(r.media_catalog_sha256 == media_catalog_digest(catalog) for r in second)
    assert all(
        r.checked_at != old.checked_at for r, old in zip(second, first, strict=True)
    )
    assert (workspace / "current.json").read_bytes() == content_pointer


def test_finalize_media_receipts_rejects_altered_asset_bytes(tmp_path: Path) -> None:
    workspace, events = batch(tmp_path)
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    stage = (
        workspace
        / json.loads((workspace / "media-staging.json").read_text())["generation"]
    )
    catalog = MediaCatalog.model_validate_json((stage / "media.json").read_text())
    (workspace / "media-assets" / catalog.fallbacks["birth"].filename).write_bytes(
        b"changed"
    )
    receipts = pipeline.finalize_media_receipts(workspace)
    assert all(not r.passed and "asset_integrity" in r.issue_codes for r in receipts)


def test_complete_matching_machine_only_batch(tmp_path: Path) -> None:
    workspace, events = batch(tmp_path)
    pipeline.assign_media(events[0], SELECTION, workspace)
    with pytest.raises(ValueError, match="complete"):
        pipeline.finalize_media_receipts(workspace)
    pipeline.assign_media(events[1], SELECTION, workspace)
    receipts = pipeline.finalize_media_receipts(workspace)
    generation = (
        workspace
        / json.loads((workspace / "media-current.json").read_text())["generation"]
    )
    catalog = MediaCatalog.model_validate_json((generation / "media.json").read_text())
    assigned = [
        EventRecord.model_validate_json(line)
        for line in (generation / "events.jsonl").read_text().splitlines()
    ]
    for event, receipt in zip(assigned, receipts, strict=True):
        assert receipt.passed and receipt.stage == "content_media"
        assert receipt.candidate_sha256 == candidate_digest(event)
        assert not validate_receipt(event, receipt, receipt.source_sha256, catalog)
        content = next(
            r
            for r in active(workspace, "receipts.jsonl")
            if r["event_id"] == str(event.event_id)
        )
        assert content["stage"] == "content"


@pytest.mark.parametrize(
    "metadata",
    [
        {"ObjectName": "Portrait from 1800"},
        {"DateTimeOriginal": "1800-01-01"},
        {"License": "cc-by-3.0"},
        {"UsageTerms": "Creative Commons Attribution-Share Alike 3.0"},
        {"Artist": '<a href="https://example.org/1800">Synthetic photographer</a>'},
        {"Permission": "Territorial permission only"},
        {"ImageDescription": "Map of a voyage"},
    ],
)
def test_metadata_conflicts_dates_and_unsafe_compositions_fallback(
    tmp_path: Path, metadata: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, events = with_image(tmp_path)
    cache(workspace, "File:Synthetic Ada.png", commons(**metadata))
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    decision = pipeline.assign_media(events[0], SELECTION, workspace)
    assert decision.media is None and decision.reason
    assert any(
        code in decision.reason
        for code in ("date_bearing", "license_conflict", "unresolved", "unsafe")
    )


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "169.254.169.254", "10.1.1.1", "::1", "fe80::1", "::ffff:8.8.8.8"],
)
def test_dns_private_linklocal_and_mapped_ipv6_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    monkeypatch.setattr(download, "_resolve", lambda _host: (address,))
    with pytest.raises(ValueError, match="private"):
        download.download_image(
            candidate().download_url, tmp_path / "image", ("upload.wikimedia.org",)
        )
    assert not (tmp_path / "image").exists()


def test_transport_pins_checked_address_and_preserves_tls_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(download, "_resolve", lambda _host: ("8.8.8.8",))

    def dial(_self: Any, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "8.8.8.8"
        assert request.headers["Host"] == "upload.wikimedia.org"
        assert request.extensions["sni_hostname"] == "upload.wikimedia.org"
        return httpx.Response(200, content=b"ok")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", dial)
    with download._client() as client:
        assert client.get(candidate().download_url).content == b"ok"


def test_download_stream_limit_and_approved_redirect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(download, "_resolve", lambda _host: ("8.8.8.8",))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("Synthetic_Ada.png"):
            return httpx.Response(
                302, headers={"location": "/wikipedia/commons/a/ab/photo.png"}
            )
        return httpx.Response(
            200, content=pixels(), headers={"content-type": "image/png"}
        )

    monkeypatch.setattr(
        download,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    path = download.download_image(
        candidate().download_url, tmp_path / "image", ("upload.wikimedia.org",)
    )
    assert path.read_bytes() == pixels()
    monkeypatch.setattr(download, "MAX_BYTES", 10)
    with pytest.raises(ValueError, match="too_large"):
        download.download_image(
            candidate().download_url, tmp_path / "large", ("upload.wikimedia.org",)
        )
    assert not (tmp_path / "large").exists()


@pytest.mark.parametrize("kind", ["broken", "large", "metadata", "animation"])
def test_broken_large_metadata_and_animation_are_rejected(
    tmp_path: Path, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo

    from app.content.media import prepare

    body = pixels()
    if kind == "broken":
        body = b"not an image"
    elif kind == "large":
        monkeypatch.setattr(prepare, "MAX_DIMENSION", 50)
    elif kind == "metadata":
        out = io.BytesIO()
        info = PngInfo()
        info.add_text("Title", "Portrait from 1800")
        Image.new("RGB", (10, 10)).save(out, "PNG", pnginfo=info)
        body = out.getvalue()
    else:
        out = io.BytesIO()
        Image.new("RGB", (10, 10)).save(
            out, "PNG", save_all=True, append_images=[Image.new("RGB", (10, 10), "red")]
        )
        body = out.getvalue()
    source = tmp_path / "source"
    source.write_bytes(body)
    with pytest.raises(ValueError):
        prepare_image(
            source, tmp_path, candidate(upstream_sha1=hashlib.sha1(body).hexdigest())
        )


def test_finalization_rechecks_current_content_not_c3_pass(tmp_path: Path) -> None:
    workspace, events = batch(tmp_path)
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    content = (
        workspace / json.loads((workspace / "current.json").read_text())["generation"]
    )
    rows = [
        json.loads(line) for line in (content / "raw.jsonl").read_text().splitlines()
    ]
    rows[0]["payload"]["entity"]["claims"]["P569"][0]["mainsnak"]["datavalue"]["value"][
        "time"
    ] = "+00000001801-00-00T00:00:00Z"
    (content / "raw.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert all(row["passed"] for row in active(workspace, "receipts.jsonl"))
    receipts = pipeline.finalize_media_receipts(workspace)
    assert not receipts[0].passed and "source_integrity" in receipts[0].issue_codes


def test_final_media_metadata_conflict_and_bytes_fail_without_reusing_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, events = with_image(tmp_path)
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    first = pipeline.finalize_media_receipts(workspace)
    assert all(r.passed for r in first)
    stage = (
        workspace
        / json.loads((workspace / "media-staging.json").read_text())["generation"]
    )
    catalog = MediaCatalog.model_validate_json((stage / "media.json").read_text())
    changed = catalog.records[0].model_copy(
        update={"license_url": "https://creativecommons.org/licenses/by/3.0/"}
    )
    (stage / "media.json").write_text(
        catalog.model_copy(update={"records": (changed,)}).model_dump_json()
    )
    second = pipeline.finalize_media_receipts(workspace)
    assert all(
        not r.passed and "media_record_mismatch" in r.issue_codes for r in second
    )
    (workspace / "media-assets" / changed.filename).write_bytes(b"corrupt")
    third = pipeline.finalize_media_receipts(workspace)
    assert all(not r.passed and "asset_integrity" in r.issue_codes for r in third)


def test_failed_final_write_keeps_previous_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, events = batch(tmp_path)
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    pipeline.finalize_media_receipts(workspace)
    pointer = (workspace / "media-current.json").read_bytes()

    def fail(_path: Path, _data: bytes) -> None:
        raise OSError("disk failure")

    monkeypatch.setattr(pipeline, "immutable_write", fail)
    with pytest.raises(OSError, match="disk failure"):
        pipeline.finalize_media_receipts(workspace)
    assert (workspace / "media-current.json").read_bytes() == pointer


def test_all_same_fallback_events_and_unrelated_events_get_fresh_catalog_receipts(
    tmp_path: Path,
) -> None:
    workspace, _ = batch(tmp_path)
    data = json.loads(Path("tests/fixtures/content/source-snapshot.json").read_text())
    data["records"] = data["records"][:1]
    data["records"][0].update(entity_id="Q900002", record_id="another-birth")
    data["entity"]["id"] = "Q900002"
    data["entity"]["labels"]["en"]["value"] = "Synthetic Beatrice"
    data["page"]["pageprops"]["wikibase_item"] = "Q900002"
    data["page"]["title"] = "Synthetic Beatrice"
    import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), workspace)
    events = [
        EventRecord.model_validate_json(json.dumps(row))
        for row in active(workspace, "candidates.jsonl")
    ]
    assert len(events) == 3
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    first = pipeline.finalize_media_receipts(workspace)
    assert all(r.passed for r in first)
    stage = (
        workspace
        / json.loads((workspace / "media-staging.json").read_text())["generation"]
    )
    catalog = MediaCatalog.model_validate_json((stage / "media.json").read_text())
    changed = catalog.fallbacks["birth"].model_copy(
        update={"creator": "Updated original author provenance"}
    )
    updated = catalog.model_copy(
        update={"fallbacks": {**catalog.fallbacks, "birth": changed}}
    )
    (stage / "media.json").write_text(updated.model_dump_json())
    second = pipeline.finalize_media_receipts(workspace)
    assert all(r.passed for r in second)
    assert all(
        new.media_catalog_sha256 != old.media_catalog_sha256
        and new.checked_at != old.checked_at
        for new, old in zip(second, first, strict=True)
    )
    assert all(
        new.candidate_sha256 == old.candidate_sha256
        for new, old in zip(second, first, strict=True)
    )


def test_assignment_replacement_prunes_only_unreferenced_draft_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, events = with_image(tmp_path)
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    assert all(r.passed for r in pipeline.finalize_media_receipts(workspace))
    cache(workspace, "File:Synthetic Ada.png", commons(Credit="Credit from 1800"))
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    receipts = pipeline.finalize_media_receipts(workspace)
    assert all(r.passed for r in receipts)
    generation = (
        workspace
        / json.loads((workspace / "media-current.json").read_text())["generation"]
    )
    assert (
        MediaCatalog.model_validate_json(
            (generation / "media.json").read_text()
        ).records
        == ()
    )


def test_date_bearing_arbitrary_png_metadata_is_not_silently_stripped(
    tmp_path: Path,
) -> None:
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo

    out = io.BytesIO()
    info = PngInfo()
    info.add_text("CustomDate", "1800")
    Image.new("RGB", (10, 10)).save(out, "PNG", pnginfo=info)
    source = tmp_path / "source"
    source.write_bytes(out.getvalue())
    with pytest.raises(ValueError, match="metadata"):
        prepare_image(
            source,
            tmp_path,
            candidate(upstream_sha1=hashlib.sha1(out.getvalue()).hexdigest()),
        )


def test_final_asset_snapshot_is_checked_before_passed_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, events = batch(tmp_path)
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    stage = (
        workspace
        / json.loads((workspace / "media-staging.json").read_text())["generation"]
    )
    catalog = MediaCatalog.model_validate_json((stage / "media.json").read_text())
    original_write = pipeline._write

    def mutate_at_artifact_write(path: Path, text: str) -> None:
        if path.name == "events.jsonl":
            (
                workspace / "media-assets" / catalog.fallbacks["birth"].filename
            ).write_bytes(b"corrupt after validation")
        original_write(path, text)

    monkeypatch.setattr(pipeline, "_write", mutate_at_artifact_write)
    receipts = pipeline.finalize_media_receipts(workspace)
    generation = (
        workspace
        / json.loads((workspace / "media-current.json").read_text())["generation"]
    )
    frozen_sha = hashlib.sha256(
        (generation / catalog.fallbacks["birth"].filename).read_bytes()
    ).hexdigest()
    assert frozen_sha == catalog.fallbacks["birth"].sha256 or all(
        not r.passed for r in receipts
    )


def test_selected_api_lookup_is_bounded_cached_and_records_real_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, events = with_image(tmp_path)
    for path in (workspace / "media-cache" / "commons").iterdir():
        path.unlink()
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        assert str(request.url).startswith(pipeline.COMMONS_API)
        assert request.url.params["titles"] == "File:Synthetic Ada.png"
        assert request.url.params["maxlag"] == "5"
        return httpx.Response(200, json=commons())

    original_client = httpx.Client
    monkeypatch.setattr(
        pipeline.httpx,
        "Client",
        lambda **_kwargs: original_client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(pipeline.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    for event in events:
        assert pipeline.assign_media(event, SELECTION, workspace).media is not None
    assert len(requested) == 1
    assert all(r.passed for r in pipeline.finalize_media_receipts(workspace))


def test_required_linked_credit_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, events = with_image(tmp_path)
    cache(
        workspace,
        "File:Synthetic Ada.png",
        commons(
            Artist='<a href="https://example.org/author">Synthetic photographer</a>'
        ),
    )
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    decision = pipeline.assign_media(events[0], SELECTION, workspace)
    assert (
        decision.media is not None
        and "https://example.org/author" in decision.media.attribution
    )


def test_visible_credit_detects_small_civil_answer_year(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = json.loads(Path("tests/fixtures/content/source-snapshot.json").read_text())
    data["records"] = data["records"][:1]
    data["entity"]["claims"]["P569"][0]["mainsnak"]["datavalue"]["value"]["time"] = (
        "-00000000044-00-00T00:00:00Z"
    )
    data["page"]["revisions"][0]["slots"]["main"]["content"] = (
        "{{Infobox person|birth_date=44 BCE}}"
    )
    data["entity"]["claims"]["P18"] = [
        {
            "rank": "normal",
            "mainsnak": {
                "snaktype": "value",
                "datavalue": {"value": "Synthetic Ada.png"},
            },
        }
    ]
    workspace = tmp_path / "work"
    import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), workspace)
    event = EventRecord.model_validate_json(
        json.dumps(active(workspace, "candidates.jsonl")[0])
    )
    cache(workspace, "File:Synthetic Ada.png", commons(Credit="Archive item 44"))
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    decision = pipeline.assign_media(event, SELECTION, workspace)
    assert decision.media is None and "date_bearing" in str(decision.reason)


def test_finalization_rechecks_original_acquisition_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, events = with_image(tmp_path)
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    assert all(r.passed for r in pipeline.finalize_media_receipts(workspace))
    path = next((workspace / "media-cache" / "originals").glob("*.meta.json"))
    data = json.loads(path.read_text())
    data["acquired_at"] = "2100-01-01T00:00:00+00:00"
    path.write_text(json.dumps(data))
    assert all(not r.passed for r in pipeline.finalize_media_receipts(workspace))


def test_download_origin_is_checked_even_when_prepare_called_directly() -> None:
    assert check_candidate(
        candidate(download_url="https://upload.wikimedia.org/wikipedia/en/local.png")
    )


def test_final_catalog_asset_decode_warning_is_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PIL import Image

    source = tmp_path / "source"
    source.write_bytes(pixels())
    record = prepare_image(source, tmp_path, candidate())
    catalog = MediaCatalog(
        records=(record,), fallbacks=pipeline.install_fallbacks(tmp_path)
    )
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 5000)
    assert pipeline._check_assets(catalog, tmp_path)


@pytest.mark.parametrize(
    "rights,license_url",
    list(pipeline.LICENSES.items())
    + [("PD-old-100-expired", "https://creativecommons.org/publicdomain/mark/1.0/")],
)
def test_supported_per_file_licenses_preserve_exact_terms(
    tmp_path: Path, rights: str, license_url: str
) -> None:
    source = tmp_path / "source"
    source.write_bytes(pixels())
    record = prepare_image(
        source,
        tmp_path,
        candidate(
            rights_basis=rights,
            license_url=license_url,
            attribution=f"Synthetic photographer / Wikimedia Commons / {rights}",
        ),
    )
    assert record.rights_basis == rights and record.license_url == license_url
    assert rights in record.attribution and "adaptation under" in record.attribution


def test_new_c3_generation_requires_all_fresh_assignments(tmp_path: Path) -> None:
    workspace, events = batch(tmp_path)
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    assert all(r.passed for r in pipeline.finalize_media_receipts(workspace))
    old_pointer = (workspace / "media-current.json").read_bytes()
    data = json.loads(Path("tests/fixtures/content/source-snapshot.json").read_text())
    data["entity"]["labels"]["en"]["value"] = "Synthetic Revised Ada"
    data["page"]["title"] = "Synthetic Revised Ada"
    import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), workspace)
    with pytest.raises(ValueError, match="complete"):
        pipeline.finalize_media_receipts(workspace)
    assert (workspace / "media-current.json").read_bytes() == old_pointer
    for row in active(workspace, "candidates.jsonl"):
        pipeline.assign_media(
            EventRecord.model_validate_json(json.dumps(row)), SELECTION, workspace
        )
    assert all(r.passed for r in pipeline.finalize_media_receipts(workspace))


def test_finalization_checks_date_bearing_changed_fallback_metadata(
    tmp_path: Path,
) -> None:
    workspace, events = batch(tmp_path)
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    stage = (
        workspace
        / json.loads((workspace / "media-staging.json").read_text())["generation"]
    )
    catalog = MediaCatalog.model_validate_json((stage / "media.json").read_text())
    changed = catalog.fallbacks["birth"].model_copy(
        update={"alt_text": "Representative birth illustration from eighteen oh zero"}
    )
    (stage / "media.json").write_text(
        catalog.model_copy(
            update={"fallbacks": {**catalog.fallbacks, "birth": changed}}
        ).model_dump_json()
    )
    assert all(not r.passed for r in pipeline.finalize_media_receipts(workspace))


def test_fallback_embedded_accessible_label_cannot_disagree_with_safe_alt(
    tmp_path: Path,
) -> None:
    record = pipeline.install_fallbacks(tmp_path)["birth"]
    data = (
        (tmp_path / record.filename)
        .read_bytes()
        .replace(b"cradle beneath a rising sun", b"cradle from 44 BCE")
    )
    updated = record.model_copy(
        update={
            "sha256": hashlib.sha256(data).hexdigest(),
            "filename": f"media/{hashlib.sha256(data).hexdigest()}.svg",
        }
    )
    assert pipeline.check_fallback(updated, data)


@pytest.mark.parametrize(
    "metadata",
    [
        {"ObjectName": "Titled image with a plaque"},
        {"Sensitivity": "Unresolved"},
        {"ObjectName": "Map of a voyage"},
    ],
)
def test_risk_in_other_file_metadata_never_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metadata: dict[str, str]
) -> None:
    workspace, events = with_image(tmp_path)
    cache(workspace, "File:Synthetic Ada.png", commons(**metadata))
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    result = pipeline.assign_media(events[0], SELECTION, workspace)
    assert result.media is None and "unsafe" in str(result.reason)


UNRESOLVED_COMPOSITIONS = (
    "Object photograph of a handwritten letter against a plain background.",
    "Portrait photograph of Synthetic Ada holding a sign reading MDCCC against a plain background.",
    "Portrait photograph of Synthetic Ada carrying an unspecified item against a plain background.",
    "Portrait photograph of Synthetic Ada and another person against a plain background.",
    "Object photograph of an ordinary item against a plain background.",
)


@pytest.mark.parametrize("description", UNRESOLVED_COMPOSITIONS)
def test_round1_unresolved_subject_composition_uses_reasoned_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, description: str
) -> None:
    workspace, events = with_image(tmp_path)
    body = commons(ImageDescription=description)
    cache(workspace, "File:Synthetic Ada.png", body)
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    for event in events:
        result = pipeline.assign_media(event, SELECTION, workspace)
        assert result.media is None and result.reason
        assert any(
            code in result.reason
            for code in ("unresolved_visual_safety", "unsafe", "date_bearing")
        )
    receipts = pipeline.finalize_media_receipts(workspace)
    generation = (
        workspace
        / json.loads((workspace / "media-current.json").read_text())["generation"]
    )
    assert all(
        receipt.passed for receipt in receipts
    )  # valid representative art, never this image
    assert (
        MediaCatalog.model_validate_json(
            (generation / "media.json").read_text()
        ).records
        == ()
    )
    assert all(
        json.loads(line)["media_asset_id"] is None
        for line in (generation / "events.jsonl").read_text().splitlines()
    )
    assert json.dumps(body, sort_keys=True) in json.dumps(
        json.loads((generation / "decisions.json").read_text())[
            str(events[0].event_id)
        ]["attempts"][0]["file_metadata"],
        sort_keys=True,
    )


def _legacy_composition_evidence(workspace: Path, description: str) -> None:
    """Construct an internally consistent old accepted-image artifact, without mocking gates."""
    stage = (
        workspace
        / json.loads((workspace / "media-staging.json").read_text())["generation"]
    )
    decisions = json.loads((stage / "decisions.json").read_text())
    assignments = json.loads((stage / "assignments.json").read_text())
    catalog = MediaCatalog.model_validate_json((stage / "media.json").read_text())
    body = commons(ImageDescription=description)
    cache(workspace, "File:Synthetic Ada.png", body)
    metadata_sha = hashlib.sha256(json.dumps(body).encode()).hexdigest()
    info = body["query"]["pages"][0]["imageinfo"][0]
    revision = info["timestamp"] + ";sha1=" + info["sha1"] + ";metadata=" + metadata_sha
    asset_id = uuid5(NAMESPACE_URL, info["descriptionurl"] + revision)
    record = catalog.records[0].model_copy(
        update={"asset_id": asset_id, "source_revision": revision}
    )
    for event_id, decision in decisions.items():
        decision["candidate"].update(
            description=description,
            metadata_sha256=metadata_sha,
            source_revision=revision,
            asset_id=str(asset_id),
        )
        assigned = EventRecord.model_validate_json(
            json.dumps(assignments[event_id])
        ).model_copy(update={"media_asset_id": asset_id})
        assignments[event_id] = assigned.model_dump(mode="json")
        decision["candidate_sha256"] = candidate_digest(assigned)
        decision["attempts"][0].update(
            file_metadata=body,
            metadata_sha256=metadata_sha,
            candidate=decision["candidate"],
        )
    (stage / "decisions.json").write_text(json.dumps(decisions))
    (stage / "assignments.json").write_text(json.dumps(assignments))
    (stage / "media.json").write_text(
        catalog.model_copy(update={"records": (record,)}).model_dump_json()
    )


@pytest.mark.parametrize("description", UNRESOLVED_COMPOSITIONS[:2])
def test_round1_finalization_rejects_previously_accepted_letter_or_sign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, description: str
) -> None:
    workspace, events = with_image(tmp_path)
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    for event in events:
        assert pipeline.assign_media(event, SELECTION, workspace).media is not None
    assert all(
        receipt.passed for receipt in pipeline.finalize_media_receipts(workspace)
    )
    _legacy_composition_evidence(workspace, description)
    receipts = pipeline.finalize_media_receipts(workspace)
    assert all(
        not receipt.passed and "unresolved_visual_safety" in receipt.issue_codes
        for receipt in receipts
    )


@pytest.mark.parametrize(
    "key,field,value",
    [
        ("birth", "creator", "Original illustrator / racist propaganda and gore"),
        ("art", "creator", "Original illustrator / racist propaganda and gore"),
        (
            "art",
            "alt_text",
            "Representative art illustration: racist propaganda and gore",
        ),
        ("book", "creator", "Original illustrator / handwritten letter with a sign"),
    ],
)
def test_round1_catalog_wide_public_fallback_text_is_rechecked(
    tmp_path: Path, key: str, field: str, value: str
) -> None:
    workspace, events = batch(tmp_path)
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    assert all(
        receipt.passed for receipt in pipeline.finalize_media_receipts(workspace)
    )
    stage = (
        workspace
        / json.loads((workspace / "media-staging.json").read_text())["generation"]
    )
    catalog = MediaCatalog.model_validate_json((stage / "media.json").read_text())
    record = catalog.fallbacks[key]
    original_data = (workspace / "media-assets" / record.filename).read_bytes()
    changes: dict[str, Any] = {field: value}
    if field == "alt_text":
        data = original_data.replace(record.alt_text.encode(), value.encode())
        sha = hashlib.sha256(data).hexdigest()
        changes.update(sha256=sha, filename=f"media/{sha}.svg")
        download.immutable_write(workspace / "media-assets" / changes["filename"], data)
    altered = record.model_copy(update=changes)
    (stage / "media.json").write_text(
        catalog.model_copy(
            update={"fallbacks": {**catalog.fallbacks, key: altered}}
        ).model_dump_json()
    )
    assert all(
        not receipt.passed and "unsafe_fallback" in receipt.issue_codes
        for receipt in pipeline.finalize_media_receipts(workspace)
    )
    assert (workspace / "media-assets" / record.filename).read_bytes() == original_data


@pytest.mark.parametrize(
    "kind,version", [("BY", "2.0"), ("BY", "3.0"), ("BY-SA", "2.0"), ("BY-SA", "3.0")]
)
def test_round1_older_cc_derivative_retains_supplied_work_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, version: str
) -> None:
    workspace, events = with_image(tmp_path)
    rights = f"CC {kind} {version}"
    terms = f"Creative Commons Attribution{'-Share Alike' if kind == 'BY-SA' else ''} {version}"
    cache(
        workspace,
        "File:Synthetic Ada.png",
        commons(
            ObjectName="Quiet profile study",
            LicenseShortName=rights,
            LicenseUrl=pipeline.LICENSES[rights],
            UsageTerms=terms,
        ),
    )
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    for event in events:
        result = pipeline.assign_media(event, SELECTION, workspace)
        assert (
            result.media is not None
            and "Quiet profile study" in result.media.attribution
        )
        assert (
            rights in result.media.attribution
            and "Converted" in result.media.attribution
        )
    assert all(
        receipt.passed for receipt in pipeline.finalize_media_receipts(workspace)
    )


def test_round1_finalization_regenerates_required_supplied_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, events = with_image(tmp_path)
    cache(
        workspace,
        "File:Synthetic Ada.png",
        commons(
            ObjectName="Quiet profile study",
            LicenseShortName="CC BY 3.0",
            LicenseUrl=pipeline.LICENSES["CC BY 3.0"],
            UsageTerms="Creative Commons Attribution 3.0",
        ),
    )
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    assert all(
        receipt.passed for receipt in pipeline.finalize_media_receipts(workspace)
    )
    stage = (
        workspace
        / json.loads((workspace / "media-staging.json").read_text())["generation"]
    )
    catalog = MediaCatalog.model_validate_json((stage / "media.json").read_text())
    record = catalog.records[0].model_copy(
        update={
            "attribution": catalog.records[0].attribution.replace(
                "Quiet profile study / ", ""
            )
        }
    )
    decisions = json.loads((stage / "decisions.json").read_text())
    for decision in decisions.values():
        decision["candidate"]["attribution"] = decision["candidate"][
            "attribution"
        ].replace("Quiet profile study / ", "")
    (stage / "decisions.json").write_text(json.dumps(decisions))
    (stage / "media.json").write_text(
        catalog.model_copy(update={"records": (record,)}).model_dump_json()
    )
    assert all(
        not receipt.passed for receipt in pipeline.finalize_media_receipts(workspace)
    )


@pytest.mark.parametrize(
    "work_title",
    [
        "Profile MDCCC",
        "Profile_MDCCC",
        "Profile ⅯⅮⅭⅭⅭ",
        "Handwritten letter",
        "Portrait from 1800",
    ],
)
def test_round1_unsafe_required_work_title_is_fallback_not_stripped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, work_title: str
) -> None:
    workspace, events = with_image(tmp_path)
    cache(
        workspace,
        "File:Synthetic Ada.png",
        commons(
            ObjectName=work_title,
            LicenseShortName="CC BY 3.0",
            LicenseUrl=pipeline.LICENSES["CC BY 3.0"],
            UsageTerms="Creative Commons Attribution 3.0",
        ),
    )
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    result = pipeline.assign_media(events[0], SELECTION, workspace)
    assert result.media is None and result.reason
    stage = (
        workspace
        / json.loads((workspace / "media-staging.json").read_text())["generation"]
    )
    evidence = json.loads((stage / "decisions.json").read_text())[
        str(events[0].event_id)
    ]["attempts"][0]["file_metadata"]
    assert (
        evidence["query"]["pages"][0]["imageinfo"][0]["extmetadata"]["ObjectName"][
            "value"
        ]
        == work_title
    )


@pytest.mark.parametrize("short_name", ["CC0", "CC0 1.0"])
def test_round1_commons_cc_zero_dedication_acquisition_to_final_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, short_name: str
) -> None:
    workspace, events = with_image(tmp_path)
    body = commons(
        LicenseShortName=short_name,
        License="cc-zero",
        LicenseUrl=pipeline.LICENSES["CC0"],
        Copyrighted="False",
        AttributionRequired="False",
        UsageTerms="Creative Commons CC0 1.0 Universal Public Domain Dedication",
    )
    cache(workspace, "File:Synthetic Ada.png", body)
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    for event in events:
        result = pipeline.assign_media(event, SELECTION, workspace)
        assert result.media is not None and result.media.rights_basis == "CC0"
        assert result.media.license_url == pipeline.LICENSES["CC0"]
        assert "Synthetic photographer" in result.media.attribution
    receipts = pipeline.finalize_media_receipts(workspace)
    assert len(receipts) == 2 and all(receipt.passed for receipt in receipts)
    generation = (
        workspace
        / json.loads((workspace / "media-current.json").read_text())["generation"]
    )
    catalog = MediaCatalog.model_validate_json((generation / "media.json").read_text())
    assigned = [
        EventRecord.model_validate_json(line)
        for line in (generation / "events.jsonl").read_text().splitlines()
    ]
    assert (
        workspace / "media-cache" / "originals" / f"{candidate().upstream_sha1}.bin"
    ).read_bytes() == pixels()
    for event, receipt in zip(assigned, receipts, strict=True):
        assert not validate_receipt(event, receipt, receipt.source_sha256, catalog)
        assert (
            hashlib.sha256(
                (generation / catalog.records[0].filename).read_bytes()
            ).hexdigest()
            == catalog.records[0].sha256
        )


@pytest.mark.parametrize(
    "terms", ["Creative Commons Attribution 4.0", "Unspecified terms"]
)
def test_round1_cc0_cannot_ignore_conflicting_usage_terms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terms: str
) -> None:
    workspace, events = with_image(tmp_path)
    cache(
        workspace,
        "File:Synthetic Ada.png",
        commons(
            LicenseShortName="CC0",
            License="cc0",
            LicenseUrl=pipeline.LICENSES["CC0"],
            Copyrighted="False",
            AttributionRequired="False",
            UsageTerms=terms,
        ),
    )
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    result = pipeline.assign_media(events[0], SELECTION, workspace)
    assert result.media is None and "license_conflict" in str(result.reason)


def test_round1_old_rules_or_dependency_fingerprint_cannot_reuse_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, events = with_image(tmp_path)
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    assert all(
        receipt.passed for receipt in pipeline.finalize_media_receipts(workspace)
    )
    pointer = json.loads((workspace / "media-current.json").read_text())
    assert len(pointer.get("media_rules_sha256", "")) == 64
    generation = workspace / pointer["generation"]
    assert (
        json.loads((generation / "batch.json").read_text())["media_rules_sha256"]
        == pointer["media_rules_sha256"]
    )
    stage = (
        workspace
        / json.loads((workspace / "media-staging.json").read_text())["generation"]
    )
    decisions = json.loads((stage / "decisions.json").read_text())
    for decision in decisions.values():
        decision.pop("media_rules_sha256", None)  # pre-fix persisted assignments
    (stage / "decisions.json").write_text(json.dumps(decisions))
    assert all(
        not receipt.passed and "stale_media_rules" in receipt.issue_codes
        for receipt in pipeline.finalize_media_receipts(workspace)
    )
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    assert all(
        receipt.passed for receipt in pipeline.finalize_media_receipts(workspace)
    )
    monkeypatch.setattr(pipeline, "package_version", lambda _name: "0.0.0")
    assert pipeline.media_rules_digest() != pointer["media_rules_sha256"]
    assert all(
        not receipt.passed and "stale_media_rules" in receipt.issue_codes
        for receipt in pipeline.finalize_media_receipts(workspace)
    )
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    assert all(
        receipt.passed for receipt in pipeline.finalize_media_receipts(workspace)
    )


def test_round1_changed_commons_lookup_invalidates_unchanged_event_and_asset_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, events = with_image(tmp_path)
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    old_receipts = pipeline.finalize_media_receipts(workspace)
    old_generation = (
        workspace
        / json.loads((workspace / "media-current.json").read_text())["generation"]
    )
    old_catalog = MediaCatalog.model_validate_json(
        (old_generation / "media.json").read_text()
    )
    old_bytes = (old_generation / old_catalog.records[0].filename).read_bytes()
    cache(
        workspace, "File:Synthetic Ada.png", commons(ObjectName="Quiet profile study")
    )
    assert all(
        not receipt.passed for receipt in pipeline.finalize_media_receipts(workspace)
    )
    for event in events:
        result = pipeline.assign_media(event, SELECTION, workspace)
        assert (
            result.media is not None
            and "Quiet profile study" in result.media.attribution
        )
    new_receipts = pipeline.finalize_media_receipts(workspace)
    assert all(receipt.passed for receipt in new_receipts)
    assert all(
        old.media_catalog_sha256 != new.media_catalog_sha256
        for old, new in zip(old_receipts, new_receipts, strict=True)
    )
    assert (old_generation / old_catalog.records[0].filename).read_bytes() == old_bytes


def test_round1_roman_date_screen_never_matches_empty_civic_word() -> None:
    from app.content.media.rights import date_bearing

    assert not date_bearing("Representative politics illustration: civic assembly")
    assert not date_bearing("Synthetic photographer / CC BY-SA 3.0")
    assert date_bearing("Profile_MDCCC")
    assert date_bearing("Profile ⅯⅮⅭⅭⅭ")


def test_round1_corrected_source_fingerprint_requires_new_complete_fallback_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, events = batch(tmp_path)
    for event in events:
        pipeline.assign_media(event, SELECTION, workspace)
    assert all(
        receipt.passed for receipt in pipeline.finalize_media_receipts(workspace)
    )
    old_pointer = json.loads((workspace / "media-current.json").read_text())
    old_generation = workspace / old_pointer["generation"]
    original_reader = Path.read_bytes
    rules_path = Path(pipeline.__file__).with_name("rights.py")

    def corrected_source_bytes(path: Path) -> bytes:
        data = original_reader(path)
        return data + b"\n# simulated corrected rules\n" if path == rules_path else data

    # Source-file input double, not a mocked fingerprint/check: no repo edits.
    monkeypatch.setattr(Path, "read_bytes", corrected_source_bytes)
    assert pipeline.media_rules_digest() != old_pointer["media_rules_sha256"]
    assert all(
        not receipt.passed and "stale_media_rules" in receipt.issue_codes
        for receipt in pipeline.finalize_media_receipts(workspace)
    )
    pipeline.assign_media(events[0], SELECTION, workspace)
    with pytest.raises(ValueError, match="complete"):
        pipeline.finalize_media_receipts(workspace)
    pipeline.assign_media(events[1], SELECTION, workspace)
    assert all(
        receipt.passed for receipt in pipeline.finalize_media_receipts(workspace)
    )
    assert (old_generation / "media.json").read_text() == (
        workspace
        / json.loads((workspace / "media-current.json").read_text())["generation"]
        / "media.json"
    ).read_text()


@pytest.mark.parametrize(
    "subject,description",
    [
        ("Transistor", "Object photograph of a transistor against a plain background."),
        (
            "Sailing ship",
            "Ship photograph of a sailing ship against a plain background.",
        ),
    ],
)
def test_round1_closed_physical_subjects_remain_supported(
    subject: str, description: str
) -> None:
    assert not check_candidate(candidate(subject_name=subject, description=description))
