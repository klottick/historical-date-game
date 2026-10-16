"""B3 service boundaries against real PostgreSQL and verified synthetic releases."""

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlmodel import Session, select

from app.content.adapters.selected import SelectedSourceAdapter
from app.content.importer import import_snapshot
from app.content.media import pipeline
from app.content.publish import publish_release
from app.core.db import engine
from app.game.catalog_repository import activate_catalog, load_events
from app.game.models import GameOperation, GameRun
from app.game.schemas import FreeplayStart, RunPublic
from app.models import User
from tests.content.test_importer import snapshot
from tests.content.test_media import SELECTION, fake_download, with_image


@pytest.fixture
def game_context(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[UUID, str]]:
    # Four independently sourced fixture answers permit lost-response retries
    # after later moves. All snapshots pass the existing C5 publication gate.
    workspace, _ = with_image(tmp_path)
    second = tmp_path / "second"
    second.mkdir()
    raw = Path("tests/fixtures/content/source-snapshot.json").read_text()
    raw = raw.replace("900001", "900002").replace(
        "Synthetic Ada", "Borealis Cartographer Meridian"
    )
    raw = raw.replace("1800", "1810").replace("1870", "1880")
    data = json.loads(raw)
    for record in data["records"]:
        record["record_id"] += "-second"
    import_snapshot(SelectedSourceAdapter(), snapshot(second, data), workspace)
    monkeypatch.setattr(pipeline, "download_image", fake_download)
    pointer = json.loads((workspace / "current.json").read_text())
    for line in (
        (workspace / pointer["generation"] / "candidates.jsonl")
        .read_text()
        .splitlines()
    ):
        pipeline.assign_media(
            pipeline.EventRecord.model_validate_json(line), SELECTION, workspace
        )
    assert all(r.passed for r in pipeline.finalize_media_receipts(workspace))
    release_id = "b3-" + uuid4().hex
    publish_release(workspace, tmp_path / "releases", release_id, fixture=True)
    root = tmp_path / "releases" / release_id
    activate_catalog(db, root, root / "media", require_beta=False)
    owner = User(email=uuid4().hex + "@example.com", hashed_password="unused")
    db.add(owner)
    db.commit()
    owner_id = owner.id
    assert len(load_events(db, release_id)) == 4
    db.commit()
    yield owner_id, release_id
    db.rollback()
    db.delete(db.get(User, owner_id))
    db.commit()


def start_command(release_id: str, **changes: Any) -> Any:
    from app.game.schemas import FreeplayStart

    data = {
        "protocol_version": 2,
        "operation_id": str(uuid4()),
        "catalog_release_id": release_id,
        "config": {
            "category_ids": ["births", "deaths"],
            "start": {"value": 1, "era": "BCE"},
            "end": {"value": 2026, "era": "CE"},
            "min_gap": 1,
        },
    }
    data.update(changes)
    return FreeplayStart.model_validate_json(json.dumps(data))


def correct_command(session: Session, response: Any, **changes: Any) -> Any:
    from app.game.schemas import PlaceCommand

    events = load_events(session, response.catalog_release_id)
    year = events[response.pending.event_id].year_index
    slot = sum(events[card.event_id].year_index < year for card in response.timeline)
    data = {
        "protocol_version": 2,
        "operation_id": uuid4(),
        "expected_revision": response.revision,
        "event_id": response.pending.event_id,
        "slot": slot,
    }
    data.update(changes)
    return PlaceCommand(**data)


def start(session: Session, context: tuple[UUID, str]) -> Any:
    from app.game.run_service import start_freeplay

    return start_freeplay(session, context[0], start_command(context[1]))


