"""Run alone on a NEW owned lives_backend_test DB; never use retained state.

Invoke this file explicitly: its name keeps it out of normal pytest discovery.
This acceptance test intentionally overrides the inherited init/delete fixture.
It runs real prestart, leaves evidence intact, and requires an empty schema.
See docs/operations/catalogue.md for the offline container procedure.
"""

import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlmodel import Session, select, text

from app.content.runtime import verify_default
from app.core.config import settings
from app.core.db import engine
from app.game.guest_models import GuestSession
from app.game.models import CatalogSelection, EventRevision
from app.main import app
from app.models import User
from tests.browser.guest_test_environment import (
    _maintenance_connection,
    require_owned_guest_database,
)
from tests.db_guard import require_test_database

BACKEND = Path(__file__).resolve().parents[3]
BASE = "/api/v1/games"


@pytest.fixture(scope="session", autouse=True)
def db() -> None:
    """Refuse setup before prestart can touch anything but a new owned schema."""
    require_test_database(settings.POSTGRES_DB)
    assert settings.POSTGRES_DB == "historical_date_game_lives_backend_test"
    assert settings.POSTGRES_SERVER == "127.0.0.1" and settings.POSTGRES_PORT == 5433
    require_owned_guest_database()
    with _maintenance_connection() as connection:
        assert connection.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = %s",
            (settings.POSTGRES_DB,),
        ).fetchone() == (0,), "Refusing acceptance while target has consumers"
    assert inspect(engine).get_table_names() == [], "Requires a NEW empty schema"
    engine.dispose()


