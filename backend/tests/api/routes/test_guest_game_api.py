"""Game-only identity, CSRF, ownership and retry contracts over real HTTP jars."""

import hashlib
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, select, text

from app.api.deps import get_db
from app.core.config import settings
from app.core.db import engine
from app.core.security import create_access_token
from app.game import daily_service, run_service
from app.game.guest_models import GuestSession
from app.game.models import DailyDefinition, GameOperation, GameRun
from app.game.schemas import RunPublic
from app.main import app
from app.models import User
from tests.api.routes import test_game_daily
from tests.api.routes.test_game_runs import correct_command, start_command
from tests.browser.guest_test_environment import require_owned_guest_database

BASE = "/api/v1/games"
daily_context = test_game_daily.daily_context


@pytest.fixture(autouse=True)
def guest_cleanup(db: Session) -> Generator[None]:
    existing = set(db.exec(select(User.id).where(User.is_guest)).all())
    db.rollback()
    yield
    db.rollback()
    require_owned_guest_database()
    for owner in db.exec(select(User).where(User.is_guest)).all():
        if owner.id not in existing:
            db.delete(owner)
    db.commit()


def counts(db: Session) -> tuple[int, ...]:
    db.rollback()
    return tuple(
        db.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
        for table in (
            "user",
            "guestsession",
            "gamerun",
            "gameoperation",
            "dailydefinition",
        )
    )


def mutation_headers(context: str | None = None) -> dict[str, str]:
    headers = {"Origin": settings.FRONTEND_HOST, "X-Game-Request": "1"}
    if context is not None:
        headers["X-Game-Context"] = context
    return headers


def bootstrap(client: TestClient) -> str:
    response = client.post(f"{BASE}/session", headers=mutation_headers())
    assert response.status_code == 200
    assert set(response.json()) == {"kind", "context_id"}
    assert response.json()["kind"] == "guest"
    context = str(response.json()["context_id"])
    client.headers.update(mutation_headers(context))
    return context


def bearer(owner: UUID) -> dict[str, str]:
    token = create_access_token(owner, timedelta(minutes=5))
    return {"Authorization": f"Bearer {token}"}


def assert_error(response: Any, status: int, code: str) -> None:
    assert response.status_code == status
    assert set(response.json()["detail"]) == {"code", "message"}
    assert response.json()["detail"]["code"] == code


def public_run(response: Any) -> RunPublic:
    assert response.status_code == 200
    return RunPublic.model_validate_json(response.text)


def test_public_options_do_not_allocate_identity(
    db: Session, daily_context: tuple[list[UUID], str, datetime]
) -> None:
    _, release_id, _ = daily_context
    before = counts(db)
    with TestClient(app) as client:
        response = client.get(f"{BASE}/options")
        assert response.status_code == 200
        assert response.json()["catalog_release_id"] == release_id
        assert set(response.json()) == {
            "catalog_release_id",
            "categories",
            "start",
            "end",
            "registration_open",
        }
        assert not response.headers.get("set-cookie") and not client.cookies
    assert counts(db) == before


def test_session_errors_are_not_cacheable(db: Session) -> None:
    before = counts(db)
    with TestClient(app) as client:
        responses = [
            client.get(f"{BASE}/session"),
            client.post(f"{BASE}/session"),
            client.post(f"{BASE}/session", headers={"Authorization": "Bearer bad"}),
            client.get(f"{BASE}/session", headers={"Authorization": "Basic bad"}),
        ]
        assert [r.status_code for r in responses] == [401, 403, 403, 401]
        for response in responses:
            assert response.headers.get("cache-control") == "no-store"
            assert "set-cookie" not in response.headers
        assert responses[-1].headers["www-authenticate"] == "Bearer"
    assert counts(db) == before


