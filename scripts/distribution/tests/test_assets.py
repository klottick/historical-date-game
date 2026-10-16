import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
DIGEST = "sha256:" + "d" * 64
NAMES = {"compose.yaml", "env.example", "INSTALL.md", "image-digest.txt", "SHA256SUMS"}


class AssetsTests(unittest.TestCase):
    def test_new_assets_upload_exact_bundle_bytes_and_retry_skips_identical_files(self):
        from urllib.parse import parse_qs, urlsplit

        from scripts.distribution.assets import attach_bundle, write_bundle

        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            directory = Path(tmp) / "bundle"
            write_bundle(ROOT, directory, "1.0.0", "a" * 40, DIGEST)
            remote = {}
            writes = []

            def request(path, *, data=None, **_):
                if data is not None:
                    name = parse_qs(urlsplit(path).query)["name"][0]
                    self.assertNotIn(name, remote)
                    remote[name] = data
                    writes.append(name)
                    return b"{}"
                if "/assets?" in path:
                    rows = [
                        {"id": i + 1, "name": name, "size": len(value)}
                        for i, (name, value) in enumerate(remote.items())
                    ]
                    return json.dumps(rows if path.endswith("&page=1") else []).encode()
                return list(remote.values())[int(path.rsplit("/", 1)[1]) - 1]

            with patch("scripts.distribution.assets.api_request", side_effect=request):
                attach_bundle("owner/repo", 7, directory)
                attach_bundle("owner/repo", 7, directory)
            self.assertEqual(set(remote), NAMES)
            self.assertEqual(len(writes), 5)
            for name, data in remote.items():
                self.assertEqual(data, (directory / name).read_bytes())

    def test_bundle_pins_identical_image_and_ships_no_secrets(self):
        import yaml

        from scripts.distribution.assets import write_bundle

        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            destination = Path(tmp) / "bundle"
            checksums = write_bundle(ROOT, destination, "1.10.0", "a" * 40, DIGEST)
            self.assertEqual({p.name for p in destination.iterdir()}, NAMES)
            reference = "ghcr.io/klottick/historical-date-game:1.10.0@" + DIGEST
            compose = yaml.safe_load((destination / "compose.yaml").read_text())
            for service in ("app", "initialize"):
                self.assertEqual(compose["services"][service]["image"], reference)
            env = (destination / "env.example").read_text()
            self.assertIn("HDG_IMAGE=" + reference + "\n", env)
            for field in (
                "SECRET_KEY",
                "POSTGRES_PASSWORD",
                "FIRST_SUPERUSER_PASSWORD",
            ):
                self.assertIn(field + "=\n", env)
            for line in (destination / "SHA256SUMS").read_text().splitlines():
                checksum, name = line.split("  ")
                self.assertEqual(
                    hashlib.sha256((destination / name).read_bytes()).hexdigest(),
                    checksum,
                )
                self.assertEqual(checksums[name], checksum)
            self.assertEqual(
                write_bundle(ROOT, destination, "1.10.0", "a" * 40, DIGEST), checksums
            )
            (destination / "INSTALL.md").write_text("conflicting retained asset")
            with self.assertRaises(ValueError):
                write_bundle(ROOT, destination, "1.10.0", "a" * 40, DIGEST)
            self.assertEqual(
                (destination / "INSTALL.md").read_text(), "conflicting retained asset"
            )

    def test_preview_versions_and_unknown_output_files_are_refused(self):
        from scripts.distribution.assets import write_bundle

        for version in ("unreleased", "01.0.0", "v1.0.0", "1.0.0-rc.1"):
            with (
                tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp,
                self.assertRaises(ValueError),
            ):
                write_bundle(ROOT, Path(tmp) / "bundle", version, "a" * 40, DIGEST)
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            (root / ".env").write_text("private retained data")
            with self.assertRaises(ValueError):
                write_bundle(ROOT, root, "1.0.0", "a" * 40, DIGEST)

    def test_asset_retry_checks_bytes_without_clobbering_or_duplicate_uploads(self):
        from scripts.distribution.assets import attach_bundle, write_bundle

        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            directory = Path(tmp) / "bundle"
            write_bundle(ROOT, directory, "1.0.0", "a" * 40, DIGEST)
            existing = [
                {"id": i + 1, "name": name, "size": (directory / name).stat().st_size}
                for i, name in enumerate(sorted(NAMES))
            ]
            uploads = []

            def request(path, *, data=None, **_):
                if data is not None:
                    uploads.append(path)
                    return b"{}"
                if "/assets?" in path:
                    return json.dumps(
                        existing if path.endswith("&page=1") else []
                    ).encode()
                identity = int(path.rsplit("/", 1)[1])
                return (directory / existing[identity - 1]["name"]).read_bytes()

            with patch("scripts.distribution.assets.api_request", side_effect=request):
                attach_bundle("owner/repo", 7, directory)
                self.assertEqual(uploads, [])
                existing[0]["name"] = "unexpected.txt"
                with self.assertRaises(ValueError):
                    attach_bundle("owner/repo", 7, directory)
            existing[0]["name"] = "INSTALL.md"
            with (
                patch(
                    "scripts.distribution.assets.api_request",
                    side_effect=lambda path, **kwargs: (
                        json.dumps(
                            existing if path.endswith("&page=1") else []
                        ).encode()
                        if "/assets?" in path
                        else b"mismatch"
                    ),
                ),
                self.assertRaises(ValueError),
            ):
                attach_bundle("owner/repo", 7, directory)


if __name__ == "__main__":
    unittest.main()
