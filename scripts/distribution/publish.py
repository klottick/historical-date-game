"""Publish only a same-run tested archive; image builds are deliberately absent."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from scripts.distribution import registry
from scripts.distribution.assets import IMAGE, attach_bundle, write_bundle
from scripts.distribution.release import (
    SHA,
    VERSION,
    api_json,
    commit_object,
    refresh_release,
    repository_path,
    validate_release,
)
from scripts.distribution.smoke import private_temp

REPOSITORY = "klottick/historical-date-game"


def docker(*args: str, environment: dict, data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["docker", *args],
        env=environment,
        input=data,
        capture_output=True,
        check=True,
        timeout=300,
    ).stdout


def verify_archive(archive: Path, metadata: Path, revision: str) -> dict:
    value = json.loads(metadata.read_bytes())
    if (
        not isinstance(value, dict)
        or not SHA.fullmatch(revision)
        or value.get("revision") != revision
        or value.get("platform") != "linux/amd64"
        or value.get("smoke_passed") is not True
        or not VERSION.fullmatch(value.get("version", ""))
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", value.get("image_id", ""))
        or not os.environ.get("GITHUB_RUN_ID")
        or value.get("run_id") != os.environ["GITHUB_RUN_ID"]
    ):
        raise ValueError("Archive is not this run's successful tested image")
    attempt = value.get("run_attempt", "")
    current = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if (
        not isinstance(attempt, str)
        or not attempt.isdecimal()
        or not current.isdecimal()
        or not 1 <= int(attempt) <= int(current)
    ):
        raise ValueError("Invalid artifact attempt provenance")
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != value.get(
            "archive_sha256"
        ):
            raise ValueError("Tested image archive checksum mismatch")
    return value


def verify_config(config: dict, revision: str, version: str) -> None:
    if config.get("os") != "linux" or config.get("architecture") != "amd64":
        raise ValueError("Image is not native Linux amd64")
    labels = config.get("config", {}).get("Labels", {})
    if (
        labels.get("org.opencontainers.image.revision") != revision
        or labels.get("org.opencontainers.image.version") != version
    ):
        raise ValueError("Image source/version labels do not match tested release")


def verify_latest(version: str, credential: str) -> str | None:
    latest = registry.manifest(IMAGE, "latest", credential)
    if latest is None:
        return None
    config_id = json.loads(latest[1])["config"]["digest"]
    config = registry.config_blob(IMAGE, config_id, credential)
    labels = config.get("config", {}).get("Labels", {})
    prior = labels.get("org.opencontainers.image.version", "")
    revision = labels.get("org.opencontainers.image.revision", "")
    previous = VERSION.fullmatch(prior)
    target = VERSION.fullmatch(version)
    if not previous or not target or not SHA.fullmatch(revision):
        raise ValueError("Existing latest has unverifiable release identity")
    verify_config(config, revision, prior)
    if tuple(map(int, previous.groups())) >= tuple(map(int, target.groups())):
        raise ValueError("Existing latest forbids equal or backward publication")
    for reference in (prior, "sha-" + revision):
        alias = registry.manifest(IMAGE, reference, credential)
        if alias is None or alias[:2] != latest[:2]:
            raise ValueError("Existing latest does not match immutable release aliases")
    return latest[0]


def publish(
    archive: Path,
    metadata: Path,
    repository: str,
    release_id: int,
    revision: str,
    output: Path,
) -> dict:
    if repository != REPOSITORY or output.exists() or output.is_symlink():
        raise ValueError("Refusing wrong repository or existing publication evidence")
    record = {
        "passed": False,
        "repository": repository,
        "release_id": release_id,
        "revision": revision,
        "tags": {},
        "failure": None,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        stream.write(json.dumps(record) + "\n")

    def save():
        output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")

    try:
        value = verify_archive(archive, metadata, revision)
        record.update(
            {
                key: value[key]
                for key in (
                    "image_id",
                    "version",
                    "archive_sha256",
                    "run_id",
                    "run_attempt",
                )
            }
        )
        version = value["version"]
        with tempfile.TemporaryDirectory(
            prefix="hdg-publisher-auth-", dir=private_temp()
        ) as tmp:
            environment = {
                key: val
                for key, val in os.environ.items()
                if key in ("PATH", "HOME", "DOCKER_HOST", "XDG_RUNTIME_DIR")
            }
            environment["DOCKER_CONFIG"] = tmp
            docker("load", "--input", str(archive), environment=environment)
            loaded = json.loads(
                docker("image", "inspect", value["image_id"], environment=environment)
            )[0]
            if loaded["Id"] != value["image_id"]:
                raise ValueError("Loaded image identity mismatch")
            verify_config(
                {
                    "os": loaded["Os"],
                    "architecture": loaded["Architecture"],
                    "config": loaded["Config"],
                },
                revision,
                version,
            )
            if refresh_release(repository, release_id, revision) != version:
                raise ValueError("Release version changed since testing")
            credential = registry.token(IMAGE, push=True)
            registry.require_absent_version(IMAGE, version, revision, credential)
            latest_before = verify_latest(version, credential)
            record["latest_before"] = latest_before
            actor = os.environ.get("GITHUB_ACTOR")
            secret = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
            if not actor or not secret:
                raise ValueError("Missing explicit publication credentials")
            docker(
                "login",
                "ghcr.io",
                "--username",
                actor,
                "--password-stdin",
                environment=environment,
                data=(secret + "\n").encode(),
            )
            staging = (
                "staging-"
                + os.environ["GITHUB_RUN_ID"]
                + "-"
                + os.environ["GITHUB_RUN_ATTEMPT"]
                + "-"
                + uuid4().hex
            )
            record["staging"] = IMAGE + ":" + staging
            save()
            docker("tag", value["image_id"], record["staging"], environment=environment)
            docker("push", record["staging"], environment=environment)
            promoted = registry.manifest(IMAGE, staging, credential)
            if promoted is None:
                raise ValueError("Pushed staging manifest unavailable")
            digest, body, media = promoted
            record["digest"] = digest
            save()
            if json.loads(body)["config"]["digest"] != value["image_id"]:
                raise ValueError("Pushed manifest is not the tested image")
            for tag in (version, "sha-" + revision, "latest"):
                if refresh_release(repository, release_id, revision) != version:
                    raise ValueError("Release eligibility changed before promotion")
                if verify_latest(version, credential) != latest_before:
                    raise ValueError(
                        "Latest changed during publication; inspect partial state"
                    )
                # Immutable aliases must still be absent immediately before PUT.
                if (
                    tag != "latest"
                    and registry.manifest(IMAGE, tag, credential) is not None
                ):
                    raise ValueError(
                        "Immutable image alias appeared during publication"
                    )
                record["tags"][tag] = "attempted"
                save()
                registry.put_manifest(IMAGE, tag, credential, body, media)
                actual = registry.manifest(IMAGE, tag, credential)
                if actual is None or actual[0] != digest or actual[1] != body:
                    raise ValueError("Promoted manifest bytes/digest mismatch")
                record["tags"][tag] = "verified"
                save()
            for tag in (version, "sha-" + revision, "latest"):
                actual = registry.manifest(IMAGE, tag, credential)
                if actual is None or actual[0] != digest:
                    raise ValueError("Final tag digest equality not verified")
            record["passed"] = True
    except BaseException as exc:
        record["failure"] = type(exc).__name__
        raise
    finally:
        save()
    return record


def verify_attachment(
    repository: str,
    release_id: int,
    revision: str,
    version: str,
    digest: str,
    image_id: str,
) -> str:
    prefix = repository_path(repository)
    current = api_json(prefix + f"/releases/{release_id}")
    tag = commit_object(repository, api_json(prefix + "/git/ref/tags/v" + version))
    main = commit_object(repository, api_json(prefix + "/git/ref/heads/main"))
    comparison = api_json(prefix + f"/compare/{revision}...{main}")
    ancestor = (
        comparison.get("status") in {"ahead", "identical"}
        and comparison.get("base_commit", {}).get("sha") == revision
        and comparison.get("merge_base_commit", {}).get("sha") == revision
    )
    # Attachment never moves aliases. A newer stable release need not block
    # repairing assets for this fully published immutable version.
    eligible = validate_release(current, [current], release_id, revision, tag, ancestor)
    if eligible != version:
        raise ValueError("Attachment release version mismatch")
    credential = registry.token(IMAGE)
    for reference in (version, "sha-" + revision):
        manifest = registry.manifest(IMAGE, reference, credential)
        if (
            manifest is None
            or manifest[0] != digest
            or json.loads(manifest[1])["config"]["digest"] != image_id
        ):
            raise ValueError("Attachment image identity does not match publication")
    verify_config(registry.config_blob(IMAGE, image_id, credential), revision, version)
    return version


def attach(
    publication: Path,
    repository: str,
    release_id: int,
    revision: str,
    source: Path,
    destination: Path,
) -> None:
    record = json.loads(publication.read_bytes())
    if (
        repository != REPOSITORY
        or record.get("passed") is not True
        or record.get("repository") != repository
        or record.get("release_id") != release_id
        or record.get("revision") != revision
    ):
        raise ValueError("Only verified complete publication may attach assets")
    verify_attachment(
        repository,
        release_id,
        revision,
        record["version"],
        record["digest"],
        record["image_id"],
    )
    write_bundle(source, destination, record["version"], revision, record["digest"])
    attach_bundle(repository, release_id, destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--release-id", required=True, type=int)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--output", type=Path, default=Path("publication.json"))
    parser.add_argument("--attach-only", type=Path)
    parser.add_argument("--source", type=Path, default=Path.cwd())
    parser.add_argument("--bundle", type=Path, default=Path("install-assets"))
    args = parser.parse_args()
    try:
        if args.attach_only:
            attach(
                args.attach_only,
                args.repository,
                args.release_id,
                args.expected_sha,
                args.source,
                args.bundle,
            )
        elif args.archive and args.metadata:
            publish(
                args.archive,
                args.metadata,
                args.repository,
                args.release_id,
                args.expected_sha,
                args.output,
            )
        else:
            parser.error("provide --archive and --metadata, or --attach-only")
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        sys.stderr.write(
            "Publication/attachment refused; inspect retained publication evidence before any retry.\n"
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
