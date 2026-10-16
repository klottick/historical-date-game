"""B5 HTTP contracts exercise real services, PostgreSQL, and published fixtures."""

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from starlette.routing import Mount

from app.core.config import settings
from app.core.security import create_access_token
from app.game import daily_service
from app.game.catalog_repository import load_events
from app.game.models import CatalogSelection, DailyDefinition, GameRun
from app.game.run_repository import load_media
from app.game.schemas import RunPublic
from app.main import app
from tests.api.routes import test_game_daily, test_game_runs
from tests.api.routes.test_game_runs import correct_command, start_command

game_context = test_game_runs.game_context
daily_context = test_game_daily.daily_context

BASE = f"{settings.API_V1_STR}/games"


def headers(owner: UUID) -> dict[str, str]:
    token = create_access_token(owner, timedelta(minutes=10))
    return {"Authorization": f"Bearer {token}"}


def test_owned_games_require_a_game_session(client: TestClient) -> None:
    for method, path in (
        ("post", "/freeplay"),
        ("get", "/active-runs"),
        ("get", f"/runs/{uuid4()}"),
        ("post", f"/runs/{uuid4()}/placements"),
        ("get", "/daily"),
        ("post", "/daily"),
        ("get", "/daily/2026-10-12/leaderboard"),
    ):
        # Valid mutation protections do not substitute for a player credential.
        response = client.request(
            method,
            BASE + path,
            headers={"Origin": settings.FRONTEND_HOST, "X-Game-Request": "1"},
        )
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "game_session_required"


def test_http_commands_reject_answers_and_score(
    client: TestClient, game_context: tuple[UUID, str]
) -> None:
    owner, release_id = game_context
    command = start_command(release_id).model_dump(mode="json")
    for field in ("answer", "score", "seed", "pool", "order"):
        assert (
            client.post(
                BASE + "/freeplay", headers=headers(owner), json={**command, field: 1}
            ).status_code
            == 422
        )
    for config in (
        {**command["config"], "year": 1800},
        {**command["config"], "min_gap": 0},
        {**command["config"], "min_gap": "1"},
        {**command["config"], "start": {"value": 0, "era": "CE"}},
    ):
        assert (
            client.post(
                BASE + "/freeplay",
                headers=headers(owner),
                json={**command, "config": config},
            ).status_code
            == 422
        )
    response = client.post(BASE + "/freeplay", headers=headers(owner), json=command)
    assert response.status_code == 200
    run = response.json()
    place = {
        "protocol_version": 2,
        "operation_id": str(uuid4()),
        "expected_revision": 0,
        "event_id": run["pending"]["event_id"],
        "slot": 0,
    }
    for field in ("answer", "year", "score", "seed"):
        assert (
            client.post(
                BASE + f"/runs/{run['run_id']}/placements",
                headers=headers(owner),
                json={**place, field: 1},
            ).status_code
            == 422
        )
    for field in ("day", "seed", "config", "score"):
        assert (
            client.post(
                BASE + "/daily",
                headers=headers(owner),
                json={
                    "protocol_version": 2,
                    "operation_id": str(uuid4()),
                    field: "2026-01-01",
                },
            ).status_code
            == 422
        )
    assert (
        client.get(BASE + "/runs/not-a-uuid", headers=headers(owner)).status_code == 422
    )
    assert (
        client.get(
            BASE + "/daily/not-a-day/leaderboard", headers=headers(owner)
        ).status_code
        == 422
    )