def test_packaged_prestart_is_playable_offline_and_preserves_state() -> None:
    # Removing the catalogue COPY or initialization step must break this test.
    startup = subprocess.run(
        ["bash", "scripts/prestart.sh"], cwd=BACKEND, capture_output=True, text=True
    )
    assert startup.returncode == 0, startup.stdout + startup.stderr
    snapshot = verify_default(BACKEND / "catalogue")
    release_id = "chronology-1276-runtime-v2"
    assert snapshot.manifest.release_id == release_id
    assert snapshot.manifest.event_count == 1276
    assert settings.GAME_DATA_DIR == BACKEND / "catalogue"
    with Session(engine) as session:
        account = session.exec(select(User)).one()
        assert account.email == settings.FIRST_SUPERUSER and account.is_superuser
        assert len(session.exec(select(EventRevision)).all()) == 1276
        selected = session.get(CatalogSelection, 1)
        assert selected is not None and selected.release_id == release_id

    with TestClient(app) as player, TestClient(app) as other:
        with Session(engine) as session:
            identities_before = set(session.exec(select(User.id)).all())
            sessions_before = set(session.exec(select(GuestSession.token_digest)).all())
        options_response = player.get(BASE + "/options")
        assert options_response.status_code == 200
        assert not player.cookies and "set-cookie" not in options_response.headers
        with Session(engine) as session:
            assert set(session.exec(select(User.id)).all()) == identities_before
            assert (
                set(session.exec(select(GuestSession.token_digest)).all())
                == sessions_before
            )
        options = options_response.json()
        assert options["catalog_release_id"] == release_id
        assert options["protocol_version"] == 2 and options["categories"]
        assert player.get("/api/v1/users/me").status_code == 401
        headers = {"Origin": settings.FRONTEND_HOST, "X-Game-Request": "1"}
        bootstrap = player.post(BASE + "/session", headers=headers)
        assert bootstrap.status_code == 200 and bootstrap.json()["kind"] == "guest"
        player.headers.update(
            {**headers, "X-Game-Context": bootstrap.json()["context_id"]}
        )
        second = other.post(BASE + "/session", headers=headers)
        assert second.status_code == 200
        other.headers.update({**headers, "X-Game-Context": second.json()["context_id"]})
        starts = (
            ("daily", {"protocol_version": 2, "operation_id": str(uuid4())}),
            (
                "freeplay",
                {
                    "protocol_version": 2,
                    "operation_id": str(uuid4()),
                    "catalog_release_id": release_id,
                    "config": {
                        "category_ids": [c["id"] for c in options["categories"]],
                        "start": options["start"],
                        "end": options["end"],
                        "min_gap": 1,
                    },
                },
            ),
        )
        for mode, command in starts:
            response = player.post(BASE + "/" + mode, json=command)
            assert response.status_code == 200, response.text
            initial = response.json()
            assert initial["mode"] == mode and initial["status"] == "active"
            assert initial["catalog_release_id"] == release_id
            assert set(initial["pending"]) == {
                "event_id",
                "prompt",
                "category_ids",
                "media",
            }
            for private in (
                "year_index",
                "identity_key",
                "owner_id",
                "seed",
                "pool",
                "order",
            ):
                assert f'"{private}"' not in response.text
            for card in [*initial["timeline"], initial["pending"]]:
                media = card["media"]
                assert media["credits"] and any(
                    "CC0" in c["label"] for c in media["credits"]
                )
                for url in (media["url"], media["fallback_url"]):
                    assert url.startswith(f"/media/{release_id}/")
                    asset = player.get(url)
                    assert asset.status_code == 200
                    assert asset.content == snapshot.assets[url.rsplit("/", 1)[1]]
                    assert player.head(url).status_code == 200
            revealed = initial["timeline"][0]
            assert revealed["sources"] and all(
                s["url"].startswith("https://") for s in revealed["sources"]
            )
            assert revealed["learn_more"]["kind"] == "source"
            assert revealed["learn_more"]["url"] in {
                s["url"] for s in revealed["sources"]
            }
            run_url = BASE + "/runs/" + initial["run_id"]
            assert other.get(run_url).status_code == 404
            assert player.post(BASE + "/" + mode, json=command).json() == initial
            events = {event.event_id: event for event in snapshot.events}
            pending_id = UUID(initial["pending"]["event_id"])
            year = events[pending_id].year_index
            move = {
                "protocol_version": 2,
                "operation_id": str(uuid4()),
                "expected_revision": 0,
                "event_id": str(pending_id),
                "slot": sum(
                    events[UUID(card["event_id"])].year_index < year
                    for card in initial["timeline"]
                ),
            }
            moved = player.post(run_url + "/placements", json=move)
            assert moved.status_code == 200
            assert moved.json()["revision"] == moved.json()["score"] == 1
            assert moved.json()["feedback"]["card"]["event_id"] == str(
                UUID(initial["pending"]["event_id"])
            )
            assert "year" in moved.json()["feedback"]["card"]
            assert (
                player.post(run_url + "/placements", json=move).json() == moved.json()
            )
            assert player.get(run_url).json() == moved.json()
            assert other.post(run_url + "/placements", json=move).status_code == 404

        # Probe actual installed answer/lock/notice files, not synthetic secrets.
        for name in (
            "events.jsonl",
            "runtime-manifest.json",
            "build.lock.json",
            "attribution.json",
            "NOTICE.catalog.md",
        ):
            for path in (
                f"/catalogue/releases/{release_id}/{name}",
                f"/media/{release_id}/{name}",
                f"/media/%2e%2e/releases/{release_id}/{name}",
                f"/media/{release_id}/%2e%2e/%2e%2e/releases/{release_id}/{name}",
                f"/media/{release_id}/%2f..%2f..%2freleases/{release_id}/{name}",
                f"/@fs/{BACKEND}/catalogue/releases/{release_id}/{name}",
            ):
                assert player.get(path).status_code == 404, path
        assert player.get("/catalogue/default.json").status_code == 404

    # Snapshot EVERY row (including credentials/guest sessions/operations), not
    # just counts: repeated actual prestart must preserve complete state.
    tables = inspect(engine).get_table_names()
    states = []
    for _ in range(2):
        with Session(engine) as session:
            states.append(
                {
                    table: session.execute(
                        text(
                            f'SELECT to_jsonb(t)::text FROM "{table}" t ORDER BY to_jsonb(t)::text'
                        )
                    )
                    .scalars()
                    .all()
                    for table in tables
                }
            )
        engine.dispose()
        if len(states) == 1:
            require_owned_guest_database()
            again = subprocess.run(
                ["bash", "scripts/prestart.sh"],
                cwd=BACKEND,
                capture_output=True,
                text=True,
            )
            assert again.returncode == 0, again.stdout + again.stderr
    assert states[0] == states[1]
