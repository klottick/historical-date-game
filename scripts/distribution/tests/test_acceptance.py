import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SHA = "a" * 40


class AcceptanceTests(unittest.TestCase):
    def test_downloads_only_anonymous_attachments_into_an_empty_source_free_directory(
        self,
    ):
        import os

        from scripts.distribution.acceptance import download_bundle
        from scripts.distribution.assets import NAMES, write_bundle
        from scripts.distribution.tests.test_release import CURRENT, Fixture

        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp, Fixture() as api:
            root = Path(tmp)
            write_bundle(ROOT, root / "source", "1.10.0", SHA, "sha256:" + "d" * 64)
            api.routes["/repos/owner/repo/releases/tags/v1.10.0"] = CURRENT
            api.routes["/repos/owner/repo/releases/7/assets?per_page=100&page=1"] = [
                {
                    "id": index + 1,
                    "name": name,
                    "size": (root / "source" / name).stat().st_size,
                }
                for index, name in enumerate(sorted(NAMES))
            ]
            api.routes["/repos/owner/repo/releases/7/assets?per_page=100&page=2"] = []
            for index, name in enumerate(sorted(NAMES)):
                api.routes[f"/repos/owner/repo/releases/assets/{index + 1}"] = (
                    root / "source" / name
                ).read_bytes()
            with (
                patch("scripts.distribution.release.API", api.url),
                patch.dict(os.environ, {"GH_TOKEN": "MUST-NOT-BE-SENT"}),
            ):
                identity = download_bundle(
                    "owner/repo", "v1.10.0", root / "downloaded", SHA
                )
            self.assertEqual(identity["version"], "1.10.0")
            self.assertEqual({p.name for p in (root / "downloaded").iterdir()}, NAMES)
            self.assertTrue(all(header is None for header in api.authorization))

    def test_downloaded_bundle_is_required_to_match_checksums_source_and_digest(self):
        from scripts.distribution.acceptance import validate_bundle
        from scripts.distribution.assets import write_bundle

        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp) / "install"
            write_bundle(ROOT, root, "1.0.0", SHA, "sha256:" + "d" * 64)
            self.assertEqual(
                validate_bundle(root, "v1.0.0", SHA)["digest"], "sha256:" + "d" * 64
            )
            (root / "compose.yaml").write_text("tampered")
            with self.assertRaises(ValueError):
                validate_bundle(root, "v1.0.0", SHA)

    def test_anonymous_config_is_empty_private_and_no_helpers_or_tokens_are_inherited(
        self,
    ):
        import os

        from scripts.distribution.acceptance import anonymous_environment

        with (
            tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp,
            patch.dict(
                os.environ,
                {
                    "DOCKER_CONFIG": "/foreign",
                    "GH_TOKEN": "private",
                    "GITHUB_TOKEN": "private",
                    "DOCKER_AUTH_CONFIG": "private",
                    "DOCKER_CONTEXT": "foreign",
                },
            ),
            anonymous_environment(Path(tmp)) as environment,
        ):
            config = Path(environment["DOCKER_CONFIG"])
            self.assertEqual(list(config.iterdir()), [])
            self.assertEqual(config.stat().st_mode & 0o777, 0o700)
            for field in (
                "GH_TOKEN",
                "GITHUB_TOKEN",
                "DOCKER_AUTH_CONFIG",
                "DOCKER_CONTEXT",
            ):
                self.assertNotIn(field, environment)
            self.assertNotEqual(environment["DOCKER_CONFIG"], "/foreign")

    def test_anonymous_manifest_probe_refuses_mismatched_tags_and_non_amd64(self):
        from scripts.distribution.acceptance import verify_image

        body = json.dumps({"config": {"digest": "sha256:" + "b" * 64}}).encode()
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
        config = {
            "os": "linux",
            "architecture": "amd64",
            "config": {
                "Labels": {
                    "org.opencontainers.image.revision": SHA,
                    "org.opencontainers.image.version": "1.0.0",
                }
            },
        }
        with (
            patch(
                "scripts.distribution.registry.token", return_value="anonymous-token"
            ),
            patch(
                "scripts.distribution.registry.manifest",
                return_value=(digest, body, "native"),
            ),
            patch("scripts.distribution.registry.config_blob", return_value=config),
        ):
            self.assertEqual(verify_image("1.0.0", SHA, digest), "sha256:" + "b" * 64)
            config["architecture"] = "arm64"
            with self.assertRaises(ValueError):
                verify_image("1.0.0", SHA, digest)
        with (
            patch(
                "scripts.distribution.registry.token", return_value="anonymous-token"
            ),
            patch(
                "scripts.distribution.registry.manifest",
                side_effect=[(digest, body, "native"), None],
            ),
            self.assertRaises(ValueError),
        ):
            verify_image("1.0.0", SHA, digest)


if __name__ == "__main__":
    unittest.main()