def test_owner_and_pending_answer_boundaries(
    db: Session, game_context: tuple[UUID, str]
) -> None:
    from app.game.run_service import (
        GameServiceError,
        list_active_runs,
        read_run,
        submit_placement,
    )

    response = start(db, game_context)
    assert set(response.model_dump()) == {
        "initial_lives",
        "lives_remaining",
        "score",
        "run_id",
        "mode",
        "daily_date",
        "catalog_release_id",
        "config",
        "categories",
        "status",
        "streak",
        "revision",
        "timeline",
        "pending",
        "feedback",
    }
    assert set(response.pending.model_dump()) == {
        "event_id",
        "prompt",
        "category_ids",
        "media",
    }
    assert set(response.pending.media.model_dump()) == {
        "url",
        "fallback_url",
        "alt_text",
        "fit",
        "credits",
    }
    assert response.pending.media.credits
    assert response.pending.media.fallback_url.endswith(".svg")
    text = response.model_dump_json()
    for private in (
        '"seed"',
        '"order"',
        '"pool"',
        '"year_index"',
        '"identity_key"',
        '"owner_id"',
        '"raw_date"',
    ):
        assert private not in text
    assert [r.run_id for r in list_active_runs(db, game_context[0])] == [
        response.run_id
    ]
    assert list_active_runs(db, uuid4()) == []
    for run_id in (response.run_id, uuid4()):
        with pytest.raises(GameServiceError) as error:
            read_run(db, uuid4(), run_id)
        assert error.value.status_code == 404 and error.value.code == "run_not_found"
    with pytest.raises(GameServiceError) as error:
        submit_placement(db, uuid4(), response.run_id, correct_command(db, response))
    assert error.value.status_code == 404
    assert read_run(db, game_context[0], response.run_id) == response


def test_invalid_settings_and_terminal_commands_do_not_lose(
    db: Session, game_context: tuple[UUID, str]
) -> None:
    from app.game.run_service import (
        GameServiceError,
        read_run,
        start_freeplay,
        submit_placement,
    )

    owner_id, release_id = game_context
    config = start_command(release_id).config.model_dump(mode="json")
    for bad in (
        {**config, "category_ids": ["missing"]},
        {**config, "category_ids": []},
        {**config, "min_gap": 10000},
        {**config, "start": {"value": 3000, "era": "CE"}},
    ):
        try:
            command = start_command(release_id, config=bad)
        except ValidationError:
            continue
        with pytest.raises(GameServiceError):
            start_freeplay(db, owner_id, command)
    assert not db.exec(select(GameRun).where(GameRun.owner_id == owner_id)).all()
    assert not db.exec(
        select(GameOperation).where(GameOperation.owner_id == owner_id)
    ).all()
    response = start(db, game_context)
    for changes, status in (
        ({"slot": -1}, 422),
        ({"slot": 20}, 422),
        ({"event_id": uuid4()}, 409),
        ({"expected_revision": 1}, 409),
    ):
        with pytest.raises(GameServiceError) as error:
            submit_placement(
                db, owner_id, response.run_id, correct_command(db, response, **changes)
            )
        assert error.value.status_code == status
        assert read_run(db, owner_id, response.run_id) == response
    correct = correct_command(db, response)
    wrong = correct.model_copy(update={"slot": 1 - correct.slot})
    lost = submit_placement(db, owner_id, response.run_id, wrong)
    assert lost.status == "active" and lost.pending is not None
    assert (
        len(lost.timeline) == len(response.timeline) + 1
        and lost.feedback.card in lost.timeline
        and lost.streak == 0
        and lost.revision == 1
        and lost.lives_remaining == 2
        and lost.score == 0
    )
    assert (
        not lost.feedback.correct
        and lost.feedback.card.event_id == response.pending.event_id
    )
    assert lost.feedback.correct_slot == correct.slot
    with pytest.raises(GameServiceError) as error:
        submit_placement(
            db,
            owner_id,
            response.run_id,
            correct.model_copy(update={"expected_revision": 1}),
        )
    assert error.value.status_code == 409
    assert read_run(db, owner_id, response.run_id) == lost


