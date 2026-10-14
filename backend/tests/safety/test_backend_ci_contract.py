"""Exercise the retained CI setup without Docker, SQL connections or migrations."""

import shlex
from importlib import import_module
from typing import Any

import pytest


def test_backend_ci_prepares_owned_target_before_migration_and_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from tests.browser import guest_test_environment as env

    workflow = import_module("yaml").safe_load(
        (env.WORKTREE / ".github/workflows/test-backend.yml").read_text()
    )
    job = workflow["jobs"]["test-backend"]
    target = job["env"]["POSTGRES_DB"]
    host = job["env"].get("POSTGRES_SERVER", "localhost")
    environment = job["env"].get("ENVIRONMENT", "local")
    env.require_guest_test_target(target, host, environment)
    monkeypatch.setattr(settings, "POSTGRES_DB", target)
    monkeypatch.setattr(settings, "POSTGRES_SERVER", host)
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)

    steps = job["steps"]
    boot = next(
        i for i, step in enumerate(steps) if "compose up" in step.get("run", "")
    )
    # Compose must not pre-create the verification target without its comment.
    assert steps[boot]["env"]["POSTGRES_DB"] != target
    setup = next(
        i for i, step in enumerate(steps) if "prepare-db" in step.get("run", "")
    )
    migrate = next(
        i for i, step in enumerate(steps) if "prestart.sh" in step.get("run", "")
    )
    tests = next(
        i for i, step in enumerate(steps) if "tests-start.sh" in step.get("run", "")
    )
    assert boot < setup < migrate < tests
    assert steps[setup]["working-directory"] == "backend"
    command = shlex.split(steps[setup]["run"].replace("$POSTGRES_DB", target))
    assert command[:5] == [
        "uv",
        "run",
        "python",
        "-m",
        "tests.browser.guest_test_environment",
    ]

    # Intercept SQL transport only; real creation, comment and ownership logic run.
    class Maintenance:
        identity: tuple[str, str] | None = None
        created = False
        commented = False

        def __enter__(self) -> Maintenance:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def execute(self, query: Any, params: Any = None) -> Maintenance:
            statement = query if isinstance(query, str) else query.as_string()
            if statement.startswith("SELECT shobj_description"):
                assert params == (target,)
            elif statement.startswith("CREATE DATABASE"):
                assert not self.created and self.identity is None
                assert (
                    statement
                    == f'CREATE DATABASE "{target}" OWNER "{settings.POSTGRES_USER}"'
                )
                self.created = True
            elif statement.startswith("COMMENT ON DATABASE"):
                assert self.created
                expected = f"historical-date-game guest-play verification; worktree={env.WORKTREE}; database={target}"
                assert statement == f"COMMENT ON DATABASE \"{target}\" IS '{expected}'"
                self.identity = (expected, settings.POSTGRES_USER)
                self.commented = True
            else:
                pytest.fail("Unexpected SQL at pure CI boundary")
            return self

        def fetchone(self) -> tuple[str, str] | None:
            return self.identity

    maintenance = Maintenance()
    monkeypatch.setattr(env, "_maintenance_connection", lambda: maintenance)

    def migration(database: str, direction: str, revision: str) -> None:
        assert maintenance.created and maintenance.commented
        env.require_owned_guest_database(database)
        assert (database, direction, revision) == (target, "upgrade", "head")

    monkeypatch.setattr(env, "run_migration", migration)
    assert env.main(command[5:]) == 0
    env.require_owned_guest_database()
    # An existing target without the exact comment is never adopted/relabelled.
    maintenance.identity = ("unowned Compose database", settings.POSTGRES_USER)
    with pytest.raises(RuntimeError, match="ownership"):
        env.prepare_database(target)
