"""Private Commons acquisition stop/retry state; not media acceptance policy.

No automatic retry or long sleep. Assignment holds the workspace media lock;
explicit retry uses that same lock. A stopped workspace cannot finalize until
the operator explicitly retries after the persisted provider deadline.
"""

import fcntl
import hashlib
import json
import math
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

from app.content.importer import _sync_directory, _write
from app.content.media.download import immutable_write

DEFAULT_RETRY_SECONDS = 300
MAX_RESPONSE_BYTES = 1024 * 1024
THROTTLE_CODES = {
    "maxlag",
    "ratelimited",
    "rate-limited",
    "throttled",
    "actionthrottled",
}
EVIDENCE_HEADERS = {"retry-after", "date", "content-type", "x-database-lag"}


class CommonsThrottle(RuntimeError):
    """Not a ValueError/HTTPError: must escape the individual-image fallback gate."""

    def __init__(self, details: dict[str, Any]):
        self.details = details
        super().__init__("commons_throttled")


def utc_now() -> datetime:
    return datetime.now(UTC)


def _http_date(value: str) -> datetime:
    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        raise ValueError("ambiguous_http_date")
    return parsed.astimezone(UTC)


def _retry_seconds(headers: httpx.Headers, now: datetime) -> tuple[int, str]:
    value = headers.get("retry-after", "").strip()
    try:
        if re.fullmatch(r"[0-9]+", value):
            if len(value) > 100:
                return 10**100, "seconds"
            return max(1, int(value)), "seconds"
        deadline = _http_date(value)
        delay = (deadline - now).total_seconds()
        if headers.get("date"):
            # Clock skew must never shorten the server's requested interval.
            try:
                delay = max(
                    delay, (deadline - _http_date(headers["date"])).total_seconds()
                )
            except ValueError, TypeError, OverflowError:
                pass
        if delay > 0:
            return math.ceil(delay), "http-date"
    except ValueError, TypeError, OverflowError:
        pass
    return DEFAULT_RETRY_SECONDS, "conservative-default"


def _state(workspace: Path) -> dict[str, Any] | None:
    path = workspace / "commons-throttle.json"
    if not path.exists() and not path.is_symlink():
        return None
    try:
        if path.is_symlink() or path.stat().st_size > MAX_RESPONSE_BYTES:
            raise ValueError("unsafe_state")
        state = json.loads(path.read_text())
        deadline = (
            datetime.fromisoformat(state["retry_at"])
            if state["retry_at"] is not None
            else None
        )
        if (deadline is not None and deadline.tzinfo is None) or state[
            "provider"
        ] != "commons":
            raise ValueError("invalid_state")
        return dict(state)
    except ValueError, KeyError, TypeError, OSError:
        raise CommonsThrottle(
            {
                "provider": "commons",
                "retry_at": None,
                "reason": "invalid_private_throttle_state",
            }
        ) from None


def ensure_commons_ready(workspace: Path) -> None:
    state = _state(workspace)
    if state is not None:
        raise CommonsThrottle(state)