def test_timeout_retry_returns_recorded_outcome(
    db: Session, game_context: tuple[UUID, str]
) -> None:
    from app.game.run_service import (
        list_active_runs,
        read_run,
        start_freeplay,
        submit_placement,
    )

    owner_id, release_id = game_context
    command = start_command(release_id)
    initial = start_freeplay(db, owner_id, command)
    move = correct_command(db, initial)
    first = submit_placement(db, owner_id, initial.run_id, move)
    assert first.streak == 1 and first.revision == 1 and first.feedback.correct
    later = submit_placement(db, owner_id, first.run_id, correct_command(db, first))
    with Session(engine) as reconnect:
        resumed = read_run(reconnect, owner_id, first.run_id)
        assert resumed == later and resumed.feedback == later.feedback
        assert (
            submit_placement(reconnect, owner_id, first.run_id, move).model_dump()
            == first.model_dump()
        )
        assert (
            start_freeplay(reconnect, owner_id, command).model_dump()
            == initial.model_dump()
        )
        final = submit_placement(
            reconnect, owner_id, later.run_id, correct_command(reconnect, later)
        )
        assert final.status == "won" and final.streak == 3 and final.revision == 3
        assert final.pending is None and len(final.timeline) == 4
        assert list_active_runs(reconnect, owner_id) == []
        assert submit_placement(reconnect, owner_id, first.run_id, move) == first
        assert read_run(reconnect, owner_id, first.run_id) == final


def test_reused_operation_payload_conflicts(
    db: Session, game_context: tuple[UUID, str]
) -> None:
    from app.game.run_service import (
        GameServiceError,
        read_run,
        start_freeplay,
        submit_placement,
    )

    owner_id, release_id = game_context
    command = start_command(release_id)
    initial = start_freeplay(db, owner_id, command)
    reordered = command.model_copy(
        update={
            "config": command.config.model_copy(
                update={"category_ids": ["deaths", "births"]}
            )
        }
    )
    assert start_freeplay(db, owner_id, reordered) == initial
    altered = command.model_copy(
        update={"config": command.config.model_copy(update={"min_gap": 2})}
    )
    with pytest.raises(GameServiceError) as error:
        start_freeplay(db, owner_id, altered)
    assert error.value.status_code == 409
    move = correct_command(db, initial)
    first = submit_placement(db, owner_id, initial.run_id, move)
    for changes in (
        {"slot": 1 - move.slot},
        {"expected_revision": 1},
        {"event_id": uuid4()},
        {"operation_id": command.operation_id},
    ):
        with pytest.raises(GameServiceError) as error:
            submit_placement(
                db, owner_id, initial.run_id, move.model_copy(update=changes)
            )
        assert error.value.status_code == 409
    second = start(db, game_context)
    assert db.get(GameRun, initial.run_id).seed != db.get(GameRun, second.run_id).seed
    with pytest.raises(GameServiceError) as error:
        submit_placement(db, owner_id, second.run_id, move)
    assert error.value.status_code == 409
    assert read_run(db, owner_id, initial.run_id) == first
    assert read_run(db, owner_id, second.run_id) == second


@pytest.mark.parametrize(
    "field,value",
    [
        ("slot", True),
        ("slot", "0"),
        ("slot", 0.0),
        ("expected_revision", False),
        ("expected_revision", "0"),
        ("event_id", "bad"),
        ("operation_id", 1),
        ("unknown", 1),
    ],
)
def test_strict_placement_contract(field: str, value: Any) -> None:
    from app.game.schemas import PlaceCommand

    data = {
        "operation_id": str(uuid4()),
        "event_id": str(uuid4()),
        "expected_revision": 0,
        "slot": 0,
    }
    data[field] = value
    with pytest.raises(ValidationError):
        PlaceCommand.model_validate_json(json.dumps(data))


