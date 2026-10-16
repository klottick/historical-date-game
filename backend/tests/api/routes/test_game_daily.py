"""Shared UTC Daily contracts against independent real PostgreSQL sessions."""

import json
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta, timezone
from itertools import count
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event
from sqlmodel import Session, col, select, text

from app.content.adapters.selected import SelectedSourceAdapter
from app.content.importer import import_snapshot
from app.content.media import pipeline
from app.content.publish import publish_release
from app.content.schemas import EventRecord
from app.core.db import engine
from app.game.catalog_repository import activate_catalog, load_events
from app.game.models import CatalogSelection, DailyDefinition, GameOperation, GameRun
from app.game.schemas import DailyStart as DailyStartSchema
from app.game.schemas import RunPublic
from app.models import User
from tests.api.routes.test_game_runs import correct_command, start_command
from tests.content.test_importer import snapshot
from tests.content.test_media import SELECTION

_days = count()


def DailyStart(*, operation_id: Any, protocol_version: int = 2) -> DailyStartSchema:
    """Build current-protocol Daily commands; allow explicit negative versions."""
    return DailyStartSchema(
        protocol_version=protocol_version, operation_id=operation_id
    )


def release(session: Session, root: Path, *, shift: int = 0) -> str:
    """C5-verified synthetic milestones, six selected and two excluded events."""
    root.mkdir()
    workspace = root / "work"
    original = Path("tests/fixtures/content/source-snapshot.json").read_text()
    variants = [
        (
            "battles",
            "start",
            "end",
            "P580",
            "P582",
            "start_date",
            "end_date",
            "military conflict",
            1800,
            1870,
        ),
        (
            "exploration",
            "launch",
            "landing",
            "P619",
            "P620",
            "launch_date",
            "landing_date",
            "spaceflight",
            1810,
            1880,
        ),
        (
            "inventions",
            "invention",
            None,
            "P575",
            None,
            "invention_year",
            None,
            "electronic component",
            1820,
            0,
        ),
        (
            "politics",
            "inception",
            None,
            "P571",
            None,
            "established",
            None,
            "organization",
            1830,
            0,
        ),
        (
            None,
            "birth",
            "death",
            "P569",
            "P570",
            "birth_date",
            "death_date",
            "person",
            1000,
            2000,
        ),
    ]
    for i, (
        category,
        first,
        second,
        prop1,
        prop2,
        field1,
        field2,
        box,
        year1,
        year2,
    ) in enumerate(variants):
        raw = original.replace("900001", str(910001 + i + shift))
        raw = raw.replace("Synthetic Ada", f"Synthetic Milestone {i} Revision {shift}")
        raw = raw.replace("1800", str(year1 + shift)).replace(
            "1870", str(year2 + shift)
        )
        raw = raw.replace("P569", prop1).replace("birth_date", field1)
        raw = raw.replace("Infobox person", "Infobox " + box)
        if second is not None:
            raw = raw.replace("P570", prop2).replace("death_date", field2)
        data = json.loads(raw)
        for record in data["records"]:
            record["record_id"] += f"-{i}-{shift}"
            if record["milestone"] == "birth":
                record["milestone"] = first
            elif second is not None:
                record["milestone"] = second
            if category is not None:
                record["category_ids"] = [category]
        if second is None:
            data["records"] = [r for r in data["records"] if r["milestone"] != "death"]
            del data["entity"]["claims"]["P570"]
        source = root / f"source-{i}"
        source.mkdir()
        import_snapshot(SelectedSourceAdapter(), snapshot(source, data), workspace)
    pointer = json.loads((workspace / "current.json").read_text())
    events = [
        EventRecord.model_validate_json(line)
        for line in (workspace / pointer["generation"] / "candidates.jsonl")
        .read_text()
        .splitlines()
    ]
    assert len(events) == 8
    for item in events:
        pipeline.assign_media(item, SELECTION, workspace)
    assert all(r.passed for r in pipeline.finalize_media_receipts(workspace))
    release_id = "b4-" + uuid4().hex
    publish_release(workspace, root / "releases", release_id, fixture=True)
    published = root / "releases" / release_id
    activate_catalog(session, published, published / "media", require_beta=False)
    session.commit()
    return release_id


