import pytest
from sqlalchemy.engine import Engine


@pytest.fixture(scope="session", autouse=True)
def db() -> None:
    """Password compatibility tests never use the inherited integration database."""


@pytest.fixture(autouse=True)
def forbid_database_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Pure password tests must not connect to a database")

    monkeypatch.setattr(Engine, "connect", forbidden_connect)
