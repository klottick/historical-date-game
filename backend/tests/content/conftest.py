import pytest


@pytest.fixture(scope="session", autouse=True)
def db() -> None:
    """Content contracts are pure: never run the inherited destructive DB fixture."""
