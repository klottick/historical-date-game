from typing import Any, NoReturn

import pytest

from tests import conftest as integration_fixtures
from tests.db_guard import require_test_database


@pytest.mark.parametrize("name", ["app", "", "production", "app_test_backup"])
def test_rejects_non_test_database(name: str) -> None:
    with pytest.raises(RuntimeError):
        require_test_database(name)


def test_accepts_explicit_test_database() -> None:
    assert require_test_database("historical_date_game_test") is None


@pytest.mark.parametrize("name", ["app", "", "production"])
def test_db_fixture_rejects_before_init_or_cleanup(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    def fail_on_database_access(*_args: Any, **_kwargs: Any) -> NoReturn:
        pytest.fail("Unsafe database reached session creation, init, or cleanup")

    monkeypatch.setattr(integration_fixtures.settings, "POSTGRES_DB", name)
    monkeypatch.setattr(integration_fixtures, "Session", fail_on_database_access)
    monkeypatch.setattr(integration_fixtures, "init_db", fail_on_database_access)
    monkeypatch.setattr(integration_fixtures, "delete", fail_on_database_access)

    fixture = integration_fixtures.db.__wrapped__(None)
    with pytest.raises(RuntimeError):
        next(fixture)
