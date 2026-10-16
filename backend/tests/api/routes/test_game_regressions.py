"""Focused Task 3 regressions for the versioned three-life service contract."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.db import engine
from app.game import daily_service, run_service
from app.game.catalog_repository import load_events
from app.game.models import GameOperation, GameRun
from app.game.schemas import DailyStart, RunPublic
from app.main import app
from app.models import User
from tests.api.routes import test_game_daily, test_game_runs
from tests.api.routes.test_game_runs import correct_command, start_command
from tests.api.routes.test_guest_game_api import BASE, bearer, bootstrap, counts

game_context = test_game_runs.game_context
daily_context = test_game_daily.daily_context


def _wrong_command(session: Session, run: RunPublic) -> Any:
    command = correct_command(session, run)
    return command.model_copy(
        update={"slot": (command.slot + 1) % (len(run.timeline) + 1)}
    )


def _protocol_body(body: dict[str, Any], value: object) -> dict[str, Any]:
    result = dict(body)
    if value is MISSING:
        result.pop("protocol_version", None)
    else:
        result["protocol_version"] = value
    return result


class _Missing:
    pass


MISSING = _Missing()
PROTOCOL_REJECTIONS = [
    pytest.param(1, id="old-integer"),
    pytest.param(MISSING, id="missing"),
    pytest.param(True, id="boolean"),
    pytest.param("2", id="string"),
]


@pytest.mark.parametrize("identity", ["account", "guest"])
@pytest.mark.parametrize("protocol", PROTOCOL_REJECTIONS)
def test_missing_or_old_protocol_cannot_mutate(
    db: Session,
    game_context: tuple[UUID, str],
    identity: str,
    protocol: object,
) -> None:
    owner_id, release_id = game_context
    with TestClient(app) as client:
        if identity == "account":
            client.headers.update(bearer(owner_id))
        else:
            bootstrap(client)

        run = client.post(
            f"{BASE}/freeplay",
            json=start_command(release_id).model_dump(mode="json"),
        )
        assert run.status_code == 200
        run_id = run.json()["run_id"]
        placement = correct_command(db, RunPublic.model_validate_json(run.text))

        requests = (
            (
                f"{BASE}/freeplay",
                _protocol_body(
                    start_command(release_id).model_dump(mode="json"), protocol
                ),
            ),
            (
                f"{BASE}/daily",
                _protocol_body(
                    {"protocol_version": 2, "operation_id": str(uuid4())},
                    protocol,
                ),
            ),
            (
                f"{BASE}/runs/{run_id}/placements",
                _protocol_body(placement.model_dump(mode="json"), protocol),
            ),
        )
        before = counts(db)
        for path, body in requests:
            response = client.post(path, json=body)
            assert response.status_code == 422, response.text
            assert counts(db) == before


def test_nonfinal_miss_is_atomic_and_reloadable(
    db: Session,
    game_context: tuple[UUID, str],
) -> None:
    owner_id, release_id = game_context
    initial = run_service.start_freeplay(db, owner_id, start_command(release_id))
    wrong = _wrong_command(db, initial)
    url = f"{BASE}/runs/{initial.run_id}"
    with TestClient(app) as client:
        client.headers.update(bearer(owner_id))
        response = client.post(f"{url}/placements", json=wrong.model_dump(mode="json"))
        assert response.status_code == 200
        body = response.json()
        assert (
            body["initial_lives"],
            body["lives_remaining"],
            body["score"],
            body["streak"],
            body["revision"],
        ) == (3, 2, 0, 0, 1)
        assert body["status"] == "active"
        assert "year" not in body["pending"]
        card_id = body["feedback"]["card"]["event_id"]
        assert sum(card["event_id"] == card_id for card in body["timeline"]) == 1
        assert body["feedback"]["attempted_slot"] == wrong.slot
        assert body["feedback"]["correct_slot"] != wrong.slot
        events = load_events(db, release_id)
        years = [events[UUID(card["event_id"])].year_index for card in body["timeline"]]
        assert years == sorted(years)
        reloaded = client.get(url)
        assert reloaded.status_code == 200
        assert reloaded.json()["feedback"] == body["feedback"]
        assert reloaded.json()["timeline"] == body["timeline"]

    persisted = db.get(GameRun, initial.run_id)
    assert persisted is not None
    assert (
        persisted.mistakes,
        persisted.correct_count,
        persisted.revision,
        persisted.streak,
        persisted.status,
    ) == (1, 0, 1, 0, "active")
    assert persisted.timeline == [card["event_id"] for card in body["timeline"]]
    operation = db.exec(
        select(GameOperation).where(
            GameOperation.owner_id == owner_id,
            GameOperation.operation_id == wrong.operation_id,
        )
    ).one()
    assert operation.outcome["feedback"] == body["feedback"]


def test_mixed_sequence_scores_correct_count(
    db: Session, game_context: tuple[UUID, str]
) -> None:
    owner_id, release_id = game_context
    run = run_service.start_freeplay(db, owner_id, start_command(release_id))
    run = run_service.submit_placement(
        db, owner_id, run.run_id, correct_command(db, run)
    )
    run = run_service.submit_placement(
        db, owner_id, run.run_id, _wrong_command(db, run)
    )
    run = run_service.submit_placement(
        db, owner_id, run.run_id, correct_command(db, run)
    )
    assert (run.score, run.streak, run.lives_remaining, run.revision) == (2, 1, 2, 3)


def test_three_misses_end_run(db: Session, game_context: tuple[UUID, str]) -> None:
    owner_id, release_id = game_context
    run = run_service.start_freeplay(db, owner_id, start_command(release_id))
    for _ in range(3):
        run = run_service.submit_placement(
            db, owner_id, run.run_id, _wrong_command(db, run)
        )
    assert (run.status, run.lives_remaining, run.score, run.revision) == (
        "lost",
        0,
        0,
        3,
    )
    assert run.feedback is not None
    assert all(card.event_id != run.feedback.card.event_id for card in run.timeline)


def test_correct_rejected_stale_and_foreign_commands_do_not_change_lives(
    db: Session, game_context: tuple[UUID, str]
) -> None:
    owner_id, release_id = game_context
    initial = run_service.start_freeplay(db, owner_id, start_command(release_id))
    missed = run_service.submit_placement(
        db, owner_id, initial.run_id, _wrong_command(db, initial)
    )
    scored = run_service.submit_placement(
        db, owner_id, missed.run_id, correct_command(db, missed)
    )
    assert (scored.lives_remaining, scored.score, scored.streak) == (2, 1, 1)
    operation_count = db.exec(
        select(func.count())
        .select_from(GameOperation)
        .where(GameOperation.run_id == initial.run_id)
    ).one()

    stale = correct_command(db, scored, expected_revision=1)
    with pytest.raises(run_service.GameServiceError) as error:
        run_service.submit_placement(db, owner_id, scored.run_id, stale)
    assert error.value.status_code == 409

    foreign = User(
        email="foreign-" + str(UUID(int=17)) + "@example.com", hashed_password="unused"
    )
    db.add(foreign)
    db.commit()
    with pytest.raises(run_service.GameServiceError) as error:
        run_service.submit_placement(
            db, foreign.id, scored.run_id, correct_command(db, scored)
        )
    assert error.value.status_code == 404
    reloaded = run_service.read_run(db, owner_id, scored.run_id)
    assert (reloaded.lives_remaining, reloaded.score, reloaded.revision) == (2, 1, 2)
    assert (
        db.exec(
            select(func.count())
            .select_from(GameOperation)
            .where(GameOperation.run_id == initial.run_id)
        ).one()
        == operation_count
    )


def test_duplicate_wrong_command_costs_one_life_and_replays_after_lost_response(
    db: Session, game_context: tuple[UUID, str]
) -> None:
    from tests.api.routes.test_game_concurrency import race

    owner_id, release_id = game_context
    initial = run_service.start_freeplay(db, owner_id, start_command(release_id))
    wrong = _wrong_command(db, initial)
    db.commit()
    outcomes = race(
        owner_id,
        [
            lambda session: run_service.submit_placement(
                session, owner_id, initial.run_id, wrong
            ),
            lambda session: run_service.submit_placement(
                session, owner_id, initial.run_id, wrong
            ),
        ],
    )
    assert outcomes[0] == outcomes[1]
    assert (outcomes[0].lives_remaining, outcomes[0].revision, outcomes[0].score) == (
        2,
        1,
        0,
    )
    with Session(engine) as reconnect:
        replay = run_service.submit_placement(
            reconnect, owner_id, initial.run_id, wrong
        )
        assert replay == outcomes[0]
        changed = wrong.model_copy(update={"slot": (wrong.slot + 1) % 2})
        with pytest.raises(run_service.GameServiceError) as error:
            run_service.submit_placement(reconnect, owner_id, initial.run_id, changed)
        assert error.value.status_code == 409
        stale = correct_command(reconnect, replay, expected_revision=0)
        with pytest.raises(run_service.GameServiceError) as error:
            run_service.submit_placement(reconnect, owner_id, initial.run_id, stale)
        assert error.value.status_code == 409
        stored = run_service.read_run(reconnect, owner_id, initial.run_id)
        assert (stored.lives_remaining, stored.revision, stored.score) == (2, 1, 0)
        assert (
            reconnect.exec(
                select(func.count())
                .select_from(GameOperation)
                .where(
                    GameOperation.run_id == initial.run_id,
                    GameOperation.scope == "placement",
                )
            ).one()
            == 1
        )


def _daily_win(session: Session, owner_id: UUID, now: Any) -> RunPublic:
    run = daily_service.start_daily(
        session, owner_id, DailyStart(protocol_version=2, operation_id=uuid4()), now
    )
    while run.status == "active":
        run = run_service.submit_placement(
            session, owner_id, run.run_id, correct_command(session, run)
        )
    return run


def _daily_four_points_then_miss(
    session: Session, owner_id: UUID, now: Any
) -> RunPublic:
    run = daily_service.start_daily(
        session, owner_id, DailyStart(protocol_version=2, operation_id=uuid4()), now
    )
    for _ in range(4):
        run = run_service.submit_placement(
            session, owner_id, run.run_id, correct_command(session, run)
        )
    run = run_service.submit_placement(
        session, owner_id, run.run_id, _wrong_command(session, run)
    )
    assert (run.status, run.score, run.streak, run.lives_remaining) == (
        "won",
        4,
        0,
        2,
    )
    return run


def test_daily_score_not_final_streak(
    db: Session, daily_context: tuple[list[UUID], str, Any]
) -> None:
    owners, _, now = daily_context
    high = _daily_four_points_then_miss(db, owners[0], now)
    tied = _daily_win(db, owners[1], now)
    lower = _daily_win(db, owners[2], now)

    # Build valid completed-score rows with differing final streaks. The
    # leaderboard query is the contract under test; DB invariants stay intact.
    high_row = db.get(GameRun, high.run_id)
    tied_row = db.get(GameRun, tied.run_id)
    lower_row = db.get(GameRun, lower.run_id)
    assert high_row is not None and tied_row is not None and lower_row is not None
    tied_row.correct_count, tied_row.mistakes, tied_row.streak, tied_row.revision = (
        4,
        0,
        4,
        4,
    )
    tied_row.timeline = tied_row.timeline[:5]
    (
        lower_row.correct_count,
        lower_row.mistakes,
        lower_row.streak,
        lower_row.revision,
    ) = (
        3,
        0,
        3,
        3,
    )
    lower_row.timeline = lower_row.timeline[:4]
    db.add_all([high_row, tied_row, lower_row])
    db.commit()

    board = daily_service.read_leaderboard(db, now.date())
    assert [entry.score for entry in board.entries] == [4, 4, 3]
    assert [entry.rank for entry in board.entries] == [1, 1, 3]
    assert {(entry.score, entry.streak) for entry in board.entries} == {
        (4, 0),
        (4, 4),
        (3, 3),
    }
