"""Revalidate stable-release identity and ordering immediately before publication."""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
SHA = re.compile(r"[0-9a-f]{40}")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def repository_path(repository: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or any(
        part in {".", ".."} for part in repository.split("/")
    ):
        raise ValueError("Invalid repository")
    return "/repos/" + repository


def api_request(
    path: str,
    *,
    data: bytes | None = None,
    accept="application/vnd.github+json",
    upload=False,
) -> bytes:
    if not path.startswith("/repos/") or "\n" in path or "\r" in path:
        raise ValueError("Invalid API path")
    headers = {
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "Cache-Control": "no-cache",
    }
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    if data is not None:
        if not token:
            raise ValueError("Asset upload requires explicit workflow credentials")
        headers["Content-Type"] = "application/octet-stream"
    opener = build_opener(NoRedirect)
    try:
        with opener.open(
            Request((UPLOADS if upload else API) + path, data=data, headers=headers),
            timeout=30,
        ) as response:
            return response.read()
    except HTTPError as exc:
        # Asset downloads may redirect to a short-lived URL. Never forward the
        # workflow token outside the API endpoint, even to an allowlisted host.
        location = exc.headers.get("Location", "")
        target = urlsplit(location)
        if (
            exc.code not in {301, 302, 303, 307, 308}
            or data is not None
            or accept != "application/octet-stream"
            or target.scheme != "https"
            or target.hostname
            not in {
                "release-assets.githubusercontent.com",
                "objects.githubusercontent.com",
            }
            or target.username
            or target.password
        ):
            raise
        with opener.open(Request(location), timeout=30) as response:
            return response.read()


def api_json(path: str):
    return json.loads(api_request(path))


def pages(path: str) -> list:
    result = []
    for page in range(1, 10001):
        batch = api_json(path + f"?per_page=100&page={page}")
        if not isinstance(batch, list) or len(batch) > 100:
            raise ValueError("Malformed paginated metadata")
        if not batch:
            return result
        result.extend(batch)
    raise ValueError("Pagination did not terminate")


def release_metadata(value: dict) -> tuple[tuple[int, ...] | None, datetime | None]:
    if (
        not isinstance(value, dict)
        or type(value.get("id")) is not int
        or value["id"] <= 0
        or not isinstance(value.get("tag_name"), str)
        or not value["tag_name"]
        or type(value.get("draft")) is not bool
        or type(value.get("prerelease")) is not bool
        or "published_at" not in value
    ):
        raise ValueError("Malformed release metadata")
    published = value["published_at"]
    if published is None and value["draft"]:
        timestamp = None
    else:
        if not isinstance(published, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", published
        ):
            raise ValueError("Malformed release publication timestamp")
        timestamp = datetime.fromisoformat(published)
    tag = value["tag_name"]
    match = VERSION.fullmatch(tag[1:]) if tag.startswith("v") else None
    return tuple(map(int, match.groups())) if match else None, timestamp


def validate_release(
    current: dict,
    history: list[dict],
    expected_id: int,
    expected_sha: str,
    tag_sha: str,
    on_main: bool,
) -> str:
    version, published = release_metadata(current)
    if (
        type(expected_id) is not int
        or current["id"] != expected_id
        or not version
        or current["draft"]
        or current["prerelease"]
        or not SHA.fullmatch(expected_sha)
        or tag_sha != expected_sha
        or on_main is not True
    ):
        raise ValueError("Release is not an eligible stable source")
    if not isinstance(history, list):
        raise ValueError("Malformed release history")  # noqa: TRY004 - public validator refusal contract
    seen = set()
    for item in history:
        prior, timestamp = release_metadata(item)
        identity = item["id"]
        if identity in seen:
            raise ValueError("Duplicate release identity")
        seen.add(identity)
        if identity == expected_id:
            for field in ("tag_name", "draft", "prerelease", "published_at"):
                if item[field] != current[field]:
                    raise ValueError("Release history changed during validation")
        elif (
            prior
            and not item["draft"]
            and not item["prerelease"]
            and (prior >= version or timestamp >= published)
        ):
            raise ValueError("A newer or equal stable release already exists")
    if expected_id not in seen:
        raise ValueError("Live release absent from complete history")
    return current["tag_name"][1:]


def commit_object(repository: str, value: dict) -> str:
    seen = set()
    for _ in range(10):
        obj = value.get("object") if isinstance(value, dict) else None
        if (
            not isinstance(obj, dict)
            or not isinstance(obj.get("sha"), str)
            or not SHA.fullmatch(obj["sha"])
            or obj["sha"] in seen
        ):
            raise ValueError("Invalid tag/commit object")
        seen.add(obj["sha"])
        if obj.get("type") == "commit":
            return obj["sha"]
        if obj.get("type") != "tag":
            raise ValueError("Tag does not resolve to a commit")
        value = api_json(repository_path(repository) + "/git/tags/" + obj["sha"])
    raise ValueError("Tag nesting limit exceeded")


def refresh_release(repository: str, release_id: int, expected_sha: str) -> str:
    prefix = repository_path(repository)
    if (
        type(release_id) is not int
        or release_id <= 0
        or not SHA.fullmatch(expected_sha)
    ):
        raise ValueError("Invalid expected release identity")
    current = api_json(prefix + f"/releases/{release_id}")
    release_metadata(current)
    history = pages(prefix + "/releases")
    tag = commit_object(
        repository,
        api_json(prefix + "/git/ref/tags/" + quote(current["tag_name"], safe="")),
    )
    main = commit_object(repository, api_json(prefix + "/git/ref/heads/main"))
    comparison = api_json(prefix + f"/compare/{expected_sha}...{main}")
    on_main = (
        isinstance(comparison, dict)
        and comparison.get("status") in {"ahead", "identical"}
        and comparison.get("base_commit", {}).get("sha") == expected_sha
        and comparison.get("merge_base_commit", {}).get("sha") == expected_sha
    )
    return validate_release(current, history, release_id, expected_sha, tag, on_main)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check",))
    parser.add_argument("--repository", required=True)
    parser.add_argument("--release-id", required=True, type=int)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    try:
        version = refresh_release(args.repository, args.release_id, args.expected_sha)
    except (ValueError, OSError, TypeError, KeyError):
        sys.stderr.write(
            "Release eligibility refused: metadata, source or ordering could not be verified.\n"
        )
        raise SystemExit(1) from None
    sys.stdout.write(version + "\n")


if __name__ == "__main__":
    main()
