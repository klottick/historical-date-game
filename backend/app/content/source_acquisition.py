"""Explicit, bounded acquisition of exact source objects, never runtime work.

No archive extraction or mutable API fallback. A missing historical route needs
an explicitly supplied source-only directory. Fresh receipts live NEXT TO the
input root, never in the historically observed payload. Trusted POSIX writers,
as for publication; links and special files are rejected before reading.
"""

import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx

from app.content.adapters.selected import UA
from app.content.publish import _safe_root, canonical
from app.content.runtime import read_checked, sha256
from app.content.runtime_models import BuildLock, LockedSource

HTTPS_HOSTS = frozenset({"raw.githubusercontent.com"})
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_SOURCE_FILES = 32
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def safe_output(path: Path) -> Path:
    """Only external scratch or ignored paths, and never an existing output."""
    # Check the original spelling first: resolving ``link/../output`` would
    # otherwise conceal the symlink. All policy checks and writes use canonical
    # paths, never lexical containment with unresolved parent components.
    path = _safe_root(path).resolve()
    if path.exists():
        raise ValueError("output_exists:" + str(path))
    if path.is_relative_to(REPOSITORY_ROOT):
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--", str(path)],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            raise ValueError("output_must_be_ignored:" + str(path))
    return path


def checked_source(source: LockedSource, body: bytes) -> bytes:
    if len(body) != source.size:
        raise ValueError("source_size_mismatch:" + source.path)
    if sha256(body) != source.sha256:
        raise ValueError("source_digest_mismatch:" + source.path)
    return body


def _bounds(lock: BuildLock) -> None:
    if (
        not 0 < len(lock.sources) <= MAX_SOURCE_FILES
        or any(not 0 < source.size <= MAX_SOURCE_BYTES for source in lock.sources)
        or sum(source.size for source in lock.sources) > MAX_TOTAL_BYTES
    ):
        raise ValueError("source_scope_or_size_limit")


def check_source_directory(lock: BuildLock, root: Path) -> None:
    # A hostile lock must not turn a local/cache read into an unbounded one.
    _bounds(lock)
    root = _safe_root(root)
    if not root.is_dir():
        raise ValueError("source_dir_missing:" + str(root))
    expected = {source.path for source in lock.sources}
    actual = set()
    directories: set[str] = set()
    for name in expected:
        directories.update(str(p) for p in Path(name).parents if str(p) != ".")
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError("unsafe_source_path:" + relative)
        if path.is_dir():
            if relative not in directories:
                raise ValueError("unexpected_source_directory:" + relative)
        else:
            actual.add(relative)
    if actual != expected:
        raise ValueError("source_dir_scope_mismatch")
    for source in lock.sources:
        checked_source(source, read_checked(root / source.path, limit=source.size))


def _url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in HTTPS_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.fragment
        or any(c.isspace() or ord(c) < 32 for c in unquote(url))
    ):
        raise ValueError("unsafe_source_host_or_url")


def _download(source: LockedSource) -> bytes:
    assert source.url is not None
    _url(source.url)
    # Serial one-shot downloads. Every non-200 (including throttle/stop status)
    # aborts the acquisition; no retries, redirects, proxies or alternate hosts.
    time.sleep(1)
    started = time.monotonic()
    with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
        with client.stream(
            "GET",
            source.url,
            headers={"User-Agent": UA, "Accept-Encoding": "identity"},
        ) as response:
            if 300 <= response.status_code < 400:
                raise ValueError("source_redirect_refused:" + source.path)
            if response.status_code != 200:
                raise ValueError(f"source_http_{response.status_code}:" + source.path)
            if (
                response.headers.get("Content-Encoding", "identity").lower()
                != "identity"
            ):
                raise ValueError("source_content_encoding_refused:" + source.path)
            data = bytearray()
            # Do not buffer a fixed-size chunk: slow small transport chunks must
            # reach the deadline check immediately. Identity encoding also keeps
            # decompression expansion outside this exact-byte boundary.
            for chunk in response.iter_bytes():
                if len(data) + len(chunk) > source.size:
                    raise ValueError("source_size_limit:" + source.path)
                if time.monotonic() - started > 30:
                    raise ValueError("source_total_timeout:" + source.path)
                data.extend(chunk)
    return checked_source(source, bytes(data))


def acquire_sources(
    lock: BuildLock, destination: Path, *, source_dir: Path | None = None
) -> Path:
    lock = BuildLock.model_validate_json(canonical(lock.model_dump(mode="json")))
    destination = safe_output(destination)
    receipt = safe_output(destination.with_name(destination.name + ".acquisition.json"))
    _bounds(lock)
    for source in lock.sources:
        if source.url is not None:
            _url(source.url)
        elif source_dir is None:
            raise ValueError(
                "missing_legacy_route_requires_checked_source_dir:" + source.path
            )
    cache = _safe_root(destination.parent / "source-cache").resolve()
    if source_dir is not None:
        source_dir = _safe_root(source_dir).resolve()
        if destination.is_relative_to(source_dir):
            raise ValueError("output_inside_source_dir")
        if cache.is_relative_to(source_dir) or source_dir.is_relative_to(cache):
            raise ValueError("cache_overlaps_source_dir")
        check_source_directory(lock, source_dir)
    if cache.exists() and not cache.is_dir():
        raise ValueError("unsafe_source_cache")
    bodies = {}
    retrievals = []
    for source in lock.sources:
        cached = cache / source.sha256
        # Even an explicitly supplied local object cannot conceal a corrupt hit.
        cached_body = (
            checked_source(source, read_checked(cached, limit=source.size))
            if cached.exists() or cached.is_symlink()
            else None
        )
        if source_dir is not None:
            body = checked_source(
                source, read_checked(source_dir / source.path, limit=source.size)
            )
            route = "checked-local-source"
        elif cached_body is not None:
            body, route = cached_body, "checked-cache"
        else:
            body, route = _download(source), "https"
        if cached_body is None:
            cache.mkdir(parents=True, exist_ok=True)
            with cached.open("xb") as stream:
                stream.write(body)
        bodies[source.path] = body
        retrievals.append(
            {
                "path": source.path,
                "sha256": source.sha256,
                "bytes": len(body),
                "route": route,
                "url": source.url,
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
        )
    destination.mkdir(parents=True)
    for name, body in bodies.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(body)
    with receipt.open("xb") as stream:
        stream.write(
            canonical(
                {
                    "retrieved_at": datetime.now(UTC).isoformat(),
                    "objects": retrievals,
                }
            )
        )
    return destination