@pytest.mark.parametrize(
    "changes",
    [
        {"min_gap": True},
        {"min_gap": "1"},
        {"min_gap": 0},
        {"category_ids": "births"},
        {"category_ids": [1]},
        {"start": {"value": True, "era": "CE"}},
        {"start": {"value": 0, "era": "CE"}},
        {"end": {"value": 2026, "era": "CE", "extra": 1}},
        {"unknown": 1},
    ],
)
def test_strict_config_contract(changes: dict[str, Any]) -> None:
    from app.game.schemas import GameConfig

    data = {
        "category_ids": ["births"],
        "start": {"value": 1, "era": "BCE"},
        "end": {"value": 2026, "era": "CE"},
        "min_gap": 1,
    }
    with pytest.raises(ValidationError):
        GameConfig.model_validate_json(json.dumps({**data, **changes}))


def test_daily_start_and_public_contracts_forbid_extra_fields(
    db: Session, game_context: tuple[UUID, str]
) -> None:
    from app.game.schemas import DailyStart, RunPublic

    for field in ("seed", "config", "day"):
        with pytest.raises(ValidationError):
            DailyStart.model_validate_json(
                json.dumps({"operation_id": str(uuid4()), field: 1})
            )
    response = start(db, game_context)
    data = response.model_dump(mode="json")
    with pytest.raises(ValidationError):
        RunPublic.model_validate_json(json.dumps({**data, "seed": "hidden"}))
    data["pending"]["year"] = {"value": 1800, "era": "CE"}
    with pytest.raises(ValidationError):
        RunPublic.model_validate_json(json.dumps(data))


def test_catalog_errors_are_atomic(db: Session, game_context: tuple[UUID, str]) -> None:
    from app.game.run_service import GameServiceError, start_freeplay

    with pytest.raises(GameServiceError) as error:
        start_freeplay(db, game_context[0], start_command("unknown"))
    assert error.value.status_code == 409
    assert not db.exec(select(GameRun).where(GameRun.owner_id == game_context[0])).all()
    assert not db.exec(
        select(GameOperation).where(GameOperation.owner_id == game_context[0])
    ).all()


def test_media_credits_and_resume_use_frozen_release(
    db: Session, game_context: tuple[UUID, str], tmp_path: Path
) -> None:
    from app.game.run_repository import load_media
    from app.game.run_service import read_run, start_freeplay
    from tests.content.test_publish import final_batch

    owner_id, release_id = game_context
    command = start_command(release_id)
    response = start_freeplay(db, owner_id, command)
    events = load_events(db, release_id)
    assets = load_media(db, release_id)
    # Every card's credits/URLs can be checked without relying on random order.
    from app.game.projections import project_media

    for event in events.values():
        projected = project_media(event, assets, "/media/" + release_id)
        fallback = assets["fallback:" + event.fallback_key]
        assert projected.fallback_url == f"/media/{release_id}/{fallback.sha256}.svg"
        assert (
            projected.credits[-1].label
            == f"{fallback.creator} / {fallback.rights_basis}"
        )
        if event.media_asset_id:
            asset = assets["asset:" + str(event.media_asset_id)]
            assert projected.url == f"/media/{release_id}/{asset.sha256}.webp"
            assert projected.credits[0].label == asset.attribution
            assert projected.credits[0].url == asset.source_url
            assert projected.credits[1].url == asset.license_url
    # A new, verified fallback-only release has different actual media snapshots.
    other = tmp_path / "other"
    other.mkdir()
    workspace, _ = final_batch(other)
    next_id = "b3-" + uuid4().hex
    publish_release(workspace, other / "releases", next_id, fixture=True)
    root = other / "releases" / next_id
    activate_catalog(db, root, root / "media", require_beta=False)
    db.commit()
    assert load_media(db, next_id) != assets
    assert read_run(db, owner_id, response.run_id) == response
    assert start_freeplay(db, owner_id, command) == response
    assert (
        start_freeplay(db, owner_id, start_command(next_id)).catalog_release_id
        == next_id
    )


