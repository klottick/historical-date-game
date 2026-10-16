"""Release boundary tests; never initialize or connect to a real database."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[3]
ENV = {
    "PROJECT_NAME": "Distribution test",
    "SECRET_KEY": "s" * 64,
    "POSTGRES_SERVER": "not-a-database.invalid",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "hdg",
    "POSTGRES_PASSWORD": "p" * 32,
    "POSTGRES_DB": "hdg",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "a" * 32,
    "FRONTEND_HOST": "http://localhost:8000",
    "ENVIRONMENT": "local",
}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, ENV)
        environment.start()
        self.addCleanup(environment.stop)

    def test_missing_or_placeholder_secrets_refuse_before_settings_or_db(self):
        from app.distribution.config import validate_environment

        validate_environment(ENV)
        for field, minimum in (
            ("SECRET_KEY", 32),
            ("POSTGRES_PASSWORD", 20),
            ("FIRST_SUPERUSER_PASSWORD", 12),
        ):
            for bad in ("", " ", "changethis", "x" * (minimum - 1)):
                with self.subTest(field=field, bad_length=len(bad)):
                    with self.assertRaises(ValueError) as caught:
                        validate_environment(ENV | {field: bad})
                    self.assertIn(field, str(caught.exception))
                    self.assertNotIn("s" * 64, str(caught.exception))
        for field in ENV:
            with self.subTest(missing=field), self.assertRaises(ValueError):
                validate_environment({k: v for k, v in ENV.items() if k != field})

    def test_origin_and_mode_are_consistent(self):
        from app.distribution.config import validate_environment

        for origin in (
            "http://localhost:9876",
            "http://127.0.0.1:8000",
            "https://game.example",
        ):
            validate_environment(ENV | {"FRONTEND_HOST": origin})
        validate_environment(
            ENV | {"FRONTEND_HOST": "https://game.example", "ENVIRONMENT": "production"}
        )
        for origin in (
            "http://user:password@host",
            "http://host/path",
            "http://host?x=1",
            "http://host#x",
            "//host",
            "http://*",
            "http://host\n",
            "http://host:bad",
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                validate_environment(ENV | {"FRONTEND_HOST": origin})
        for mode in ("production", "staging", "other"):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate_environment(ENV | {"ENVIRONMENT": mode})

    def test_initialize_failure_never_serves_or_resets(self):
        for command in ("initialize", "serve"):
            process = subprocess.run(
                [
                    str(ROOT / "backend/.venv/bin/python"),
                    "-m",
                    "app.distribution",
                    command,
                ],
                cwd=ROOT / "backend",
                env={"PATH": os.environ["PATH"], "PYTHONPATH": str(ROOT / "backend")},
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("configuration", process.stderr.lower())
            self.assertNotIn("OperationalError", process.stderr)
            self.assertNotIn("Uvicorn running", process.stdout + process.stderr)

    def test_spa_fallback_never_captures_api_media_or_secrets(self):
        from app.distribution.web import create_app
        from fastapi.testclient import TestClient

        with (
            patch.dict(os.environ, ENV),
            tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp,
        ):
            root = Path(tmp)
            (root / "assets").mkdir()
            (root / "index.html").write_text('<div id="root"></div>')
            (root / "assets/app-1234abcd.js").write_text("export const a=1")
            (root / "assets/link.js").symlink_to(
                ROOT / "backend/catalogue/default.json"
            )
            client = TestClient(create_app(root))
            for path in (
                "/",
                "/daily",
                "/freeplay",
                "/login",
                "/admin",
                "/play/11111111-1111-4111-8111-111111111111",
            ):
                response = client.get(path)
                self.assertEqual(response.status_code, 200, path)
                self.assertEqual(response.headers["cache-control"], "no-cache")
            asset = client.get("/assets/app-1234abcd.js")
            self.assertEqual(asset.status_code, 200)
            self.assertIn("javascript", asset.headers["content-type"])
            self.assertIn("immutable", asset.headers["cache-control"])
            for path in (
                "/assets/missing.js",
                "/assets/link.js",
                "/api/missing",
                "/media/missing",
                "/catalogue/default.json",
                "/.env",
                "/@fs/etc/passwd",
                "/app/backend/app/main.py",
                "/assets/%2e%2e/login",
                "/%2e%2e/",
                "/assets/%5clink.js",
                "/unknown",
                "/play/not-a-uuid",
            ):
                response = client.get(path)
                self.assertEqual(response.status_code, 404, path)
                self.assertNotIn('<div id="root">', response.text, path)
            response = client.get("/api/v1/utils/public-config")
            self.assertEqual(response.status_code, 200)
            self.assertIn("registration_open", response.json())
            self.assertEqual(
                client.get(
                    "/api/v1/games/runs/11111111-1111-4111-8111-111111111111"
                ).status_code,
                401,
            )
            from app.main import app

            self.assertEqual(TestClient(app).get("/daily").status_code, 404)

    def test_readiness_is_read_only_and_reports_503(self):
        from app.distribution.web import create_app
        from fastapi.testclient import TestClient

        with (
            patch.dict(os.environ, ENV),
            tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp,
        ):
            root = Path(tmp)
            (root / "index.html").write_text("ready")
            client = TestClient(create_app(root))
            with patch(
                "app.distribution.startup.check_ready",
                side_effect=RuntimeError("private db password"),
            ):
                response = client.get("/healthz")
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {"status": "unavailable"})
                self.assertEqual(response.headers["cache-control"], "no-store")
            with patch("app.distribution.startup.check_ready", return_value=None):
                self.assertEqual(client.get("/healthz").json(), {"status": "ready"})

    def test_initializer_refuses_missing_media_storage_before_migrations(self):
        from app.core.config import settings
        from app.distribution.startup import initialize

        with (
            patch.dict(os.environ, ENV),
            tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp,
        ):
            root = Path(tmp)
            # A non-directory media target must fail before any DB mutation.
            (root / "media").write_text("not media storage")
            with (
                patch.object(settings, "GAME_DATA_DIR", root),
                patch("alembic.command.upgrade") as upgrade,
                patch("app.backend_pre_start.main") as wait,
            ):
                self.assertEqual(initialize(), 1)
                upgrade.assert_not_called()
                wait.assert_not_called()

    def test_migration_refusal_never_creates_admin_or_installs_catalogue(self):
        from app.core.config import settings
        from app.distribution.startup import initialize

        with (
            patch.dict(os.environ, ENV),
            tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp,
            patch.object(settings, "GAME_DATA_DIR", Path(tmp)),
            patch("app.backend_pre_start.main"),
            patch("app.core.db.engine.connect") as connection,
            patch(
                "alembic.command.upgrade",
                side_effect=ValueError("populated gameplay refuses migration"),
            ),
            patch("app.initial_data.init") as admin,
            patch("app.game.runtime_catalog.install_runtime") as install,
        ):
            self.assertEqual(initialize(), 1)
            admin.assert_not_called()
            install.assert_not_called()
            sql = [
                str(call.args[0])
                for call in connection.return_value.__enter__.return_value.execute.call_args_list
            ]
            self.assertEqual(
                sql,
                [
                    "SELECT pg_advisory_lock(20261016, 1)",
                    "SELECT pg_advisory_unlock(20261016, 1)",
                ],
            )

    def test_existing_guest_cookie_and_origin_rules_survive_release_adapter(self):
        from datetime import UTC, datetime
        from uuid import UUID

        from app.api.deps import get_db
        from app.core.config import settings
        from app.distribution.web import create_app
        from app.game.guest_sessions import GamePlayer, GuestBootstrap
        from fastapi.testclient import TestClient

        bootstrap = GuestBootstrap(
            GamePlayer(
                UUID("11111111-1111-4111-8111-111111111111"), "guest", "g:testing"
            ),
            "c" * 43,
            datetime(2026, 10, 16, tzinfo=UTC),
        )
        with (
            patch.dict(os.environ, ENV),
            tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp,
        ):
            app = create_app(Path(tmp))
            session = MagicMock()
            app.dependency_overrides[get_db] = lambda: session
            for mode, origin in (
                ("local", "http://localhost:9898"),
                ("production", "https://game.example"),
            ):
                with (
                    patch.object(settings, "ENVIRONMENT", mode),
                    patch.object(settings, "FRONTEND_HOST", origin),
                    patch(
                        "app.api.routes.games.bootstrap_guest_session",
                        return_value=bootstrap,
                    ) as create,
                ):
                    client = TestClient(app, base_url=origin)
                    response = client.post(
                        "/api/v1/games/session",
                        headers={
                            "Origin": origin,
                            "X-Game-Request": "1",
                            "X-Forwarded-Proto": "https",
                        },
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("HttpOnly", response.headers["set-cookie"])
                    self.assertIn("SameSite=lax", response.headers["set-cookie"])
                    self.assertEqual(
                        "Secure" in response.headers["set-cookie"], mode != "local"
                    )
                    self.assertEqual(response.headers["cache-control"], "no-store")
                    create.reset_mock()
                    for headers in (
                        {"Origin": "https://foreign.example", "X-Game-Request": "1"},
                        {"Origin": origin},
                        {"X-Game-Request": "1", "X-Forwarded-Host": origin},
                    ):
                        self.assertEqual(
                            client.post(
                                "/api/v1/games/session", headers=headers
                            ).status_code,
                            403,
                        )
                    create.assert_not_called()

    def test_readiness_requires_exact_schema_selection_and_media_without_writes(self):
        import hashlib

        from app.core.config import settings
        from app.distribution.startup import check_ready
        from app.game.catalog_repository import CatalogOptions
        from app.game.models import MediaAsset

        data = b"<svg/>"
        digest = hashlib.sha256(data).hexdigest()
        row = MediaAsset(
            release_id="owned",
            key="fallback:general",
            snapshot={
                "key": "general",
                "filename": f"media/{digest}.svg",
                "sha256": digest,
                "alt_text": "A fallback",
                "creator": "Test",
                "rights_basis": "CC0",
            },
        )
        with (
            tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp,
            patch.object(settings, "GAME_DATA_DIR", Path(tmp)),
            patch("sqlmodel.Session") as session_type,
            patch("alembic.migration.MigrationContext.configure") as schema,
            patch("alembic.script.ScriptDirectory.from_config") as packaged,
            patch(
                "app.game.catalog_repository.load_options",
                return_value=CatalogOptions("owned", ("category",), -1, 1),
            ),
        ):
            session = session_type.return_value.__enter__.return_value
            session.exec.return_value.all.return_value = [row]
            schema.return_value.get_current_heads.return_value = ("head",)
            packaged.return_value.get_heads.return_value = ["head"]
            target = Path(tmp) / "media/owned" / f"{digest}.svg"
            target.parent.mkdir(parents=True)
            target.write_bytes(data)
            check_ready()
            self.assertEqual(
                str(session.execute.call_args_list[0].args[0]),
                "SET TRANSACTION READ ONLY",
            )
            session.commit.assert_not_called()
            session.add.assert_not_called()
            target.write_bytes(b"corrupted")
            with self.assertRaises(ValueError):
                check_ready()
            target.unlink()
            with self.assertRaises(ValueError):
                check_ready()
            schema.return_value.get_current_heads.return_value = ("old-head",)
            with self.assertRaises(ValueError):
                check_ready()


if __name__ == "__main__":
    unittest.main()
