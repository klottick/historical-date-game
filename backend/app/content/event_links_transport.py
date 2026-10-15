"""Private per-attempt HTTP isolation: 10s acquisition + at most 1s kill/reap.

Native hostname resolution may block in libc even after cancelling an async
request. Only the child owns HTTP, DNS threads and Runner cleanup; the parent
owns the deadline and drains/reaps before allowing another attempt. No cache or
game state crosses this boundary. TLS/hostname validation remain httpx defaults.
"""

import asyncio
import base64
import json
import subprocess
import sys
import time
from typing import Any

import httpx

API_URL = "https://en.wikipedia.org/w/api.php"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_PARAMS_BYTES = 128 * 1024
# Base64 body plus bounded protocol/header overhead; never raw provider logs.
MAX_IPC_BYTES = 4 * ((MAX_RESPONSE_BYTES + 2) // 3) + 1024 * 1024
ACQUISITION_SECONDS = 10.0
CLEANUP_SECONDS = 1.0


async def read_response(params: dict[str, str]) -> tuple[httpx.Response, bytes | None]:
    """One native HTTP read. Called in a killable child, not in the parent."""
    async with asyncio.timeout(ACQUISITION_SECONDS):
        async with httpx.AsyncClient(
            timeout=ACQUISITION_SECONDS,
            follow_redirects=False,
            trust_env=False,
            headers={
                "User-Agent": "HistoricalDateGame/1.0 (https://github.com/klottick/historical-date-game; offline event-link enrichment)"
            },
        ) as client:
            async with client.stream("GET", API_URL, params=params) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        return response, None
                    body.extend(chunk)
                return response, bytes(body)


def _kill_and_reap(process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + CLEANUP_SECONDS
    process.kill()
    # communicate, rather than wait alone, finishes partially written/read pipes.
    # There is no unbounded Popen context-manager wait or executor in the parent.
    process.communicate(timeout=max(0, deadline - time.monotonic()))


def acquire(params: dict[str, str]) -> tuple[httpx.Response, bytes | None]:
    payload = json.dumps(params, separators=(",", ":")).encode()
    if len(payload) > MAX_PARAMS_BYTES:
        raise ValueError("event_link_request_limits")
    deadline = time.monotonic() + ACQUISITION_SECONDS
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "app.content.event_links_transport"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as exc:
        raise httpx.TransportError("event_link_worker_start_failed") from exc
    try:
        try:
            output, _ = process.communicate(
                input=payload, timeout=max(0, deadline - time.monotonic())
            )
        except subprocess.TimeoutExpired:
            _kill_and_reap(process)
            raise TimeoutError("event_link_response_deadline") from None
        except BaseException:
            _kill_and_reap(process)
            raise
    finally:
        for pipe in (process.stdin, process.stdout):
            if pipe is not None:
                pipe.close()
    if process.returncode != 0:
        raise httpx.TransportError("event_link_worker_failed")
    if len(output) > MAX_IPC_BYTES:
        raise ValueError("event_link_worker_response_limits")
    data = json.loads(output)
    if not isinstance(data, dict):
        raise ValueError("event_link_worker_response")
    error = data.get("error")
    if error == "response_deadline":
        raise TimeoutError("event_link_response_deadline")
    if error == "transport_unavailable":
        raise httpx.TransportError("event_link_transport_unavailable")
    if error or set(data) != {"status", "retry_after", "body"}:
        raise ValueError("event_link_worker_response")
    status, retry_after, encoded = data["status"], data["retry_after"], data["body"]
    if type(status) is not int or not 100 <= status <= 599:
        raise ValueError("event_link_worker_status")
    if retry_after is not None and not isinstance(retry_after, str):
        raise ValueError("event_link_worker_headers")
    if encoded is not None and not isinstance(encoded, str):
        raise ValueError("event_link_worker_body")
    body = base64.b64decode(encoded, validate=True) if encoded is not None else None
    if body is not None and len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("event_link_worker_response_limits")
    return httpx.Response(
        status, headers={"Retry-After": retry_after} if retry_after is not None else {}
    ), body


def main() -> None:
    """Internal worker protocol, deliberately not a user-facing acquisition CLI."""
    result: dict[str, Any]
    try:
        raw = sys.stdin.buffer.read(MAX_PARAMS_BYTES + 1)
        if len(raw) > MAX_PARAMS_BYTES:
            raise ValueError("event_link_request_limits")
        params = json.loads(raw)
        if not isinstance(params, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in params.items()
        ):
            raise ValueError("event_link_request")
        # asyncio.run's executor join may hang on DNS. Parent kills the entire
        # child before accepting a result, including during Runner cleanup.
        response, body = asyncio.run(read_response(params))
        result = {
            "status": response.status_code,
            "retry_after": response.headers.get("Retry-After"),
            "body": base64.b64encode(body).decode("ascii")
            if body is not None
            else None,
        }
    except TimeoutError:
        result = {"error": "response_deadline"}
    except httpx.HTTPError:
        result = {"error": "transport_unavailable"}
    except ValueError, TypeError:
        result = {"error": "malformed_evidence"}
    output = json.dumps(result, separators=(",", ":")).encode()
    if len(output) > MAX_IPC_BYTES:
        output = b'{"error":"malformed_evidence"}'
    sys.stdout.buffer.write(output)


if __name__ == "__main__":
    main()
