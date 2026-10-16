"""One immutable definition per UTC day and one owned, idempotent attempt."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlmodel import Session, col

from app.game import run_service
from app.game.catalog_repository import CatalogError, load_events, load_options
from app.game.daily_config import daily_pool, load_daily_config
from app.game.models import DailyDefinition, GameRun, utc_now
from app.game.ordering import GENERATION_VERSION, generate_seed, seeded_order
from app.game.rules import start_run
from app.game.run_repository import (
    find_daily_attempt,
    find_daily_definition,
    insert_or_read_daily,
    lock_operation,
    lock_owner,
)
from app.game.schemas import (
    DailyOverview,
    DailyStart,
    LeaderboardEntry,
    LeaderboardPublic,
    RunPublic,
)
from app.game.types import RunRules
from app.models import User


def _utc_day(now: datetime) -> date:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Daily server time must be timezone-aware")
    return now.astimezone(UTC).date()


def _definition(session: Session, day: date) -> DailyDefinition:
    existing = find_daily_definition(session, day)
    if existing is not None:
        # Never consult today's active release/config when the date is frozen.
        return existing
    try:
        config = load_daily_config()
        options = load_options(session)
        known = frozenset(c.id for c in options.categories)
        events = load_events(session, options.release_id)
        keys = run_service._keys(events)
        rules, pool = daily_pool(tuple(keys.values()), known, config)
        seed = generate_seed()
        order = seeded_order(tuple(e.event_id for e in pool), seed)
        state = start_run(keys, rules, order)
        candidate = DailyDefinition(
            day=day,
            catalog_release_id=options.release_id,
            seed=seed,
            generation_version=GENERATION_VERSION,
            rules={
                "category_ids": sorted(rules.category_ids),
                "start_year_index": rules.start_year_index,
                "end_year_index": rules.end_year_index,
                "min_gap": rules.min_gap,
            },
            pool=[
                str(e.event_id) for e in sorted(pool, key=lambda e: e.event_id.bytes)
            ],
            order=[str(id_) for id_ in order],
            anchor_event_id=state.timeline[0],
        )
    except (ValueError, OSError, TypeError, AttributeError) as exc:
        # Server-side configuration/pool errors are availability failures, not
        # malformed player commands, and must not allocate any scored attempt.
        raise CatalogError("catalog_unavailable") from exc
    return insert_or_read_daily(session, candidate)


def read_daily(
    session: Session, owner_id: UUID, now: datetime | None = None
) -> DailyOverview:
    """Allocate only the shared definition; `now` is trusted server/test input."""
    try:
        day = _utc_day(utc_now() if now is None else now)
        definition = _definition(session, day)
        attempt = find_daily_attempt(session, owner_id, definition.id)
        response = DailyOverview(
            day=day,
            reset_at=datetime.combine(day + timedelta(days=1), time.min, UTC),
            category_ids=list(definition.rules["category_ids"]),
            attempt_run_id=attempt.id if attempt is not None else None,
        )
        session.commit()
        return response
    except Exception as exc:
        session.rollback()
        raise run_service._map_error(exc) from exc


def start_daily(
    session: Session, owner_id: UUID, command: DailyStart, now: datetime | None = None
) -> RunPublic:
    try:
        command = DailyStart.model_validate(command)
        digest = run_service._digest("daily", {})
        lock_operation(session, owner_id, command.operation_id)
        replay = run_service.replay_operation(
            session, owner_id, command.operation_id, "daily", digest
        )
        if replay is not None:
            session.rollback()
            return replay  # Before even reading the clock: midnight retries are exact.
        day = _utc_day(utc_now() if now is None else now)
        lock_owner(session, owner_id)
        definition = _definition(session, day)
        run = find_daily_attempt(session, owner_id, definition.id)
        if run is None:
            rules = RunRules(
                frozenset(definition.rules["category_ids"]),
                definition.rules["start_year_index"],
                definition.rules["end_year_index"],
                definition.rules["min_gap"],
            )
            state = start_run(
                run_service._keys(load_events(session, definition.catalog_release_id)),
                rules,
                tuple(UUID(id_) for id_ in definition.order),
            )
            if state.timeline[0] != definition.anchor_event_id:
                raise CatalogError("catalog_unavailable")
            run = GameRun(
                owner_id=owner_id,
                mode="daily",
                daily_definition_id=definition.id,
                catalog_release_id=definition.catalog_release_id,
                seed=definition.seed,
                generation_version=definition.generation_version,
                rules=dict(definition.rules),
                pool=list(definition.pool),
                order=list(definition.order),
                timeline=[str(definition.anchor_event_id)],
                pending_event_id=state.pending_event_id,
                status=state.status,
                streak=state.streak,
                mistakes=state.mistakes,
                correct_count=state.correct_count,
                revision=state.revision,
            )
            session.add(run)
            session.flush()
        response = run_service._project(session, run)
        run_service._record(
            session, owner_id, command.operation_id, "daily", digest, response
        )
        session.commit()
        return response
    except Exception as exc:
        session.rollback()
        if isinstance(exc, run_service.GameServiceError):
            raise
        raise run_service._map_error(exc) from exc


def read_leaderboard(session: Session, day: date) -> LeaderboardPublic:
    # Rank completed runs by correct confirmations, without secondary scoring.
    # A separate private UUID ordering makes presentation deterministic, without
    # exposing either that identifier or account emails in public entries.
    rows = session.execute(
        select(
            col(User.full_name),
            col(GameRun.correct_count),
            col(GameRun.streak),
            col(GameRun.status),
            func.rank().over(order_by=col(GameRun.correct_count).desc()).label("rank"),
        )
        .join(GameRun, col(GameRun.owner_id) == col(User.id))
        .join(
            DailyDefinition, col(DailyDefinition.id) == col(GameRun.daily_definition_id)
        )
        .where(
            col(DailyDefinition.day) == day,
            col(GameRun.mode) == "daily",
            col(GameRun.status).in_(("lost", "won")),
        )
        .order_by(col(GameRun.correct_count).desc(), col(GameRun.id))
    ).all()
    return LeaderboardPublic(
        day=day,
        entries=[
            LeaderboardEntry(
                display_name=name or "Player",
                streak=streak,
                score=score,
                status=cast(Literal["lost", "won"], status),
                rank=rank,
            )
            for name, score, streak, status, rank in rows
        ],
    )
