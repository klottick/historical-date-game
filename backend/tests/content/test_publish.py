"""Publication attacks use synthetic provider envelopes, never real beta claims."""

import copy
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
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
from tests.content.test_media import (
    SELECTION,
    batch,
    commons,
    fake_download,
    with_image,
)


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


def uncached_media_workspace(tmp_path: Path) -> Path:
    workspace, _ = with_image(tmp_path)
    for path in (workspace / "media-cache" / "commons").glob("*.json"):
        path.unlink()
    return workspace


def mock_commons_client(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(pipeline.time, "sleep", lambda _: None)
    monkeypatch.setattr(pipeline, "download_image", fake_download)


def media_args(workspace: Path) -> list[str]:
    return [
        "media",
        "--selection",
        "../docs/research/source-selection.json",
        "--workspace",
        str(workspace),
    ]


@pytest.mark.parametrize(
    "status,body,retry,expected_delay",
    [
        (429, {"error": {"code": "ratelimited", "info": "slow down"}}, "120", 120),
        (429, {"error": {"code": "ratelimited"}}, "Mon, 12 Oct 2026 00:02:00 GMT", 120),
        (429, {}, None, 300),
        (429, {}, "nonsense", 300),
        (429, {}, "-1", 300),
        (429, {}, "Sun, 11 Oct 2026 00:00:00 GMT", 300),
        (503, {"error": {"code": "maxlag", "info": "database lag"}}, "60", 60),
        (200, {"error": {"code": "maxlag", "info": "database lag"}}, "60", 60),
        (200, {"error": {"code": "ratelimited", "info": "slow down"}}, None, 300),
    ],
)
def test_commons_throttle_stops_cli_before_next_event_and_preserves_retry_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: int,
    body: dict[str, Any],
    retry: str | None,
    expected_delay: int,
) -> None:
    from app.content import commons_transport
    from app.content.cli import main

    monkeypatch.setattr(
        commons_transport, "utc_now", lambda: datetime(2026, 10, 12, tzinfo=UTC)
    )
    workspace = uncached_media_workspace(tmp_path)
    calls = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        headers = {
            "Date": "Mon, 12 Oct 2026 00:00:00 GMT",
            "Set-Cookie": "private-token=do-not-save",
        }
        if retry is not None:
            headers["Retry-After"] = retry
        return httpx.Response(status, json=body, headers=headers)

    mock_commons_client(monkeypatch, response)
    # Existing code must fail on batch behavior, not importing the new helper.
    result = main(media_args(workspace))
    assert len(calls) == 1, "provider throttle must stop before the next CLI event"
    assert result != 0
    output = capsys.readouterr()
    assert not output.out
    failure = json.loads(output.err)
    assert failure["error"] == "commons_throttled" and failure["incomplete"] is True
    state = json.loads((workspace / "commons-throttle.json").read_text())
    captured_at = datetime.fromisoformat(state["observed_at"])
    expected = datetime.fromisoformat(state["retry_at"])
    # HTTP-date is relative to server Date too, never a local skew shortcut.
    assert expected == captured_at + timedelta(seconds=expected_delay)
    assert state["http_status"] == status and state["retry_after"] == retry
    assert state["api_error"] == body.get("error")
    evidence = json.loads((workspace / state["evidence"]).read_text())
    assert json.loads(evidence["body"]) == body
    assert "set-cookie" not in evidence["headers"]
    assert "private-token" not in json.dumps(evidence)
    assert state["retry_at"] in output.err and "--retry-throttled" in output.err
    assert not (workspace / "media-current.json").exists()
    assert not (workspace / "media-staging.json").exists()
    assert not list((workspace / "media-cache" / "commons").glob("*.json"))
    # A future command cannot silently treat a provider failure as image fallback.
    assert main(media_args(workspace)) != 0
    assert len(calls) == 1


