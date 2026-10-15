"""Explicit, local-only service/persistence proof; never a pytest fixture.

Run from backend/ after ownership verification and migrations. Private catalog
years are used only here to choose slots; no answer/clock endpoint is introduced.
"""

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from functools import partial
from itertools import combinations
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4

from sqlmodel import Session, select

from app.content.adapters.onthisday import PROJECT_URL, TEXT_CREDIT, TEXT_LICENSE_URL
from app.content.publish import verify_release
from app.content.schemas import CATEGORY_IDS, EventRecord
from app.core.config import settings
from app.core.db import engine
from app.game.catalog_repository import activate_catalog, load_events, load_options
from app.game.daily_service import read_daily, start_daily
from app.game.models import (
    CatalogRelease,
    DailyDefinition,
    EventRevision,
    GameOperation,
    GameRun,
)
from app.game.projections import public_year
from app.game.run_service import (
    GameServiceError,
    read_run,
    start_freeplay,
    submit_placement,
)
from app.game.schemas import (
    DailyStart,
    FreeplayStart,
    GameConfig,
    PlaceCommand,
    RunPublic,
)
from app.models import User
from tests.db_guard import require_test_database


def require_local_probe_target(database: str, host: str, environment: str) -> None:
    require_test_database(database)
    if not __debug__:
        raise RuntimeError("Probe assertions must not be disabled")
    if (
        database != "historical_date_game_catalog_test"
        or host not in {"localhost", "127.0.0.1"}
        or environment != "local"
    ):
        raise RuntimeError("Real catalog probe requires its isolated local database")


def _require_report_target(release: Path, media: Path, report: Path) -> None:
    target = report.resolve()
    if report.is_symlink() or any(
        target.is_relative_to(root.resolve()) for root in (release, media)
    ):
        raise RuntimeError(
            "Probe report must stay outside immutable release/public media"
        )


