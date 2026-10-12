import pytest


@pytest.fixture(scope="session", autouse=True)
def db() -> None:
    """Game rules are pure: never run the inherited destructive DB fixture."""
