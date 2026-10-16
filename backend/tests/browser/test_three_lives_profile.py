import os
import unittest
from unittest.mock import patch

from tests.browser import guest_test_environment as environment


class ThreeLivesProfileTests(unittest.TestCase):
    def test_profile_uses_only_exact_owned_database_names(self) -> None:
        with patch.dict(os.environ, {"HDG_VERIFICATION_PROFILE": "lives"}):
            self.assertEqual(environment.verification_profile(), "lives")
            self.assertEqual(
                environment.LIVES_DATABASES,
                frozenset(
                    {
                        "historical_date_game_lives_test",
                        "historical_date_game_lives_fixture_test",
                        "historical_date_game_lives_migration_test",
                        "historical_date_game_lives_backend_test",
                    }
                ),
            )
            for name in environment.LIVES_DATABASES:
                environment.require_guest_test_target(name, "127.0.0.1", "local")
            for name in (
                "historical_date_game_random_test",
                "historical_date_game_guest_test",
                "historical_date_game_board_test",
            ):
                with self.assertRaises(RuntimeError):
                    environment.require_guest_test_target(name, "127.0.0.1", "local")

    def test_prepare_creates_only_absent_owned_target(self) -> None:
        database = "historical_date_game_lives_test"
        with patch.dict(os.environ, {"HDG_VERIFICATION_PROFILE": "lives"}):
            connection = unittest.mock.MagicMock()
            connection.execute.return_value.fetchone.side_effect = [
                None,
                ("historical-date-game board-polish-three-lives verification; "
                 f"worktree={environment.WORKTREE}; database={database}",
                 environment.settings.POSTGRES_USER),
            ]
            manager = unittest.mock.MagicMock()
            manager.__enter__.return_value = connection
            with patch.object(environment, "_maintenance_connection", return_value=manager):
                self.assertTrue(environment.prepare_database(database))
            self.assertEqual(connection.execute.call_count, 4)

    def test_prepare_rejects_unowned_target_without_modification(self) -> None:
        database = "historical_date_game_lives_test"
        with patch.dict(os.environ, {"HDG_VERIFICATION_PROFILE": "lives"}):
            connection = unittest.mock.MagicMock()
            connection.execute.return_value.fetchone.return_value = ("other", "other")
            manager = unittest.mock.MagicMock()
            manager.__enter__.return_value = connection
            with patch.object(environment, "_maintenance_connection", return_value=manager):
                with self.assertRaises(RuntimeError):
                    environment.prepare_database(database)
            connection.execute.assert_called_once()

    def test_existing_profiles_and_paths_remain_unchanged(self) -> None:
        with patch.dict(os.environ, {"HDG_VERIFICATION_PROFILE": "guest"}):
            self.assertEqual(environment.verification_profile(), "guest")
            self.assertIn("historical_date_game_guest_test", environment.GUEST_DATABASES)
            self.assertEqual(environment.evidence_directory(), environment.EVIDENCE)
        with patch.dict(os.environ, {"HDG_VERIFICATION_PROFILE": "board"}):
            self.assertEqual(environment.verification_profile(), "board")
            self.assertIn("historical_date_game_board_test", environment.BOARD_DATABASES)
            self.assertEqual(
                environment.evidence_directory(),
                environment.WORKTREE / ".superpowers/sdd/2026-10-14-game-board-redesign/integration",
            )
