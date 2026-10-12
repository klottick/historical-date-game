def require_test_database(name: str) -> None:
    """Refuse integration fixture initialization and cleanup on non-test DBs."""
    if not name.endswith("_test"):
        raise RuntimeError("Database tests require a database name ending in '_test'")
