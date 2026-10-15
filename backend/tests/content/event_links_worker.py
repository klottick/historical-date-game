"""Controlled subprocess providers; never imported by production acquisition."""

import asyncio
import os
import socket
import ssl
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

import httpx


def main() -> None:
    mode, marker_arg = sys.argv[1:]
    marker = Path(marker_arg)
    marker.with_suffix(".started").write_text(str(os.getpid()))
    # The parent deliberately makes its lock inheritable in one regression.
    descriptors = Path("/proc/self/fd")
    assert not any(
        os.readlink(fd).endswith("/.lock")
        for fd in descriptors.iterdir()
        if fd.exists()
    )
    if mode in {"startup", "partial_output_stall"}:
        if mode == "partial_output_stall":
            sys.stdout.buffer.write(b"x" * (256 * 1024))
            sys.stdout.buffer.flush()
        time.sleep(12)
        marker.with_suffix(".finished").write_text("late worker")
        return
    if mode == "crash":
        sys.exit(7)
    if mode == "malformed_ipc":
        sys.stdout.buffer.write(b"not json")
        return

    from app.content import event_links_transport as transport

    if mode == "dns":

        def stalled_dns(host: Any, *_args: Any, **_kwargs: Any) -> Any:
            assert host in ("en.wikipedia.org", b"en.wikipedia.org")
            marker.with_suffix(".dns").write_text("en.wikipedia.org")
            time.sleep(12)
            marker.with_suffix(".finished").write_text("late resolver")
            raise socket.gaierror("controlled DNS stall, no external lookup")

        socket.getaddrinfo = stalled_dns
    elif mode in {"headers", "slow_trickle"}:
        original_read = transport.read_response
        original_client = httpx.AsyncClient

        async def read_with_provider(
            params: dict[str, str],
        ) -> tuple[httpx.Response, bytes | None]:
            tasks: set[asyncio.Task[Any]] = set()

            async def provider(
                reader: asyncio.StreamReader, writer: asyncio.StreamWriter
            ) -> None:
                task = asyncio.current_task()
                assert task is not None
                tasks.add(task)
                try:
                    await reader.readuntil(b"\r\n\r\n")
                    marker.with_suffix(".request").write_text("native HTTP request")
                    if mode == "headers":
                        await asyncio.sleep(12)
                        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
                        await writer.drain()
                    else:
                        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 24\r\n\r\n")
                        await writer.drain()
                        for _ in range(24):
                            await asyncio.sleep(0.5)
                            writer.write(b" ")
                            await writer.drain()
                    marker.with_suffix(".finished").write_text("late response")
                finally:
                    writer.close()
                    with suppress(ConnectionError):
                        await writer.wait_closed()

            server = await asyncio.start_server(provider, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]

            class LoopbackTransport(httpx.AsyncHTTPTransport):
                async def handle_async_request(
                    self, request: httpx.Request
                ) -> httpx.Response:
                    assert str(request.url).startswith(
                        "https://en.wikipedia.org/w/api.php?"
                    )
                    # Production's default TLS context must still verify both.
                    assert self._pool._ssl_context.check_hostname
                    assert self._pool._ssl_context.verify_mode == ssl.CERT_REQUIRED
                    request.url = request.url.copy_with(
                        scheme="http", host="127.0.0.1", port=port
                    )
                    return await super().handle_async_request(request)

            httpx.AsyncClient = lambda **kwargs: original_client(
                **kwargs, transport=LoopbackTransport()
            )
            try:
                return await original_read(params)
            finally:
                server.close()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await server.wait_closed()

        transport.read_response = read_with_provider
    else:
        original_client = httpx.AsyncClient

        def handler(request: httpx.Request) -> httpx.Response:
            assert (
                request.url.scheme == "https" and request.url.host == "en.wikipedia.org"
            )
            assert request.url.path == "/w/api.php"
            assert request.url.params["maxlag"] == "5"
            assert request.headers["User-Agent"].startswith("HistoricalDateGame/1.0")
            marker.with_suffix(".request").write_text(str(request.url))
            if mode == "transport_error":
                raise httpx.ConnectError("controlled transport error")
            if mode == "redirect":
                return httpx.Response(
                    302, headers={"Location": "https://evil.example/article"}, json={}
                )
            if mode == "throttle":
                return httpx.Response(
                    429, headers={"Retry-After": "7"}, content=b"busy"
                )
            if mode == "oversize":
                return httpx.Response(200, content=b"x" * (5 * 1024 * 1024 + 1))
            return httpx.Response(
                200,
                json={
                    "parse": {
                        "title": "January 1",
                        "revid": 991,
                        "text": "x" * (4 * 1024 * 1024),
                    }
                },
            )

        def client(**kwargs: Any) -> httpx.AsyncClient:
            assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
            assert kwargs.get("verify", True) is not False
            return original_client(**kwargs, transport=httpx.MockTransport(handler))

        httpx.AsyncClient = client
    transport.main()


if __name__ == "__main__":
    main()
