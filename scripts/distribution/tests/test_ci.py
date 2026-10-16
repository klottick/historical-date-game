import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def workflow(name):
    return yaml.load(
        (ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader
    )


class CiTests(unittest.TestCase):
    def test_unparseable_trace_is_quarantined_instead_of_uploaded_unredacted(self):
        import json
        import zipfile

        from scripts.distribution.diagnostics import sanitize_tree

        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            with zipfile.ZipFile(root / "trace.zip", "w") as archive:
                archive.writestr("broken.network", "private invalid JSON")
            with self.assertRaises(ValueError):
                sanitize_tree(root)
            self.assertFalse((root / "trace.zip").exists())
            marker = json.loads((root / "trace.redaction-failed.json").read_text())
            private = Path(marker["private_copy"])
            self.assertFalse(private.is_relative_to(root))
            self.assertEqual(private.stat().st_mode & 0o777, 0o600)
            private.unlink()
            private.parent.rmdir()

    def test_first_failure_trace_headers_are_redacted_not_discarded(self):
        import json
        import zipfile

        from scripts.distribution.diagnostics import sanitize_tree

        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            original = {
                "request": {
                    "headers": [
                        {"name": "Cookie", "value": "guest-private"},
                        {"name": "Accept", "value": "application/json"},
                    ],
                    "cookies": [{"name": "hdg_guest", "value": "guest-private"}],
                },
                "response": {
                    "headers": [{"name": "Set-Cookie", "value": "guest-private"}]
                },
                "access_token": "private-token",
            }
            with zipfile.ZipFile(root / "trace.zip", "w") as archive:
                archive.writestr("trace.network", json.dumps(original) + "\n")
                archive.writestr("resources/screenshot.png", b"PNG")
                archive.writestr(
                    "resources/login.json",
                    json.dumps({"access_token": "pretty-private"}, indent=2),
                )
                archive.writestr(
                    "trace.trace",
                    json.dumps(
                        {
                            "apiName": "locator.fill",
                            "params": {"value": "typed-private"},
                        }
                    )
                    + "\n",
                )
            sanitize_tree(root)
            with zipfile.ZipFile(root / "trace.zip") as archive:
                self.assertEqual(archive.read("resources/screenshot.png"), b"PNG")
                content = archive.read("trace.network").decode()
                self.assertNotIn("guest-private", content)
                self.assertNotIn("private-token", content)
                self.assertIn("application/json", content)
                self.assertNotIn(
                    b"pretty-private", archive.read("resources/login.json")
                )
                self.assertNotIn(b"typed-private", archive.read("trace.trace"))

    def test_new_compose_never_changes_development_file_selection(self):
        for name, job in (
            ("test-backend.yml", "test-backend"),
            ("test-docker-compose.yml", "test-docker-compose"),
            ("playwright.yml", "test-playwright"),
        ):
            with self.subTest(workflow=name):
                value = workflow(name)["jobs"][job]["env"]["COMPOSE_FILE"]
                self.assertEqual(
                    value, "docker-compose.yml:docker-compose.override.yml"
                )

    def test_legacy_render_still_uses_development_services_and_volumes(self):
        import json

        from scripts.distribution.tests.test_image import ENV

        env = (
            {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]}
            | ENV
            | {
                "STACK_NAME": "hdg-render-contract",
                "DOMAIN": "localhost",
                "DOCKER_IMAGE_BACKEND": "hdg-dev-backend",
                "DOCKER_IMAGE_FRONTEND": "hdg-dev-frontend",
                "POSTGRES_PORT": "5432",
                "BACKEND_CORS_ORIGINS": "[]",
            }
        )
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                "/dev/null",
                "-f",
                str(ROOT / "docker-compose.yml"),
                "-f",
                str(ROOT / "docker-compose.override.yml"),
                "config",
                "--format",
                "json",
            ],
            check=True,
            capture_output=True,
            env=env,
            text=True,
        )
        config = json.loads(result.stdout)
        self.assertEqual(
            set(config["services"]),
            {
                "backend",
                "frontend",
                "prestart",
                "db",
                "adminer",
                "proxy",
                "mailcatcher",
                "playwright",
            },
        )
        self.assertNotIn("game-data", config["volumes"])
        self.assertEqual(set(config["volumes"]), {"app-db-data-pg18"})
        self.assertEqual(config["services"]["db"]["ports"][0]["published"], "5433")
        self.assertIn("build", config["services"]["backend"])

    def test_release_event_never_deploys(self):
        for name in ("deploy-staging.yml", "deploy-production.yml"):
            self.assertEqual(set(workflow(name)["on"]), {"workflow_dispatch"})

    def test_pr_container_jobs_are_read_only_native_amd64(self):
        names = (
            "test-distribution.yml",
            "test-backend.yml",
            "test-docker-compose.yml",
            "playwright.yml",
            "lint-backend.yml",
            "generate-client.yml",
        )
        for name in names:
            data = workflow(name)
            with self.subTest(workflow=name):
                self.assertEqual(data["permissions"]["contents"], "read")
                self.assertNotIn("write", data["permissions"].values())
                for job in data["jobs"].values():
                    self.assertNotIn("write", job.get("permissions", {}).values())
                    for step in job.get("steps", []):
                        if step.get("uses", "").startswith("actions/checkout@"):
                            self.assertEqual(
                                step["with"]["persist-credentials"], "false"
                            )
        release = workflow("test-distribution.yml")
        self.assertEqual(set(release["on"]), {"push", "pull_request", "workflow_call"})
        job = release["jobs"]["image"]
        self.assertEqual(job["runs-on"], "ubuntu-24.04")
        text = (ROOT / ".github/workflows/test-distribution.yml").read_text()
        for forbidden in (
            "setup-qemu",
            "packages: write",
            "docker push",
            "pull_request_target",
            "continue-on-error",
        ):
            self.assertNotIn(forbidden, text)

    def test_browser_failures_are_not_retried(self):
        config = (ROOT / "frontend/playwright.config.ts").read_text()
        self.assertIn("retries: 0", config)
        self.assertIn("trace: 'retain-on-failure'", config)
        steps = workflow("playwright.yml")["jobs"]["test-playwright"]["steps"]
        run = next(s["run"] for s in steps if s.get("name") == "Run Playwright tests")
        self.assertIn("--retries=0", run)

    def test_failed_smoke_cannot_upload_eligible_image(self):
        steps = workflow("test-distribution.yml")["jobs"]["image"]["steps"]
        smoke = next(s for s in steps if s.get("id") == "smoke")
        upload = next(s for s in steps if s.get("name") == "Upload tested image")
        self.assertIn("success()", upload["if"])
        self.assertIn("github.event_name == 'release'", upload["if"])
        self.assertIn("inputs.release-version != 'unreleased'", upload["if"])
        self.assertEqual(upload["with"]["name"], "tested-image")
        self.assertNotIn("continue-on-error", smoke)
        # Execute the actual shell block with only the external Python boundary
        # substituted: a failed first smoke must abort before the second invocation.
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            fake = root / "python3"
            marker = root / "calls"
            fake.write_text('#!/bin/sh\necho called >> "$MARKER"\nexit 42\n')
            fake.chmod(0o700)
            result = subprocess.run(
                ["bash", "-e", "-o", "pipefail", "-c", smoke["run"]],
                env={
                    "PATH": str(root) + ":/usr/bin:/bin",
                    "MARKER": str(marker),
                    "RUNNER_TEMP": tmp,
                    "IMAGE": "test-only",
                },
                check=False,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 42)
            self.assertEqual(marker.read_text().splitlines(), ["called"])

    def test_failure_diagnostics_precede_cleanup(self):
        for name, job in (
            ("test-backend.yml", "test-backend"),
            ("test-docker-compose.yml", "test-docker-compose"),
            ("playwright.yml", "test-playwright"),
        ):
            steps = workflow(name)["jobs"][job]["steps"]
            logs = next(
                i
                for i, s in enumerate(steps)
                if s.get("name") == "Save service failure logs"
            )
            cleanup = next(
                i
                for i, s in enumerate(steps)
                if "docker compose down" in s.get("run", "")
            )
            self.assertLess(logs, cleanup)
            self.assertEqual(steps[logs]["if"], "always()")
            self.assertTrue(
                any(
                    s.get("if") == "always()"
                    and "upload-artifact@" in s.get("uses", "")
                    for s in steps
                )
            )

    def test_local_legacy_scripts_refuse_retained_projects_before_docker(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            marker = root / "docker-was-called"
            for executable in ("docker", "docker-compose"):
                fake = root / executable
                fake.write_text('#!/bin/sh\necho called >> "$MARKER"\nexit 42\n')
                fake.chmod(0o700)
            for name in ("test.sh", "test-local.sh"):
                result = subprocess.run(
                    ["bash", str(ROOT / "scripts" / name)],
                    cwd=ROOT,
                    env={
                        "PATH": str(root) + ":/usr/bin:/bin",
                        "MARKER": str(marker),
                        "COMPOSE_PROJECT_NAME": "historical-date-game",
                    },
                    check=False,
                    capture_output=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(marker.exists(), name)


if __name__ == "__main__":
    unittest.main()