def test_error_status_and_resume(
    client: TestClient,
    db: Session,
    game_context: tuple[UUID, str],
    superuser_token_headers: dict[str, str],
) -> None:
    owner, release_id = game_context
    auth = headers(owner)
    command = start_command(release_id).model_dump(mode="json")
    started = client.post(BASE + "/freeplay", headers=auth, json=command)
    assert started.status_code == 200
    run = started.json()
    url = BASE + f"/runs/{run['run_id']}"
    assert client.get(url, headers=auth).json() == run
    assert client.get(BASE + "/active-runs", headers=auth).json() == [run]
    for target in (url, BASE + f"/runs/{uuid4()}"):
        response = client.get(target, headers=superuser_token_headers)
        assert response.status_code == 404
        assert response.json()["detail"] == {
            "code": "run_not_found",
            "message": "Run not found",
        }
    assert (
        client.get(BASE + "/active-runs", headers=superuser_token_headers).json() == []
    )
    public = RunPublic.model_validate_json(started.text)
    place = correct_command(db, public).model_dump(mode="json")
    assert (
        client.post(
            url + "/placements", headers=superuser_token_headers, json=place
        ).status_code
        == 404
    )
    for changes, code, status in (
        ({"expected_revision": 99}, "stale_revision", 409),
        ({"event_id": str(uuid4())}, "stale_event", 409),
        ({"slot": 99}, "invalid_slot", 422),
    ):
        response = client.post(
            url + "/placements", headers=auth, json={**place, **changes}
        )
        assert response.status_code == status
        assert response.json()["detail"]["code"] == code
        assert isinstance(response.json()["detail"]["message"], str)
    placed = client.post(url + "/placements", headers=auth, json=place)
    assert placed.status_code == 200 and placed.json()["streak"] == 1
    assert (
        client.post(url + "/placements", headers=auth, json=place).json()
        == placed.json()
    )
    assert client.get(url, headers=auth).json() == placed.json()
    reused = client.post(
        url + "/placements", headers=auth, json={**place, "slot": place["slot"] + 1}
    )
    assert (
        reused.status_code == 409
        and reused.json()["detail"]["code"] == "operation_conflict"
    )
    assert client.post(BASE + "/freeplay", headers=auth, json=command).json() == run
    # Public cards retain credits and origin URLs, but pending never has an answer.
    assert set(run["pending"]) == {"event_id", "prompt", "category_ids", "media"}
    for card in [*run["timeline"], run["pending"]]:
        assert card["media"]["credits"]
        assert card["media"]["url"].startswith(f"/media/{release_id}/")
        assert card["media"]["fallback_url"].endswith(".svg")
    assert run["timeline"][0]["sources"][0]["url"].startswith("https://")
    for private in (
        '"seed"',
        '"pool"',
        '"order"',
        '"owner_id"',
        '"year_index"',
        '"identity_key"',
        '"raw_date"',
    ):
        assert private not in started.text + placed.text
    # Finish via HTTP so every fixture card (including the pictured one) crosses
    # the response boundary; mandatory source/license/fallback credits survive.
    completed = RunPublic.model_validate_json(placed.text)
    while completed.status == "active":
        response = client.post(
            url + "/placements",
            headers=auth,
            json=correct_command(db, completed).model_dump(mode="json"),
        )
        assert response.status_code == 200
        completed = RunPublic.model_validate_json(response.text)
    events = load_events(db, release_id)
    assets = load_media(db, release_id)
    pictured = 0
    for card in completed.timeline:
        event = events[card.event_id]
        fallback = assets["fallback:" + event.fallback_key]
        expected = []
        if event.media_asset_id is not None:
            pictured += 1
            asset = assets["asset:" + str(event.media_asset_id)]
            expected.append({"label": asset.attribution, "url": asset.source_url})
            if asset.license_url is not None:
                expected.append({"label": asset.rights_basis, "url": asset.license_url})
        expected.append(
            {"label": f"{fallback.creator} / {fallback.rights_basis}", "url": None}
        )
        assert [credit.model_dump() for credit in card.media.credits] == expected
        assert [source.url for source in card.sources] == [
            source.url for source in event.sources
        ]
    assert pictured > 0
    assert completed.status == "won"
    assert client.get(BASE + "/active-runs", headers=auth).json() == []