def test_commons_explicit_retry_resumes_only_after_deadline_then_finalizes_and_publishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.content.cli import main

    workspace = uncached_media_workspace(tmp_path)
    calls = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return (
            httpx.Response(
                429,
                headers={"Retry-After": "120"},
                json={"error": {"code": "ratelimited"}},
            )
            if len(calls) == 1
            else httpx.Response(200, json=commons())
        )

    mock_commons_client(monkeypatch, response)
    assert main(media_args(workspace)) != 0
    assert len(calls) == 1
    from app.content import commons_transport

    state = json.loads((workspace / "commons-throttle.json").read_text())
    evidence_bytes = (workspace / state["evidence"]).read_bytes()
    with pytest.raises(commons_transport.CommonsThrottle):
        pipeline.finalize_media_receipts(workspace)
    retry_at = datetime.fromisoformat(state["retry_at"])
    monkeypatch.setattr(
        commons_transport, "utc_now", lambda: retry_at - timedelta(seconds=1)
    )
    assert main([*media_args(workspace), "--retry-throttled"]) != 0
    assert len(calls) == 1
    monkeypatch.setattr(commons_transport, "utc_now", lambda: retry_at)
    assert main(media_args(workspace)) != 0  # expiration alone is not consent to retry
    assert len(calls) == 1
    capsys.readouterr()
    assert main([*media_args(workspace), "--retry-throttled"]) == 0
    assert len(calls) == 2  # second event reuses successful exact-title cache
    output = json.loads(capsys.readouterr().out)
    assert output == {"events": 2, "passed": 2, "failed": 0}
    assert (workspace / state["evidence"]).read_bytes() == evidence_bytes
    assert not (workspace / "commons-throttle.json").exists()
    release = publish_release(workspace, tmp_path / "out", "resumed", fixture=True)
    assert release.event_count == 2
    assert (
        verify_release(
            tmp_path / "out" / "resumed", tmp_path / "out" / "resumed" / "media"
        )
        == release
    )


def test_ordinary_one_image_http_failure_still_falls_back_and_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.content.cli import main

    workspace = uncached_media_workspace(tmp_path)
    calls = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return (
            httpx.Response(404, json={"error": {"code": "missingtitle"}})
            if len(calls) == 1
            else httpx.Response(200, json=commons())
        )

    mock_commons_client(monkeypatch, response)
    assert main(media_args(workspace)) == 0
    assert len(calls) == 2
    assert json.loads(capsys.readouterr().out)["passed"] == 2
    generation = (
        workspace
        / json.loads((workspace / "media-current.json").read_text())["generation"]
    )
    decisions = json.loads((generation / "decisions.json").read_text())
    assert sum(decision["candidate"] is None for decision in decisions.values()) == 1
    assert any(
        "commons_http_404" in (decision["reason"] or "")
        for decision in decisions.values()
    )
    assert not (workspace / "commons-throttle.json").exists()


@pytest.mark.parametrize("status", [429, 503])
def test_image_download_throttle_is_not_an_individual_image_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: int,
) -> None:
    from app.content.cli import main

    workspace, _ = with_image(tmp_path)
    calls = []

    def throttled_download(
        url: str, _destination: Path, _allowed_hosts: tuple[str, ...]
    ) -> Path:
        calls.append(url)
        response = httpx.Response(
            status, headers={"Retry-After": "120"}, request=httpx.Request("GET", url)
        )
        response.raise_for_status()
        raise AssertionError("unreachable")

    monkeypatch.setattr(pipeline, "download_image", throttled_download)
    assert main(media_args(workspace)) != 0
    assert len(calls) == 1
    assert json.loads(capsys.readouterr().err)["error"] == "commons_throttled"
    assert not (workspace / "media-current.json").exists()


def test_throttle_body_read_failure_still_stops_on_known_http_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.content.cli import main

    workspace = uncached_media_workspace(tmp_path)
    calls = []

    class BrokenBody(httpx.SyncByteStream):
        def __iter__(self) -> Any:
            yield b"busy"
            raise httpx.ReadError("failed response body")

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"}, stream=BrokenBody())

    mock_commons_client(monkeypatch, response)
    assert main(media_args(workspace)) != 0
    assert len(calls) == 1
    state = json.loads(capsys.readouterr().err)
    assert state["http_status"] == 429
    evidence = json.loads((workspace / state["evidence"]).read_text())
    assert evidence["body_truncated"] is True


@pytest.mark.parametrize(
    "error", [OSError("disk failure"), ValueError("immutable evidence conflict")]
)
def test_throttle_evidence_write_failure_cannot_become_fallback_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    from app.content import commons_transport
    from app.content.cli import main

    workspace = uncached_media_workspace(tmp_path)
    calls = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    mock_commons_client(monkeypatch, response)

    def failed_write(_path: Path, _data: bytes) -> None:
        raise error

    monkeypatch.setattr(commons_transport, "immutable_write", failed_write)
    assert main(media_args(workspace)) != 0
    assert len(calls) == 1
    assert not capsys.readouterr().out
    assert not (workspace / "media-current.json").exists()
    assert not (workspace / "media-staging.json").exists()


