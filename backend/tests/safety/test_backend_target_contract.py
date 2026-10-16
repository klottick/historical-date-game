"""Pure fixture-boundary proofs: never import settings or access a database."""

import __future__

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tests.browser.ci_backend import require_ci_target
from tests.db_guard import require_test_database


def fixture_functions(
    profile: str, database: str, **overrides: Any
) -> tuple[dict[str, Any], list[str]]:
    settings = SimpleNamespace(
        POSTGRES_DB=database,
        POSTGRES_SERVER="127.0.0.1",
        POSTGRES_PORT=5433,
        ENVIRONMENT="local",
    )
    settings.__dict__.update(overrides)
    calls: list[str] = []

    class Connection:
        def __enter__(self) -> Any:
            calls.append("maintenance")
            return self

        def __exit__(self, *_args: Any) -> None:
            pass

        def execute(self, *_args: Any) -> Any:
            return self

        def fetchone(self) -> tuple[int]:
            return (0,)

    class Session:
        def __init__(self, *_args: Any) -> None:
            calls.append("session")

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_args: Any) -> None:
            pass

        def rollback(self) -> None:
            calls.append("rollback")

        def execute(self, *_args: Any) -> None:
            calls.append("delete")

        def commit(self) -> None:
            calls.append("commit")

    namespace: dict[str, Any] = {
        "settings": settings,
        "os": SimpleNamespace(environ={"HDG_VERIFICATION_PROFILE": profile}),
        "require_test_database": require_test_database,
        "require_ci_target": require_ci_target,
        # Ownership/idleness are intentionally satisfied. The target must still
        # refuse BEFORE reaching these boundaries or any session mutation.
        "require_owned_guest_database": lambda: calls.append("ownership"),
        "_maintenance_connection": Connection,
        "Session": Session,
        "engine": object(),
        "init_db": lambda _session: calls.append("init"),
        "delete": lambda model: model,
    }
    for model in (
        "GameOperation",
        "GameRun",
        "DailyDefinition",
        "CatalogSelection",
        "MediaAsset",
        "EventRevision",
        "CatalogCategory",
        "CatalogRelease",
        "Item",
        "User",
    ):
        namespace[model] = object()
    source = Path(__file__).resolve().parents[1] / "conftest.py"
    nodes = []
    for node in ast.parse(source.read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.name in {
            "_require_backend_verification_target",
            "_verification_database_safety",
            "db",
        }:
            node.decorator_list = []
            nodes.append(node)
    code = compile(
        ast.Module(body=nodes, type_ignores=[]),
        str(source),
        "exec",
        flags=__future__.annotations.compiler_flag,
        dont_inherit=True,
    )
    exec(code, namespace)
    return namespace, calls


class BackendTargetContracts(unittest.TestCase):
    def test_documented_commands_use_the_supported_backend_target(self) -> None:
        readme = (Path(__file__).resolve().parents[2] / "README.md").read_text()
        instructions = readme.split("## Backend tests", 1)[1].split(
            "### Test Coverage", 1
        )[0]
        for command in (
            "export HDG_VERIFICATION_PROFILE=lives",
            "export POSTGRES_DB=historical_date_game_lives_backend_test",
            "python -m tests.browser.ci_backend prepare",
            "bash scripts/prestart.sh",
        ):
            self.assertIn(command, instructions)

    def test_owned_idle_wrong_targets_refuse_before_setup_or_session(self) -> None:
        targets = [
            ("guest", "historical_date_game_guest_test", {}),
            ("guest", "historical_date_game_guest_fixture_test", {}),
            ("board", "historical_date_game_board_test", {}),
            ("lives", "historical_date_game_lives_test", {}),
            ("lives", "historical_date_game_lives_fixture_test", {}),
            ("lives", "historical_date_game_lives_migration_test", {}),
            ("guest", "historical_date_game_lives_backend_test", {}),
            (
                "lives",
                "historical_date_game_lives_backend_test",
                {"POSTGRES_SERVER": "localhost"},
            ),
            (
                "lives",
                "historical_date_game_lives_backend_test",
                {"POSTGRES_PORT": 5432},
            ),
            (
                "lives",
                "historical_date_game_lives_backend_test",
                {"ENVIRONMENT": "production"},
            ),
        ]
        for profile, database, settings in targets:
            for boundary in ("_verification_database_safety", "db"):
                with self.subTest(
                    profile=profile,
                    database=database,
                    settings=settings,
                    boundary=boundary,
                ):
                    namespace, calls = fixture_functions(profile, database, **settings)
                    with self.assertRaises(RuntimeError):
                        if boundary == "db":
                            next(namespace[boundary](None))
                        else:
                            namespace[boundary]()
                    self.assertEqual(
                        calls, [], "Wrong target crossed the setup/mutation boundary"
                    )

    def test_exact_backend_target_keeps_ownership_and_idleness_checks(self) -> None:
        namespace, calls = fixture_functions(
            "lives", "historical_date_game_lives_backend_test"
        )
        namespace["_verification_database_safety"]()
        self.assertEqual(calls, ["ownership", "maintenance"])

    def test_wrong_target_at_teardown_refuses_before_deleting_rows(self) -> None:
        namespace, calls = fixture_functions(
            "lives", "historical_date_game_lives_backend_test"
        )
        fixture = namespace["db"](None)
        next(fixture)
        self.assertIn("init", calls)
        calls.clear()
        namespace["settings"].POSTGRES_DB = "historical_date_game_lives_test"
        rejected = False
        try:
            next(fixture)
        except RuntimeError:
            rejected = True
        except StopIteration:
            pass
        self.assertTrue(rejected, "Wrong target was not refused at teardown")
        self.assertNotIn("delete", calls)
        self.assertNotIn("commit", calls)


if __name__ == "__main__":
    unittest.main()