def test_options_and_public_config(
    client: TestClient, game_context: tuple[UUID, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, release_id = game_context
    for enabled in (False, True):
        monkeypatch.setattr(settings, "PUBLIC_REGISTRATION_ENABLED", enabled)
        config = client.get(settings.API_V1_STR + "/utils/public-config")
        assert config.status_code == 200
        assert config.json() == {"registration_open": enabled}
        response = client.get(BASE + "/options", headers=headers(owner))
        assert response.status_code == 200
        assert response.json()["catalog_release_id"] == release_id
        assert response.json()["registration_open"] is enabled
    assert set(response.json()) == {
        "protocol_version",
        "catalog_release_id",
        "categories",
        "start",
        "end",
        "registration_open",
    }


def test_catalog_and_daily_unavailable(
    client: TestClient,
    db: Session,
    game_context: tuple[UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, release_id = game_context
    pointer = db.get(CatalogSelection, 1)
    assert pointer is not None
    db.delete(pointer)
    db.commit()
    try:
        for method, path, body in (
            ("GET", "/options", None),
            ("POST", "/freeplay", start_command(release_id).model_dump(mode="json")),
        ):
            response = client.request(
                method, BASE + path, headers=headers(owner), json=body
            )
            assert response.status_code == 503
            assert response.json()["detail"] == {
                "code": "catalog_unavailable",
                "message": "Game catalog unavailable",
            }
    finally:
        db.add(CatalogSelection(release_id=release_id))
        db.commit()
    # Missing or invalid packaged policy must not allocate a Daily attempt.
    monkeypatch.setattr(
        daily_service, "utc_now", lambda: datetime(2200, 1, 1, tzinfo=UTC)
    )

    def missing_policy() -> None:
        raise FileNotFoundError("private policy location")

    monkeypatch.setattr(daily_service, "load_daily_config", missing_policy)
    for method, body in (
        ("GET", None),
        ("POST", {"protocol_version": 2, "operation_id": str(uuid4())}),
    ):
        response = client.request(
            method, BASE + "/daily", headers=headers(owner), json=body
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "catalog_unavailable"
        assert "private policy" not in response.text
    assert not db.exec(select(GameRun).where(GameRun.owner_id == owner)).all()


def test_daily_http_uses_server_utc_and_packaged_proper_pool(
    client: TestClient,
    db: Session,
    daily_context: tuple[list[UUID], str, datetime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owners, release_id, now = daily_context
    # Local calendar day differs: server must normalize to UTC, never take query day.
    clock = datetime.combine(now.date(), datetime.min.time(), UTC) - timedelta(
        minutes=30
    )
    monkeypatch.setattr(
        daily_service,
        "utc_now",
        lambda: clock.astimezone(timezone(timedelta(hours=14))),
    )
    response = client.get(
        BASE + "/daily?day=1900-01-01&seed=attacker", headers=headers(owners[0])
    )
    assert response.status_code == 200
    overview = response.json()
    assert overview["day"] == clock.date().isoformat()
    assert overview["reset_at"] == datetime.combine(
        now.date(), datetime.min.time(), UTC
    ).isoformat().replace("+00:00", "Z")
    assert overview["category_ids"] == [
        "battles",
        "exploration",
        "inventions",
        "politics",
    ]
    assert overview["attempt_run_id"] is None
    definition = db.exec(
        select(DailyDefinition).where(DailyDefinition.day == clock.date())
    ).one()
    events = load_events(db, release_id)
    assert len(definition.pool) == 6 < len(events) == 8
    assert all(
        set(events[UUID(id_)].category_ids) & set(overview["category_ids"])
        for id_ in definition.pool
    )
    command = {"protocol_version": 2, "operation_id": str(uuid4())}
    first = client.post(BASE + "/daily", headers=headers(owners[0]), json=command)
    assert first.status_code == 200
    second = client.post(
        BASE + "/daily",
        headers=headers(owners[1]),
        json={"protocol_version": 2, "operation_id": str(uuid4())},
    )
    assert second.status_code == 200
    assert first.json()["timeline"] == second.json()["timeline"]
    assert first.json()["pending"] == second.json()["pending"]
    assert first.json()["daily_date"] == clock.date().isoformat()
    assert (
        client.get(BASE + "/daily", headers=headers(owners[0])).json()["attempt_run_id"]
        == first.json()["run_id"]
    )
    monkeypatch.setattr(daily_service, "utc_now", lambda: clock + timedelta(days=1))
    assert (
        client.post(BASE + "/daily", headers=headers(owners[0]), json=command).json()
        == first.json()
    )
    run = RunPublic.model_validate_json(first.text)
    while run.status == "active":
        placed = client.post(
            BASE + f"/runs/{run.run_id}/placements",
            headers=headers(owners[0]),
            json=correct_command(db, run).model_dump(mode="json"),
        )
        assert placed.status_code == 200
        run = RunPublic.model_validate_json(placed.text)
    leaderboard = client.get(
        BASE + f"/daily/{clock.date()}/leaderboard", headers=headers(owners[1])
    )
    assert leaderboard.status_code == 200
    assert leaderboard.json() == {
        "day": clock.date().isoformat(),
        "entries": [
            {
                "display_name": "Ada",
                "streak": 5,
                "score": 5,
                "status": "won",
                "rank": 1,
            }
        ],
    }


def test_media_mount_cannot_expose_catalog(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mount = next(
        (
            route
            for route in app.routes
            if isinstance(route, Mount) and route.path == "/media"
        ),
        None,
    )
    assert mount is not None, "Only the media subtree must be mounted"
    assert Path(mount.app.directory) == settings.GAME_DATA_DIR / "media"
    media = tmp_path / "media"
    release = media / "release"
    release.mkdir(parents=True)
    asset = "a" * 64 + ".svg"
    (release / asset).write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    (tmp_path / "events.jsonl").write_text("secret year 1800")
    for name in (
        "manifest.json",
        "catalog.json",
        "events.jsonl",
        "index.html",
        "1800.svg",
    ):
        (release / name).write_text("private answers")
    (release / ("b" * 64 + ".svg")).symlink_to(tmp_path / "events.jsonl")
    (release / ("c" * 64 + ".svg")).symlink_to(release / asset)
    (media / "alias").symlink_to(release, target_is_directory=True)
    monkeypatch.setattr(mount, "app", type(mount.app)(media))
    assert client.get(f"/media/release/{asset}").status_code == 200
    assert client.head(f"/media/release/{asset}").status_code == 200
    for path in (
        "/",
        "/release/",
        "/events.jsonl",
        "/release/manifest.json",
        "/release/catalog.json",
        "/release/events.jsonl",
        "/release/index.html",
        "/release/1800.svg",
        "/release/%2e%2e/events.jsonl",
        "/%2e%2e/events.jsonl",
        "/release/%2f..%2fevents.jsonl",
        "/release/" + "b" * 64 + ".svg",
        "/release/" + "c" * 64 + ".svg",
        f"/alias/{asset}",
        f"/release/sub/{asset}",
        f"/release/{asset}%00",
    ):
        response = client.get("/media" + path)
        assert response.status_code == 404, path
        assert (
            "private answers" not in response.text
            and "secret year" not in response.text
        )
    monkeypatch.setattr(mount, "app", type(mount.app)(tmp_path / "absent" / "media"))
    assert client.get(f"/media/release/{asset}").status_code == 404
    (tmp_path / "linked-media").symlink_to(media, target_is_directory=True)
    monkeypatch.setattr(mount, "app", type(mount.app)(tmp_path / "linked-media"))
    assert client.get(f"/media/release/{asset}").status_code == 404


def test_daily_policy_is_packaged_and_matches_research(tmp_path: Path) -> None:
    from importlib.resources import files

    resource = files("app.game").joinpath("source-selection.json")
    assert resource.is_file(), "Daily policy must ship in the backend package"
    policy = resource.read_bytes()
    assert policy == Path("../docs/research/source-selection.json").read_bytes()
    # Docker's backend-only context has no root docs. Run an actual copied package.
    shutil.copytree(
        "app", tmp_path / "app", ignore=shutil.ignore_patterns("__pycache__")
    )
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    command = [
        sys.executable,
        "-c",
        "from app.game.daily_config import load_daily_config; import json; print(json.dumps(load_daily_config().category_ids))",
    ]
    result = subprocess.run(
        command, cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        "battles",
        "inventions",
        "exploration",
        "politics",
    ]
    copied_policy = tmp_path / "app/game/source-selection.json"
    copied_policy.write_text(policy.decode().replace('"battles"', '"unknown"'))
    assert (
        subprocess.run(command, cwd=tmp_path, env=env, capture_output=True).returncode
        != 0
    )
    copied_policy.unlink()
    assert (
        subprocess.run(command, cwd=tmp_path, env=env, capture_output=True).returncode
        != 0
    )


def test_openapi_exposes_only_public_game_models() -> None:
    schema = app.openapi()
    assert BASE + "/options" in schema["paths"]
    models = schema["components"]["schemas"]
    for private in (
        "EventRecord",
        "SourceCitation",
        "SourceSelection",
        "GameRun",
        "DailyDefinition",
        "MediaAsset",
        "GuestSession",
        "GamePlayer",
    ):
        assert private not in models
    for name in (
        "PendingCard",
        "RunPublic",
        "GameOptions",
        "DailyOverview",
        "LeaderboardEntry",
        "GameSessionPublic",
    ):
        fields = models[name]["properties"]
        assert (
            not {"seed", "order", "pool", "owner_id", "identity_key", "year_index"}
            & fields.keys()
        )
        assert models[name]["additionalProperties"] is False
    assert set(models["GameSessionPublic"]["properties"]) == {
        "protocol_version",
        "kind",
        "context_id",
    }
    assert models["GameSessionPublic"]["properties"]["kind"]["enum"] == [
        "guest",
        "account",
    ]
    session_routes = schema["paths"][BASE + "/session"]
    assert session_routes["get"]["operationId"] == "games-read_game_session"
    assert session_routes["post"]["operationId"] == "games-bootstrap_game_session"
    for path, methods in schema["paths"].items():
        if path.startswith(BASE):
            for operation in methods.values():
                if path == BASE + "/options":
                    assert not operation.get("security")
                else:
                    # Keep SDK bearer attachment while allowing cookie sessions.
                    assert operation["security"] == [
                        {"OAuth2PasswordBearer": []},
                        {},
                    ]
                assert all(
                    p["name"] != "require_context"
                    for p in operation.get("parameters", [])
                )
    assert set(models["PendingCard"]["properties"]) == {
        "event_id",
        "prompt",
        "category_ids",
        "media",
    }