@pytest.fixture
def daily_context(
    db: Session, tmp_path: Path
) -> Generator[tuple[list[UUID], str, datetime]]:
    release_id = release(db, tmp_path / "first")
    users = [
        User(
            email=uuid4().hex + "@example.com", hashed_password="unused", full_name=name
        )
        for name in ("Ada", None, "Grace", "Linus", "Active")
    ]
    db.add_all(users)
    db.commit()
    ids = [u.id for u in users]
    # Each fixture owns its dates; leave other tests' immutable definitions alone.
    now = datetime(2100, 1, 1, 12, tzinfo=UTC) + timedelta(days=10 * next(_days))
    db.rollback()
    yield ids, release_id, now
    db.rollback()
    for owner_id in ids:
        db.delete(db.get(User, owner_id))
    db.commit()


def definitions(session: Session, day: date) -> list[DailyDefinition]:
    return list(
        session.exec(select(DailyDefinition).where(DailyDefinition.day == day)).all()
    )


def attempts(session: Session, owners: list[UUID]) -> list[GameRun]:
    return list(
        session.exec(select(GameRun).where(col(GameRun.owner_id).in_(owners))).all()
    )


def test_daily_seed_pool_and_sequence_shared(
    db: Session, daily_context: tuple[list[UUID], str, datetime]
) -> None:
    from app.game.daily_service import read_daily, start_daily
    from app.game.ordering import seeded_order
    from app.game.run_service import submit_placement

    owners, release_id, now = daily_context
    overview = read_daily(db, owners[0], now)
    assert overview.day == now.date() and overview.reset_at == datetime.combine(
        now.date() + timedelta(days=1), datetime.min.time(), UTC
    )
    assert overview.attempt_run_id is None and not attempts(db, owners)
    assert overview.category_ids == ["battles", "exploration", "inventions", "politics"]
    definition = definitions(db, now.date())[0]
    frozen = definition.model_dump()
    assert len(definition.seed) == 32 and definition.generation_version == 1
    events = load_events(db, release_id)
    selected = {
        id_
        for id_, item in events.items()
        if set(item.category_ids) & set(overview.category_ids)
    }
    assert (
        set(definition.pool) == {str(id_) for id_ in selected}
        and len(definition.pool) == 6
    )
    assert definition.rules == {
        "category_ids": overview.category_ids,
        "start_year_index": 1800,
        "end_year_index": 1880,
        "min_gap": 1,
    }
    # Database row order cannot change the v1 sequence.
    assert seeded_order(tuple(reversed(tuple(selected))), definition.seed) == tuple(
        UUID(id_) for id_ in definition.order
    )
    command = DailyStart(operation_id=uuid4())
    first = start_daily(db, owners[0], command, now)
    second = start_daily(db, owners[1], DailyStart(operation_id=uuid4()), now)
    assert first.timeline == second.timeline and first.pending == second.pending
    assert first.timeline[0].event_id == definition.anchor_event_id
    assert read_daily(db, owners[0], now).attempt_run_id == first.run_id
    public = first.model_dump_json() + overview.model_dump_json()
    for private in ('"seed"', '"order"', '"pool"', '"owner_id"', '"year_index"'):
        assert private not in public
    for item in attempts(db, owners):
        assert (item.seed, item.order, item.pool, item.rules) == (
            definition.seed,
            definition.order,
            definition.pool,
            definition.rules,
        )
    initial = first
    assert start_daily(db, owners[0], DailyStart(operation_id=uuid4()), now) == first
    while first.status == "active":
        assert first.pending == second.pending
        first = submit_placement(
            db, owners[0], first.run_id, correct_command(db, first)
        )
        second = submit_placement(
            db, owners[1], second.run_id, correct_command(db, second)
        )
        assert first.timeline == second.timeline and first.pending == second.pending
    assert first.status == second.status == "won" and first.streak == second.streak == 5
    assert start_daily(db, owners[0], DailyStart(operation_id=uuid4()), now) == first
    assert start_daily(db, owners[0], command, now) == initial
    assert (
        len(attempts(db, owners)) == 2
        and definitions(db, now.date())[0].model_dump() == frozen
    )


