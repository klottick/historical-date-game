"""Synthetic pinned objects; never access production inputs or the network."""

import importlib
import importlib.util
import json
import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.content.runtime import sha256
from app.content.runtime_models import BuildLock, LockedSource

HTTP_CLIENT = httpx.Client


def acquisition() -> Any:
    assert importlib.util.find_spec("app.content.source_acquisition"), "Missing checked acquisition"
    return importlib.import_module("app.content.source_acquisition")


def lock_for(body: bytes = b"source", url: str | None = None) -> BuildLock:
    return BuildLock(
        release_id="replay-v1", created_at=datetime(2026, 10, 16, tzinfo=UTC),
        evaluation_date=date(2026, 10, 12), origin_release_id="origin",
        origin_manifest_sha256="a" * 64, python="3.15", dependencies={},
        code_sha256={}, sources=(LockedSource(path="supplements.jsonl", size=len(body),
        sha256=sha256(body), url=url, role="supplements"),), payload_sha256={},
    )


def transport(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    module = acquisition()
    original = HTTP_CLIENT
    monkeypatch.setattr(module.httpx, "Client", lambda **kw: original(
        **kw, transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(module.time, "sleep", lambda _: None)


def test_acquisition_checks_download_and_cache_hashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = acquisition()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["User-Agent"].startswith("HistoricalDateGame/")
        return httpx.Response(200, content=b"source")

    transport(monkeypatch, handler)
    lock = lock_for(url="https://raw.githubusercontent.com/org/repo/pin/source")
    root = module.acquire_sources(lock, tmp_path / "first")
    assert (root / "supplements.jsonl").read_bytes() == b"source"
    module.acquire_sources(lock, tmp_path / "second")
    assert len(calls) == 1
    cache = tmp_path / "source-cache" / lock.sources[0].sha256
    cache.write_bytes(b"broken")
    with pytest.raises(ValueError, match="digest|size"):
        module.acquire_sources(lock, tmp_path / "third")
    assert len(calls) == 1
    transport(monkeypatch, lambda _: httpx.Response(200, content=b"wrong!"))
    with pytest.raises(ValueError, match="digest"):
        module.acquire_sources(lock, tmp_path / "elsewhere" / "bad")


def test_missing_legacy_route_is_explicit(tmp_path: Path) -> None:
    module = acquisition()
    with pytest.raises(ValueError, match="source_dir.*supplements.jsonl"):
        module.acquire_sources(lock_for(), tmp_path / "missing")
    local = tmp_path / "local"
    local.mkdir()
    (local / "supplements.jsonl").write_bytes(b"source")
    root = module.acquire_sources(lock_for(), tmp_path / "ok", source_dir=local)
    assert (root / "supplements.jsonl").read_bytes() == b"source"
    with pytest.raises(ValueError, match="exists"):
        module.acquire_sources(lock_for(), root, source_dir=local)


@pytest.mark.parametrize("url,status,body,error", [
    ("https://raw.githubusercontent.com/a/b", 302, b"", "redirect"),
    ("https://raw.githubusercontent.com.evil/a", 200, b"source", "host"),
    ("https://127.0.0.1/a", 200, b"source", "host"),
    ("https://raw.githubusercontent.com/a/b", 200, b"too large", "size"),
    ("https://raw.githubusercontent.com/a/b", 429, b"", "http_429"),
])
def test_rejects_redirect_unsafe_host_and_oversize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        url: str, status: int, body: bytes, error: str) -> None:
    module = acquisition()
    transport(monkeypatch, lambda _: httpx.Response(status, content=body,
        headers={"Location": "https://evil.invalid/"}))
    with pytest.raises(ValueError, match=error):
        module.acquire_sources(lock_for(url=url), tmp_path / "out")


@pytest.mark.parametrize("attack", ["extra", "symlink", "hardlink", "corrupt"])
def test_local_scope_and_file_safety(tmp_path: Path, attack: str) -> None:
    module = acquisition()
    local = tmp_path / "local"
    local.mkdir()
    target = local / "supplements.jsonl"
    target.write_bytes(b"source")
    if attack == "extra":
        (local / "accepted-events.jsonl").write_bytes(b"not an input")
    elif attack == "symlink":
        target.unlink()
        target.symlink_to(tmp_path / "absent")
    elif attack == "hardlink":
        (tmp_path / "alias").hardlink_to(target)
    else:
        target.write_bytes(b"broken")
    with pytest.raises(ValueError):
        module.acquire_sources(lock_for(), tmp_path / "out", source_dir=local)


def test_retrieval_time_is_not_historical_observation(tmp_path: Path) -> None:
    module = acquisition()
    local = tmp_path / "local"
    local.mkdir()
    body = b'{"retrieved_at":"2020-01-01T00:00:00Z"}'
    (local / "supplements.jsonl").write_bytes(body)
    before = datetime.now(UTC)
    root = module.acquire_sources(lock_for(body), tmp_path / "out", source_dir=local)
    assert (root / "supplements.jsonl").read_bytes() == body
    receipt = json.loads((tmp_path / "out.acquisition.json").read_bytes())
    assert before <= datetime.fromisoformat(receipt["retrieved_at"]) <= datetime.now(UTC)
    assert {p.name for p in root.iterdir()} == {"supplements.jsonl"}


def test_local_lock_bounds_are_checked_before_any_read(tmp_path: Path) -> None:
    module = acquisition()
    lock = lock_for()
    oversized = lock.sources[0].model_copy(update={"size": module.MAX_SOURCE_BYTES + 1})
    lock = lock.model_copy(update={"sources": (oversized,)})
    local = tmp_path / "local"
    local.mkdir()
    (local / "supplements.jsonl").write_bytes(b"source")
    with pytest.raises(ValueError, match="source_scope_or_size_limit"):
        module.check_source_directory(lock, local)


def test_deadline_is_checked_between_small_transport_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = acquisition()
    elapsed = [0]
    delivered = []

    class SlowStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            for byte in b"source":
                elapsed[0] += 20
                delivered.append(byte)
                yield bytes([byte])

    transport(monkeypatch, lambda _: httpx.Response(200, stream=SlowStream()))
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: elapsed[0], sleep=lambda _: None))
    with pytest.raises(ValueError, match="timeout"):
        module.acquire_sources(lock_for(url="https://raw.githubusercontent.com/a/b"), tmp_path / "out")
    assert len(delivered) == 2  # do not buffer 64 KiB before checking the deadline


