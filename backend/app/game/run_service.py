"""Owned, transactional game commands with exact recorded public responses.

Request Sessions may already have autobegun during authentication. Mutations use
that transaction, commit once, and roll back all failures; they never nest begin.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.content.schemas import EventRecord
from app.game.catalog_repository import CatalogError, load_events, load_options
from app.game.event_links import event_link_for_run
from app.game.models import GameOperation, GameRun, utc_now
from app.game.ordering import generate_seed, seeded_order
from app.game.projections import (
    project_media,
    project_run,
    release_media_base,
    revealed_card,
)
from app.game.rules import filter_pool, place, start_run
from app.game.run_repository import (
    find_operation,
    load_categories,
    load_media,
    lock_operation,
    lock_owner,
    lock_run,
    read_owned_run,
)
from app.game.schemas import FreeplayStart, MoveFeedback, PlaceCommand, RunPublic
from app.game.types import EventKey, RuleError, RunRules, RunState
from app.game.years import to_year_index


class GameServiceError(ValueError):
    def __init__(self, code: str, status_code: int, message: str) -> None:
        self.code = code
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def _map_error(exc: Exception) -> GameServiceError:
    if isinstance(exc, CatalogError):
        if exc.code == "run_not_found":
            return GameServiceError("run_not_found", 404, "Run not found")
        return GameServiceError("catalog_unavailable", 503, "Game catalog unavailable")
    if isinstance(exc, RuleError):
        status = (
            409
            if exc.code in {"terminal_state", "stale_event", "stale_revision"}
            else 422
        )
        return GameServiceError(exc.code, status, "Game command rejected")
    if isinstance(exc, ValidationError):
        return GameServiceError("invalid_command", 422, "Invalid game command")
    if isinstance(exc, IntegrityError):
        return GameServiceError(
            "operation_conflict", 409, "Operation conflicts with a committed request"
        )
    raise exc


def _keys(events: Mapping[UUID, EventRecord]) -> dict[UUID, EventKey]:
    return {
        id_: EventKey(id_, event.year_index, frozenset(event.category_ids))
        for id_, event in events.items()
    }


def _digest(scope: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"scope": scope, "payload": payload}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def replay_operation(
    session: Session,
    owner_id: UUID,
    operation_id: UUID,
    scope: str,
    digest: str,
) -> RunPublic | None:
    operation = find_operation(session, owner_id, operation_id)
    if operation is None:
        return None
    if operation.scope != scope or operation.payload_digest != digest:
        raise GameServiceError(
            "operation_conflict",
            409,
            "Operation ID was already used for a different request",
        )
    return RunPublic.model_validate_json(json.dumps(operation.outcome))


def _record(
    session: Session,
    owner_id: UUID,
    operation_id: UUID,
    scope: str,
    digest: str,
    response: RunPublic,
) -> None:
    session.add(
        GameOperation(
            owner_id=owner_id,
            operation_id=operation_id,
            scope=scope,
            run_id=response.run_id,
            payload_digest=digest,
            outcome=response.model_dump(mode="json"),
        )
    )


def _project(session: Session, run: GameRun) -> RunPublic:
    return project_run(
        run,
        load_events(session, run.catalog_release_id),
        load_categories(session, run.catalog_release_id),
        release_media_base(run.catalog_release_id),
    )


def start_freeplay(
    session: Session, owner_id: UUID, command: FreeplayStart
) -> RunPublic:
    try:
        command = FreeplayStart.model_validate(command)
        digest = _digest(
            "freeplay", command.model_dump(mode="json", exclude={"operation_id"})
        )
        lock_operation(session, owner_id, command.operation_id)
        # Registry lock first: an owner FOR UPDATE lock also blocks the FK check
        # when a competing placement inserts its operation. Reversing this order
        # creates a start/placement deadlock for a reused operation UUID.
        lock_owner(session, owner_id)
        replay = replay_operation(
            session, owner_id, command.operation_id, "freeplay", digest
        )
        if replay is not None:
            # Replay is read-only: release transaction locks without a second
            # commit (or firing commit hooks) for the same operation.
            session.rollback()
            return replay
        options = load_options(session)
        if options.release_id != command.catalog_release_id:
            raise GameServiceError(
                "catalog_release_conflict", 409, "Refresh game options before starting"
            )
        events = load_events(session, command.catalog_release_id)
        categories = load_categories(session, command.catalog_release_id)
        rules = RunRules(
            frozenset(command.config.category_ids),
            to_year_index(command.config.start.value, command.config.start.era),
            to_year_index(command.config.end.value, command.config.end.era),
            command.config.min_gap,
        )
        keys = _keys(events)
        pool = filter_pool(
            tuple(keys.values()), rules, frozenset(c.id for c in categories)
        )
        seed = generate_seed()
        order = seeded_order(tuple(event.event_id for event in pool), seed)
        state = start_run(keys, rules, order)
        run = GameRun(
            owner_id=owner_id,
            mode="freeplay",
            catalog_release_id=command.catalog_release_id,
            seed=seed,
            rules={
                "category_ids": sorted(rules.category_ids),
                "start_year_index": rules.start_year_index,
                "end_year_index": rules.end_year_index,
                "min_gap": rules.min_gap,
            },
            pool=[str(event.event_id) for event in pool],
            order=[str(id_) for id_ in order],
            timeline=[str(id_) for id_ in state.timeline],
            pending_event_id=state.pending_event_id,
            status=state.status,
            streak=state.streak,
            revision=state.revision,
        )
        session.add(run)
        session.flush()
        response = _project(session, run)
        _record(session, owner_id, command.operation_id, "freeplay", digest, response)
        session.commit()
        return response
    except Exception as exc:
        session.rollback()
        if isinstance(exc, GameServiceError):
            raise
        raise _map_error(exc) from exc


def read_run(session: Session, owner_id: UUID, run_id: UUID) -> RunPublic:
    try:
        return _project(session, read_owned_run(session, run_id, owner_id))
    except Exception as exc:
        session.rollback()
        raise _map_error(exc) from exc


def list_active_runs(session: Session, owner_id: UUID) -> list[RunPublic]:
    try:
        runs = session.exec(
            select(GameRun)
            .where(GameRun.owner_id == owner_id, GameRun.status == "active")
            .order_by(col(GameRun.created_at), col(GameRun.id))
            .execution_options(populate_existing=True)
        ).all()
        return [_project(session, run) for run in runs]
    except Exception as exc:
        session.rollback()
        raise _map_error(exc) from exc


def submit_placement(
    session: Session, owner_id: UUID, run_id: UUID, command: PlaceCommand
) -> RunPublic:
    try:
        command = PlaceCommand.model_validate(command)
        # Do not reveal operation metadata for foreign/missing runs.
        read_owned_run(session, run_id, owner_id)
        payload = command.model_dump(mode="json", exclude={"operation_id"})
        digest = _digest("placement", {"run_id": str(run_id), **payload})
        lock_operation(session, owner_id, command.operation_id)
        replay = replay_operation(
            session, owner_id, command.operation_id, "placement", digest
        )
        if replay is not None:
            session.rollback()
            return replay
        run = lock_run(session, run_id, owner_id)
        if run.revision != command.expected_revision:
            raise RuleError("stale_revision")
        events = load_events(session, run.catalog_release_id)
        rules = RunRules(
            frozenset(run.rules["category_ids"]),
            run.rules["start_year_index"],
            run.rules["end_year_index"],
            run.rules["min_gap"],
        )
        status: Literal["active", "lost", "won"] = run.status  # type: ignore[assignment]
        state = RunState(
            rules,
            tuple(UUID(id_) for id_ in run.order),
            tuple(UUID(id_) for id_ in run.timeline),
            run.pending_event_id,
            run.streak,
            status,
            run.revision,
        )
        outcome = place(state, _keys(events), command.event_id, command.slot)
        after = outcome.state
        run.timeline = [str(id_) for id_ in after.timeline]
        run.pending_event_id = after.pending_event_id
        run.status, run.streak, run.revision = (
            after.status,
            after.streak,
            after.revision,
        )
        run.updated_at = utc_now()
        if after.status != "active":
            run.finished_at = run.updated_at
        session.add(run)
        response = _project(session, run)
        event = events[outcome.revealed_event_id]
        media = project_media(
            event,
            load_media(session, run.catalog_release_id),
            release_media_base(run.catalog_release_id),
        )
        feedback = MoveFeedback(
            correct=outcome.correct,
            card=revealed_card(
                event, media, learn_more=event_link_for_run(session, run, event)
            ),
            correct_slot=outcome.correct_slot,
            attempted_slot=command.slot,
        )
        response = RunPublic.model_validate(
            response.model_copy(update={"feedback": feedback})
        )
        _record(session, owner_id, command.operation_id, "placement", digest, response)
        session.commit()
        return response
    except Exception as exc:
        session.rollback()
        if isinstance(exc, GameServiceError):
            raise
        raise _map_error(exc) from exc
