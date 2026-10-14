"""No evidence/pending leaks, no scoring network, immutable operation links."""

import hashlib
import importlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlmodel import Session, select, text

from app.game.catalog_repository import load_events
from app.game.models import CatalogRelease, GameOperation
from app.game.run_service import read_run, submit_placement
from tests.api.routes import test_game_runs
from tests.api.routes.test_game_runs import correct_command, start

game_context = test_game_runs.game_context


def install_sidecar(
    db: Session,
    context_release: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    **changes: Any,
) -> Any:
    api = importlib.import_module("app.game.event_links")
    records = {}
    for event in load_events(db, context_release).values():
        records[str(event.event_id)] = {
            "event_id": str(event.event_id),
            "kind": "article",
            "label": "Wikipedia article",
            "url": "https://en.wikipedia.org/wiki/Synthetic_Ada",
            "source_url": event.sources[0].url,
            "source_revision": 202,
            "evidence_sha256": "a" * 64,
            "reason": "verified_source_article",
        }
    payload = {
        "schema_version": 1,
        "policy_version": "event-links-v1",
        "release_id": context_release,
        "manifest_sha256": db.get(CatalogRelease, context_release).manifest_sha256,
        "records": records,
        **changes,
    }
    file = tmp_path / "links.json"
    file.write_text(json.dumps(payload))
    loaded = api.load_event_links(file, hashlib.sha256(file.read_bytes()).hexdigest())
    monkeypatch.setattr(api, "_links", loaded)
    return api


def test_pending_projection_has_no_learn_more_or_answer(
    db: Session, game_context: tuple[UUID, str]
) -> None:
    response = start(db, game_context)
    assert set(response.pending.model_dump(mode="json")) == {
        "event_id",
        "prompt",
        "category_ids",
        "media",
    }
    assert "learn_more" not in response.pending.model_dump_json()
    assert response.timeline[0].learn_more is not None
    assert set(response.timeline[0].learn_more.model_dump()) == {"kind", "label", "url"}


@pytest.mark.parametrize(
    "changes",
    [
        {"release_id": "other"},
        {"manifest_sha256": "b" * 64},
        {"schema_version": 2},
        {"records": {}},
    ],
)
def test_wrong_release_or_corrupt_sidecar_never_breaks_projection(
    db: Session,
    game_context: tuple[UUID, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, Any],
) -> None:
    install_sidecar(db, game_context[1], tmp_path, monkeypatch, **changes)
    response = start(db, game_context)
    assert response.timeline[0].learn_more.kind == "source"
    assert response.timeline[0].learn_more.url in {
        s.url
        for s in load_events(db, game_context[1])[response.timeline[0].event_id].sources
    }


def test_loader_rejects_digest_corruption_duplicate_keys_and_unsafe_urls(
    tmp_path: Path,
) -> None:
    api = importlib.import_module("app.game.event_links")
    file = tmp_path / "links.json"
    for body in (b"not json", b'{"schema_version":1,"schema_version":1}'):
        file.write_bytes(body)
        assert api.load_event_links(file, hashlib.sha256(body).hexdigest()) is None
    assert api.load_event_links(file, "a" * 64) is None
    assert api.load_event_links(tmp_path / "missing", "a" * 64) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"url": "https://evil.example/wiki/Synthetic_Ada"},
        {"url": "https://en.wikipedia.org/wiki/January_1"},
        {"evidence_sha256": None},
        {"event_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"},
    ],
)
def test_loader_rejects_invalid_record_before_public_projection(
    db: Session,
    game_context: tuple[UUID, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, Any],
) -> None:
    api = install_sidecar(db, game_context[1], tmp_path, monkeypatch)
    file = tmp_path / "links.json"
    payload = json.loads(file.read_bytes())
    for record in payload["records"].values():
        record.update(changes)
    file.write_text(json.dumps(payload))
    assert (
        api.load_event_links(file, hashlib.sha256(file.read_bytes()).hexdigest())
        is None
    )


