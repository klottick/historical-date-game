"""Strict native-manifest registry checks: uncertainty never establishes absence."""

import base64
import hashlib
import json
import os
import re
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener

from scripts.distribution.release import SHA, VERSION, NoRedirect

registry_opener = NoRedirect()
urlopen = build_opener(registry_opener).open
ROOT = "https://ghcr.io"

MEDIA = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}


def token(image: str, *, push=False, anonymous=False) -> str:
    if not re.fullmatch(r"ghcr\.io/[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*", image):
        raise ValueError("Invalid registry image")
    if anonymous and push:
        raise ValueError("Anonymous registry writes are forbidden")
    headers = {"Cache-Control": "no-cache"}
    if not anonymous:
        credential = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        actor = os.environ.get("GITHUB_ACTOR")
        if not credential or not actor:
            raise ValueError("Explicit workflow registry credentials required")
        headers["Authorization"] = (
            "Basic " + base64.b64encode(f"{actor}:{credential}".encode()).decode()
        )
    query = urlencode(
        {
            "service": "ghcr.io",
            "scope": "repository:"
            + image.split("/", 1)[1]
            + (":pull,push" if push else ":pull"),
        }
    )
    with urlopen(
        Request(ROOT + "/token?" + query, headers=headers), timeout=30
    ) as response:
        value = json.loads(response.read())
    result = value.get("token") if isinstance(value, dict) else None
    if not isinstance(result, str) or not result or any(c.isspace() for c in result):
        raise ValueError("Registry returned no usable token")
    return result


def config_blob(image: str, digest: str, credential: str) -> dict:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Invalid configuration digest")
    request = Request(
        ROOT + "/v2/" + image.split("/", 1)[1] + "/blobs/" + digest,
        headers={"Authorization": "Bearer " + credential},
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read()
    except HTTPError as exc:
        target = exc.headers.get("Location", "")
        parsed = urlsplit(target)
        if (
            exc.code not in {302, 307}
            or parsed.scheme != "https"
            or parsed.hostname != "pkg-containers.githubusercontent.com"
            or parsed.username
            or parsed.password
        ):
            raise
        with urlopen(Request(target), timeout=30) as response:
            body = response.read()
    if "sha256:" + hashlib.sha256(body).hexdigest() != digest:
        raise ValueError("Configuration blob digest mismatch")
    config = json.loads(body)
    if not isinstance(config, dict):
        raise ValueError("Malformed image configuration")  # noqa: TRY004 - fail-closed registry contract
    return config


def put_manifest(
    image: str, reference: str, credential: str, data: bytes, media: str
) -> None:
    if (
        not credential
        or media not in MEDIA
        or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", reference)
    ):
        raise ValueError("Invalid manifest promotion")
    expected = "sha256:" + hashlib.sha256(data).hexdigest()
    request = Request(
        ROOT + "/v2/" + image.split("/", 1)[1] + "/manifests/" + reference,
        data=data,
        method="PUT",
        headers={"Authorization": "Bearer " + credential, "Content-Type": media},
    )
    with urlopen(request, timeout=30) as response:
        if (
            response.status != 201
            or response.headers.get("Docker-Content-Digest") != expected
        ):
            raise ValueError(
                "Unconfirmed manifest promotion; inspect partial publication"
            )


def manifest(image: str, reference: str, token: str) -> tuple[str, bytes, str] | None:
    if (
        not token
        or not re.fullmatch(
            r"ghcr\.io/[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*", image
        )
        or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}", reference)
    ):
        raise ValueError("Explicit registry identity and authenticated token required")
    request = Request(
        ROOT + "/v2/" + image.split("/", 1)[1] + "/manifests/" + reference,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": ", ".join(sorted(MEDIA)),
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            data = response.read()
            digest = response.headers.get("Docker-Content-Digest")
            media = response.headers.get("Content-Type", "").split(";", 1)[0]
    except HTTPError as exc:
        if exc.code == 404:
            error = json.loads(exc.read())
            if (
                isinstance(error, dict)
                and isinstance(error.get("errors"), list)
                and len(error["errors"]) == 1
                and error["errors"][0].get("code") == "MANIFEST_UNKNOWN"
            ):
                return None
        raise
    if digest != "sha256:" + hashlib.sha256(data).hexdigest() or media not in MEDIA:
        raise ValueError("Registry digest or native manifest type mismatch")
    parsed = json.loads(data)
    if (
        not isinstance(parsed, dict)
        or parsed.get("schemaVersion") != 2
        or not isinstance(parsed.get("config"), dict)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", parsed["config"].get("digest", ""))
        or not isinstance(parsed.get("layers"), list)
        or parsed.get("mediaType", media) != media
    ):
        raise ValueError("Malformed native manifest")
    return digest, data, media


def require_absent_version(image: str, version: str, revision: str, token: str) -> None:
    if not VERSION.fullmatch(version) or not SHA.fullmatch(revision):
        raise ValueError("Invalid immutable image identity")
    if manifest(image, version, token) is not None:
        raise ValueError("Stable version tag already exists; publication refused")
    # An existing SHA tag may belong to a different version-labelled image. Do
    # not guess that it is safe to replace; use verified asset-only recovery.
    if manifest(image, "sha-" + revision, token) is not None:
        raise ValueError("Source image tag already exists; publication refused")