@pytest.mark.parametrize(
    "unsafe",
    [
        "javascript:alert(1)",
        "//evil.example/x",
        "https://user:pass@example.com/x",
        "https://example.com/\nasset",
        "https://example.com\\asset",
        "https://[invalid]/asset",
        "https://example.com:invalid/asset",
        "https://example.com:99999/asset",
    ],
)
def test_projection_rejects_unsafe_credit_and_source_urls(unsafe: str) -> None:
    from app.game.catalog_repository import CatalogError
    from app.game.projections import safe_url

    with pytest.raises(CatalogError, match="catalog_unavailable"):
        safe_url(unsafe)


def test_unavailable_catalog_rolls_back_start(
    db: Session, game_context: tuple[UUID, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.game import run_service
    from app.game.catalog_repository import CatalogError

    def unavailable(_session: Session, _release_id: str) -> Any:
        raise CatalogError("catalog_unavailable")

    monkeypatch.setattr(run_service, "load_events", unavailable)
    with pytest.raises(run_service.GameServiceError) as error:
        run_service.start_freeplay(db, game_context[0], start_command(game_context[1]))
    assert error.value.code == "catalog_unavailable" and error.value.status_code == 503
    assert not db.exec(select(GameRun).where(GameRun.owner_id == game_context[0])).all()
    assert not db.exec(
        select(GameOperation).where(GameOperation.owner_id == game_context[0])
    ).all()


def test_constructed_or_mutated_commands_are_revalidated(
    db: Session, game_context: tuple[UUID, str]
) -> None:
    from app.game.run_service import (
        GameServiceError,
        read_run,
        start_freeplay,
        submit_placement,
    )

    command = start_command(game_context[1])
    for changes in (
        {"config": {}},
        {"operation_id": True},
        {"config": command.config.model_copy(update={"min_gap": True})},
    ):
        with pytest.raises(GameServiceError) as error:
            start_freeplay(db, game_context[0], command.model_copy(update=changes))
        assert error.value.status_code == 422
    assert not db.exec(select(GameRun).where(GameRun.owner_id == game_context[0])).all()
    response = start(db, game_context)
    move = correct_command(db, response)
    for changes in (
        {"slot": True},
        {"expected_revision": "0"},
        {"event_id": "not-a-uuid"},
    ):
        with pytest.raises(GameServiceError) as error:
            submit_placement(
                db, game_context[0], response.run_id, move.model_copy(update=changes)
            )
        assert error.value.status_code == 422
        assert read_run(db, game_context[0], response.run_id) == response


def test_owner_registry_isolation(db: Session, game_context: tuple[UUID, str]) -> None:
    from app.game.run_service import (
        GameServiceError,
        read_run,
        start_freeplay,
        submit_placement,
    )

    foreign = User(email=uuid4().hex + "@example.com", hashed_password="unused")
    db.add(foreign)
    db.commit()
    foreign_id = foreign.id
    command = start_command(game_context[1])
    owned = start_freeplay(db, game_context[0], command)
    other = start_freeplay(db, foreign_id, command)
    assert owned.run_id != other.run_id
    move = correct_command(db, owned, operation_id=command.operation_id)
    with pytest.raises(GameServiceError) as error:
        submit_placement(db, foreign_id, owned.run_id, move)
    assert error.value.code == "run_not_found" and error.value.status_code == 404
    assert read_run(db, game_context[0], owned.run_id) == owned
    db.delete(db.get(User, foreign_id))
    db.commit()


def test_resume_does_not_mix_old_state_with_newer_feedback(
    db: Session, game_context: tuple[UUID, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.game import run_service

    initial = start(db, game_context)
    first = run_service.submit_placement(
        db, game_context[0], initial.run_id, correct_command(db, initial)
    )
    move = correct_command(db, first)
    project = run_service._project

    def interleaved(session: Session, run: GameRun) -> Any:
        # Commit after read_run selects state, but before it selects feedback.
        if session is db:
            with Session(engine) as writer:
                run_service.submit_placement(
                    writer, game_context[0], first.run_id, move
                )
        return project(session, run)

    monkeypatch.setattr(run_service, "_project", interleaved)
    assert run_service.read_run(db, game_context[0], first.run_id) == first


def test_win_does_not_reveal_ineligible_unused_pool(
    db: Session, game_context: tuple[UUID, str]
) -> None:
    from app.game.run_service import start_freeplay, submit_placement

    config = start_command(game_context[1]).config.model_dump(mode="json")
    initial = start_freeplay(
        db,
        game_context[0],
        start_command(game_context[1], config={**config, "min_gap": 60}),
    )
    won = submit_placement(
        db, game_context[0], initial.run_id, correct_command(db, initial)
    )
    assert won.status == "won" and won.streak == 1 and won.revision == 1
    assert won.pending is None and len(won.timeline) == 2
    persisted = db.get(GameRun, initial.run_id)
    assert len(persisted.pool) == 4
    unused = set(persisted.pool) - {str(card.event_id) for card in won.timeline}
    assert len(unused) == 2
    assert all(event_id not in won.model_dump_json() for event_id in unused)


def test_three_misses_end_run_and_preserve_feedback_on_reconnect(
    db: Session, game_context: tuple[UUID, str]
) -> None:
    from app.game.run_service import read_run, submit_placement

    owner_id, _ = game_context
    initial = start(db, game_context)
    outcome = initial
    for _ in range(3):
        correct = correct_command(db, outcome)
        wrong = correct.model_copy(
            update={"slot": (correct.slot + 1) % (len(outcome.timeline) + 1)}
        )
        outcome = submit_placement(db, owner_id, initial.run_id, wrong)
    lost = outcome
    assert lost.status == "lost" and lost.pending is None
    assert (
        len(lost.timeline) == len(initial.timeline) + 2
        and lost.streak == 0
        and lost.revision == 3
        and lost.lives_remaining == 0
        and lost.score == 0
    )
    assert lost.feedback.card.event_id == correct.event_id
    assert lost.feedback.correct is False and lost.feedback.correct_slot == correct.slot
    with Session(engine) as reconnect:
        assert read_run(reconnect, owner_id, initial.run_id) == lost
        assert submit_placement(reconnect, owner_id, initial.run_id, wrong) == lost


@pytest.mark.parametrize(
    "era,value,accepted",
    [
        ("CE", 2**63 - 1, True),
        ("BCE", 2**63 + 1, True),
        ("CE", 2**63, False),
        ("BCE", 2**63 + 2, False),
        ("CE", 10**30, False),
        ("BCE", 10**30, False),
        ("CE", True, False),
        ("BCE", 1.0, False),
    ],
)
def test_year_storage_dto_bounds(era: str, value: Any, accepted: bool) -> None:
    from app.game.schemas import YearInput

    body = json.dumps({"era": era, "value": value})
    if accepted:
        assert YearInput.model_validate_json(body).value == value
    else:
        with pytest.raises(ValidationError):
            YearInput.model_validate_json(body)


@pytest.mark.parametrize(
    "field,era,value",
    [
        ("end", "CE", 10**30),
        ("end", "CE", 2**63),
        ("start", "BCE", 10**30),
        ("start", "BCE", 2**63 + 2),
    ],
)
def test_year_storage_service_rejection_is_atomic(
    db: Session, game_context: tuple[UUID, str], field: str, era: str, value: int
) -> None:
    from app.game.run_service import GameServiceError, start_freeplay

    command = start_command(game_context[1])
    # Exercise service revalidation independently of the wire validator.
    changed = getattr(command.config, field).model_copy(
        update={"era": era, "value": value}
    )
    invalid = command.model_copy(
        update={"config": command.config.model_copy(update={field: changed})}
    )
    with pytest.raises(GameServiceError) as error:
        start_freeplay(db, game_context[0], invalid)
    assert error.value.code == "invalid_command" and error.value.status_code == 422
    assert not db.in_transaction()
    assert not db.exec(select(GameRun).where(GameRun.owner_id == game_context[0])).all()
    assert not db.exec(
        select(GameOperation).where(GameOperation.owner_id == game_context[0])
    ).all()


def test_year_storage_extreme_bounds_accept_sparse_pool(
    db: Session, game_context: tuple[UUID, str]
) -> None:
    from app.game.run_service import read_run, start_freeplay, submit_placement

    config = start_command(game_context[1]).config.model_dump(mode="json")
    config.update(
        start={"value": 2**63 + 1, "era": "BCE"}, end={"value": 2**63 - 1, "era": "CE"}
    )
    initial = start_freeplay(
        db, game_context[0], start_command(game_context[1], config=config)
    )
    persisted = db.get(GameRun, initial.run_id)
    assert persisted.rules["start_year_index"] == -(2**63)
    assert persisted.rules["end_year_index"] == 2**63 - 1
    assert len(persisted.pool) == 4 and initial.status == "active"
    assert initial.config.model_dump(mode="json") == config
    with Session(engine) as reconnect:
        assert read_run(reconnect, game_context[0], initial.run_id) == initial
        scored = submit_placement(
            reconnect,
            game_context[0],
            initial.run_id,
            correct_command(reconnect, initial),
        )
        assert scored.streak == 1 and scored.revision == 1


@pytest.mark.parametrize(
    "field,era,value", [("end", "CE", 10**30), ("start", "BCE", 10**30)]
)
def test_year_storage_routed_dto_rejects_before_allocation(
    db: Session, game_context: tuple[UUID, str], field: str, era: str, value: int
) -> None:
    from app.game.run_service import start_freeplay

    # Test-only route verifies FastAPI's decoded-JSON boundary without adding B5
    # endpoints, dependencies, or generated OpenAPI to the production app.
    app = FastAPI()

    @app.post("/runs")
    def create_run(command: FreeplayStart) -> RunPublic:
        with Session(engine) as session:
            return start_freeplay(session, game_context[0], command)

    body = start_command(game_context[1]).model_dump(mode="json")
    body["config"][field] = {"era": era, "value": value}
    with TestClient(app) as client:
        response = client.post("/runs", json=body)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][:3] == ["body", "config", field]
    assert not db.exec(select(GameRun).where(GameRun.owner_id == game_context[0])).all()
    assert not db.exec(
        select(GameOperation).where(GameOperation.owner_id == game_context[0])
    ).all()


def test_other_huge_integer_commands_do_not_reach_unsafe_persistence(
    db: Session, game_context: tuple[UUID, str]
) -> None:
    from app.game.run_service import (
        GameServiceError,
        read_run,
        start_freeplay,
        submit_placement,
    )

    config = start_command(game_context[1]).config.model_dump(mode="json")
    # min_gap is JSONB without a bigint cast; no artificial 64-bit cap is needed.
    command = start_command(game_context[1], config={**config, "min_gap": 10**30})
    with pytest.raises(GameServiceError) as error:
        start_freeplay(db, game_context[0], command)
    assert error.value.code == "insufficient_pool" and error.value.status_code == 422
    assert not db.exec(select(GameRun).where(GameRun.owner_id == game_context[0])).all()
    assert not db.exec(
        select(GameOperation).where(GameOperation.owner_id == game_context[0])
    ).all()
    initial = start(db, game_context)
    for changes, code, status in (
        ({"slot": 10**30}, "invalid_slot", 422),
        ({"expected_revision": 10**30}, "stale_revision", 409),
    ):
        with pytest.raises(GameServiceError) as error:
            submit_placement(
                db,
                game_context[0],
                initial.run_id,
                correct_command(db, initial, **changes),
            )
        assert error.value.code == code and error.value.status_code == status
        assert read_run(db, game_context[0], initial.run_id) == initial
    assert (
        len(
            db.exec(
                select(GameOperation).where(GameOperation.owner_id == game_context[0])
            ).all()
        )
        == 1
    )