def race(calls: list[tuple[UUID, Any]]) -> list[Any]:
    gate = Barrier(2)
    pids: list[int] = []

    def request(owner: UUID, call: Any) -> Any:
        from app.game.run_service import GameServiceError

        with Session(engine) as session:
            session.execute(text("SET LOCAL statement_timeout = '10s'"))
            session.get(User, owner)
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            gate.wait(timeout=10)  # Before any operation/owner/definition locks.
            try:
                return call(session)
            except GameServiceError as exc:
                return exc

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(request, owner, call) for owner, call in calls]
        results = [f.result(timeout=20) for f in futures]
    assert len(set(pids)) == 2
    return results


@pytest.mark.parametrize(
    "kind", ["different_owners", "same_owner", "same_operation", "overview_start"]
)
@pytest.mark.parametrize("round_number", range(3))
def test_concurrent_daily_starts_share_definition_and_attempt(
    db: Session,
    daily_context: tuple[list[UUID], str, datetime],
    kind: str,
    round_number: int,
) -> None:
    from app.game.daily_service import read_daily, start_daily

    owners, _, now = daily_context
    now += timedelta(days=round_number)
    one = DailyStart(operation_id=uuid4())
    two = one if kind == "same_operation" else DailyStart(operation_id=uuid4())
    other = owners[1] if kind in {"different_owners", "overview_start"} else owners[0]
    db.rollback()
    results = race(
        [
            (
                owners[0],
                lambda s: (
                    read_daily(s, owners[0], now)
                    if kind == "overview_start"
                    else start_daily(s, owners[0], one, now)
                ),
            ),
            (other, lambda s: start_daily(s, other, two, now)),
        ]
    )
    if kind == "overview_start":
        assert results[0].attempt_run_id is None and isinstance(results[1], RunPublic)
    else:
        assert all(isinstance(r, RunPublic) for r in results)
        assert (
            results[0].timeline == results[1].timeline
            and results[0].pending == results[1].pending
        )
        assert (results[0].run_id == results[1].run_id) == (kind != "different_owners")
    with Session(engine) as observer:
        assert len(definitions(observer, now.date())) == 1
        saved = attempts(observer, owners)
        assert len(saved) == (2 if kind == "different_owners" else 1)
        assert len(
            observer.exec(
                select(GameOperation).where(col(GameOperation.owner_id).in_(owners))
            ).all()
        ) == (1 if kind in {"same_operation", "overview_start"} else 2)
        definition = definitions(observer, now.date())[0]
        assert all(
            r.seed == definition.seed and r.order == definition.order for r in saved
        )


