"""Anonymous released-image and downloaded-asset acceptance, never publication."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from scripts.distribution import registry
from scripts.distribution.assets import IMAGE, NAMES
from scripts.distribution.publish import REPOSITORY, verify_config
from scripts.distribution.release import SHA, VERSION, api_request, repository_path
from scripts.distribution.smoke import Installation, full_probe, private_temp, run_owned


@contextmanager
def anonymous_environment(root: Path):
    with tempfile.TemporaryDirectory(prefix="empty-docker-auth-", dir=root) as tmp:
        os.chmod(tmp, 0o700)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in ("PATH", "HOME", "DOCKER_HOST", "XDG_RUNTIME_DIR")
        }
        environment["DOCKER_CONFIG"] = tmp
        yield environment


def validate_bundle(directory: Path, tag: str, revision: str) -> dict:
    if (
        not tag.startswith("v")
        or not VERSION.fullmatch(tag[1:])
        or not SHA.fullmatch(revision)
        or {p.name for p in directory.iterdir()} != NAMES
    ):
        raise ValueError("Unexpected released installation asset set or source")
    seen = set()
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        if not match or match[2] not in NAMES - {"SHA256SUMS"} or match[2] in seen:
            raise ValueError("Malformed released checksums")
        seen.add(match[2])
        path = directory / match[2]
        if (
            path.is_symlink()
            or hashlib.sha256(path.read_bytes()).hexdigest() != match[1]
        ):
            raise ValueError("Released asset checksum mismatch")
    if seen != NAMES - {"SHA256SUMS"}:
        raise ValueError("Incomplete released checksums")
    identity = json.loads((directory / "image-digest.txt").read_text())
    digest = identity.get("digest", "")
    reference = f"{IMAGE}:{tag[1:]}@{digest}"
    if (
        not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
        or identity.get("revision") != revision
        or identity.get("version") != tag[1:]
        or identity.get("platform") != "linux/amd64"
        or identity.get("image") != reference
    ):
        raise ValueError("Released image identity mismatch")
    if (
        "HDG_IMAGE=" + reference + "\n" not in (directory / "env.example").read_text()
        or "image: " + reference not in (directory / "compose.yaml").read_text()
    ):
        raise ValueError("Installer does not pin released image digest")
    return identity


def verify_image(version: str, revision: str, expected: str) -> str:
    credential = registry.token(IMAGE, anonymous=True)
    image_id = None
    for reference in (version, "sha-" + revision, "latest", expected):
        manifest = registry.manifest(IMAGE, reference, credential)
        if manifest is None or manifest[0] != expected:
            raise ValueError("Anonymous tag/digest equality not verified")
        current_id = json.loads(manifest[1])["config"]["digest"]
        if image_id is not None and current_id != image_id:
            raise ValueError("Image configuration differs between tags")
        image_id = current_id
    verify_config(registry.config_blob(IMAGE, image_id, credential), revision, version)
    return image_id


def download_bundle(repository: str, tag: str, directory: Path, revision: str) -> dict:
    prefix = repository_path(repository)
    if not tag.startswith("v") or not VERSION.fullmatch(tag[1:]):
        raise ValueError("Canonical release tag required")
    release = json.loads(api_request(prefix + "/releases/tags/" + tag, anonymous=True))
    if (
        release.get("tag_name") != tag
        or release.get("draft") is not False
        or release.get("prerelease") is not False
        or type(release.get("id")) is not int
    ):
        raise ValueError("Release unavailable anonymously")
    directory.mkdir(mode=0o700, exist_ok=False)
    assets = {}
    for page in range(1, 10001):
        rows = json.loads(
            api_request(
                prefix + f"/releases/{release['id']}/assets?per_page=100&page={page}",
                anonymous=True,
            )
        )
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("Malformed anonymous asset listing")
        if not rows:
            break
        for row in rows:
            name = row.get("name")
            if name not in NAMES or name in assets or type(row.get("id")) is not int:
                raise ValueError("Unexpected anonymous release asset")
            assets[name] = row
    else:
        raise ValueError("Anonymous asset pagination did not terminate")
    if set(assets) != NAMES:
        raise ValueError("Missing released installation attachments")
    for name, asset in assets.items():
        data = api_request(
            prefix + f"/releases/assets/{asset['id']}",
            accept="application/octet-stream",
            anonymous=True,
        )
        if len(data) != asset.get("size"):
            raise ValueError("Incomplete anonymous asset download")
        (directory / name).write_bytes(data)
    return validate_bundle(directory, tag, revision)


def verify_pulled_image(info: dict, config_id: str, digest: str, config: dict) -> None:
    """Bind either Docker store's inspect identity to the verified registry image."""
    descriptor = info.get("Descriptor")
    if info.get("Id") not in {config_id, digest} or (
        (info.get("Id") == digest or descriptor is not None)
        and (
            not isinstance(descriptor, dict)
            or descriptor.get("digest") != digest
            or descriptor.get("mediaType") not in registry.MEDIA
        )
    ):
        raise ValueError("Anonymously pulled image identity mismatch")
    if (
        info.get("Os") != "linux"
        or info.get("Architecture") != "amd64"
        or config.get("os") != "linux"
        or config.get("architecture") != "amd64"
    ):
        raise ValueError("Anonymously pulled image is not native Linux amd64")
    expected_root = config.get("rootfs", {})
    root = info.get("RootFS", {})
    layers = expected_root.get("diff_ids")
    if (
        expected_root.get("type") != "layers"
        or not isinstance(layers, list)
        or not layers
        or root.get("Type") != "layers"
        or root.get("Layers") != layers
    ):
        raise ValueError("Anonymously pulled image layers mismatch")
    expected = config.get("config")
    runtime = info.get("Config")
    if (
        not isinstance(expected, dict)
        or not isinstance(runtime, dict)
        or any(
            runtime.get(key) != expected.get(key)
            for key in runtime.keys() | expected.keys()
        )
    ):
        raise ValueError("Anonymously pulled image runtime configuration mismatch")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    if args.repository != REPOSITORY:
        parser.error("This distribution is bound to " + REPOSITORY)
    evidence = args.evidence_dir
    evidence.mkdir(parents=True, mode=0o700, exist_ok=False)
    result = {
        "passed": False,
        "repository": args.repository,
        "revision": args.expected_sha,
        "release_tag": args.release_tag,
    }
    try:
        with tempfile.TemporaryDirectory(
            prefix="hdg-anonymous-", dir=private_temp()
        ) as tmp:
            root = Path(tmp)
            with anonymous_environment(root) as environment:
                identity = download_bundle(
                    args.repository,
                    args.release_tag,
                    evidence / "downloaded-assets",
                    args.expected_sha,
                )
                image_id = verify_image(
                    args.release_tag[1:], args.expected_sha, identity["digest"]
                )
                with (evidence / "anonymous-pull.log").open("wb") as log:
                    subprocess.run(
                        [
                            "docker",
                            "pull",
                            "--platform",
                            "linux/amd64",
                            identity["image"],
                        ],
                        env=environment,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        check=True,
                        timeout=300,
                    )
                info = json.loads(
                    subprocess.check_output(
                        ["docker", "image", "inspect", identity["image"]],
                        env=environment,
                    )
                )[0]
                config = registry.config_blob(
                    IMAGE, image_id, registry.token(IMAGE, anonymous=True)
                )
                verify_pulled_image(info, image_id, identity["digest"], config)
                installation = Installation(
                    identity["image"],
                    evidence / "downloaded-assets",
                    root / "installation",
                )
                installation.env = environment
                smoke = evidence / "installation"
                smoke.mkdir(mode=0o700)
                if run_owned(
                    installation,
                    smoke,
                    lambda project: full_probe(project, smoke, args.browser),
                ):
                    raise ValueError(
                        "Downloaded release installation acceptance failed"
                    )
                result.update(identity)
                result["passed"] = True
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        result["failure"] = type(exc).__name__
        sys.stderr.write(
            "Anonymous release acceptance failed. Inspect evidence; visibility is not changed automatically.\n"
        )
    finally:
        (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