@pytest.mark.parametrize("environment", ["local", "staging", "production"])
def test_bootstrap_cookie_allowlist_and_refresh(
    db: Session, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    monkeypatch.setattr(settings, "GAME_GUEST_COOKIE_NAME", "hdg_guest_api_test")
    with TestClient(app, base_url="https://testserver") as client:
        before = counts(db)
        response = client.post(f"{BASE}/session", headers=mutation_headers())
        assert response.status_code == 200
        assert set(response.json()) == {"kind", "context_id"}
        assert response.json()["kind"] == "guest"
        assert response.headers["cache-control"] == "no-store"
        cookie: SimpleCookie[str] = SimpleCookie()
        cookie.load(response.headers["set-cookie"])
        morsel = cookie["hdg_guest_api_test"]
        assert morsel["httponly"] and morsel["samesite"].lower() == "lax"
        assert morsel["path"] == BASE and morsel["max-age"] == "7776000"
        assert not morsel["domain"]
        assert bool(morsel["secure"]) == (environment != "local")
        credential = client.cookies.get("hdg_guest_api_test")
        assert credential is not None and credential not in response.text
        digest = hashlib.sha256(credential.encode()).hexdigest()
        stored = db.get(GuestSession, digest)
        assert stored is not None
        owner_id = stored.owner_id
        assert str(owner_id) not in response.text and digest not in response.text
        assert response.json()["context_id"] == f"g:{stored.public_id}"
        stored.expires_at = datetime.now(UTC) + timedelta(days=1)
        db.add(stored)
        db.commit()
        after = counts(db)
        assert after == (before[0] + 1, before[1] + 1, *before[2:])
        read = client.get(f"{BASE}/session", headers={"X-Game-Context": "old"})
        assert read.status_code == 200 and read.json() == response.json()
        assert read.headers["cache-control"] == "no-store"
        assert "set-cookie" not in read.headers and counts(db) == after
        refreshed = client.post(f"{BASE}/session", headers=mutation_headers())
        assert refreshed.status_code == 200 and refreshed.json() == response.json()
        assert client.cookies.get("hdg_guest_api_test") == credential
        assert "set-cookie" in refreshed.headers and counts(db) == after
        db.expire_all()
        stored = db.get(GuestSession, digest)
        assert stored is not None and stored.owner_id == owner_id
        assert stored.expires_at > datetime.now(UTC) + timedelta(days=89)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Game-Request": "1"},
        {"Origin": "null", "X-Game-Request": "1"},
        {"Origin": "https://untrusted.example", "X-Game-Request": "1"},
        {
            "Origin": "https://untrusted.example",
            "Host": "untrusted.example",
            "X-Game-Request": "1",
        },
        {"Origin": "http://localhost:5173/", "X-Game-Request": "1"},
        {"Origin": "http://localhost:5173.evil.example", "X-Game-Request": "1"},
        {"Origin": "http://localhost:5173"},
        {"Origin": "http://localhost:5173", "X-Game-Request": "0"},
    ],
)
def test_guest_mutations_reject_csrf_before_writes(
    db: Session, headers: dict[str, str]
) -> None:
    with TestClient(app) as client:
        before = counts(db)
        assert_error(
            client.post(f"{BASE}/session", headers=headers),
            403,
            "game_request_rejected",
        )
        assert counts(db) == before and not client.cookies
        context = bootstrap(client)
        client.headers.clear()
        rejected = {**headers, "X-Game-Context": context}
        for path, body in (
            ("/daily", {"operation_id": str(uuid4())}),
            ("/freeplay", start_command("unavailable").model_dump(mode="json")),
            (
                f"/runs/{uuid4()}/placements",
                {
                    "operation_id": str(uuid4()),
                    "expected_revision": 0,
                    "event_id": str(uuid4()),
                    "slot": 0,
                },
            ),
        ):
            before = counts(db)
            assert_error(
                client.post(BASE + path, headers=rejected, json=body),
                403,
                "game_request_rejected",
            )
            assert counts(db) == before


