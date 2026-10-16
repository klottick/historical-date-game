"""Compose rendering and real image checks; no application lifecycle commands."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENV = {
    "HDG_IMAGE": "hdg-distribution-local:check",
    "PROJECT_NAME": "Image test",
    "SECRET_KEY": "s" * 64,
    "POSTGRES_USER": "hdg",
    "POSTGRES_PASSWORD": "p" * 32,
    "POSTGRES_DB": "hdg",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "a" * 32,
    "FRONTEND_HOST": "http://localhost:8000",
    "ENVIRONMENT": "local",
}


class ImageContracts(unittest.TestCase):
    def compose(self, environment=None):
        self.assertTrue((ROOT / "compose.yaml").is_file(), "release compose is missing")
        return subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                "/dev/null",
                "-f",
                str(ROOT / "compose.yaml"),
                "config",
                "--format",
                "json",
            ],
            cwd="/tmp/opencode",
            env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]}
            | (ENV if environment is None else environment),
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def test_release_compose_is_pull_only_and_internal_db_is_unpublished(self):
        result = self.compose()
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(result.stdout)
        services = config["services"]
        self.assertEqual(set(services), {"app", "initialize", "db"})
        self.assertEqual(set(config["volumes"]), {"postgres-data", "game-data"})
        for service in services.values():
            self.assertNotIn("build", service)
            self.assertNotIn("container_name", service)
            self.assertEqual(service["platform"], "linux/amd64")
            self.assertFalse(service.get("privileged", False))
        self.assertNotIn("ports", services["db"])
        self.assertEqual(services["db"]["volumes"][0]["target"], "/var/lib/postgresql")
        self.assertRegex(
            services["db"]["image"], r"^postgres:18\.6@sha256:[0-9a-f]{64}$"
        )
        app = services["app"]
        self.assertEqual(app["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(app["ports"][0]["published"], "8000")
        self.assertEqual(app["volumes"][0]["target"], "/data")
        self.assertTrue(app["volumes"][0]["read_only"])
        self.assertEqual(
            app["depends_on"]["initialize"]["condition"],
            "service_completed_successfully",
        )
        self.assertEqual(
            services["initialize"]["depends_on"]["db"]["condition"], "service_healthy"
        )
        self.assertEqual(app["stop_grace_period"], "30s")
        self.assertEqual(services["db"]["stop_grace_period"], "30s")
        self.assertEqual(app["restart"], "unless-stopped")

    def test_application_and_initializer_use_identical_reference(self):
        result = self.compose()
        self.assertEqual(result.returncode, 0, result.stderr)
        services = json.loads(result.stdout)["services"]
        self.assertEqual(services["app"]["image"], services["initialize"]["image"])
        self.assertEqual(
            services["app"]["environment"], services["initialize"]["environment"]
        )
        self.assertEqual(services["initialize"]["command"], ["initialize"])
        raw = (ROOT / "env.example").read_text()
        for key in (
            "SECRET_KEY",
            "POSTGRES_PASSWORD",
            "FIRST_SUPERUSER_PASSWORD",
            "HDG_IMAGE",
        ):
            self.assertIn(f"{key}=\n", raw)
            broken = ENV | {key: ""}
            self.assertNotEqual(self.compose(broken).returncode, 0, key)

    def test_context_excludes_nested_credentials_and_private_worktrees(self):
        self.assertTrue((ROOT / ".dockerignore").is_file(), "safe context is missing")
        ignored = (ROOT / ".dockerignore").read_text()
        self.assertIn("**/.npmrc", ignored)
        if os.environ.get("HDG_CONTEXT_AUDIT") != "1":
            self.skipTest("set HDG_CONTEXT_AUDIT=1 for real BuildKit context probe")
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            context = root / "context"
            context.mkdir()
            shutil.copyfile(ROOT / ".dockerignore", context / ".dockerignore")
            private = (
                ".env",
                "backend/app/.env.secret",
                "frontend/src/.npmrc",
                ".worktrees/kept/private",
                ".superpowers/evidence/secret",
                "data/game/raw/private",
                "backend/catalogue/raw/private",
                "frontend/playwright/.auth/private",
                "backend/app/credentials.json",
                "frontend/public/private.pem",
                "frontend/unknown-private.txt",
                "backend/unknown-private.txt",
                "docker/unknown-private.txt",
                "frontend/src/test-results/private",
            )
            for name in private:
                path = context / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("SYNTHETIC_PRIVATE_SENTINEL")
            (context / "backend/app/allowed.py").write_text("allowed=True")
            dockerfile = root / "Dockerfile.context"
            dockerfile.write_text("FROM scratch AS context\nCOPY . /\n")
            subprocess.run(
                [
                    "docker",
                    "build",
                    "--file",
                    str(dockerfile),
                    "--output",
                    f"type=local,dest={root / 'export'}",
                    str(context),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
            self.assertTrue((root / "export/backend/app/allowed.py").exists())
            for name in private:
                self.assertFalse((root / "export" / name).exists(), name)

    def test_runtime_contains_only_expected_artifacts(self):
        self.assertTrue(
            (ROOT / "Dockerfile").is_file(), "release Dockerfile is missing"
        )
        image = os.environ.get("HDG_TEST_IMAGE")
        if not image:
            self.skipTest("set HDG_TEST_IMAGE for native runtime image probe")
        info = json.loads(
            subprocess.run(
                ["docker", "image", "inspect", image],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )[0]
        self.assertEqual((info["Os"], info["Architecture"]), ("linux", "amd64"))
        self.assertEqual(info["Config"]["User"], "10001:10001")
        self.assertEqual(
            info["Config"]["Entrypoint"], ["python", "-m", "app.distribution"]
        )
        script = """
import importlib.metadata as m, os, pathlib, shutil
assert os.getuid() == 10001
for name in ('gcc', 'cc', 'node', 'npm', 'uv'): assert shutil.which(name) is None, name
for name in ('pytest', 'mypy', 'ruff', 'coverage', 'hatchling', 'setuptools'):
    try: m.version(name)
    except m.PackageNotFoundError: pass
    else: raise AssertionError(name)
for path in ('/app/backend/tests', '/app/.env', '/app/.git', '/app/frontend/node_modules', '/app/backend/app/.env.secret'):
    assert not pathlib.Path(path).exists(), path
for path in ('/app/LICENSE', '/app/backend/catalogue/README.md', '/app/backend/catalogue/releases/chronology-1276-runtime-v2/NOTICE.catalog.md', '/app/frontend/dist/index.html'):
    assert pathlib.Path(path).is_file(), path
import psycopg, pydantic_core, PIL._imaging, mwparserfromhell.parser._tokenizer, uvloop, argon2
from app.content.runtime import verify_default
assert verify_default(pathlib.Path('/app/backend/catalogue')).manifest.event_count == 1276
from app.distribution.frontend import check_frontend
check_frontend(pathlib.Path('/app/frontend/dist'))
assert os.stat('/data').st_uid == 10001
print('native runtime privacy/import/catalogue checks passed')
"""
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "python",
                image,
                "-c",
                script,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
