"""Deterministic digest-pinned install assets; retries never overwrite conflicts."""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote

from scripts.distribution.release import SHA, VERSION, api_request, repository_path

NAMES = {"compose.yaml", "env.example", "INSTALL.md", "image-digest.txt", "SHA256SUMS"}
IMAGE = "ghcr.io/klottick/historical-date-game"


def write_bundle(
    source: Path, destination: Path, version: str, revision: str, digest: str
) -> dict[str, str]:
    if (
        not VERSION.fullmatch(version)
        or not SHA.fullmatch(revision)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
    ):
        raise ValueError(
            "A canonical tested release version, source and digest are required"
        )
    reference = f"{IMAGE}:{version}@{digest}"
    compose = (source / "compose.yaml").read_text()
    pattern = r"\$\{HDG_IMAGE:\?[^}\n]+\}"
    if len(re.findall(pattern, compose)) != 1:
        raise ValueError("Release Compose template image boundary changed")
    compose = re.sub(pattern, reference, compose)
    environment = (source / "env.example").read_text()
    if environment.count("\nHDG_IMAGE=\n") != 1:
        raise ValueError("Release environment template changed")
    for field in (
        "SECRET_KEY",
        "POSTGRES_PASSWORD",
        "FIRST_SUPERUSER_PASSWORD",
        "FIRST_SUPERUSER",
        "SMTP_PASSWORD",
    ):
        if not re.search(r"^" + field + r"=$", environment, re.MULTILINE):
            raise ValueError("Nonempty secret or identity in release template")
    environment = environment.replace(
        "\nHDG_IMAGE=\n", "\nHDG_IMAGE=" + reference + "\n"
    )
    files = {
        "compose.yaml": compose.encode(),
        "env.example": environment.encode(),
        "INSTALL.md": (source / "INSTALL.md").read_bytes(),
        "image-digest.txt": (
            json.dumps(
                {
                    "image": reference,
                    "digest": digest,
                    "revision": revision,
                    "version": version,
                    "platform": "linux/amd64",
                },
                sort_keys=True,
            )
            + "\n"
        ).encode(),
    }
    checksums = {
        name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())
    }
    files["SHA256SUMS"] = "".join(
        f"{checksum}  {name}\n" for name, checksum in checksums.items()
    ).encode()
    if destination.is_symlink() or any(p.is_symlink() for p in destination.parents):
        raise ValueError("Unsafe bundle destination")
    if destination.exists():
        if {p.name for p in destination.iterdir()} - NAMES:
            raise ValueError("Unexpected existing bundle files")
        for name, data in files.items():
            path = destination / name
            if path.exists() and (
                path.is_symlink() or not path.is_file() or path.read_bytes() != data
            ):
                raise ValueError("Conflicting existing bundle bytes")
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        path = destination / name
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(data)
    return checksums


def attach_bundle(repository: str, release_id: int, directory: Path) -> None:
    if (
        type(release_id) is not int
        or release_id <= 0
        or {p.name for p in directory.iterdir()} != NAMES
        or any(p.is_symlink() or not p.is_file() for p in directory.iterdir())
    ):
        raise ValueError("Unexpected release asset set")
    prefix = repository_path(repository)
    existing = {}
    for page in range(1, 10001):
        rows = json.loads(
            api_request(
                prefix + f"/releases/{release_id}/assets?per_page=100&page={page}"
            )
        )
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("Malformed asset metadata")
        if not rows:
            break
        for asset in rows:
            if (
                not isinstance(asset, dict)
                or asset.get("name") not in NAMES
                or asset["name"] in existing
                or type(asset.get("id")) is not int
                or asset["id"] <= 0
                or type(asset.get("size")) is not int
            ):
                raise ValueError("Unexpected or duplicate existing asset")
            existing[asset["name"]] = asset
    else:
        raise ValueError("Asset pagination did not terminate")
    # Check every existing asset before any upload: partial conflicting bundles
    # are refused without expanding their remotely published state.
    for name, asset in existing.items():
        expected = (directory / name).read_bytes()
        actual = api_request(
            prefix + f"/releases/assets/{asset['id']}",
            accept="application/octet-stream",
        )
        if len(expected) != asset["size"] or actual != expected:
            raise ValueError("Conflicting published asset; never clobber")
    for name in sorted(NAMES - existing.keys()):
        data = (directory / name).read_bytes()
        api_request(
            prefix + f"/releases/{release_id}/assets?name=" + quote(name, safe=""),
            data=data,
            upload=True,
        )
