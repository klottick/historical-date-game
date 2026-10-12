import pytest


@pytest.fixture(scope="session", autouse=True)
def db() -> None:
    """Bypass the destructive integration fixture for database safety tests."""