def test_encoded_source_bodies_are_refused_before_decoding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = acquisition()
    transport(monkeypatch, lambda _: httpx.Response(200, headers={"Content-Encoding": "gzip"},
        stream=httpx.ByteStream(b"not-decoded-source-bytes")))
    with pytest.raises(ValueError, match="encoding"):
        module.acquire_sources(lock_for(url="https://raw.githubusercontent.com/a/b"), tmp_path / "out")


def tree_state(root: Path) -> dict[str, tuple[bytes | None, int, int]]:
    """Detect writes/additions/removals, including rewriting identical bytes."""
    result = {}
    for path in (root, *root.rglob("*")):
        info = path.lstat()
        body = (
            os.fsencode(path.readlink()) if path.is_symlink()
            else None if path.is_dir() else path.read_bytes()
        )
        result[path.relative_to(root).as_posix()] = (body, info.st_mtime_ns, info.st_ctime_ns)
    return result


def test_acquire_canonical_containment_precedes_all_mutations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = acquisition()
    local = tmp_path / "retained"
    local.mkdir()
    (local / "supplements.jsonl").write_bytes(b"source")
    other = tmp_path / "other"
    other.mkdir()
    calls = []
    transport(monkeypatch, lambda request: calls.append(request) or httpx.Response(200, content=b"source"))
    before = tree_state(tmp_path)
    output = other / ".." / "retained" / "new"
    with pytest.raises(ValueError, match="output_inside_source_dir"):
        module.acquire_sources(lock_for(), output, source_dir=local)
    assert calls == []
    assert tree_state(tmp_path) == before


def test_safe_output_checks_canonical_repository_boundary(tmp_path: Path) -> None:
    module = acquisition()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = module.REPOSITORY_ROOT / "backend/review-unignored-output"
    assert not target.exists()
    spelling = outside / os.path.relpath(target, outside)
    before = tree_state(tmp_path)
    with pytest.raises(ValueError, match="output_must_be_ignored"):
        module.safe_output(spelling)
    assert tree_state(tmp_path) == before
    assert not target.exists()


def test_original_spelling_symlink_is_rejected_before_canonicalization(tmp_path: Path) -> None:
    module = acquisition()
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    before = tree_state(tmp_path)
    with pytest.raises(ValueError, match="symlink_path"):
        module.safe_output(alias / ".." / "new")
    assert tree_state(tmp_path) == before


def test_cache_cannot_alias_retained_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = acquisition()
    local = tmp_path / "source-cache"
    local.mkdir()
    (local / "supplements.jsonl").write_bytes(b"source")
    calls = []
    transport(monkeypatch, lambda request: calls.append(request) or httpx.Response(200, content=b"source"))
    before = tree_state(tmp_path)
    with pytest.raises(ValueError, match="cache.*source_dir"):
        module.acquire_sources(lock_for(), tmp_path / "new-inputs", source_dir=local)
    assert calls == []
    assert tree_state(tmp_path) == before