def retry_commons(workspace: Path) -> None:
    with (workspace / ".media.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = _state(workspace)
        if state is None:
            return
        if state["retry_at"] is None or utc_now() < datetime.fromisoformat(
            state["retry_at"]
        ):
            raise CommonsThrottle(state)
        (workspace / "commons-throttle.json").unlink()
        _sync_directory(workspace)


def _api_error(body: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(body)
        error = value.get("error") if isinstance(value, dict) else None
        return error if isinstance(error, dict) else None
    except ValueError, UnicodeDecodeError:
        return None


def _stop(
    workspace: Path,
    title: str,
    response: httpx.Response,
    body: bytes,
    *,
    truncated: bool = False,
) -> None:
    now = utc_now()
    seconds, basis = _retry_seconds(response.headers, now)
    try:
        retry_at = (now + timedelta(seconds=seconds)).isoformat()
    except OverflowError:
        # Never turn a valid but unrepresentably long wait into an early retry.
        retry_at = None
    headers = {
        name: response.headers[name]
        for name in EVIDENCE_HEADERS
        if name in response.headers
    }
    evidence = {
        "provider": "commons",
        "title": title,
        "http_status": response.status_code,
        "headers": headers,
        "api_error": _api_error(body),
        "body": body.decode("utf-8", errors="replace"),
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "body_truncated": truncated,
        "observed_at": now.isoformat(),
        "retry_after": response.headers.get("retry-after"),
        "retry_at": retry_at,
        "retry_basis": basis,
    }
    encoded = json.dumps(evidence, sort_keys=True).encode()
    relative = (
        Path("media-failures")
        / "commons"
        / (hashlib.sha256(encoded).hexdigest() + ".json")
    )
    details = {
        key: value for key, value in evidence.items() if key not in {"body", "headers"}
    }
    details["evidence"] = str(relative)
    try:
        temporary = workspace / "commons-throttle.json.tmp"
        _write(temporary, json.dumps(details, sort_keys=True))
        temporary.chmod(0o600)
        temporary.replace(workspace / "commons-throttle.json")
        _sync_directory(workspace)
        (workspace / relative.parent).mkdir(parents=True, exist_ok=True, mode=0o700)
        immutable_write(workspace / relative, encoded)
    except OSError, ValueError:
        details["reason"] = "private_throttle_evidence_write_failed"
        raise CommonsThrottle(details) from None
    raise CommonsThrottle(details)


class _MetadataClient:
    def __init__(self, client: httpx.Client, workspace: Path, title: str):
        self.client = client
        self.workspace = workspace
        self.title = title

    @contextmanager
    def stream(self, method: str, url: str, **kwargs: Any) -> Iterator[httpx.Response]:
        ensure_commons_ready(self.workspace)
        with self.client.stream(method, url, **kwargs) as response:
            started = time.monotonic()
            body = bytearray()
            truncated = False
            try:
                for chunk in response.iter_bytes(64 * 1024):
                    if (
                        len(body) + len(chunk) > MAX_RESPONSE_BYTES
                        or time.monotonic() - started > 20
                    ):
                        body.extend(chunk[: max(0, MAX_RESPONSE_BYTES - len(body))])
                        truncated = True
                        break
                    body.extend(chunk)
            except httpx.HTTPError:
                if response.status_code in {429, 503}:
                    _stop(
                        self.workspace,
                        self.title,
                        response,
                        bytes(body),
                        truncated=True,
                    )
                raise
            error = _api_error(bytes(body))
            if response.status_code in {429, 503} or (
                error and error.get("code") in THROTTLE_CODES
            ):
                _stop(
                    self.workspace,
                    self.title,
                    response,
                    bytes(body),
                    truncated=truncated,
                )
            if truncated:
                raise ValueError("commons_response_limits")
            headers = dict(response.headers)
            # iter_bytes already decoded transport encoding; do not decode twice.
            headers.pop("content-encoding", None)
            headers.pop("content-length", None)
            yield httpx.Response(
                response.status_code,
                headers=headers,
                content=bytes(body),
                request=response.request,
            )


@contextmanager
def client(workspace: Path, title: str, **kwargs: Any) -> Iterator[_MetadataClient]:
    ensure_commons_ready(workspace)
    with httpx.Client(**kwargs) as transport:
        yield _MetadataClient(transport, workspace, title)


def check_http_failure(workspace: Path, title: str, error: Exception) -> None:
    """The pinned upload transport preserves the failed response in HTTPStatusError."""
    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code in {
        429,
        503,
    }:
        response = error.response
        # Never read a closed/unchecked stream from the pinned image downloader.
        body = (
            response.content[:MAX_RESPONSE_BYTES]
            if response.is_stream_consumed
            else b""
        )
        _stop(
            workspace,
            title,
            response,
            body,
            truncated=not response.is_stream_consumed
            or len(response.content) > MAX_RESPONSE_BYTES,
        )


def fingerprint_source(path: Path) -> bytes:
    """Keep existing C5 acceptance fingerprints for this acquisition-only fix.

    Project ONLY the exact operational hooks added here back to their BASE
    0bc76c7 spelling. Every other byte (including all offline cache validation,
    media acceptance, provenance freezing and receipt rules) remains hashed.
    This module is outside media/: it controls stopping/retry, not image passes.
    Any actual acceptance change still invalidates the whole persisted batch.
    """
    source = path.read_bytes()
    if path.parent.name != "media" or path.name != "pipeline.py":
        return source
    for current, baseline in (
        (b"from app.content import commons_transport\n", b""),
        (b"commons_transport.fingerprint_source(path)", b"path.read_bytes()"),
        (
            b"with commons_transport.client(\n            workspace, title, timeout=10, follow_redirects=False, trust_env=False\n",
            b"with httpx.Client(\n            timeout=10, follow_redirects=False, trust_env=False\n",
        ),
        (b"        commons_transport.ensure_commons_ready(workspace)\n", b""),
        (
            b"                commons_transport.check_http_failure(workspace, title, exc)\n",
            b"",
        ),
    ):
        source = source.replace(current, baseline)
    return source