def _write_report(path: Path, report: dict[str, object]) -> None:
    # Explicit allowlist: never serialize settings, exceptions, runs or answers.
    allowed = {
        "passed",
        "error",
        "release_id",
        "manifest_sha256",
        "event_count",
        "category_counts",
        "asset_hashes",
        "database",
        "host",
        "port",
        "environment",
        "checks",
        "daily_day",
        "next_day",
        "fixture_release_id",
    }
    sanitized = {key: value for key, value in report.items() if key in allowed}
    if path.is_symlink():
        raise OSError("Probe report symlinks are not allowed")
    path.parent.mkdir(parents=True, exist_ok=True)
    # A report entry may hardlink immutable source/media. Never open its inode:
    # write a fresh private inode on the same filesystem, then replace the entry.
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o600)
            json.dump(sanitized, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _denied(action: Callable[[], object], code: str, status: int) -> None:
    try:
        action()
    except GameServiceError as exc:
        assert (exc.code, exc.status_code) == (code, status)
    else:
        raise AssertionError("Expected service rejection")


def _unused_probe_day(used_days: set[date]) -> datetime:
    # Existing integration tests own 2100/2200 ranges. Never reset their definitions.
    now = datetime(2300, 1, 1, 12, tzinfo=UTC)
    while now.date() in used_days or (now + timedelta(days=1)).date() in used_days:
        now += timedelta(days=2)
    return now


def _command(
    release_id: str, categories: list[str], start: int, end: int, gap: int = 1
) -> FreeplayStart:
    return FreeplayStart(
        operation_id=uuid4(),
        catalog_release_id=release_id,
        config=GameConfig(
            category_ids=categories,
            start=public_year(start),
            end=public_year(end),
            min_gap=gap,
        ),
    )


def _placement(
    response: RunPublic, events: Mapping[UUID, EventRecord], *, wrong: bool = False
) -> PlaceCommand:
    assert response.pending is not None
    year = events[response.pending.event_id].year_index
    slot = sum(events[card.event_id].year_index < year for card in response.timeline)
    if wrong:
        slot = (slot + 1) % (len(response.timeline) + 1)
    return PlaceCommand(
        operation_id=uuid4(),
        expected_revision=response.revision,
        event_id=response.pending.event_id,
        slot=slot,
    )


def _privacy(response: RunPublic) -> None:
    text = response.model_dump_json()
    for private in (
        "seed",
        "order",
        "pool",
        "owner_id",
        "year_index",
        "identity_key",
        "raw_date",
        "snapshot_id",
        "record_id",
        "rights_basis",
        "calendar",
        "date_resolution",
    ):
        assert f'"{private}"' not in text
    assert response.pending is not None
    pending = response.pending.model_dump(mode="json")
    assert set(pending) == {"event_id", "prompt", "category_ids", "media"}
    assert set(pending["media"]) == {
        "url",
        "fallback_url",
        "alt_text",
        "fit",
        "credits",
    }
    credits = response.pending.media.credits
    assert any(c.label == TEXT_CREDIT and c.url == PROJECT_URL for c in credits)
    assert any(c.url == TEXT_LICENSE_URL for c in credits)
    # Credits name the dataset/license, not the unanswered event's source URL/year.
    assert all(
        c.url is None or c.url in {PROJECT_URL, TEXT_LICENSE_URL} for c in credits
    )


def _revealed(response: RunPublic, events: Mapping[UUID, EventRecord]) -> None:
    assert response.feedback is not None
    card = response.feedback.card
    event = events[card.event_id]
    assert card.year == public_year(event.year_index)
    assert card.explanation == event.explanation
    assert {(s.source_id, s.url) for s in event.sources} <= {
        (s.label, s.url) for s in card.sources
    }
    assert any(
        c.label == TEXT_CREDIT and c.url == PROJECT_URL for c in card.media.credits
    )
    assert any(c.url == TEXT_LICENSE_URL for c in card.media.credits)


def _pair_gaps(response: RunPublic, events: Mapping[UUID, EventRecord]) -> None:
    ids = [c.event_id for c in response.timeline]
    assert len(ids) == len(set(ids))
    years = [events[id_].year_index for id_ in ids]
    assert len(years) == len(set(years))
    assert years == sorted(years)
    assert all(abs(a - b) >= response.config.min_gap for a, b in combinations(years, 2))
    if response.pending is not None:
        pending_year = events[response.pending.event_id].year_index
        assert all(
            abs(pending_year - year) >= response.config.min_gap for year in years
        )


def _exercise_services(
    session: Session, release_dir: Path, media_dir: Path, release_id: str
) -> dict[str, object]:
    events = load_events(session, release_id)
    options = load_options(session)
    assert options.release_id == release_id
    assert {c.id for c in options.categories} == set(CATEGORY_IDS)
    assert len(events) >= 1000 and all(
        e.review_status == "approved" and e.sources for e in events.values()
    )
    # The reviewed real release also retains independently sourced Wikidata births.
    assert any(e.identity_key.startswith("onthisday:") for e in events.values())
    assert options.start_year_index == min(e.year_index for e in events.values())
    assert options.end_year_index == max(e.year_index for e in events.values())
    users = [
        User(
            email=f"catalog-probe-{uuid4().hex}@example.com",
            hashed_password="disabled-probe-login",
            full_name="Catalog probe",
        )
        for _ in range(2)
    ]
    session.add_all(users)
    session.commit()
    owners = [u.id for u in users]
    categories = ["battles", "politics"]
    selected = [e for e in events.values() if set(e.category_ids) & set(categories)]
    lower, upper = (
        min(e.year_index for e in selected),
        max(e.year_index for e in selected),
    )
    free = start_freeplay(
        session, owners[0], _command(release_id, categories, lower, upper, 10)
    )
    assert free.streak == free.revision == 0 and len(free.timeline) == 1
    _privacy(free)
    row = session.get(GameRun, free.run_id, populate_existing=True)
    assert row is not None
    expected_pool = {
        str(e.event_id) for e in selected if lower <= e.year_index <= upper
    }
    assert set(row.pool) == expected_pool and len(row.pool) == len(expected_pool)
    assert any(events[UUID(id_)].year_index == lower for id_ in row.pool)
    assert any(events[UUID(id_)].year_index == upper for id_ in row.pool)
    # This real union must contain events that neither individual category alone covers.
    assert any(
        "battles" in e.category_ids and "politics" not in e.category_ids
        for e in selected
    )
    assert any(
        "politics" in e.category_ids and "battles" not in e.category_ids
        for e in selected
    )
    _pair_gaps(free, events)
    command = _placement(free, events)
    moved = submit_placement(session, owners[0], free.run_id, command)
    assert moved.revision == free.revision + 1 and moved.streak == 1
    assert moved.feedback is not None and moved.feedback.correct
    _revealed(moved, events)
    assert free.pending is not None and moved.feedback.card.media == free.pending.media
    assert submit_placement(session, owners[0], free.run_id, command) == moved
    operations = session.exec(
        select(GameOperation).where(
            GameOperation.owner_id == owners[0],
            GameOperation.operation_id == command.operation_id,
        )
    ).all()
    assert len(operations) == 1
    assert read_run(session, owners[0], free.run_id) == moved
    _pair_gaps(moved, events)
    _privacy(moved)
    _denied(lambda: read_run(session, owners[1], free.run_id), "run_not_found", 404)
    _denied(
        lambda: submit_placement(session, owners[1], free.run_id, command),
        "run_not_found",
        404,
    )

    count_before = len(
        session.exec(select(GameRun).where(GameRun.owner_id == owners[0])).all()
    )
    for invalid, code in [
        (_command(release_id, ["unknown"], lower, upper), "unknown_category"),
        (_command(release_id, categories, lower, lower), "insufficient_pool"),
        (
            _command(release_id, categories, lower, upper, upper - lower + 1),
            "insufficient_pool",
        ),
        (_command(release_id, categories, upper, lower), "invalid_rules"),
    ]:
        _denied(
            partial(start_freeplay, session, owners[0], invalid),
            code,
            422,
        )
        assert (
            session.exec(
                select(GameOperation).where(
                    GameOperation.owner_id == owners[0],
                    GameOperation.operation_id == invalid.operation_id,
                )
            ).first()
            is None
        )
    assert (
        len(session.exec(select(GameRun).where(GameRun.owner_id == owners[0])).all())
        == count_before
    )

    # A bounded genuine real-data run reaches won only after exhaustion; no round cap.
    winning = start_freeplay(
        session, owners[0], _command(release_id, categories, lower, upper, 200)
    )
    while winning.status == "active":
        previous = winning
        winning = submit_placement(
            session, owners[0], winning.run_id, _placement(winning, events)
        )
        assert (
            winning.revision == previous.revision + 1
            and winning.streak == previous.streak + 1
        )
        _pair_gaps(winning, events)
    assert winning.status == "won" and winning.pending is None
    won_row = session.get(GameRun, winning.run_id, populate_existing=True)
    assert won_row is not None
    used = {c.event_id for c in winning.timeline}
    assert not any(
        UUID(id_) not in used
        and all(
            abs(events[UUID(id_)].year_index - events[placed].year_index) >= 200
            for placed in used
        )
        for id_ in won_row.pool
    )
    terminal_command = PlaceCommand(
        operation_id=uuid4(),
        expected_revision=winning.revision,
        event_id=winning.timeline[0].event_id,
        slot=0,
    )
    _denied(
        lambda: submit_placement(session, owners[0], winning.run_id, terminal_command),
        "terminal_state",
        409,
    )
    assert read_run(session, owners[0], winning.run_id) == winning

    losing = start_freeplay(
        session, owners[0], _command(release_id, categories, lower, upper)
    )
    wrong = _placement(losing, events, wrong=True)
    lost = submit_placement(session, owners[0], losing.run_id, wrong)
    assert lost.status == "lost" and lost.streak == losing.streak == 0
    assert (
        lost.revision == losing.revision + 1
        and lost.feedback is not None
        and not lost.feedback.correct
    )
    _revealed(lost, events)
    assert submit_placement(session, owners[0], losing.run_id, wrong) == lost
    _denied(
        lambda: submit_placement(
            session,
            owners[0],
            losing.run_id,
            wrong.model_copy(
                update={"operation_id": uuid4(), "expected_revision": lost.revision}
            ),
        ),
        "terminal_state",
        409,
    )
    assert read_run(session, owners[0], losing.run_id) == lost

    # Pick a trusted service-only day with BOTH it and next day unused. Never reset definitions.
    used_days = {d.day for d in session.exec(select(DailyDefinition)).all()}
    now = _unused_probe_day(used_days)
    overview = read_daily(session, owners[0], now)
    assert overview.attempt_run_id is None
    assert overview.category_ids == ["battles", "exploration", "inventions", "politics"]
    definition = session.exec(
        select(DailyDefinition).where(DailyDefinition.day == now.date())
    ).one()
    frozen_definition = definition.model_dump()
    dailies = [
        start_daily(session, owner, DailyStart(operation_id=uuid4()), now)
        for owner in owners
    ]
    assert (
        dailies[0].timeline == dailies[1].timeline
        and dailies[0].pending == dailies[1].pending
    )
    assert dailies[0].timeline[0].event_id == definition.anchor_event_id
    rows = [session.get(GameRun, d.run_id) for d in dailies]
    for item in rows:
        assert item is not None
        assert (item.seed, item.order, item.pool, item.rules) == (
            definition.seed,
            definition.order,
            definition.pool,
            definition.rules,
        )
    for _ in range(3):
        dailies = [
            submit_placement(
                session, owner, response.run_id, _placement(response, events)
            )
            for owner, response in zip(owners, dailies, strict=True)
        ]
        assert (
            dailies[0].timeline == dailies[1].timeline
            and dailies[0].pending == dailies[1].pending
        )
        for response in dailies:
            _pair_gaps(response, events)
            _privacy(response)
    for owner, response in zip(owners, dailies, strict=True):
        assert (
            start_daily(session, owner, DailyStart(operation_id=uuid4()), now)
            == response
        )
        attempts = session.exec(
            select(GameRun).where(
                GameRun.owner_id == owner, GameRun.daily_definition_id == definition.id
            )
        ).all()
        assert len(attempts) == 1

    frozen_free = session.get(GameRun, moved.run_id, populate_existing=True)
    assert frozen_free is not None
    free_snapshot = frozen_free.model_dump()
    daily_snapshots = []
    for daily in dailies:
        daily_row = session.get(GameRun, daily.run_id)
        assert daily_row is not None
        daily_snapshots.append(daily_row.model_dump())
    # Reuse the existing offline C5 fixture builder, never fabricate database rows.
    from tests.api.routes.test_game_daily import release as build_fixture

    private_build = settings.GAME_DATA_DIR.resolve() / ("probe-switch-" + uuid4().hex)
    private_build.parent.mkdir(parents=True, exist_ok=True)
    try:
        fixture_id = build_fixture(session, private_build)
        fixture_root = private_build / "releases" / fixture_id
        fixture_manifest = verify_release(
            fixture_root, fixture_root / "media", require_beta=False
        )
        assert fixture_manifest.fixture and fixture_manifest.event_count == 8
        assert load_options(session).release_id == fixture_id
        fresh = start_freeplay(
            session,
            owners[0],
            _command(fixture_id, ["battles", "politics"], 1000, 2000),
        )
        assert fresh.catalog_release_id == fixture_id
        assert read_run(session, owners[0], moved.run_id) == moved
        frozen_free = session.get(GameRun, moved.run_id, populate_existing=True)
        assert frozen_free is not None and frozen_free.model_dump() == free_snapshot
        for owner, response, snapshot in zip(
            owners, dailies, daily_snapshots, strict=True
        ):
            assert read_run(session, owner, response.run_id) == response
            daily_row = session.get(GameRun, response.run_id, populate_existing=True)
            assert daily_row is not None and daily_row.model_dump() == snapshot
            assert (
                start_daily(session, owner, DailyStart(operation_id=uuid4()), now)
                == response
            )
        assert read_daily(session, owners[0], now).attempt_run_id == dailies[0].run_id
        frozen_row = session.get(DailyDefinition, definition.id, populate_existing=True)
        assert frozen_row is not None and frozen_row.model_dump() == frozen_definition
        moved = submit_placement(
            session, owners[0], moved.run_id, _placement(moved, events)
        )
        assert moved.catalog_release_id == release_id and moved.streak == 2
        dailies = [
            submit_placement(
                session, owner, response.run_id, _placement(response, events)
            )
            for owner, response in zip(owners, dailies, strict=True)
        ]
        assert dailies[0].timeline == dailies[1].timeline and dailies[0].streak == 4
        for response in [moved, *dailies]:
            assert response.catalog_release_id == release_id
            _revealed(response, events)
            _privacy(response)
        # Old exact operation retry remains exact even after later moves and a switch.
        assert submit_placement(session, owners[0], moved.run_id, command).revision == 1
    finally:
        session.rollback()
        assert (
            activate_catalog(session, release_dir, media_dir, require_beta=True)
            == release_id
        )
        session.commit()
    assert load_options(session).release_id == release_id
    next_now = now + timedelta(days=1)
    next_daily = start_daily(
        session, owners[0], DailyStart(operation_id=uuid4()), next_now
    )
    next_definition = session.exec(
        select(DailyDefinition).where(DailyDefinition.day == next_now.date())
    ).one()
    assert (
        next_definition.id != definition.id
        and next_definition.catalog_release_id == release_id
    )
    assert (
        next_daily.catalog_release_id == release_id
        and next_daily.daily_date == next_now.date()
    )
    frozen_row = session.get(DailyDefinition, definition.id, populate_existing=True)
    assert frozen_row is not None and frozen_row.model_dump() == frozen_definition

    # Release all locks, discard ORM identity state, then read via another connection/session.
    session.rollback()
    engine.dispose()
    with Session(engine) as restarted:
        assert load_options(restarted).release_id == release_id
        for owner, expected in [
            (owners[0], moved),
            (owners[0], winning),
            (owners[0], lost),
            *zip(owners, dailies, strict=True),
            (owners[0], next_daily),
        ]:
            assert read_run(restarted, owner, expected.run_id) == expected
        frozen_row = restarted.get(DailyDefinition, definition.id)
        assert frozen_row is not None and frozen_row.model_dump() == frozen_definition
    return {
        "daily_day": now.date().isoformat(),
        "next_day": next_now.date().isoformat(),
        "fixture_release_id": fixture_id,
        "category_counts": {
            category: sum(category in e.category_ids for e in events.values())
            for category in CATEGORY_IDS
        },
        "checks": dict.fromkeys(
            (
                "real_catalog_options",
                "idempotent_activation",
                "pending_privacy",
                "pending_text_credits",
                "revealed_sources_credits",
                "inclusive_bounds_category_union",
                "all_pairs_gap",
                "zero_streak_anchor",
                "correct_move_exact_retry",
                "wrong_move_no_streak_gain",
                "invalid_sparse_no_run",
                "terminal_immutability",
                "ownership_denial",
                "daily_shared_prefix_one_attempt",
                "daily_frozen_definition",
                "switch_new_freeplay_old_runs_frozen",
                "selection_restored",
                "next_day_real_release",
                "restart_separate_session",
            ),
            True,
        ),
    }


def run_probe(
    release_dir: Path, media_dir: Path, report_path: Path
) -> dict[str, object]:
    require_local_probe_target(
        settings.POSTGRES_DB, settings.POSTGRES_SERVER, settings.ENVIRONMENT
    )
    _require_report_target(release_dir, media_dir, report_path)
    # Verification MUST precede the first Session construction and every activation.
    manifest = verify_release(release_dir, media_dir, require_beta=True)
    assert not manifest.fixture and manifest.event_count >= 1000
    manifest_bytes = (release_dir / "manifest.json").read_bytes()
    with Session(engine) as session:
        release_id = activate_catalog(
            session, release_dir, media_dir, require_beta=True
        )
        session.commit()
        row = session.get(CatalogRelease, release_id)
        assert row is not None and row.manifest_bytes == manifest_bytes
        before = row.model_dump()
        count_before = len(
            session.exec(
                select(EventRevision).where(EventRevision.release_id == release_id)
            ).all()
        )
        assert count_before == manifest.event_count
        assert (
            activate_catalog(session, release_dir, media_dir, require_beta=True)
            == release_id
        )
        session.commit()
        row = session.get(CatalogRelease, release_id, populate_existing=True)
        assert row is not None and row.model_dump() == before
        assert (
            len(
                session.exec(
                    select(EventRevision).where(EventRevision.release_id == release_id)
                ).all()
            )
            == count_before
        )
        result = _exercise_services(session, release_dir, media_dir, release_id)
    report: dict[str, object] = {
        "passed": True,
        "release_id": release_id,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "event_count": manifest.event_count,
        "asset_hashes": {
            name: digest
            for name, digest in manifest.files.items()
            if name.startswith("media/")
        },
        "database": settings.POSTGRES_DB,
        "host": settings.POSTGRES_SERVER,
        "port": settings.POSTGRES_PORT,
        "environment": settings.ENVIRONMENT,
        **result,
    }
    assert (release_dir / "manifest.json").read_bytes() == manifest_bytes
    _write_report(report_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--media", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    writable_report = False
    try:
        _require_report_target(args.release, args.media, args.report)
        writable_report = True
        run_probe(args.release, args.media, args.report)
    except Exception:
        # Do not echo exception text: DB errors can contain credentials/private payloads.
        if writable_report:
            try:
                _write_report(args.report, {"passed": False, "error": "probe_failed"})
            except OSError:
                pass
        sys.stderr.write("real catalog probe failed; no success claimed\n")
        return 1
    sys.stdout.write("real catalog probe passed; sanitized private report written\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
