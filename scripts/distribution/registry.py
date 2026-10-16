"""Strict native-manifest registry checks: uncertainty never establishes absence."""

import hashlib
import json
import re
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from scripts.distribution.release import SHA, VERSION, NoRedirect

registry_opener = NoRedirect()
urlopen = build_opener(registry_opener).open

MEDIA = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}


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
        "https://"
        + image.split("/", 1)[0]
        + "/v2/"
        + image.split("/", 1)[1]
        + "/manifests/"
        + reference,
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
