"""Publication workflow contracts; run with backend's development dependencies."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow(name: str) -> dict:
    # BaseLoader keeps the YAML 1.2 GitHub key `on` as text, not a 1.1 boolean.
    return yaml.load(
        (ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader
    )


class WorkflowContracts(unittest.TestCase):
    def test_main_pushes_run_all_validation_workflows(self) -> None:
        for name in (
            "test-backend.yml",
            "lint-backend.yml",
            "playwright.yml",
            "test-docker-compose.yml",
        ):
            with self.subTest(workflow=name):
                self.assertEqual(workflow(name)["on"]["push"]["branches"], ["main"])

    def test_changelog_targets_the_actual_default_branch(self) -> None:
        self.assertEqual(
            workflow("latest-changes.yml")["on"]["pull_request_target"]["branches"],
            ["main"],
        )

    def test_main_publication_never_triggers_a_deployment(self) -> None:
        self.assertEqual(
            set(workflow("deploy-staging.yml")["on"]), {"workflow_dispatch"}
        )
        self.assertEqual(
            workflow("deploy-production.yml")["on"],
            {"release": {"types": ["published"]}},
        )

    def test_backend_job_prepares_the_exact_lives_databases_before_testing(
        self,
    ) -> None:
        job = workflow("test-backend.yml")["jobs"]["test-backend"]
        env = job["env"]
        self.assertEqual(env.get("HDG_VERIFICATION_PROFILE"), "lives")
        self.assertEqual(env["POSTGRES_DB"], "historical_date_game_lives_backend_test")
        self.assertEqual(env["POSTGRES_SERVER"], "127.0.0.1")
        self.assertEqual(env["POSTGRES_PORT"], "5433")
        self.assertEqual(env["ENVIRONMENT"], "local")
        steps = job["steps"]
        prepare = next(
            i
            for i, s in enumerate(steps)
            if "tests.browser.ci_backend prepare" in s.get("run", "")
        )
        migrate = next(
            i for i, s in enumerate(steps) if "scripts/prestart.sh" in s.get("run", "")
        )
        tests = next(
            i
            for i, s in enumerate(steps)
            if "scripts/tests-start.sh" in s.get("run", "")
        )
        self.assertLess(prepare, migrate)
        self.assertLess(migrate, tests)
        self.assertEqual(steps[prepare]["working-directory"], "backend")
        maintenance = next(
            s for s in steps if "up -d --wait db mailcatcher" in s.get("run", "")
        )
        self.assertEqual(maintenance["env"]["POSTGRES_DB"], "postgres")

    def test_compose_cleanup_is_owned_and_runs_after_failure(self) -> None:
        for name, job_name in (
            ("test-backend.yml", "test-backend"),
            ("test-docker-compose.yml", "test-docker-compose"),
        ):
            with self.subTest(workflow=name):
                job = workflow(name)["jobs"][job_name]
                project = job.get("env", {}).get("COMPOSE_PROJECT_NAME")
                self.assertIsInstance(project, str)
                self.assertIn("github.run_id", project)
                self.assertIn("github.run_attempt", project)
                cleanup = [
                    s for s in job["steps"] if "docker compose down" in s.get("run", "")
                ]
                self.assertTrue(cleanup)
                self.assertEqual(cleanup[-1].get("if"), "always()")


if __name__ == "__main__":
    unittest.main()
