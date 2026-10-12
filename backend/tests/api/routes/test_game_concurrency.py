"""Independent sessions compete before locks; no barriers inside transactions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event
from sqlmodel import Session, select, text

from app.core.db import engine
from app.game.models import GameOperation, GameRun
from app.models import User
from tests.api.routes.test_game_runs import (
    correct_command,
    game_context,
    start,
    start_command,
)

__all__ = ["game_context"]


def race(owner_id: UUID, calls: list[Any]) -> list[Any]:
    assert engine.dialect.name == "postgresql"
    gate = Barrier(2)
    backend_pids: list[int] = []
    commits: list[None] = []

    def request(call: Any) -> Any:
        from app.game.run_service import GameServiceError

        with Session(engine) as session:
            event.listen(session, "after_commit", lambda _session: commits.append(None))
            # Model the CurrentUser dependency's existing autobegun transaction.
            session.execute(text("SET LOCAL statement_timeout = '10s'"))
            session.get(User, owner_id)
            backend_pids.append(
                session.execute(text("SELECT pg_backend_pid()")).scalar_one()
            )
            gate.wait(timeout=10)
            try:
                return call(session)
            except GameServiceError as exc:
                return exc

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(request, call) for call in calls]
        results = [future.result(timeout=20) for future in futures]
    assert len(set(backend_pids)) == 2
    assert len(commits) == 1
    return results


@pytest.mark.parametrize("duplicate", [True, False])
def test_two_tabs_score_only_once(
    db: Session, game_context: tuple[UUID, str], duplicate: bool
) -> None:
    from app.game.run_service import GameServiceError, read_run, submit_placement

    owner_id, _ = game_context
    initial = start(db, game_context)
    first = correct_command(db, initial)
    second = first if duplicate else first.model_copy(update={"operation_id": uuid4()})
    db.commit()
    outcomes = race(
        owner_id,
        [
            lambda s: submit_placement(s, owner_id, initial.run_id, first),
            lambda s: submit_placement(s, owner_id, initial.run_id, second),
        ],
    )
    successes = [r for r in outcomes if not isinstance(r, GameServiceError)]
    if duplicate:
        assert (
            len(successes) == 2
            and successes[0].model_dump() == successes[1].model_dump()
        )
    else:
        assert len(successes) == 1
        assert [r.status_code for r in outcomes if isinstance(r, GameServiceError)] == [
            409
        ]
    with Session(engine) as observer:
        persisted = read_run(observer, owner_id, initial.run_id)
        assert persisted.revision == 1 and persisted.streak == 1
        assert (
            len(
                observer.exec(
                    select(GameOperation).where(
                        GameOperation.run_id == initial.run_id,
                        GameOperation.scope == "placement",
                    )
                ).all()
            )
            == 1
        )


def test_duplicate_starts_allocate_one_run(
    db: Session, game_context: tuple[UUID, str]
) -> None:
    from app.game.run_service import start_freeplay

    owner_id, release_id = game_context
    command = start_command(release_id)
    db.commit()
    outcomes = race(
        owner_id,
        [
            lambda s: start_freeplay(s, owner_id, command),
            lambda s: start_freeplay(s, owner_id, command),
        ],
    )
    assert outcomes[0].model_dump() == outcomes[1].model_dump()
    with Session(engine) as observer:
        assert (
            len(
                observer.exec(select(GameRun).where(GameRun.owner_id == owner_id)).all()
            )
            == 1
        )
        assert (
            len(
                observer.exec(
                    select(GameOperation).where(GameOperation.owner_id == owner_id)
                ).all()
            )
            == 1
        )


def test_cross_run_operation_race_is_conflict_not_partial_score(
    db: Session, game_context: tuple[UUID, str]
) -> None:
    from app.game.run_service import GameServiceError, read_run, submit_placement

    owner_id, _ = game_context
    first, second = start(db, game_context), start(db, game_context)
    operation_id = uuid4()
    move1 = correct_command(db, first, operation_id=operation_id)
    move2 = correct_command(db, second, operation_id=operation_id)
    db.commit()
    outcomes = race(
        owner_id,
        [
            lambda s: submit_placement(s, owner_id, first.run_id, move1),
            lambda s: submit_placement(s, owner_id, second.run_id, move2),
        ],
    )
    assert sum(not isinstance(r, GameServiceError) for r in outcomes) == 1
    assert [r.status_code for r in outcomes if isinstance(r, GameServiceError)] == [409]
    with Session(engine) as observer:
        saved = [read_run(observer, owner_id, r.run_id) for r in (first, second)]
        assert sorted(r.streak for r in saved) == [0, 1]
        assert sorted(r.revision for r in saved) == [0, 1]
        assert (
            len(
                observer.exec(
                    select(GameOperation).where(
                        GameOperation.owner_id == owner_id,
                        GameOperation.scope == "placement",
                    )
                ).all()
            )
            == 1
        )


@pytest.mark.parametrize("round_number", range(6))
def test_cross_scope_start_and_placement_race(
    db: Session, game_context: tuple[UUID, str], round_number: int
) -> None:
    from app.game.run_service import (
        GameServiceError,
        read_run,
        start_freeplay,
        submit_placement,
    )

    owner_id, release_id = game_context
    initial = start(db, game_context)
    command = start_command(release_id)
    move = correct_command(db, initial, operation_id=command.operation_id)
    db.commit()
    outcomes = race(
        owner_id,
        [
            lambda s: start_freeplay(s, owner_id, command),
            lambda s: submit_placement(s, owner_id, initial.run_id, move),
        ],
    )
    assert sum(not isinstance(r, GameServiceError) for r in outcomes) == 1, round_number
    assert [r.status_code for r in outcomes if isinstance(r, GameServiceError)] == [409]
    with Session(engine) as observer:
        winner = next(r for r in outcomes if not isinstance(r, GameServiceError))
        saved = read_run(observer, owner_id, initial.run_id)
        assert saved.revision == (1 if winner.run_id == initial.run_id else 0)
        assert saved.streak == saved.revision
        assert (
            len(
                observer.exec(
                    select(GameOperation).where(GameOperation.owner_id == owner_id)
                ).all()
            )
            == 2
        )


@pytest.mark.parametrize("kind", ["placement", "start"])
def test_failure_before_commit_rolls_back_everything(
    db: Session, game_context: tuple[UUID, str], kind: str
) -> None:
    from app.game.run_service import read_run, start_freeplay, submit_placement

    owner_id, release_id = game_context
    initial = start(db, game_context)
    move = correct_command(db, initial)
    command = start_command(release_id)
    db.commit()

    def fail(session: Session) -> None:
        session.flush()  # Ensure real writes reach PostgreSQL before the failure.
        raise RuntimeError("injected before commit")

    with Session(engine) as writer:
        event.listen(writer, "before_commit", fail)
        with pytest.raises(RuntimeError, match="injected"):
            if kind == "placement":
                submit_placement(writer, owner_id, initial.run_id, move)
            else:
                start_freeplay(writer, owner_id, command)
        event.remove(writer, "before_commit", fail)
        assert not writer.in_transaction()
    with Session(engine) as observer:
        assert read_run(observer, owner_id, initial.run_id) == initial
        assert (
            len(
                observer.exec(select(GameRun).where(GameRun.owner_id == owner_id)).all()
            )
            == 1
        )
        assert (
            len(
                observer.exec(
                    select(GameOperation).where(GameOperation.owner_id == owner_id)
                ).all()
            )
            == 1
        )
        recovered = submit_placement(observer, owner_id, initial.run_id, move)
        assert recovered.streak == 1 and recovered.revision == 1