def test_legacy_snapshot_missing_learn_more_remains_null_without_rewriting(
    db: Session, game_context: tuple[UUID, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.game import run_service

    response = start(db, game_context)
    correct = correct_command(db, response)
    command = correct.model_copy(update={"slot": 1 - correct.slot})
    record = run_service._record

    def old_writer(
        session: Session,
        owner_id: UUID,
        operation_id: UUID,
        scope: str,
        digest: str,
        outcome: Any,
    ) -> None:
        record(session, owner_id, operation_id, scope, digest, outcome)
        for pending in session.new:
            if isinstance(pending, GameOperation):
                pending.outcome["feedback"]["card"].pop("learn_more", None)
                for card in pending.outcome["timeline"]:
                    card.pop("learn_more", None)

    with monkeypatch.context() as legacy:
        legacy.setattr(run_service, "_record", old_writer)
        submit_placement(db, game_context[0], response.run_id, command)
    op = db.exec(
        select(GameOperation).where(GameOperation.operation_id == command.operation_id)
    ).one()
    before = db.execute(
        text("SELECT outcome::text FROM gameoperation WHERE id=:id"), {"id": op.id}
    ).scalar_one()
    replay = submit_placement(db, game_context[0], response.run_id, command)
    assert replay.feedback.card.learn_more is None
    assert all(card.learn_more is None for card in replay.timeline)
    assert (
        read_run(db, game_context[0], response.run_id).feedback.card.learn_more is None
    )
    after = db.execute(
        text("SELECT outcome::text FROM gameoperation WHERE id=:id"), {"id": op.id}
    ).scalar_one()
    assert before == after


def test_link_sidecar_for_other_event_is_not_projected(
    db: Session,
    game_context: tuple[UUID, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = install_sidecar(db, game_context[1], tmp_path, monkeypatch)
    real = next(iter(load_events(db, game_context[1]).values()))
    other = real.model_copy(update={"event_id": uuid4()})
    assert (
        api.link_for_event(
            other,
            game_context[1],
            db.get(CatalogRelease, game_context[1]).manifest_sha256,
        ).kind
        == "source"
    )


def test_replay_retains_original_link_snapshot(
    db: Session,
    game_context: tuple[UUID, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = install_sidecar(db, game_context[1], tmp_path, monkeypatch)
    response = start(db, game_context)
    command = correct_command(db, response)
    outcome = submit_placement(db, game_context[0], response.run_id, command)
    assert outcome.feedback.card.learn_more.kind == "article"
    assert outcome.timeline[command.slot].learn_more == outcome.feedback.card.learn_more
    op = db.exec(
        select(GameOperation).where(GameOperation.operation_id == command.operation_id)
    ).one()
    before = db.execute(
        text("SELECT outcome::text FROM gameoperation WHERE id=:id"), {"id": op.id}
    ).scalar_one()
    monkeypatch.setattr(api, "_links", None)
    assert submit_placement(db, game_context[0], response.run_id, command) == outcome
    assert read_run(db, game_context[0], response.run_id).feedback == outcome.feedback
    after = db.execute(
        text("SELECT outcome::text FROM gameoperation WHERE id=:id"), {"id": op.id}
    ).scalar_one()
    assert before == after


def test_cache_failure_uses_source_without_network_in_scoring(
    db: Session,
    game_context: tuple[UUID, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = install_sidecar(db, game_context[1], tmp_path, monkeypatch)
    monkeypatch.setattr(api, "_links", None)

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("gameplay invoked acquisition or file reading")

    monkeypatch.setattr(httpx.Client, "stream", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    response = start(db, game_context)
    outcome = submit_placement(
        db, game_context[0], response.run_id, correct_command(db, response)
    )
    assert outcome.feedback.card.learn_more.kind == "source"
    assert read_run(db, game_context[0], response.run_id).feedback == outcome.feedback