def test_valid_http_date_survives_malformed_server_date_and_large_seconds_are_honored() -> (
    None
):
    from app.content import commons_transport

    now = datetime(2026, 10, 12, tzinfo=UTC)
    seconds, basis = commons_transport._retry_seconds(
        httpx.Headers(
            {"Retry-After": "Mon, 12 Oct 2026 01:00:00 GMT", "Date": "malformed"}
        ),
        now,
    )
    assert seconds >= 3600 and basis == "http-date"
    seconds, basis = commons_transport._retry_seconds(
        httpx.Headers({"Retry-After": "3153600000"}), now
    )
    assert seconds == 3153600000 and basis == "seconds"


def test_successful_compressed_metadata_keeps_existing_cache_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import gzip

    from app.content.cli import main

    workspace = uncached_media_workspace(tmp_path)

    def response(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=gzip.compress(json.dumps(commons()).encode()),
            headers={"Content-Encoding": "gzip"},
        )

    mock_commons_client(monkeypatch, response)
    assert main(media_args(workspace)) == 0
    assert json.loads(capsys.readouterr().out)["passed"] == 2
    generation = (
        workspace
        / json.loads((workspace / "media-current.json").read_text())["generation"]
    )
    assert (
        len(
            MediaCatalog.model_validate_json(
                (generation / "media.json").read_text()
            ).records
        )
        == 1
    )


def test_stopped_retry_preserves_existing_frozen_batch_and_success_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.content.cli import main
    from app.content.commons_transport import CommonsThrottle
    from tests.content.test_media import cache

    workspace, _ = with_image(tmp_path)
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    assert main(media_args(workspace)) == 0
    old_pointer = (workspace / "media-current.json").read_bytes()
    generation = workspace / json.loads(old_pointer)["generation"]
    frozen_files = {
        str(path.relative_to(generation)): path.read_bytes()
        for path in generation.rglob("*")
        if path.is_file()
    }
    source_pointer = (workspace / "current.json").read_bytes()
    for path in (workspace / "media-cache" / "commons").glob("*.json"):
        path.unlink()
    calls = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    mock_commons_client(monkeypatch, response)
    capsys.readouterr()
    assert main(media_args(workspace)) != 0
    assert not capsys.readouterr().out
    with pytest.raises(CommonsThrottle):
        pipeline.finalize_media_receipts(
            workspace
        )  # an old complete stage is not new success
    assert (workspace / "media-current.json").read_bytes() == old_pointer
    assert (workspace / "current.json").read_bytes() == source_pointer
    assert {
        str(path.relative_to(generation)): path.read_bytes()
        for path in generation.rglob("*")
        if path.is_file()
    } == frozen_files
    cache(workspace, "File:Synthetic Ada.png", commons())
    # Cache-only lookup remains available and doesn't clear cooldown or issue HTTP.
    assert (
        pipeline._commons_metadata(workspace, "File:Synthetic Ada.png", fetch=True)[0]
        == commons()
    )
    assert len(calls) == 1


def test_huge_throttle_body_is_bounded_private_evidence_not_success_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.content import commons_transport
    from app.content.cli import main

    workspace = uncached_media_workspace(tmp_path)

    def response(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            headers={"Retry-After": "999999999999999999999999999999"},
            content=b"x" * (2 * 1024 * 1024),
        )

    mock_commons_client(monkeypatch, response)
    assert main(media_args(workspace)) != 0
    state = json.loads(capsys.readouterr().err)
    evidence = json.loads((workspace / state["evidence"]).read_text())
    assert evidence["body_truncated"] is True
    assert len(evidence["body"].encode()) == commons_transport.MAX_RESPONSE_BYTES
    assert (
        state["retry_at"] is None
    )  # unrepresentable wait must never become an early retry
    assert main([*media_args(workspace), "--retry-throttled"]) != 0
    assert not (workspace / "media-current.json").exists()


def test_corrupt_private_throttle_state_fails_closed_without_provider_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.content.cli import main

    workspace = uncached_media_workspace(tmp_path)
    (workspace / "commons-throttle.json").write_text("not-json")

    def response(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("stopped workspace must not request provider")

    mock_commons_client(monkeypatch, response)
    assert main(media_args(workspace)) != 0
    assert (
        json.loads(capsys.readouterr().err)["reason"]
        == "invalid_private_throttle_state"
    )


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
