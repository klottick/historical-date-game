"""Safety gates run without the destructive integration fixture."""

import pytest


@pytest.mark.parametrize(
    "database,host,environment",
    [
        ("historical_date_game_test", "127.0.0.1", "local"),
        ("historical_date_game_guest_test_extra", "127.0.0.1", "local"),
        ("historical_date_game_guest_test", "remote.example", "local"),
        ("historical_date_game_guest_test", "127.0.0.1", "production"),
        ("historical_date_game_guest_test", "127.0.0.1", "staging"),
    ],
)
def test_rejects_nonowned_target_names_and_nonlocal_hosts(
    database: str, host: str, environment: str
) -> None:
    from tests.browser.guest_test_environment import require_guest_test_target

    with pytest.raises(RuntimeError):
        require_guest_test_target(database, host, environment)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
@pytest.mark.parametrize(
    "database",
    [
        "historical_date_game_guest_test",
        "historical_date_game_guest_migration_test",
        "historical_date_game_guest_fixture_test",
    ],
)
def test_accepts_only_named_local_verification_targets(
    database: str, host: str
) -> None:
    from tests.browser.guest_test_environment import require_guest_test_target

    require_guest_test_target(database, host, "local")


@pytest.mark.parametrize(
    "comment,owner",
    [(None, "postgres"), ("unrelated", "postgres"), ("correct", "other")],
)
def test_requires_exact_ownership_comment_and_database_owner(
    comment: str | None, owner: str
) -> None:
    from app.core.config import settings
    from tests.browser.guest_test_environment import (
        ownership_comment,
        require_ownership,
    )

    database = "historical_date_game_guest_test"
    if comment == "correct":
        comment = ownership_comment(database)
    with pytest.raises(RuntimeError):
        require_ownership(database, comment, owner)
    require_ownership(database, ownership_comment(database), settings.POSTGRES_USER)


def test_prepare_refuses_unsafe_target_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.browser import guest_test_environment as env

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("database connection attempted before target validation")

    monkeypatch.setattr(env.psycopg, "connect", forbidden)
    with pytest.raises(RuntimeError):
        env.prepare_database("historical_date_game_test")


def test_migration_proof_refuses_wrong_database_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.browser import guest_test_environment as env

    monkeypatch.setattr(env.settings, "POSTGRES_DB", "historical_date_game_guest_test")

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("migration proof crossed database/subprocess boundary")

    monkeypatch.setattr(env.psycopg, "connect", forbidden)
    monkeypatch.setattr(env.subprocess, "run", forbidden)
    with pytest.raises(RuntimeError):
        env.migration_proof()


def test_integration_fixture_rejects_live_target_before_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from tests import conftest

    monkeypatch.setattr(settings, "POSTGRES_DB", "historical_date_game_fixture_test")

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("destructive fixture opened a session on an unowned database")

    monkeypatch.setattr(conftest, "Session", forbidden)
    fixture = conftest.db.__wrapped__()
    with pytest.raises(RuntimeError):
        next(fixture)
