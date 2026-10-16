import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[3]
REPO = "klottick/historical-date-game"
SHA = "a" * 40
ID = "sha256:" + "b" * 64


class PublishTests(unittest.TestCase):
    def test_actual_cli_promotes_exact_bytes_through_local_registry_and_refuses_retry(
        self,
    ):
        import subprocess
        import sys
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread

        from scripts.distribution.tests.test_release import Fixture

        for fail in (False, True):
            with (
                tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp,
                Fixture() as api,
            ):
                api.routes = {
                    path.replace("owner/repo", REPO): value
                    for path, value in api.routes.items()
                }
                root = Path(tmp)
                archive, metadata, _, info, _ = self.setup_boundaries(root)
                value = json.loads(metadata.read_text()) | {"version": "1.10.0"}
                metadata.write_text(json.dumps(value))
                info["Config"]["Labels"]["org.opencontainers.image.version"] = "1.10.0"
                calls = root / "docker-calls.jsonl"
                executable = root / "docker"
                executable.write_text(
                    f"#!{sys.executable}\nimport sys,json\nfrom pathlib import Path\nargs=sys.argv[1:]\nwith Path({str(calls)!r}).open('a') as f: f.write(json.dumps(args)+'\\n')\nif args[:2]==['image','inspect']: print({json.dumps([info])!r})\nelif args[0]=='login': assert sys.stdin.read()=='ephemeral\\n'\nelif args[0] not in ('tag','push','load'): raise SystemExit(9)\n"
                )
                executable.chmod(0o700)
                body = json.dumps(
                    {
                        "schemaVersion": 2,
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "config": {"digest": ID},
                        "layers": [],
                    },
                    indent=2,
                ).encode()
                digest = "sha256:" + hashlib.sha256(body).hexdigest()
                remote, writes = {}, []

                class Handler(BaseHTTPRequestHandler):
                    def do_GET(
                        self, remote=remote, calls=calls, body=body, digest=digest
                    ):
                        if self.path.startswith("/token?"):
                            self.send_response(200)
                            self.end_headers()
                            self.wfile.write(b'{"token":"local-registry-token"}')
                            return
                        reference = self.path.rsplit("/", 1)[1]
                        exists = (
                            reference in remote
                            or reference.startswith("staging-")
                            and calls.exists()
                            and any(
                                json.loads(line)[0] == "push"
                                for line in calls.read_text().splitlines()
                            )
                        )
                        self.send_response(200 if exists else 404)
                        self.send_header(
                            "Content-Type",
                            "application/vnd.oci.image.manifest.v1+json"
                            if exists
                            else "application/json",
                        )
                        if exists:
                            self.send_header("Docker-Content-Digest", digest)
                        self.end_headers()
                        self.wfile.write(
                            body
                            if exists
                            else b'{"errors":[{"code":"MANIFEST_UNKNOWN"}]}'
                        )

                    def do_PUT(
                        self, writes=writes, remote=remote, fail=fail, digest=digest
                    ):
                        reference = self.path.rsplit("/", 1)[1]
                        data = self.rfile.read(int(self.headers["Content-Length"]))
                        writes.append((reference, data, self.headers["Content-Type"]))
                        if fail and reference.startswith("sha-"):
                            self.send_response(500)
                            self.end_headers()
                            return
                        remote[reference] = data
                        self.send_response(201)
                        self.send_header("Docker-Content-Digest", digest)
                        self.end_headers()

                    def log_message(self, *_):
                        pass

                server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
                Thread(target=server.serve_forever, daemon=True).start()
                try:
                    env = dict(os.environ) | {
                        "PATH": str(root) + ":" + os.environ["PATH"],
                        "GITHUB_RUN_ID": "123",
                        "GITHUB_RUN_ATTEMPT": "2",
                        "GITHUB_ACTOR": "actor",
                        "GH_TOKEN": "ephemeral",
                        "DOCKER_CALLS": str(calls),
                    }
                    command = [
                        sys.executable,
                        "-c",
                        f"from scripts.distribution import release,registry;release.API={api.url!r};registry.ROOT='http://127.0.0.1:{server.server_port}';from scripts.distribution.publish import main;main()",
                        "--archive",
                        str(archive),
                        "--metadata",
                        str(metadata),
                        "--repository",
                        REPO,
                        "--release-id",
                        "7",
                        "--expected-sha",
                        SHA,
                        "--output",
                    ]
                    first = subprocess.run(
                        [*command, str(root / "publication.json")],
                        env=env,
                        capture_output=True,
                        check=False,
                        timeout=15,
                    )
                    self.assertEqual(
                        first.returncode == 0,
                        not fail,
                        (
                            first.stderr,
                            (root / "publication.json").read_text(),
                            calls.read_text() if calls.exists() else "no Docker calls",
                        ),
                    )
                    self.assertEqual(
                        [w[0] for w in writes],
                        ["1.10.0", "sha-" + SHA]
                        if fail
                        else ["1.10.0", "sha-" + SHA, "latest"],
                    )
                    self.assertTrue(
                        all(
                            w[1] == body
                            and w[2] == "application/vnd.oci.image.manifest.v1+json"
                            for w in writes
                        )
                    )
                    second = subprocess.run(
                        [*command, str(root / "retry.json")],
                        env=env,
                        capture_output=True,
                        check=False,
                        timeout=15,
                    )
                    self.assertNotEqual(second.returncode, 0)
                    history = [
                        json.loads(line) for line in calls.read_text().splitlines()
                    ]
                    self.assertEqual(sum(c[0] == "push" for c in history), 1)
                    self.assertFalse(any("build" in c for c in history))
                    self.assertNotIn(b"ephemeral", first.stderr + second.stderr)
                finally:
                    server.shutdown()
                    server.server_close()

    def setup_boundaries(self, root):
        archive = root / "image.tar"
        archive.write_bytes(b"tested archive")
        metadata = root / "image.json"
        metadata.write_text(
            json.dumps(
                {
                    "image_id": ID,
                    "revision": SHA,
                    "version": "1.0.0",
                    "platform": "linux/amd64",
                    "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "run_id": "123",
                    "run_attempt": "1",
                    "smoke_passed": True,
                }
            )
        )
        calls = []
        info = {
            "Id": ID,
            "Os": "linux",
            "Architecture": "amd64",
            "Config": {
                "Labels": {
                    "org.opencontainers.image.revision": SHA,
                    "org.opencontainers.image.version": "1.0.0",
                }
            },
        }

        def docker(*args, **kwargs):
            calls.append(args)
            self.assertNotIn("build", args)
            if args[:2] == ("image", "inspect"):
                return json.dumps([info]).encode()
            return b""

        return archive, metadata, calls, info, docker

    def test_publisher_loads_only_this_runs_successful_image(self):
        from scripts.distribution.publish import publish

        for change in (
            {"run_id": "122"},
            {"smoke_passed": False},
            {"run_attempt": "3"},
            {"platform": "linux/arm64"},
            {"revision": "c" * 40},
        ):
            with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
                root = Path(tmp)
                archive, metadata, calls, _, docker = self.setup_boundaries(root)
                metadata.write_text(
                    json.dumps(json.loads(metadata.read_text()) | change)
                )
                with (
                    patch.dict(
                        os.environ, {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"}
                    ),
                    patch("scripts.distribution.publish.docker", side_effect=docker),
                    self.assertRaises(ValueError),
                ):
                    publish(archive, metadata, REPO, 7, SHA, root / "publication.json")
                self.assertEqual(calls, [])

    def test_archive_and_loaded_image_identity_must_match(self):
        from scripts.distribution.publish import publish

        for corrupt in (True, False):
            with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
                root = Path(tmp)
                archive, metadata, calls, info, docker = self.setup_boundaries(root)
                if corrupt:
                    archive.write_bytes(b"different image")
                else:
                    info["Id"] = "sha256:" + "c" * 64
                with (
                    patch.dict(
                        os.environ, {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"}
                    ),
                    patch("scripts.distribution.publish.docker", side_effect=docker),
                    self.assertRaises(ValueError),
                ):
                    publish(archive, metadata, REPO, 7, SHA, root / "publication.json")
                self.assertFalse(any(c[0] in {"push", "login"} for c in calls))

    def test_no_registry_write_after_stale_retry_or_failed_smoke(self):
        from scripts.distribution.publish import publish

        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            archive, metadata, calls, _, docker = self.setup_boundaries(root)
            with (
                patch.dict(
                    os.environ, {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"}
                ),
                patch("scripts.distribution.publish.docker", side_effect=docker),
                patch(
                    "scripts.distribution.publish.refresh_release",
                    side_effect=ValueError("newer stable release"),
                ),
                self.assertRaises(ValueError),
            ):
                publish(archive, metadata, REPO, 7, SHA, root / "publication.json")
            self.assertFalse(any(c[0] in {"push", "login"} for c in calls))

    def test_promotion_uses_identical_manifest_bytes_and_partial_retry_refuses(self):
        from scripts.distribution.publish import publish

        body = (
            b'{"schemaVersion":2,"mediaType":"application/vnd.oci.image.manifest.v1+json","config":{"digest":"'
            + ID.encode()
            + b'"},"layers":[]}'
        )
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
        for fail_tag in (None, "sha-" + SHA):
            with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
                root = Path(tmp)
                archive, metadata, calls, _, docker = self.setup_boundaries(root)
                tags = {}
                writes = []

                def manifest(_image, reference, _token, tags=tags):
                    if reference.startswith("staging-") or reference in tags:
                        return (
                            digest,
                            body,
                            "application/vnd.oci.image.manifest.v1+json",
                        )
                    return None

                def promote(
                    image,
                    reference,
                    token,
                    raw,
                    media,
                    writes=writes,
                    tags=tags,
                    fail_tag=fail_tag,
                ):
                    writes.append((reference, raw, media))
                    if reference == fail_tag:
                        raise OSError("uncertain PUT")
                    tags[reference] = digest

                with (
                    patch.dict(
                        os.environ,
                        {
                            "GITHUB_RUN_ID": "123",
                            "GITHUB_RUN_ATTEMPT": "2",
                            "GH_TOKEN": "ephemeral",
                            "GITHUB_ACTOR": "owner",
                        },
                    ),
                    patch("scripts.distribution.publish.docker", side_effect=docker),
                    patch(
                        "scripts.distribution.publish.refresh_release",
                        return_value="1.0.0",
                    ),
                    patch(
                        "scripts.distribution.registry.token",
                        return_value="registry-token",
                    ),
                    patch(
                        "scripts.distribution.registry.manifest", side_effect=manifest
                    ),
                    patch(
                        "scripts.distribution.registry.put_manifest",
                        side_effect=promote,
                    ),
                ):
                    if fail_tag:
                        with self.assertRaises(OSError):
                            publish(
                                archive,
                                metadata,
                                REPO,
                                7,
                                SHA,
                                root / "publication.json",
                            )
                    else:
                        publish(
                            archive, metadata, REPO, 7, SHA, root / "publication.json"
                        )
                    journal = json.loads((root / "publication.json").read_text())
                    self.assertEqual(journal["digest"], digest)
                    self.assertEqual(journal["passed"], fail_tag is None)
                    self.assertEqual(sum(c[0] == "push" for c in calls), 1)
                    self.assertEqual(
                        [w[0] for w in writes],
                        ["1.0.0", "sha-" + SHA]
                        if fail_tag
                        else ["1.0.0", "sha-" + SHA, "latest"],
                    )
                    self.assertTrue(all(w[1] == body for w in writes))
                    before = len(writes)
                    with self.assertRaises(ValueError):
                        publish(archive, metadata, REPO, 7, SHA, root / "retry.json")
                    self.assertEqual(len(writes), before)

    def test_asset_only_retry_does_not_republish_or_require_latest_still_points_here(
        self,
    ):
        from scripts.distribution.publish import attach

        evidence = {
            "passed": True,
            "version": "1.0.0",
            "revision": SHA,
            "image_id": ID,
            "digest": "sha256:" + "d" * 64,
            "repository": REPO,
            "release_id": 7,
        }
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            path = root / "publication.json"
            path.write_text(json.dumps(evidence))
            with (
                patch(
                    "scripts.distribution.publish.verify_attachment",
                    return_value="1.0.0",
                ),
                patch("scripts.distribution.publish.attach_bundle") as upload,
                patch(
                    "scripts.distribution.publish.docker",
                    side_effect=AssertionError("no Docker push/load in attachment"),
                ),
            ):
                attach(path, REPO, 7, SHA, ROOT, root / "bundle")
                upload.assert_called_once()

    def test_workflow_only_consumes_successful_same_run_archive_and_separates_privileges(
        self,
    ):
        data = yaml.load(
            (ROOT / ".github/workflows/release-image.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        self.assertEqual(data["on"], {"release": {"types": ["published"]}})
        self.assertEqual(data["concurrency"]["cancel-in-progress"], "false")
        jobs = data["jobs"]
        self.assertEqual(
            jobs["image"]["uses"], "./.github/workflows/test-distribution.yml"
        )
        self.assertEqual(set(jobs["publish"]["needs"]), {"validate", "image"})
        self.assertEqual(
            jobs["publish"]["permissions"], {"contents": "read", "packages": "write"}
        )
        self.assertEqual(
            jobs["attach"]["permissions"], {"contents": "write", "packages": "read"}
        )
        for name in ("publish", "attach"):
            for step in jobs[name]["steps"]:
                if "download-artifact@" in step.get("uses", ""):
                    self.assertNotIn("run-id", step.get("with", {}))
                if "checkout@" in step.get("uses", ""):
                    self.assertEqual(step["with"]["ref"], "${{ github.sha }}")
                    self.assertEqual(step["with"]["persist-credentials"], "false")


if __name__ == "__main__":
    unittest.main()
