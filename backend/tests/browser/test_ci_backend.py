"""Backend CI preparation must refuse unsafe targets before changing either DB."""

import importlib
import os
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4


class CIBackendTargetTests(unittest.TestCase):
    valid = {
        "HDG_VERIFICATION_PROFILE": "lives",
        "POSTGRES_DB": "historical_date_game_lives_backend_test",
        "POSTGRES_SERVER": "127.0.0.1",
        "POSTGRES_PORT": "5433",
        "ENVIRONMENT": "local",
    }

    def helper(self):
        return importlib.import_module("tests.browser.ci_backend")

    def test_exact_target_required_including_missing_values(self):
        helper = self.helper()
        helper.require_ci_target(self.valid)
        for key, unsafe in {
            "HDG_VERIFICATION_PROFILE": "guest",
            "POSTGRES_DB": "historical_date_game_test",
            "POSTGRES_SERVER": "localhost",
            "POSTGRES_PORT": "5432",
            "ENVIRONMENT": "production",
        }.items():
            for value in (unsafe, None):
                candidate = dict(self.valid)
                if value is None:
                    del candidate[key]
                else:
                    candidate[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                    helper.require_ci_target(candidate)

    def test_cli_mismatch_refuses_even_with_unreachable_database(self):
        candidate = dict(os.environ, **self.valid)
        candidate.update(HDG_VERIFICATION_PROFILE="guest", POSTGRES_SERVER="192.0.2.1")
        completed = subprocess.run(
            [sys.executable, "-m", "tests.browser.ci_backend", "prepare"],
            env=candidate, capture_output=True, text=True, timeout=10,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("exact lives backend disposable endpoint", completed.stderr)
        self.assertNotIn("psycopg", completed.stderr)

    def test_foreign_owner_comment_and_idle_pool_refuse_before_any_mutation(self):
        helper = self.helper()
        from app.core.config import settings
        from tests.browser import guest_test_environment as environment

        class Connection:
            def __init__(self, identity, active):
                self.identity = identity
                self.active = active
                self.statements = []

            def execute(self, statement, parameters):
                self.statements.append(str(statement))
                if "FROM pg_database" in str(statement):
                    row = self.identity(parameters[0])
                elif "FROM pg_stat_activity" in str(statement):
                    row = (self.active,)
                else:
                    raise AssertionError(f"Unexpected mutation: {statement}")
                return type("Rows", (), {"fetchone": lambda _: row})()

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        for mismatch in ("comment", "owner", "idle-pool"):
            def identity(database, mismatch=mismatch):
                # The second target is unsafe: the first must not be prepared yet.
                if database == "historical_date_game_lives_backend_test":
                    return None
                return (
                    "foreign" if mismatch == "comment" else environment.ownership_comment(database),
                    "foreign" if mismatch == "owner" else settings.POSTGRES_USER,
                )

            connection = Connection(identity, int(mismatch == "idle-pool"))
            with (
                self.subTest(mismatch=mismatch),
                patch.dict(os.environ, self.valid),
                patch.object(environment, "_maintenance_connection", return_value=connection),
                self.assertRaisesRegex(RuntimeError, "ownership|consumers"),
            ):
                helper.prepare()
            self.assertFalse(any("CREATE" in s or "COMMENT" in s for s in connection.statements))

    def test_existing_owned_idle_secondary_is_unchanged_and_real_idle_pool_refuses(self):
        helper = self.helper()
        from sqlalchemy import create_engine, text

        from app.core.config import settings
        from tests.browser import guest_test_environment as environment

        database = "historical_date_game_lives_migration_test"
        environment.require_owned_guest_database(database)
        helper.require_idle_owned(database)
        engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI).rsplit("/", 1)[0] + "/" + database)
        try:
            with engine.connect() as connection:
                before = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            with self.assertRaisesRegex(RuntimeError, "consumers"):
                helper.require_idle_owned(database)
        finally:
            engine.dispose()
        helper.require_idle_owned(database)
        with environment._maintenance_connection() as connection:
            identity = environment._database_identity(connection, database)
        self.assertEqual(identity, (environment.ownership_comment(database), settings.POSTGRES_USER))
        # The refused check neither migrates nor mutates the selected catalogue.
        try:
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(), before)
                self.assertEqual(connection.execute(text("SELECT r.fixture,r.event_count FROM catalogselection s JOIN catalogrelease r ON r.id=s.release_id WHERE s.id=1")).one(), (True, 8))
        finally:
            engine.dispose()

    def test_existing_synthetic_selection_is_reused_without_row_changes(self):
        helper = self.helper()
        from sqlalchemy import create_engine
        from sqlmodel import Session

        from app.core.config import settings
        from tests.browser import guest_test_environment as environment

        database = "historical_date_game_lives_migration_test"
        helper.require_idle_owned(database)
        engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI).rsplit("/", 1)[0] + "/" + database)
        try:
            with Session(engine) as session:
                before = environment._private_row_digests(session)
            engine.dispose()
            helper._seed_migration_catalogue()
            with Session(engine) as session:
                self.assertEqual(environment._private_row_digests(session), before)
        finally:
            engine.dispose()

    def test_mismatched_selected_catalogue_is_not_replaced(self):
        helper = self.helper()
        from sqlalchemy import create_engine, text

        from app.core.config import settings

        database = "historical_date_game_lives_migration_test"
        helper.require_idle_owned(database)
        engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI).rsplit("/", 1)[0] + "/" + database)
        original_selection = None
        release_id = "ci-mismatch-" + uuid4().hex
        try:
            with engine.begin() as connection:
                original_selection = connection.execute(text("SELECT release_id FROM catalogselection WHERE id=1")).scalar_one()
                # Insert an owned synthetic mismatch; never update an immutable
                # release or disable its production database trigger.
                connection.execute(text(
                    "INSERT INTO catalogrelease (id,manifest,manifest_bytes,manifest_sha256,created_at,activated_at,event_count,fixture) "
                    "SELECT :release,manifest,manifest_bytes,manifest_sha256,created_at,activated_at,1,true "
                    "FROM catalogrelease WHERE id=:original"
                ), {"release": release_id, "original": original_selection})
                connection.execute(text("UPDATE catalogselection SET release_id=:release WHERE id=1"), {"release": release_id})
            engine.dispose()
            with self.assertRaisesRegex(RuntimeError, "Refusing to replace"):
                helper._seed_migration_catalogue()
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT r.id,r.event_count FROM catalogselection s JOIN catalogrelease r ON r.id=s.release_id WHERE s.id=1")).one(), (release_id, 1))
        finally:
            if original_selection is not None:
                with engine.begin() as connection:
                    connection.execute(text("UPDATE catalogselection SET release_id=:release WHERE id=1"), {"release": original_selection})
                    connection.execute(text("DELETE FROM catalogrelease WHERE id=:release"), {"release": release_id})
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
