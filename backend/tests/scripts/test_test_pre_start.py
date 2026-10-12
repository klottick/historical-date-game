from sqlalchemy import create_engine, event

from app.tests_pre_start import init


def test_init_successful_connection() -> None:
    engine = create_engine("sqlite://")
    statements: list[str] = []
    event.listen(
        engine,
        "before_cursor_execute",
        lambda connection, cursor, statement, parameters, context, executemany: (
            statements.append(statement)
        ),
    )

    try:
        init(engine)
        assert statements == ["SELECT 1"]
    finally:
        engine.dispose()