def test_midnight_and_midday_updates(
    db: Session,
    daily_context: tuple[list[UUID], str, datetime],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.game import daily_service, run_service
    from app.game.daily_config import DailyConfig
    from app.game.run_service import read_run, submit_placement

    owners, release_id, now = daily_context
    initial_overview = daily_service.read_daily(db, owners[0], now)
    command = DailyStart(operation_id=uuid4())
    initial = daily_service.start_daily(db, owners[0], command, now)
    frozen = definitions(db, now.date())[0].model_dump()
    next_release = release(db, tmp_path / "next", shift=10)
    monkeypatch.setattr(
        daily_service,
        "load_daily_config",
        lambda: DailyConfig(("exploration",), min_gap=1),
    )
    with Session(engine) as restarted:
        assert (
            daily_service.read_daily(restarted, owners[1], now).category_ids
            == initial_overview.category_ids
        )
        second = daily_service.start_daily(
            restarted, owners[1], DailyStart(operation_id=uuid4()), now
        )
        assert (
            second.categories == initial.categories and second.config == initial.config
        )
        assert (
            second.catalog_release_id == release_id
            and second.pending == initial.pending
        )
        assert definitions(restarted, now.date())[0].model_dump() == frozen
        # Offset clocks normalize to UTC, not the caller's civil date.
        offset = datetime.combine(
            now.date() + timedelta(days=1),
            datetime.min.time(),
            timezone(timedelta(hours=2)),
        ) + timedelta(hours=1)
        assert daily_service.read_daily(restarted, owners[0], offset).day == now.date()
        tomorrow = datetime.combine(
            now.date() + timedelta(days=1), datetime.min.time(), UTC
        )
        assert (
            daily_service.start_daily(restarted, owners[0], command, tomorrow)
            == initial
        )
        assert (
            definitions(restarted, tomorrow.date()) == []
        )  # Replay before today's definition.
        next_run = daily_service.start_daily(
            restarted, owners[0], DailyStart(operation_id=uuid4()), tomorrow
        )
        assert (
            next_run.daily_date == tomorrow.date()
            and next_run.catalog_release_id == next_release
        )
        assert next_run.config.category_ids == ["exploration"]
        assert next_run.config.start.value == 1820 and next_run.config.end.value == 1890
        assert definitions(restarted, tomorrow.date())[0].seed != frozen["seed"]
        assert daily_service.read_daily(
            restarted, owners[0], tomorrow
        ).reset_at == tomorrow + timedelta(days=1)
        monkeypatch.setattr(
            run_service, "utc_now", lambda: tomorrow + timedelta(hours=1)
        )
        old = read_run(restarted, owners[0], initial.run_id)
        while old.status == "active":
            old = submit_placement(
                restarted, owners[0], old.run_id, correct_command(restarted, old)
            )
        assert old.daily_date == now.date() and old.catalog_release_id == release_id
        assert restarted.get(GameRun, old.run_id).finished_at == tomorrow + timedelta(
            hours=1
        )
        assert (
            daily_service.read_leaderboard(restarted, now.date()).entries[0].streak == 5
        )
        assert daily_service.read_leaderboard(restarted, tomorrow.date()).entries == []


def test_rank_ties_and_display_name_privacy(
    db: Session, daily_context: tuple[list[UUID], str, datetime]
) -> None:
    from app.game.daily_service import read_leaderboard, start_daily
    from app.game.run_service import start_freeplay, submit_placement

    owners, release_id, now = daily_context
    for owner in owners[:2]:
        response = start_daily(db, owner, DailyStart(operation_id=uuid4()), now)
        while response.status == "active":
            response = submit_placement(
                db, owner, response.run_id, correct_command(db, response)
            )
    low = start_daily(db, owners[2], DailyStart(operation_id=uuid4()), now)
    low = submit_placement(db, owners[2], low.run_id, correct_command(db, low))
    lost = low
    while lost.status == "active" and lost.lives_remaining > 0:
        move = correct_command(db, lost)
        lost = submit_placement(
            db,
            owners[2],
            low.run_id,
            move.model_copy(
                update={"slot": (move.slot + 1) % (len(lost.timeline) + 1)}
            ),
        )
    assert lost.status == "lost" and lost.streak == 0 and lost.score == 1
    free = start_freeplay(db, owners[3], start_command(release_id))
    move = correct_command(db, free)
    submit_placement(
        db, owners[3], free.run_id, move.model_copy(update={"slot": 1 - move.slot})
    )
    start_daily(db, owners[4], DailyStart(operation_id=uuid4()), now)
    board = read_leaderboard(db, now.date())
    assert [e.rank for e in board.entries] == [1, 1, 3]
    assert [e.streak for e in board.entries] == [5, 5, 0]
    assert [e.status for e in board.entries] == ["won", "won", "lost"]
    assert {e.display_name for e in board.entries[:2]} == {"Ada", "Player"}
    assert board.entries[2].display_name == "Grace"
    assert read_leaderboard(db, now.date()) == board
    assert read_leaderboard(db, now.date() + timedelta(days=1)).entries == []
    public = board.model_dump_json()
    assert "@" not in public and "owner_id" not in public and "run_id" not in public
    assert all(str(owner) not in public for owner in owners)


@pytest.mark.parametrize(
    "categories,gap",
    [
        ((), 1),
        (("missing",), 1),
        (("battles", "battles"), 1),
        ((True,), 1),
        (("battles",), True),
        (("battles",), 0),
        (("battles",), "1"),
    ],
)
def test_declared_daily_config_is_strict(categories: Any, gap: Any) -> None:
    from app.game.daily_config import DailyConfig

    with pytest.raises(ValueError):
        DailyConfig(categories, min_gap=gap)


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "invalid",
        "unknown_release_category",
        "full_catalog",
        "full_union",
        "empty_pool",
        "sparse",
        "gap",
        "mutated",
        "no_selection",
    ],
)
def test_unavailable_daily_never_consumes_attempt(
    db: Session,
    daily_context: tuple[list[UUID], str, datetime],
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    from app.game import daily_service
    from app.game.daily_config import DailyConfig
    from app.game.run_service import GameServiceError

    owners, _, now = daily_context
    if kind == "no_selection":
        pointer = db.get(CatalogSelection, 1)
        db.delete(pointer)
        db.commit()
    elif kind == "unknown_release_category":
        # Simulate a release with a narrower taxonomy at its repository boundary.
        original = daily_service.load_options
        from dataclasses import replace

        monkeypatch.setattr(
            daily_service,
            "load_options",
            lambda s: replace(
                original(s),
                categories=tuple(
                    c for c in original(s).categories if c.id != "battles"
                ),
            ),
        )
    elif kind in {"missing", "invalid"}:

        def broken() -> Any:
            raise (
                FileNotFoundError("selection missing")
                if kind == "missing"
                else ValueError("invalid selection")
            )

        monkeypatch.setattr(daily_service, "load_daily_config", broken)
    else:
        from app.content.schemas import CATEGORY_IDS

        values = {
            "full_catalog": DailyConfig(tuple(CATEGORY_IDS)),
            "full_union": DailyConfig(
                ("battles", "exploration", "inventions", "politics", "births", "deaths")
            ),
            "empty_pool": DailyConfig(("arts",)),
            "sparse": DailyConfig(("politics",)),
            "gap": DailyConfig(("battles",), min_gap=10000),
            "mutated": DailyConfig(("battles",)),
        }
        config = values[kind]
        if kind == "mutated":
            object.__setattr__(config, "min_gap", True)
        monkeypatch.setattr(daily_service, "load_daily_config", lambda: config)
    for call in (
        lambda: daily_service.read_daily(db, owners[0], now),
        lambda: daily_service.start_daily(
            db, owners[0], DailyStart(operation_id=uuid4()), now
        ),
    ):
        with pytest.raises(GameServiceError) as error:
            call()
        assert error.value.status_code == 503
        assert not db.in_transaction()
        assert not definitions(db, now.date()) and not attempts(db, owners)
        assert not db.exec(
            select(GameOperation).where(col(GameOperation.owner_id).in_(owners))
        ).all()
        db.rollback()


def test_operation_registry_scope_and_payload_conflicts(
    db: Session, daily_context: tuple[list[UUID], str, datetime]
) -> None:
    from app.game.daily_service import start_daily
    from app.game.run_service import (
        GameServiceError,
        _digest,
        _record,
        start_freeplay,
        submit_placement,
    )

    owners, release_id, now = daily_context
    free_command = start_command(release_id)
    free = start_freeplay(db, owners[0], free_command)
    with pytest.raises(GameServiceError) as error:
        start_daily(
            db, owners[0], DailyStart(operation_id=free_command.operation_id), now
        )
    assert error.value.status_code == 409 and not definitions(db, now.date())
    daily_command = DailyStart(operation_id=uuid4())
    daily = start_daily(db, owners[0], daily_command, now)
    with pytest.raises(GameServiceError) as error:
        start_freeplay(
            db,
            owners[0],
            start_command(release_id, operation_id=str(daily_command.operation_id)),
        )
    assert error.value.status_code == 409
    with pytest.raises(GameServiceError) as error:
        submit_placement(
            db,
            owners[0],
            daily.run_id,
            correct_command(db, daily, operation_id=daily_command.operation_id),
        )
    assert error.value.status_code == 409
    move = correct_command(db, free)
    submit_placement(db, owners[0], free.run_id, move)
    with pytest.raises(GameServiceError) as error:
        start_daily(db, owners[0], DailyStart(operation_id=move.operation_id), now)
    assert error.value.status_code == 409
    # Immutable registry payload mismatch is rejected even for an existing attempt.
    corrupt_id = uuid4()
    _record(
        db, owners[0], corrupt_id, "daily", _digest("daily", {"unexpected": 1}), daily
    )
    db.commit()
    with pytest.raises(GameServiceError) as error:
        start_daily(db, owners[0], DailyStart(operation_id=corrupt_id), now)
    assert error.value.status_code == 409
    assert len([r for r in attempts(db, owners) if r.mode == "daily"]) == 1


@pytest.mark.parametrize("kind", ["read", "start"])
def test_unexpected_failure_rolls_back_definition_and_attempt(
    db: Session, daily_context: tuple[list[UUID], str, datetime], kind: str
) -> None:
    from app.game.daily_service import read_daily, start_daily

    owners, _, now = daily_context
    command = DailyStart(operation_id=uuid4())
    db.rollback()

    def fail(session: Session) -> None:
        session.flush()
        raise RuntimeError("injected before commit")

    with Session(engine) as writer:
        event.listen(writer, "before_commit", fail)
        with pytest.raises(RuntimeError, match="injected"):
            if kind == "read":
                read_daily(writer, owners[0], now)
            else:
                start_daily(writer, owners[0], command, now)
        event.remove(writer, "before_commit", fail)
        assert not writer.in_transaction()
    with Session(engine) as observer:
        assert not definitions(observer, now.date()) and not attempts(observer, owners)
        assert not observer.exec(
            select(GameOperation).where(col(GameOperation.owner_id).in_(owners))
        ).all()
        assert start_daily(observer, owners[0], command, now).status == "active"


def test_server_clock_and_command_boundaries(
    db: Session, daily_context: tuple[list[UUID], str, datetime]
) -> None:
    from pydantic import ValidationError

    from app.game.daily_service import read_daily, start_daily
    from app.game.run_service import GameServiceError

    owners, _, now = daily_context
    with pytest.raises(ValueError):
        read_daily(db, owners[0], now.replace(tzinfo=None))
    with pytest.raises(ValueError):
        start_daily(
            db, owners[0], DailyStart(operation_id=uuid4()), now.replace(tzinfo=None)
        )
    for key in ("now", "day", "config", "seed"):
        with pytest.raises(ValidationError):
            DailyStartSchema.model_validate_json(
                json.dumps(
                    {"protocol_version": 2, "operation_id": str(uuid4()), key: 1}
                )
            )
    with pytest.raises(GameServiceError) as error:
        start_daily(
            db,
            owners[0],
            DailyStartSchema.model_construct(protocol_version=2, operation_id=True),
            now,
        )
    assert (
        error.value.status_code == 422
        and not definitions(db, now.date())
        and not attempts(db, owners)
    )


def test_default_clock_is_server_owned_and_replay_precedes_clock(
    db: Session,
    daily_context: tuple[list[UUID], str, datetime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.game import daily_service

    owners, _, now = daily_context
    monkeypatch.setattr(daily_service, "utc_now", lambda: now)
    assert daily_service.read_daily(db, owners[0]).day == now.date()
    command = DailyStart(operation_id=uuid4())
    original = daily_service.start_daily(db, owners[0], command)

    def clock_failure() -> datetime:
        raise RuntimeError("clock must not be read for an operation replay")

    monkeypatch.setattr(daily_service, "utc_now", clock_failure)
    assert daily_service.start_daily(db, owners[0], command) == original
    tomorrow = now + timedelta(days=1)
    monkeypatch.setattr(daily_service, "utc_now", lambda: tomorrow)
    fresh = daily_service.start_daily(db, owners[0], DailyStart(operation_id=uuid4()))
    assert fresh.daily_date == tomorrow.date() and fresh.run_id != original.run_id


def test_insert_conflict_reads_winner_without_aborting_transaction(
    db: Session, daily_context: tuple[list[UUID], str, datetime]
) -> None:
    from app.game.daily_service import read_daily
    from app.game.run_repository import insert_or_read_daily

    owners, _, now = daily_context
    read_daily(db, owners[0], now)
    template = definitions(db, now.date())[0].model_dump()
    target = now.date() + timedelta(days=1)
    candidates = [
        DailyDefinition(
            **{**template, "id": uuid4(), "day": target, "seed": bytes([i]) * 32}
        )
        for i in (1, 2)
    ]
    db.rollback()
    rowcounts: list[int] = []

    def capture(
        _connection: Any,
        cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: Any,
    ) -> None:
        if statement.startswith("INSERT INTO dailydefinition"):
            rowcounts.append(cursor.rowcount)

    def insert(session: Session, candidate: DailyDefinition) -> tuple[UUID, bytes]:
        winner = insert_or_read_daily(session, candidate)
        result = winner.id, winner.seed
        # A losing insert must still have a usable transaction.
        assert session.execute(text("SELECT 1")).scalar_one() == 1
        session.commit()
        return result

    event.listen(engine, "after_cursor_execute", capture)
    try:
        results = race(
            [
                (owners[0], lambda s: insert(s, candidates[0])),
                (owners[1], lambda s: insert(s, candidates[1])),
            ]
        )
    finally:
        event.remove(engine, "after_cursor_execute", capture)
    assert results[0] == results[1]
    assert sorted(rowcounts) == [0, 1]
    with Session(engine) as observer:
        assert len(definitions(observer, target)) == 1 and not attempts(
            observer, owners
        )


@pytest.mark.parametrize("scope", ["freeplay", "placement"])
@pytest.mark.parametrize("round_number", range(3))
def test_daily_cross_scope_race(
    db: Session,
    daily_context: tuple[list[UUID], str, datetime],
    scope: str,
    round_number: int,
) -> None:
    from app.game.daily_service import start_daily
    from app.game.run_service import (
        GameServiceError,
        read_run,
        start_freeplay,
        submit_placement,
    )

    owners, release_id, now = daily_context
    now += timedelta(days=round_number)
    initial = start_freeplay(db, owners[0], start_command(release_id))
    command = DailyStart(operation_id=uuid4())
    move = correct_command(db, initial, operation_id=command.operation_id)
    free_command = start_command(release_id, operation_id=str(command.operation_id))
    db.rollback()
    results = race(
        [
            (owners[0], lambda s: start_daily(s, owners[0], command, now)),
            (
                owners[0],
                lambda s: (
                    start_freeplay(s, owners[0], free_command)
                    if scope == "freeplay"
                    else submit_placement(s, owners[0], initial.run_id, move)
                ),
            ),
        ]
    )
    assert sum(isinstance(r, RunPublic) for r in results) == 1
    assert [r.status_code for r in results if isinstance(r, GameServiceError)] == [409]
    with Session(engine) as observer:
        registry = observer.exec(
            select(GameOperation).where(GameOperation.owner_id == owners[0])
        ).all()
        assert len(registry) == 2
        daily_won = isinstance(results[0], RunPublic)
        assert len(definitions(observer, now.date())) == int(daily_won)
        assert len(attempts(observer, owners)) == (
            2 if daily_won or scope == "freeplay" else 1
        )
        assert read_run(observer, owners[0], initial.run_id).revision == (
            1 if not daily_won and scope == "placement" else 0
        )


@pytest.mark.parametrize("round_number", range(6))
def test_fresh_start_and_placement_different_operations_do_not_deadlock(
    db: Session, daily_context: tuple[list[UUID], str, datetime], round_number: int
) -> None:
    from app.game.daily_service import start_daily
    from app.game.run_service import read_run, submit_placement

    owners, _, now = daily_context
    now += timedelta(days=round_number)
    initial = start_daily(db, owners[0], DailyStart(operation_id=uuid4()), now)
    move = correct_command(db, initial)
    db.rollback()
    results = race(
        [
            (
                owners[0],
                lambda s: start_daily(
                    s, owners[0], DailyStart(operation_id=uuid4()), now
                ),
            ),
            (owners[0], lambda s: submit_placement(s, owners[0], initial.run_id, move)),
        ]
    )
    assert all(isinstance(r, RunPublic) and r.run_id == initial.run_id for r in results)
    with Session(engine) as observer:
        assert len(attempts(observer, owners)) == 1
        assert read_run(observer, owners[0], initial.run_id).streak == 1