def test_explicit_configured_origin_not_request_host_authorizes_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BACKEND_CORS_ORIGINS", ["http://192.168.1.99:5184"])
    with TestClient(app) as client:
        response = client.post(
            f"{BASE}/session",
            headers={
                "Origin": "http://192.168.1.99:5184",
                "X-Game-Request": "1",
                "Host": "other.example",
            },
        )
        assert response.status_code == 200


@pytest.mark.parametrize(
    "credential", [None, "malformed", "A" * 43, "expired", "revoked"]
)
def test_missing_invalid_or_expired_cookie_never_allocates_scored_identity(
    db: Session, credential: str | None
) -> None:
    with TestClient(app) as client:
        if credential in {"expired", "revoked"}:
            context = bootstrap(client)
            raw = client.cookies.get(settings.GAME_GUEST_COOKIE_NAME)
            assert raw is not None
            stored = db.get(GuestSession, hashlib.sha256(raw.encode()).hexdigest())
            assert stored is not None
            if credential == "expired":
                stored.created_at = datetime.now(UTC) - timedelta(days=91)
                stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                db.add(stored)
            else:
                db.delete(stored)
            db.commit()
        else:
            context = "g:non-authorizing-context"
            if credential is not None:
                client.cookies.set(
                    settings.GAME_GUEST_COOKIE_NAME, credential, path=BASE
                )
        client.headers.update(mutation_headers(context))
        before = counts(db)
        for path in (
            "/session",
            "/active-runs",
            "/daily",
            f"/runs/{uuid4()}",
            "/daily/2300-01-01/leaderboard",
        ):
            assert_error(client.get(BASE + path), 401, "game_session_required")
        for path, body in (
            ("/daily", {"operation_id": str(uuid4())}),
            ("/freeplay", start_command("unavailable").model_dump(mode="json")),
            (
                f"/runs/{uuid4()}/placements",
                {
                    "operation_id": str(uuid4()),
                    "expected_revision": 0,
                    "event_id": str(uuid4()),
                    "slot": 0,
                },
            ),
        ):
            assert_error(
                client.post(BASE + path, json=body), 401, "game_session_required"
            )
        assert counts(db) == before
        assert client.post(f"{BASE}/session").status_code == 200
        assert counts(db)[:2] == (before[0] + 1, before[1] + 1)


@pytest.mark.parametrize(
    "authorization,status",
    [("", 401), ("Basic bad", 401), ("Bearer", 401), ("Bearer bad", 403)],
)
def test_explicit_invalid_authorization_never_falls_back_to_cookie(
    db: Session, authorization: str, status: int
) -> None:
    with TestClient(app) as client:
        bootstrap(client)
        client.headers["Authorization"] = authorization
        before = counts(db)
        assert client.get(f"{BASE}/session").status_code == status
        assert client.post(f"{BASE}/session").status_code == status
        assert (
            client.post(
                f"{BASE}/daily", json={"operation_id": str(uuid4())}
            ).status_code
            == status
        )
        assert counts(db) == before


