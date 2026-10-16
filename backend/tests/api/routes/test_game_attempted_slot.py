"""Persist submitted positions in actual operation snapshots, including recovery."""

import json
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlmodel import Session, select

from app.core.db import engine
from app.game.models import GameOperation, GameRun
from app.game.run_service import read_run, submit_placement
from app.game.schemas import MoveFeedback, RunPublic
from tests.api.routes import test_game_runs
from tests.api.routes.test_game_api import BASE, headers
from tests.api.routes.test_game_runs import correct_command, start

game_context = test_game_runs.game_context


def test_wrong_placement_retains_attempted_slot_after_read_and_replay(
    client: TestClient, db: Session, game_context: tuple[UUID, str]
) -> None:
    owner, _ = game_context
    initial = start(db, game_context)
    confirmed = submit_placement(
        db, owner, initial.run_id, correct_command(db, initial)
    )
    correct = correct_command(db, confirmed)
    command = correct.model_copy(
        update={"slot": (correct.slot + 1) % (len(confirmed.timeline) + 1)}
    )
    url = BASE + f"/runs/{initial.run_id}"
    response = client.post(
        url + "/placements",
        headers=headers(owner),
        json=command.model_dump(mode="json"),
    )
    assert response.status_code == 200
    outcome = RunPublic.model_validate_json(response.text)
    assert outcome.feedback is not None
    assert outcome.feedback.attempted_slot == command.slot
    assert outcome.feedback.correct_slot != command.slot
    assert outcome.feedback.correct is False
    assert outcome.feedback.card.event_id == command.event_id
    assert len(outcome.timeline) == len(confirmed.timeline) + 1
    assert outcome.timeline[outcome.feedback.correct_slot] == outcome.feedback.card
    assert (outcome.status, outcome.revision, outcome.streak) == ("active", 2, 0)
    assert outcome.lives_remaining == 2 and outcome.score == 1

    owned_response = client.get(url, headers=headers(owner))
    assert owned_response.status_code == 200
    owned_get = RunPublic.model_validate_json(owned_response.text)
    assert owned_get.feedback == outcome.feedback
    replay_response = client.post(
        url + "/placements",
        headers=headers(owner),
        json=command.model_dump(mode="json"),
    )
    assert replay_response.status_code == 200
    exact_replay = RunPublic.model_validate_json(replay_response.text)
    assert exact_replay == outcome
    assert replay_response.content == response.content
    with Session(engine) as reconnect:
        assert read_run(reconnect, owner, initial.run_id) == outcome
        assert submit_placement(reconnect, owner, initial.run_id, command) == outcome
        stored = reconnect.get(GameRun, initial.run_id)
        assert stored is not None
        assert stored.timeline == [str(card.event_id) for card in outcome.timeline]
        assert (stored.revision, stored.streak) == (2, 0)
        operations = reconnect.exec(
            select(GameOperation).where(GameOperation.run_id == initial.run_id)
        ).all()
        assert len(operations) == 3  # Start and exactly two scored moves.
        loss = next(op for op in operations if op.operation_id == command.operation_id)
        assert loss.outcome["feedback"]["attempted_slot"] == command.slot


def test_correct_placement_retains_slot(
    db: Session, game_context: tuple[UUID, str]
) -> None:
    owner, _ = game_context
    initial = start(db, game_context)
    command = correct_command(db, initial)
    outcome = submit_placement(db, owner, initial.run_id, command)
    assert outcome.feedback is not None
    assert outcome.feedback.correct is True
    assert outcome.feedback.attempted_slot == command.slot
    assert outcome.feedback.correct_slot == command.slot
    assert outcome.timeline[command.slot] == outcome.feedback.card
    assert (outcome.revision, outcome.streak, len(outcome.timeline)) == (1, 1, 2)
    with Session(engine) as reconnect:
        assert read_run(reconnect, owner, initial.run_id) == outcome
        assert submit_placement(reconnect, owner, initial.run_id, command) == outcome
        # Later feedback must not replace the original move's replay snapshot.
        later = submit_placement(
            reconnect, owner, initial.run_id, correct_command(reconnect, outcome)
        )
        assert (later.revision, later.streak) == (2, 2)
        assert read_run(reconnect, owner, initial.run_id) == later
        assert submit_placement(reconnect, owner, initial.run_id, command) == outcome


def test_feedback_requires_attempted_slot(
    db: Session, game_context: tuple[UUID, str]
) -> None:
    initial = start(db, game_context)
    outcome = submit_placement(
        db, game_context[0], initial.run_id, correct_command(db, initial)
    )
    data = outcome.feedback.model_dump(mode="json")
    del data["attempted_slot"]
    with pytest.raises(ValidationError):
        MoveFeedback.model_validate_json(json.dumps(data))


def test_foreign_owner_cannot_read_loss(
    client: TestClient,
    db: Session,
    game_context: tuple[UUID, str],
    superuser_token_headers: dict[str, str],
) -> None:
    owner, _ = game_context
    initial = start(db, game_context)
    correct = correct_command(db, initial)
    command = correct.model_copy(update={"slot": 1 - correct.slot})
    outcome = submit_placement(db, owner, initial.run_id, command)
    url = BASE + f"/runs/{initial.run_id}"
    for response in (
        client.get(url, headers=superuser_token_headers),
        client.post(
            url + "/placements",
            headers=superuser_token_headers,
            json=command.model_dump(mode="json"),
        ),
    ):
        assert response.status_code == 404
        assert response.json()["detail"] == {
            "code": "run_not_found",
            "message": "Run not found",
        }
        assert "feedback" not in response.json()
    assert read_run(db, owner, initial.run_id) == outcome


@pytest.mark.parametrize("slot", [-1, True, "0", 0.0])
def test_feedback_rejects_invalid_attempted_slot(
    db: Session, game_context: tuple[UUID, str], slot: object
) -> None:
    initial = start(db, game_context)
    outcome = submit_placement(
        db, game_context[0], initial.run_id, correct_command(db, initial)
    )
    data = outcome.feedback.model_dump(mode="json")
    data["attempted_slot"] = slot
    with pytest.raises(ValidationError):
        MoveFeedback.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("slot", [0, 2])
def test_feedback_accepts_nonnegative_attempted_slot(
    db: Session, game_context: tuple[UUID, str], slot: int
) -> None:
    initial = start(db, game_context)
    outcome = submit_placement(
        db, game_context[0], initial.run_id, correct_command(db, initial)
    )
    data = outcome.feedback.model_dump(mode="json")
    data["attempted_slot"] = slot
    assert MoveFeedback.model_validate_json(json.dumps(data)).attempted_slot == slot
