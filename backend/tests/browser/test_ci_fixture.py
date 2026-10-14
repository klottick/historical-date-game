"""Pure CI contracts: no application settings, pytest, DB, or SMTP imports."""

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


class CIFixtureContracts(unittest.TestCase):
    def helper(self):
        spec = importlib.util.find_spec("tests.browser.ci_fixture")
        self.assertIsNotNone(spec, "missing CI-only guarded fixture helper")
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_endpoint_requires_hosted_fresh_fixture_loopback_and_exact_port(self):
        helper = self.helper()
        valid = {
            "GITHUB_ACTIONS": "true",
            "HDG_CI_DISPOSABLE": "true",
            "POSTGRES_DB": "historical_date_game_guest_fixture_test",
            "POSTGRES_SERVER": "127.0.0.1",
            "POSTGRES_PORT": "5433",
            "ENVIRONMENT": "local",
            "HDG_VERIFICATION_PROFILE": "guest",
        }
        helper.require_ci_target(valid)
        for key, value in {
            "GITHUB_ACTIONS": "false",
            "HDG_CI_DISPOSABLE": "false",
            "POSTGRES_DB": "historical_date_game_test",
            "POSTGRES_SERVER": "db",
            "POSTGRES_PORT": "5432",
            "ENVIRONMENT": "production",
            "HDG_VERIFICATION_PROFILE": "board",
        }.items():
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                helper.require_ci_target(dict(valid, **{key: value}))

    def test_compose_projects_public_media_only_read_only_and_creates_no_db(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as directory:
            public = Path(directory) / "media"
            config = helper.compose_override(public)
            services = config["services"]
            self.assertEqual(services["db"]["environment"]["POSTGRES_DB"], "postgres")
            self.assertEqual(
                services["prestart"]["environment"]["POSTGRES_PORT"], "5432"
            )
            mount = services["backend"]["volumes"][0]
            self.assertEqual(mount["source"], str(public))
            self.assertEqual(mount["target"], "/browser-game/media")
            self.assertTrue(mount["read_only"])
            self.assertFalse(mount["bind"]["create_host_path"])
            self.assertNotIn("playwright", services)
            self.assertFalse(public.exists())

    def test_public_projection_rejects_answers_symlinks_and_digest_mismatch(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as directory:
            public = Path(directory) / "media"
            release = public / "fixture-release"
            release.mkdir(parents=True)
            payload = b"authored synthetic illustration"
            digest = hashlib.sha256(payload).hexdigest()
            asset = release / f"{digest}.svg"
            asset.write_bytes(payload)
            files = {f"media/{asset.name}": digest}
            self.assertEqual(helper.verify_public_media(public, release.name, files), 1)
            (release / "catalog.json").write_text('{"answer": 1800}')
            with self.assertRaises(RuntimeError):
                helper.verify_public_media(public, release.name, files)
            (release / "catalog.json").unlink()
            asset.write_bytes(b"different")
            with self.assertRaises(RuntimeError):
                helper.verify_public_media(public, release.name, files)
            asset.unlink()
            asset.symlink_to(Path(directory) / "outside")
            with self.assertRaises(RuntimeError):
                helper.verify_public_media(public, release.name, files)

    def test_public_mount_refuses_symlink_ancestors_before_any_db_or_files(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "outside").mkdir()
            (root / "alias").symlink_to(root / "outside", target_is_directory=True)
            public = root / "alias" / "media"
            with self.assertRaises(RuntimeError):
                helper.compose_override(public)
            self.assertFalse(public.exists())


if __name__ == "__main__":
    unittest.main()