def test_account_precedence_context_and_existing_validation(
    db: Session,
    daily_context: tuple[list[UUID], str, datetime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owners, _, now = daily_context
    monkeypatch.setattr(daily_service, "utc_now", lambda: now)
    with TestClient(app) as client:
        guest_context = bootstrap(client)
        credential = client.cookies.get(settings.GAME_GUEST_COOKIE_NAME)
        client.headers.clear()
        client.headers.update(bearer(owners[0]))
        before = counts(db)
        session = client.post(f"{BASE}/session")  # Bearer needs no Origin/header.
        assert session.status_code == 200
        assert set(session.json()) == {"kind", "context_id"}
        assert session.json()["kind"] == "account"
        account_context = session.json()["context_id"]
        assert account_context != guest_context and str(owners[0]) not in session.text
        assert session.headers["cache-control"] == "no-store"
        assert "set-cookie" not in session.headers
        assert client.cookies.get(settings.GAME_GUEST_COOKIE_NAME) == credential
        assert counts(db) == before
        assert client.get(f"{BASE}/session").json() == session.json()
        client.headers["X-Game-Context"] = guest_context
        assert_error(
            client.post(f"{BASE}/daily", json={"operation_id": str(uuid4())}),
            409,
            "game_identity_changed",
        )
        assert counts(db) == before
        client.headers["X-Game-Context"] = account_context
        run = public_run(
            client.post(f"{BASE}/daily", json={"operation_id": str(uuid4())})
        )
        assert db.get(GameRun, run.run_id).owner_id == owners[0]
        del client.headers["X-Game-Context"]
        assert client.get(f"{BASE}/runs/{run.run_id}").status_code == 200
        owner = db.get(User, owners[0])
        assert owner is not None
        owner.is_active = False
        db.add(owner)
        db.commit()
        before = counts(db)
        assert client.post(f"{BASE}/session").status_code == 400
        assert client.get(f"{BASE}/daily").status_code == 400
        assert counts(db) == before


def test_guest_cookie_does_not_authorize_account_apis(db: Session) -> None:
    with TestClient(app) as client:
        bootstrap(client)
        credential = client.cookies.get(settings.GAME_GUEST_COOKIE_NAME)
        assert credential is not None
        for path in ("/users/me", "/users/", "/items/"):
            assert client.get("/api/v1" + path).status_code == 401
            assert (
                client.get(
                    "/api/v1" + path,
                    headers={
                        "Cookie": f"{settings.GAME_GUEST_COOKIE_NAME}={credential}"
                    },
                ).status_code
                == 401
            )
        stored = db.get(GuestSession, hashlib.sha256(credential.encode()).hexdigest())
        assert stored is not None
        client.headers.update(bearer(stored.owner_id))
        assert client.post(f"{BASE}/session").status_code == 403
        assert client.get(f"{BASE}/active-runs").status_code == 403


def test_guest_and_account_share_daily_but_not_runs(
    db: Session,
    daily_context: tuple[list[UUID], str, datetime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owners, _, now = daily_context
    monkeypatch.setattr(daily_service, "utc_now", lambda: now)
    with (
        TestClient(app) as first,
        TestClient(app) as second,
        TestClient(app) as account,
    ):
        contexts = [bootstrap(first), bootstrap(second)]
        assert contexts[0] != contexts[1]
        account.headers.update(bearer(owners[0]))
        clients = [first, second, account]
        runs = [
            public_run(c.post(f"{BASE}/daily", json={"operation_id": str(uuid4())}))
            for c in clients
        ]
        assert len({r.run_id for r in runs}) == 3
        assert all(
            r.timeline == runs[0].timeline and r.pending == runs[0].pending
            for r in runs
        )
        for i, client in enumerate(clients):
            assert client.get(f"{BASE}/daily").json()["attempt_run_id"] == str(
                runs[i].run_id
            )
            assert [r["run_id"] for r in client.get(f"{BASE}/active-runs").json()] == [
                str(runs[i].run_id)
            ]
            move = correct_command(db, runs[i]).model_dump(mode="json")
            for j, other in enumerate(clients):
                if i != j:
                    assert other.get(f"{BASE}/runs/{runs[i].run_id}").status_code == 404
                    assert (
                        other.post(
                            f"{BASE}/runs/{runs[i].run_id}/placements", json=move
                        ).status_code
                        == 404
                    )
            moved = public_run(
                client.post(f"{BASE}/runs/{runs[i].run_id}/placements", json=move)
            )
            assert moved.streak == moved.revision == 1
            assert client.post(
                f"{BASE}/runs/{runs[i].run_id}/placements", json=move
            ).json() == moved.model_dump(mode="json")
            resumed = public_run(
                client.post(f"{BASE}/daily", json={"operation_id": str(uuid4())})
            )
            assert resumed == moved
            while moved.status == "active":
                moved = public_run(
                    client.post(
                        f"{BASE}/runs/{moved.run_id}/placements",
                        json=correct_command(db, moved).model_dump(mode="json"),
                    )
                )
            assert moved.status == "won" and moved.streak == 5
        board = first.get(f"{BASE}/daily/{now.date()}/leaderboard")
        assert board.status_code == 200
        entries = board.json()["entries"]
        assert [entry["rank"] for entry in entries] == [1, 1, 1]
        assert sorted(entry["display_name"] for entry in entries) == [
            "Ada",
            "Guest",
            "Guest",
        ]
        assert all(
            set(entry) == {"rank", "streak", "status", "display_name"}
            for entry in entries
        )
        for private in (
            "@",
            "owner_id",
            "context_id",
            "seed",
            "order",
            "pool",
            *(str(r.run_id) for r in runs),
            *contexts,
        ):
            assert private not in board.text
        for run in runs:
            assert "year" not in run.pending.model_dump()  # type: ignore[union-attr]
        assert (
            len(
                db.exec(
                    select(GameRun).where(col(GameRun.id).in_([r.run_id for r in runs]))
                ).all()
            )
            == 3
        )


def test_changed_cookie_rejects_inflight_context(
    db: Session,
    daily_context: tuple[list[UUID], str, datetime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, release_id, now = daily_context
    monkeypatch.setattr(daily_service, "utc_now", lambda: now)
    with TestClient(app) as first, TestClient(app) as replacement:
        old_context = bootstrap(first)
        initial = public_run(
            first.post(f"{BASE}/daily", json={"operation_id": str(uuid4())})
        )
        new_context = bootstrap(replacement)
        assert new_context != old_context
        first.cookies.clear()
        first.cookies.update(replacement.cookies)
        before = counts(db)
        for path, body in (
            ("/daily", {"operation_id": str(uuid4())}),
            ("/freeplay", start_command(release_id).model_dump(mode="json")),
            (
                f"/runs/{initial.run_id}/placements",
                correct_command(db, initial).model_dump(mode="json"),
            ),
        ):
            assert_error(
                first.post(BASE + path, json=body), 409, "game_identity_changed"
            )
        assert_error(
            first.get(f"{BASE}/runs/{initial.run_id}"), 409, "game_identity_changed"
        )
        assert counts(db) == before
        assert first.get(f"{BASE}/session").json()["context_id"] == new_context
        first.headers["X-Game-Context"] = new_context
        assert first.get(f"{BASE}/runs/{initial.run_id}").status_code == 404
        del first.headers["X-Game-Context"]
        assert_error(
            first.post(f"{BASE}/daily", json={"operation_id": str(uuid4())}),
            409,
            "game_identity_changed",
        )
        first.cookies.clear()
        assert_error(
            first.post(f"{BASE}/daily", json={"operation_id": str(uuid4())}),
            401,
            "game_session_required",
        )
        assert counts(db) == before


def test_guest_freeplay_uses_confirmed_owner(
    db: Session, daily_context: tuple[list[UUID], str, datetime]
) -> None:
    _, release_id, _ = daily_context
    with TestClient(app) as client:
        bootstrap(client)
        command = start_command(release_id).model_dump(mode="json")
        run = public_run(client.post(f"{BASE}/freeplay", json=command))
        assert run.mode == "freeplay"
        assert client.post(f"{BASE}/freeplay", json=command).json() == run.model_dump(
            mode="json"
        )
        moved = public_run(
            client.post(
                f"{BASE}/runs/{run.run_id}/placements",
                json=correct_command(db, run).model_dump(mode="json"),
            )
        )
        assert moved.revision == moved.streak == 1


@pytest.mark.parametrize("same_operation", [False, True])
def test_concurrent_guest_daily_starts_and_placement_retries(
    db: Session,
    daily_context: tuple[list[UUID], str, datetime],
    monkeypatch: pytest.MonkeyPatch,
    same_operation: bool,
) -> None:
    _, _, now = daily_context
    monkeypatch.setattr(daily_service, "utc_now", lambda: now)
    with TestClient(app) as first, TestClient(app) as tab:
        context = bootstrap(first)
        tab.cookies.update(first.cookies)
        tab.headers.update(mutation_headers(context))
        gate = Barrier(2)
        pids: list[int] = []

        def independent_sessions() -> Generator[Session]:
            with Session(engine) as session:
                session.execute(text("SET LOCAL statement_timeout = '10s'"))
                pids.append(
                    session.execute(text("SELECT pg_backend_pid()")).scalar_one()
                )
                gate.wait(timeout=10)
                yield session

        def race(path: str, bodies: list[dict[str, Any]]) -> list[RunPublic]:
            pids.clear()
            db.rollback()
            app.dependency_overrides[get_db] = independent_sessions
            try:
                with ThreadPoolExecutor(max_workers=2) as workers:
                    futures = [
                        workers.submit(c.post, BASE + path, json=body)
                        for c, body in zip([first, tab], bodies, strict=True)
                    ]
                    responses = [public_run(f.result(timeout=20)) for f in futures]
            finally:
                del app.dependency_overrides[get_db]
            assert len(set(pids)) == 2
            return responses

        one = {"operation_id": str(uuid4())}
        two = one if same_operation else {"operation_id": str(uuid4())}
        runs = race("/daily", [one, two])
        assert runs[0] == runs[1]
        move = correct_command(db, runs[0]).model_dump(mode="json")
        moved = race(f"/runs/{runs[0].run_id}/placements", [move, move])
        assert moved[0] == moved[1] and moved[0].revision == moved[0].streak == 1
        saved = db.get(GameRun, runs[0].run_id)
        assert saved is not None
        assert (
            len(
                db.exec(select(GameRun).where(GameRun.owner_id == saved.owner_id)).all()
            )
            == 1
        )
        assert len(
            db.exec(
                select(GameOperation).where(GameOperation.owner_id == saved.owner_id)
            ).all()
        ) == (2 if same_operation else 3)
        assert (
            len(
                db.exec(
                    select(DailyDefinition).where(DailyDefinition.day == now.date())
                ).all()
            )
            == 1
        )


def test_guest_daily_utc_rollover_and_finish_after_midnight(
    db: Session,
    daily_context: tuple[list[UUID], str, datetime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, now = daily_context
    now = now.replace(hour=23, minute=59)
    monkeypatch.setattr(daily_service, "utc_now", lambda: now)
    with TestClient(app) as client:
        bootstrap(client)
        command = {"operation_id": str(uuid4())}
        old = public_run(client.post(f"{BASE}/daily", json=command))
        tomorrow = now + timedelta(minutes=2)
        monkeypatch.setattr(daily_service, "utc_now", lambda: tomorrow)
        monkeypatch.setattr(run_service, "utc_now", lambda: tomorrow)
        assert client.post(f"{BASE}/daily", json=command).json() == old.model_dump(
            mode="json"
        )
        overview = client.get(f"{BASE}/daily?day=1900-01-01&now=1900-01-01").json()
        assert (
            overview["day"] == str(tomorrow.date())
            and overview["attempt_run_id"] is None
        )
        fresh = public_run(
            client.post(f"{BASE}/daily", json={"operation_id": str(uuid4())})
        )
        assert fresh.run_id != old.run_id and fresh.daily_date == tomorrow.date()
        while old.status == "active":
            old = public_run(
                client.post(
                    f"{BASE}/runs/{old.run_id}/placements",
                    json=correct_command(db, old).model_dump(mode="json"),
                )
            )
        assert old.daily_date == now.date() and old.status == "won"
        saved = db.get(GameRun, old.run_id)
        assert saved is not None and saved.finished_at == tomorrow
        assert client.get(f"{BASE}/daily/{now.date()}/leaderboard").json()[
            "entries"
        ] == [{"display_name": "Guest", "streak": 5, "status": "won", "rank": 1}]
        assert (
            client.get(f"{BASE}/daily/{tomorrow.date()}/leaderboard").json()["entries"]
            == []
        )
