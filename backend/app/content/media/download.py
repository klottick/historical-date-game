"""Bounded downloads with explicitly checked redirects and DNS-pinned HTTPS."""

import hashlib
import ipaddress
import os
import socket
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

MAX_BYTES = 16 * 1024 * 1024
MAX_SECONDS = 30.0
HOST = "upload.wikimedia.org"
UA = "HistoricalDateGame/automated-v1 (bounded Commons media caching)"


def _resolve(host: str) -> tuple[str, ...]:
    addresses = tuple(
        sorted(
            {
                str(entry[4][0])
                for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            }
        )
    )
    if not addresses:
        raise ValueError("unresolved_download_host")
    return addresses


def _public(addresses: tuple[str, ...]) -> None:
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or getattr(ip, "ipv4_mapped", None) is not None:
            raise ValueError("private_download_target")


def _validate_url(url: str, allowed_hosts: tuple[str, ...]) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != HOST
        or HOST not in allowed_hosts
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.fragment
        or any(ord(c) < 33 for c in url)
        or "\\" in url
    ):
        raise ValueError("unapproved_download_url")
    return HOST


class _PinnedTransport(httpx.HTTPTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = _validate_url(str(request.url), (HOST,))
        addresses = _resolve(host)
        _public(addresses)
        headers = request.headers.copy()
        headers["Host"] = host
        # Keep the TLS certificate/SNI and HTTP Host tied to the approved DNS
        # name, but connect to this checked IP. No second DNS resolution at dial.
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=addresses[0]),
            headers=headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": host},
        )
        return super().handle_request(pinned)


def _client() -> httpx.Client:
    return httpx.Client(
        transport=_PinnedTransport(retries=0),
        follow_redirects=False,
        trust_env=False,
        timeout=10,
    )


def immutable_write(path: Path, data: bytes) -> None:
    """Atomic create-only installation. Existing different bytes are never replaced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".asset-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != data:
                raise ValueError("immutable_asset_conflict")
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def download_image(url: str, destination: Path, allowed_hosts: tuple[str, ...]) -> Path:
    started = time.monotonic()
    data = bytearray()
    with _client() as client:
        for _ in range(5):
            host = _validate_url(url, allowed_hosts)
            _public(_resolve(host))
            if time.monotonic() - started > MAX_SECONDS:
                raise ValueError("download_deadline")
            with client.stream(
                "GET", url, headers={"User-Agent": UA, "Accept-Encoding": "identity"}
            ) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get("location", ""))
                    _validate_url(url, allowed_hosts)
                    continue
                response.raise_for_status()
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise ValueError("encoded_download")
                if int(response.headers.get("content-length", "0")) > MAX_BYTES:
                    raise ValueError("download_too_large")
                if response.headers.get("content-type", "").split(";")[0] not in {
                    "image/jpeg",
                    "image/png",
                    "image/webp",
                }:
                    raise ValueError("unsupported_image_mime")
                for chunk in response.iter_bytes(64 * 1024):
                    if len(data) + len(chunk) > MAX_BYTES:
                        raise ValueError("download_too_large")
                    if time.monotonic() - started > MAX_SECONDS:
                        raise ValueError("download_deadline")
                    data.extend(chunk)
                if not data:
                    raise ValueError("empty_download")
                immutable_write(destination, bytes(data))
                return destination
    raise ValueError("download_redirect_limit")


def asset_sha256(path: Path) -> str:
    if path.is_symlink() or path.stat().st_size > MAX_BYTES:
        raise ValueError("invalid_asset")
    return hashlib.sha256(path.read_bytes()).hexdigest()
