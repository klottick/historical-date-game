"""Safety and scoped-reset proofs for the local three-life rollout helper."""

import hashlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.core.config import settings
from tests.browser import guest_local_rollout as old
from tests.browser import guest_test_environment as environment
from tests.browser import three_lives_local_rollout as rollout
from tests.browser.rollout_fixtures import synthetic_rollout_sources

DATABASE = "historical_date_game_lives_migration_test"


def setUpModule() -> None:
    # Historical command fixtures use this explicit root too. Empty runners must
    # create it themselves; no developer checkout or retained files are needed.
    Path("/tmp/opencode").mkdir(mode=0o700, parents=True, exist_ok=True)


def _retained_table_digests(session: Session) -> dict[str, dict[str, str | int]]:
    excluded = {"gameoperation", "gamerun", "dailydefinition"}
    names = (
        session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name"
            )
        )
        .scalars()
        .all()
    )
    result: dict[str, dict[str, str | int]] = {}
    quote = session.connection().dialect.identifier_preparer.quote
    for name in names:
        if name in excluded:
            continue
        rows = (
            session.execute(
                text(
                    f"SELECT to_jsonb(t)::text FROM {quote(name)} t "
                    "ORDER BY to_jsonb(t)::text"
                )
            )
            .scalars()
            .all()
        )
        result[name] = {
            "count": len(rows),
            "sha256": hashlib.sha256(json.dumps(rows).encode()).hexdigest(),
        }
    return result


class LocalRolloutGuardTests(unittest.TestCase):
    def _set_live_config(self, config: Any) -> None:
        config.POSTGRES_DB = rollout.DATABASE
        config.POSTGRES_SERVER = "127.0.0.1"
        config.POSTGRES_PORT = 5433
        config.ENVIRONMENT = "local"
        config.POSTGRES_USER = "operator"
        config.GAME_EVENT_LINKS_FILE = rollout.ORIGINAL_SIDECAR
        config.GAME_EVENT_LINKS_SHA256 = rollout.ORIGINAL_SIDECAR_SHA256
        config.GAME_GUEST_COOKIE_NAME = rollout.LIVE_GUEST_COOKIE_NAME
        config.GAME_DATA_DIR = rollout.ORIGINAL_LIVE / "data/game/local-catalog-runtime"
        config.FRONTEND_HOST = "http://localhost:5174"
        config.BACKEND_CORS_ORIGINS = [
            "http://localhost:5174",
            "http://192.168.1.214:5174",
        ]

    def _evidence_dir(self, path: Path) -> Path:
        path.mkdir(mode=0o700)
        return path

    def _private_json(self, path: Path, name: str, body: object) -> None:
        output = path / name
        output.write_text(json.dumps(body))
        output.chmod(0o600)

    def test_default_original_bindings_match_approved_board_runner(self) -> None:
        feature_worktree = Path(rollout.__file__).resolve().parents[3]
        approved_worktree = Path(
            "/home/klottick/repos/historical-date-game/.worktrees/board-redesign"
        )
        self.assertEqual(rollout.WORKTREE, feature_worktree)
        self.assertEqual(
            rollout.new_command("backend")[3],
            "tests.browser.three_lives_local_rollout:local_app",
        )
        self.assertEqual(rollout.new_command("ui")[1], "node_modules/vite/bin/vite.js")
        self.assertEqual(rollout.ORIGINAL_WORKTREE, approved_worktree)
        self.assertEqual(
            rollout.ORIGINAL_EVIDENCE,
            approved_worktree
            / ".superpowers/sdd/2026-10-14-game-board-redesign/local-activation",
        )
        self.assertEqual(
            rollout.ORIGINAL_LIVE,
            Path("/home/klottick/repos/historical-date-game/.worktrees/beta"),
        )
        self.assertEqual(
            rollout.ORIGINAL_RELEASE_ID, "jsonl-trial-2026-10-12-review-r1"
        )
        self.assertEqual(
            rollout.ORIGINAL_WORKTREE_HEAD,
            "f53be772f4284b94020a082dab6a09c10ecb8ca4",
        )
        self.assertEqual(
            rollout.ORIGINAL_SIDECAR,
            approved_worktree
            / ".superpowers/sdd/2026-10-14-game-board-redesign/integration/task-5/event-links.json",
        )
        self.assertEqual(
            rollout.ORIGINAL_SIDECAR_SHA256,
            "53da618a7ca6efc621296b0da429fa4c83caa906f3683b9375cb7c99302f9fcd",
        )
        self.assertEqual(
            rollout.original_command("backend"),
            [
                str(approved_worktree / "backend/.venv/bin/python"),
                "-m",
                "uvicorn",
                "tests.browser.board_local_rollout:local_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                "8010",
                "--no-access-log",
            ],
        )
        self.assertEqual(
            rollout.original_command("ui"),
            [
                "/tmp/opencode/node-v26.11.1-linux-x64/bin/node",
                "node_modules/vite/bin/vite.js",
                "--config",
                "vite.real-catalog.config.ts",
                "--host",
                "0.0.0.0",
                "--port",
                "5174",
                "--strictPort",
            ],
        )

    def test_live_runtime_selectors_are_exact_but_owned_test_is_optional(self) -> None:
        with (
            patch.object(settings, "GAME_EVENT_LINKS_FILE", None),
            patch.object(settings, "GAME_EVENT_LINKS_SHA256", None),
            patch.object(settings, "GAME_GUEST_COOKIE_NAME", "hdg_guest_real"),
            patch.object(
                settings,
                "GAME_DATA_DIR",
                rollout.ORIGINAL_LIVE / "data/game/local-catalog-runtime",
            ),
            patch.object(settings, "FRONTEND_HOST", "http://localhost:5174"),
            patch.object(
                settings,
                "BACKEND_CORS_ORIGINS",
                ["http://localhost:5174", "http://192.168.1.214:5174"],
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "Exact original sidecar"):
                rollout.require_runtime_configuration(rollout.DATABASE)
            rollout.require_runtime_configuration(rollout.TEST_DATABASE)

        with (
            patch.object(settings, "GAME_EVENT_LINKS_FILE", rollout.ORIGINAL_SIDECAR),
            patch.object(
                settings,
                "GAME_EVENT_LINKS_SHA256",
                rollout.ORIGINAL_SIDECAR_SHA256,
            ),
            patch.object(settings, "GAME_GUEST_COOKIE_NAME", "hdg_guest_real"),
            patch.object(
                settings,
                "GAME_DATA_DIR",
                rollout.ORIGINAL_LIVE / "data/game/local-catalog-runtime",
            ),
            patch.object(settings, "FRONTEND_HOST", "http://localhost:5174"),
            patch.object(
                settings,
                "BACKEND_CORS_ORIGINS",
                ["http://localhost:5174", "http://192.168.1.214:5174"],
            ),
        ):
            rollout.require_runtime_configuration(rollout.DATABASE)

        for field, value in (
            ("GAME_EVENT_LINKS_FILE", rollout.ORIGINAL_SIDECAR.parent / "wrong.json"),
            ("GAME_EVENT_LINKS_SHA256", "0" * 64),
            ("GAME_GUEST_COOKIE_NAME", "hdg_guest_verification"),
            ("GAME_DATA_DIR", Path("/tmp/foreign-runtime")),
            ("FRONTEND_HOST", "http://localhost:5174.evil"),
            ("BACKEND_CORS_ORIGINS", ["http://localhost:5174"]),
        ):
            with (
                self.subTest(field=field),
                patch.object(
                    settings,
                    "GAME_EVENT_LINKS_FILE",
                    rollout.ORIGINAL_SIDECAR,
                ),
                patch.object(
                    settings,
                    "GAME_EVENT_LINKS_SHA256",
                    rollout.ORIGINAL_SIDECAR_SHA256,
                ),
                patch.object(
                    settings,
                    "GAME_GUEST_COOKIE_NAME",
                    rollout.LIVE_GUEST_COOKIE_NAME,
                ),
                patch.object(
                    settings,
                    "GAME_DATA_DIR",
                    rollout.ORIGINAL_LIVE / "data/game/local-catalog-runtime",
                ),
                patch.object(settings, "FRONTEND_HOST", "http://localhost:5174"),
                patch.object(
                    settings,
                    "BACKEND_CORS_ORIGINS",
                    ["http://localhost:5174", "http://192.168.1.214:5174"],
                ),
            ):
                with patch.object(settings, field, value):
                    with self.assertRaises(RuntimeError):
                        rollout.require_runtime_configuration(rollout.DATABASE)

    def test_default_inspection_is_read_only_and_exactly_local(self) -> None:
        with (
            patch.object(rollout, "settings") as config,
            patch.object(
                rollout, "inspect_database", return_value={"revision": "20261013_01"}
            ) as inspect_db,
            patch.object(
                rollout, "local_source_hashes", return_value={"sidecar": "sha"}
            ),
            patch.object(rollout, "require_stopped_old_generation"),
        ):
            self._set_live_config(config)
            result = rollout.inspect_target()
        database = result["database"]
        if not isinstance(database, dict):
            raise AssertionError("inspection database proof must be an object")
        self.assertEqual(database["revision"], "20261013_01")
        inspect_db.assert_called_once_with(
            expected_revision=rollout.EXPECTED_OLD_REVISION
        )

    def test_wrong_target_configurations_reject_before_database_access(self) -> None:
        for field, value in (
            ("POSTGRES_DB", "historical_date_game_test"),
            ("POSTGRES_SERVER", "0.0.0.0"),
            ("POSTGRES_PORT", 5432),
            ("ENVIRONMENT", "production"),
        ):
            with (
                self.subTest(field=field),
                patch.object(rollout, "settings") as config,
                patch.object(rollout, "inspect_database") as inspect_db,
            ):
                self._set_live_config(config)
                setattr(config, field, value)
                with self.assertRaises(RuntimeError):
                    rollout.inspect_target()
                inspect_db.assert_not_called()

    def test_wrong_revision_stale_process_and_foreign_bind_reject(self) -> None:
        with patch.object(rollout, "settings") as config:
            self._set_live_config(config)
            with (
                patch.object(
                    rollout,
                    "inspect_database",
                    return_value={"revision": "20261011_01"},
                ),
                patch.object(
                    rollout, "local_source_hashes", return_value={"sidecar": "sha"}
                ),
                patch.object(rollout, "require_stopped_old_generation"),
            ):
                with self.assertRaises(RuntimeError):
                    rollout.inspect_target()
            record = {
                "pid": 200,
                "start_ticks": "old",
                "cwd": "/expected",
                "command": ["api"],
            }
            with patch.object(
                rollout,
                "process_identity",
                return_value={**record, "start_ticks": "new"},
            ):
                with self.assertRaises(RuntimeError):
                    rollout.require_process_identity(
                        record, expected_cwd="/expected", expected_argv=["api"]
                    )
            for actual in (
                {**record, "command": ["foreign"]},
                {**record, "cwd": "/foreign"},
            ):
                with (
                    self.subTest(actual=actual),
                    patch.object(rollout, "process_identity", return_value=actual),
                ):
                    with self.assertRaises(RuntimeError):
                        rollout.require_process_identity(
                            record, expected_cwd="/expected", expected_argv=["api"]
                        )
            with patch.object(
                rollout,
                "listeners",
                return_value=[
                    'LISTEN 0 128 0.0.0.0:8010 0.0.0.0:* users:(("foreign",pid=200,fd=4))'
                ],
            ):
                with self.assertRaises(RuntimeError):
                    rollout.require_listener("127.0.0.1:8010", 200)

    def test_foreign_database_consumers_block_inspection(self) -> None:
        with patch.object(rollout, "settings") as config:
            self._set_live_config(config)
            with (
                patch.object(
                    rollout,
                    "inspect_database",
                    side_effect=RuntimeError("Database has active consumers"),
                ),
                patch.object(
                    rollout, "local_source_hashes", return_value={"sidecar": "sha"}
                ),
            ):
                with self.assertRaises(RuntimeError):
                    rollout.inspect_target()

    def test_original_ledgers_must_be_exact_and_pids_must_be_stopped(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            evidence = Path(temp)
            with (
                patch.object(rollout, "ORIGINAL_EVIDENCE", evidence),
                patch.object(rollout, "require_original_checkout"),
            ):
                with patch.object(rollout, "listeners", return_value=[]):
                    with self.assertRaisesRegex(RuntimeError, "ledger is missing"):
                        rollout.require_stopped_old_generation()
                for component in ("backend", "ui"):
                    identity = {
                        "pid": 700 + int(component == "ui"),
                        "cwd": str(
                            rollout.ORIGINAL_WORKTREE
                            / ("backend" if component == "backend" else "frontend")
                        ),
                        "command": rollout.original_command(component),
                        "start_ticks": "12345",
                    }
                    (evidence / f"{component}-process.json").write_text(
                        json.dumps({"component": component, "identity": identity})
                    )
                    (evidence / f"{component}-process.json").chmod(0o600)
                with (
                    patch.object(rollout, "listeners", return_value=[]),
                    patch.object(
                        rollout, "process_identity", side_effect=ProcessLookupError
                    ),
                ):
                    rollout.require_stopped_old_generation()
                with (
                    patch.object(rollout, "listeners", return_value=[]),
                    patch.object(
                        rollout,
                        "process_identity",
                        side_effect=lambda pid: {
                            "pid": pid,
                            "cwd": "/foreign",
                            "command": ["foreign"],
                            "start_ticks": "reused",
                        },
                    ),
                    self.assertRaisesRegex(RuntimeError, "stale/foreign"),
                ):
                    rollout.require_stopped_old_generation()

    def test_apply_requires_confirmation_fresh_private_evidence_and_stopped_services(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as parent:
            parent_path = Path(parent)
            reused = parent_path / "used"
            reused.mkdir(mode=0o700)
            for argv in (
                ["apply", "--evidence-dir", str(parent_path / "fresh")],
                [
                    "apply",
                    "--confirm-database",
                    "historical_date_game_test",
                    "--evidence-dir",
                    str(parent_path / "fresh"),
                ],
                [
                    "apply",
                    "--confirm-database",
                    "historical_date_game_catalog_test",
                    "--evidence-dir",
                    str(reused),
                ],
            ):
                with (
                    self.subTest(argv=argv),
                    patch.object(rollout, "settings") as config,
                ):
                    self._set_live_config(config)
                    with patch.object(
                        rollout,
                        "inspect_target",
                        side_effect=RuntimeError("foreign session"),
                    ) as inspect:
                        self.assertNotEqual(rollout.main(argv), 0)
                        inspect.assert_not_called()

    def test_module_cli_parses_mutating_commands_instead_of_inspecting(self) -> None:
        backend = Path(rollout.__file__).resolve().parents[2]
        environment = dict(os.environ)
        environment.update(
            {
                "HDG_VERIFICATION_PROFILE": "lives",
                "POSTGRES_DB": "historical_date_game_lives_backend_test",
                "POSTGRES_SERVER": "127.0.0.1",
                "POSTGRES_PORT": "5433",
                "ENVIRONMENT": "local",
            }
        )
        commands = (
            ("apply", "--evidence-dir"),
            ("start", "--origin"),
            ("stop", "--evidence-dir"),
            ("resume-migration", "--evidence-dir"),
            ("verify-migration", "--evidence-dir"),
            ("relaunch", "--parent-evidence-dir"),
        )
        for command, required_option in commands:
            with self.subTest(command=command):
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "tests.browser.three_lives_local_rollout",
                        command,
                    ],
                    cwd=backend,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 2, completed.stderr)
                self.assertIn("usage:", completed.stderr)
                self.assertIn(command, completed.stderr)
                self.assertIn(required_option, completed.stderr)
                self.assertNotIn("Three-life rollout stopped", completed.stderr)
                self.assertEqual(completed.stdout, "")

    def test_main_none_uses_process_argv_and_routes_apply_once(self) -> None:
        evidence = Path("/tmp/opencode/cli-dispatch-evidence")
        with (
            patch.object(
                sys,
                "argv",
                [
                    "three_lives_local_rollout",
                    "apply",
                    "--confirm-database",
                    rollout.DATABASE,
                    "--evidence-dir",
                    str(evidence),
                ],
            ),
            patch.object(rollout, "require_local_target") as require_target,
            patch.object(rollout, "_apply") as apply,
            patch.object(rollout, "inspect_target") as inspect,
        ):
            self.assertEqual(rollout.main(None), 0)
        require_target.assert_called_once_with()
        apply.assert_called_once_with(evidence)
        inspect.assert_not_called()

    def test_explicit_empty_argv_keeps_read_only_inspect_default(self) -> None:
        proof = {"database": {"revision": rollout.EXPECTED_OLD_REVISION}}
        with (
            patch.object(
                sys,
                "argv",
                [
                    "three_lives_local_rollout",
                    "apply",
                    "--confirm-database",
                    rollout.DATABASE,
                    "--evidence-dir",
                    "/tmp/opencode/should-not-apply",
                ],
            ),
            patch.object(rollout, "inspect_target", return_value=proof) as inspect,
            patch.object(rollout, "_apply") as apply,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            self.assertEqual(rollout.main([]), 0)
        inspect.assert_called_once_with()
        apply.assert_not_called()
        self.assertIn(rollout.EXPECTED_OLD_REVISION, stdout.getvalue())

    def test_verify_migration_cli_routes_to_receipt_only_recovery(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            evidence = Path(temp)
            with patch.object(rollout, "verify_migration") as verify:
                self.assertEqual(
                    rollout.main(["verify-migration", "--evidence-dir", str(evidence)]),
                    0,
                )
            verify.assert_called_once_with(evidence)

    def test_stop_never_adopts_unrecorded_pid_or_uses_broad_kill(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            with (
                patch.object(rollout, "process_identity") as identity,
                patch.object(os, "kill") as kill,
            ):
                result = rollout.main(["stop", "--evidence-dir", temp])
            self.assertNotEqual(result, 0)
            identity.assert_not_called()
            kill.assert_not_called()
        source = Path(rollout.__file__).read_text()
        for forbidden in ("pkill", "killpg", "DROP SCHEMA", "TRUNCATE", "CASCADE"):
            self.assertNotIn(forbidden, source)

    def test_committed_reset_migration_failure_records_phase_without_restart(
        self,
    ) -> None:
        engine = MagicMock()
        transaction = MagicMock()
        transaction.__enter__.return_value = MagicMock()
        transaction.__exit__.return_value = False
        engine.begin.return_value = transaction
        phases: list[dict[str, object]] = []
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            evidence = Path(temp) / "evidence"
            with (
                patch.object(rollout, "_private_directory"),
                patch.object(
                    rollout,
                    "inspect_target",
                    return_value={"database": {"revision": "20261013_01"}},
                ),
                patch.object(rollout, "_code_commit", return_value="abc"),
                patch.object(rollout, "_write_private"),
                patch.object(
                    rollout,
                    "_replace_private",
                    side_effect=lambda _dir, _name, phase: phases.append(phase),
                ),
                patch.object(rollout, "create_engine", return_value=engine),
                patch.object(
                    rollout,
                    "retained_table_digests",
                    return_value={"item": {"count": 1, "sha256": "stable"}},
                ),
                patch.object(
                    rollout, "local_source_hashes", return_value={"source": "stable"}
                ),
                patch.object(rollout, "_schema_revision", return_value="20261013_01"),
                patch.object(
                    rollout,
                    "gameplay_counts",
                    return_value={
                        "gameoperation": 0,
                        "gamerun": 0,
                        "dailydefinition": 0,
                    },
                ),
                patch.object(
                    rollout,
                    "reset_gameplay",
                    return_value={
                        "gameoperation": 2,
                        "gamerun": 3,
                        "dailydefinition": 1,
                    },
                ),
                patch.object(
                    rollout,
                    "run_local_migration",
                    side_effect=RuntimeError("migration failed"),
                ),
                patch.object(os, "kill") as kill,
            ):
                with self.assertRaisesRegex(RuntimeError, "migration failed"):
                    rollout._apply(evidence)
            self.assertEqual(phases[-1]["phase"], "reset_committed")
            self.assertEqual(phases[-1]["error_type"], "RuntimeError")
            kill.assert_not_called()
            engine.dispose.assert_called_once_with()

    def test_retained_data_mismatch_refuses_migration(self) -> None:
        before = {
            "tables": {"user": {"count": 1, "sha256": "before"}},
            "files": {"release/file": "a"},
        }
        changed = {
            "tables": {"user": {"count": 2, "sha256": "after"}},
            "files": {"release/file": "a"},
        }
        with self.assertRaisesRegex(RuntimeError, "retained data changed"):
            rollout.require_preservation_match(before, changed, "after-delete")

    def test_source_hashes_include_private_configured_sidecar(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            sidecar = Path(temp) / "event-links.json"
            sidecar.write_bytes(b'{"retained":true}')
            sidecar.chmod(0o600)
            digest = hashlib.sha256(sidecar.read_bytes()).hexdigest()
            with (
                patch.object(settings, "GAME_EVENT_LINKS_FILE", sidecar),
                patch.object(settings, "GAME_EVENT_LINKS_SHA256", digest),
                patch.object(rollout, "ORIGINAL_LIVE", Path(temp)),
                patch.object(rollout, "ORIGINAL_RELEASE_ID", "release"),
            ):
                source = Path(temp) / "data/game/releases/release"
                runtime = Path(temp) / "data/game/local-catalog-runtime"
                source.mkdir(parents=True)
                runtime.mkdir(parents=True)
                (source / "catalog.json").write_bytes(b"catalog")
                (runtime / "media.bin").write_bytes(b"media")
                hashes = rollout.local_source_hashes(require_expected=True)
            self.assertEqual(hashes["event-link-sidecar"], digest)
            self.assertIn("data/game/releases/release/catalog.json", hashes)
            self.assertIn("data/game/local-catalog-runtime/media.bin", hashes)

    def test_synthetic_sources_use_real_hashes_and_preserve_tamper_guards(self) -> None:
        with synthetic_rollout_sources() as root:
            baseline = rollout.local_source_hashes(require_expected=True)
            self.assertEqual(len(baseline), 3)
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            media = root / "data/game/local-catalog-runtime/media.svg"
            self.assertEqual(media.stat().st_mode & 0o777, 0o600)
            media.write_bytes(b"changed synthetic media")
            self.assertNotEqual(rollout.local_source_hashes(require_expected=True), baseline)
            media.unlink()
            media.symlink_to(root / "event-links.json")
            with self.assertRaisesRegex(RuntimeError, "aliased"):
                rollout.local_source_hashes(require_expected=True)
            media.unlink()
            sidecar = root / "event-links.json"
            sidecar.write_bytes(b"tampered sidecar")
            with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
                rollout.local_source_hashes(require_expected=True)

    def test_apply_retained_mismatch_rolls_back_before_migration(self) -> None:
        engine = MagicMock()
        transaction = MagicMock()
        transaction.__enter__.return_value = MagicMock()
        transaction.__exit__.return_value = False
        engine.begin.return_value = transaction
        evidence_values: list[tuple[str, object]] = []
        before_tables = {"user": {"count": 1, "sha256": "before"}}
        after_tables = {"user": {"count": 2, "sha256": "changed"}}
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            evidence = Path(temp) / "evidence"
            with (
                patch.object(rollout, "_private_directory"),
                patch.object(rollout, "_code_commit", return_value="abc"),
                patch.object(
                    rollout,
                    "inspect_target",
                    return_value={
                        "database": {"revision": rollout.EXPECTED_OLD_REVISION}
                    },
                ),
                patch.object(
                    rollout,
                    "_write_private",
                    side_effect=lambda _d, n, v: evidence_values.append((n, v)),
                ),
                patch.object(
                    rollout,
                    "_replace_private",
                    side_effect=lambda _d, n, v: evidence_values.append((n, v)),
                ),
                patch.object(rollout, "create_engine", return_value=engine),
                patch.object(
                    rollout,
                    "_schema_revision",
                    return_value=rollout.EXPECTED_OLD_REVISION,
                ),
                patch.object(
                    rollout,
                    "retained_table_digests",
                    side_effect=[before_tables, after_tables],
                ),
                patch.object(
                    rollout, "local_source_hashes", return_value={"source": "same"}
                ),
                patch.object(
                    rollout,
                    "reset_gameplay",
                    return_value={
                        "gameoperation": 1,
                        "gamerun": 1,
                        "dailydefinition": 0,
                    },
                ),
                patch.object(rollout, "run_local_migration") as migrate,
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "retained data changed before-commit"
                ):
                    rollout._apply(evidence)
            migrate.assert_not_called()
            self.assertEqual(transaction.__exit__.call_args.args[0], RuntimeError)
            preserved = [
                value for name, value in evidence_values if name == "preservation.json"
            ][-1]
            if not isinstance(preserved, dict):
                raise AssertionError("preservation evidence must be an object")
            self.assertEqual(preserved["after_delete"]["tables"], after_tables)
            engine.dispose.assert_called_once_with()

    def test_apply_rechecks_retained_data_after_migration_and_records_mismatch(
        self,
    ) -> None:
        engine = MagicMock()
        transaction = MagicMock()
        transaction.__enter__.return_value = MagicMock()
        transaction.__exit__.return_value = False
        engine.begin.return_value = transaction
        connection = MagicMock()
        manager = MagicMock()
        manager.__enter__.return_value = connection
        engine.connect.return_value = manager
        before_tables = {"user": {"count": 1, "sha256": "stable"}}
        changed_tables = {"user": {"count": 2, "sha256": "changed"}}
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            evidence = Path(temp) / "evidence"
            with (
                patch.object(rollout, "_code_commit", return_value="abc"),
                patch.object(
                    rollout,
                    "inspect_target",
                    return_value={
                        "database": {"revision": rollout.EXPECTED_OLD_REVISION}
                    },
                ),
                patch.object(rollout, "create_engine", return_value=engine),
                patch.object(
                    rollout,
                    "retained_table_digests",
                    side_effect=[
                        before_tables,
                        before_tables,
                        before_tables,
                        changed_tables,
                    ],
                ),
                patch.object(
                    rollout, "local_source_hashes", return_value={"source": "stable"}
                ),
                patch.object(
                    rollout,
                    "_schema_revision",
                    side_effect=[
                        rollout.EXPECTED_OLD_REVISION,
                        rollout.EXPECTED_OLD_REVISION,
                        rollout.NEW_REVISION,
                    ],
                ),
                patch.object(
                    rollout,
                    "gameplay_counts",
                    return_value={
                        "gameoperation": 0,
                        "gamerun": 0,
                        "dailydefinition": 0,
                    },
                ),
                patch.object(
                    rollout,
                    "reset_gameplay",
                    return_value={
                        "gameoperation": 1,
                        "gamerun": 1,
                        "dailydefinition": 1,
                    },
                ),
                patch.object(rollout, "run_local_migration") as migrate,
                patch.object(
                    rollout,
                    "inspect_database",
                    return_value={"revision": rollout.NEW_REVISION},
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "retained data changed after-migration"
                ):
                    rollout._apply(evidence)
            migrate.assert_called_once_with(rollout.NEW_REVISION)
            phase = json.loads((evidence / "reset.json").read_text())
            preservation = json.loads((evidence / "preservation.json").read_text())
            self.assertEqual(phase["phase"], "migration_completed_unverified")
            self.assertEqual(phase["error_type"], "RuntimeError")
            self.assertEqual(preservation["after_migration"]["tables"], changed_tables)
            self.assertFalse((evidence / "migration.json").exists())

    def test_start_records_owned_processes_and_keeps_launch_secrets_private(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            evidence = self._evidence_dir(Path(temp) / "evidence")
            origins = ["http://localhost:5174", "http://192.168.1.214:5174"]
            launches: list[tuple[list[str], dict[str, str], Path]] = []
            processes = [
                MagicMock(pid=731, poll=MagicMock(return_value=None)),
                MagicMock(pid=732, poll=MagicMock(return_value=None)),
            ]

            def popen(
                command: list[str],
                *,
                cwd: Path,
                env: dict[str, str],
                stdout: Any,
                stderr: Any,
                start_new_session: bool,
            ) -> Any:
                del stdout, stderr, start_new_session
                launches.append((command, env, cwd))
                return processes[len(launches) - 1]

            def identity(process: Any, cwd: Path, command: list[str]) -> dict[str, Any]:
                return {
                    "pid": process.pid,
                    "cwd": str(cwd),
                    "command": command,
                    "start_ticks": str(process.pid * 10),
                }

            def current_identity(pid: int) -> dict[str, Any]:
                process = next(process for process in processes if process.pid == pid)
                component = "backend" if pid == 731 else "ui"
                cwd = rollout.WORKTREE / (
                    "backend" if component == "backend" else "frontend"
                )
                return identity(process, cwd, rollout.new_command(component))

            with (
                patch.object(
                    rollout,
                    "_verify_start_proof",
                    return_value={
                        "runtime": "/retained/runtime",
                        "database": {"revision": rollout.NEW_REVISION},
                    },
                ),
                patch.object(rollout, "_current_ip", return_value="192.168.1.214"),
                patch.object(rollout, "_require_free_listener"),
                patch.object(rollout, "_wait_listener"),
                patch.object(rollout, "_wait_readiness"),
                patch.object(rollout, "wait_process_identity", side_effect=identity),
                patch.object(rollout, "process_identity", side_effect=current_identity),
                patch.object(rollout, "_code_commit", return_value="abc"),
                patch.object(subprocess, "Popen", side_effect=popen),
                patch.object(settings, "SECRET_KEY", "private-test-secret"),
                patch.object(settings, "POSTGRES_PASSWORD", "private-test-password"),
                patch.object(
                    settings, "GAME_EVENT_LINKS_FILE", rollout.ORIGINAL_SIDECAR
                ),
                patch.object(
                    settings,
                    "GAME_EVENT_LINKS_SHA256",
                    rollout.ORIGINAL_SIDECAR_SHA256,
                ),
                patch.object(settings, "GAME_GUEST_COOKIE_NAME", "hdg_guest_real"),
                patch.object(
                    settings,
                    "GAME_DATA_DIR",
                    rollout.ORIGINAL_LIVE / "data/game/local-catalog-runtime",
                ),
                patch.object(settings, "FRONTEND_HOST", "http://localhost:5174"),
                patch.object(
                    settings,
                    "BACKEND_CORS_ORIGINS",
                    ["http://localhost:5174", "http://192.168.1.214:5174"],
                ),
            ):
                rollout.start_generation(evidence, origins)

            self.assertEqual(len(launches), 2)
            for component, process in zip(("backend", "ui"), processes, strict=True):
                record = json.loads(
                    (evidence / f"{component}-process.json").read_text()
                )
                self.assertEqual(record["component"], component)
                self.assertEqual(record["identity"]["pid"], process.pid)
                self.assertEqual(
                    record["identity"]["command"], rollout.new_command(component)
                )
                self.assertEqual(
                    (evidence / f"{component}-process.json").stat().st_mode & 0o777,
                    0o600,
                )
            env = launches[0][1]
            self.assertEqual(env["POSTGRES_DB"], rollout.DATABASE)
            self.assertEqual(env["BACKEND_CORS_ORIGINS"], json.dumps(origins))
            self.assertEqual(env["GAME_GUEST_COOKIE_NAME"], "hdg_guest_real")
            self.assertEqual(env["GAME_DATA_DIR"], "/retained/runtime")
            self.assertEqual(
                env["GAME_EVENT_LINKS_FILE"], str(rollout.ORIGINAL_SIDECAR)
            )
            self.assertEqual(
                env["GAME_EVENT_LINKS_SHA256"], rollout.ORIGINAL_SIDECAR_SHA256
            )
            self.assertEqual(env["SECRET_KEY"], "private-test-secret")
            self.assertEqual(env["POSTGRES_PASSWORD"], "private-test-password")
            self.assertNotIn(
                "private-test-secret", (evidence / "backend.log").read_text()
            )
            self.assertNotIn(
                "private-test-password",
                (evidence / "backend-process.json").read_text(),
            )

    def test_start_refuses_invalid_proof_before_launch(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            evidence = self._evidence_dir(Path(temp) / "evidence")
            with (
                patch.object(
                    rollout,
                    "_verify_start_proof",
                    side_effect=RuntimeError("wrong schema/proof"),
                ),
                patch.object(subprocess, "Popen") as popen,
                self.assertRaisesRegex(RuntimeError, "wrong schema/proof"),
            ):
                rollout.start_generation(
                    evidence,
                    ["http://localhost:5174", "http://192.168.1.214:5174"],
                )
            popen.assert_not_called()

    def test_start_validates_applied_schema_and_code_identity(self) -> None:
        for schema, current_code, expected_error in (
            ("20261013_01", "tested", "Verified reset/migration proof"),
            (rollout.NEW_REVISION, "other-code", "differs from applied code proof"),
        ):
            with (
                self.subTest(schema=schema, current_code=current_code),
                tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp,
            ):
                evidence = self._evidence_dir(Path(temp) / "evidence")
                baseline = {
                    "tables": {"user": {"count": 1, "sha256": "retained"}},
                    "files": {"source": "retained"},
                }
                self._private_json(
                    evidence,
                    "reset.json",
                    {
                        "phase": "migration_verified",
                        "database": rollout.DATABASE,
                        "schema_after": schema,
                        "code_commit": "tested",
                    },
                )
                self._private_json(
                    evidence,
                    "preservation.json",
                    {"before_reset": baseline, "after_migration": baseline},
                )
                self._private_json(
                    evidence, "migration.json", {"revision": rollout.NEW_REVISION}
                )
                with (
                    patch.object(rollout, "_code_commit", return_value=current_code),
                    patch.object(rollout, "inspect_database") as inspect,
                    self.assertRaisesRegex(RuntimeError, expected_error),
                ):
                    rollout._verify_start_proof(
                        evidence,
                        ["http://localhost:5174", "http://192.168.1.214:5174"],
                    )
                inspect.assert_not_called()

    def test_start_refuses_occupied_listener_before_launch(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            evidence = self._evidence_dir(Path(temp) / "evidence")
            with (
                patch.object(
                    rollout,
                    "_verify_start_proof",
                    return_value={"runtime": "/retained/runtime", "database": {}},
                ),
                patch.object(rollout, "_code_commit", return_value="abc"),
                patch.object(
                    settings, "GAME_EVENT_LINKS_FILE", rollout.ORIGINAL_SIDECAR
                ),
                patch.object(
                    settings,
                    "GAME_EVENT_LINKS_SHA256",
                    rollout.ORIGINAL_SIDECAR_SHA256,
                ),
                patch.object(settings, "GAME_GUEST_COOKIE_NAME", "hdg_guest_real"),
                patch.object(
                    settings,
                    "GAME_DATA_DIR",
                    rollout.ORIGINAL_LIVE / "data/game/local-catalog-runtime",
                ),
                patch.object(settings, "FRONTEND_HOST", "http://localhost:5174"),
                patch.object(
                    settings,
                    "BACKEND_CORS_ORIGINS",
                    ["http://localhost:5174", "http://192.168.1.214:5174"],
                ),
                patch.object(
                    rollout,
                    "_require_free_listener",
                    side_effect=RuntimeError("port occupied"),
                ),
                patch.object(subprocess, "Popen") as popen,
                self.assertRaisesRegex(RuntimeError, "port occupied"),
            ):
                rollout.start_generation(
                    evidence, ["http://localhost:5174", "http://192.168.1.214:5174"]
                )
            popen.assert_not_called()

    def test_owned_stop_success_and_second_record_mismatch_signals_nobody(self) -> None:
        for mismatch in (False, True):
            with (
                self.subTest(mismatch=mismatch),
                tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp,
            ):
                evidence = self._evidence_dir(Path(temp) / "evidence")
                identities = {}
                listener_lines = []
                for component, pid, address in (
                    ("ui", 811, "0.0.0.0:5174"),
                    ("backend", 812, "127.0.0.1:8010"),
                ):
                    identity = {
                        "pid": pid,
                        "cwd": str(
                            rollout.WORKTREE
                            / ("frontend" if component == "ui" else "backend")
                        ),
                        "command": rollout.new_command(component),
                        "start_ticks": str(pid * 10),
                    }
                    identities[pid] = identity
                    listener_lines.append(
                        f'LISTEN 0 128 {address} *:* users:(("owned",pid={pid},fd=5))'
                    )
                    self._private_json(
                        evidence,
                        f"{component}-process.json",
                        {"component": component, "identity": identity},
                    )
                self._private_json(
                    evidence,
                    "start.json",
                    {"phase": "started", "pids": {"ui": 811, "backend": 812}},
                )

                def process(
                    pid: int,
                    identities: dict[int, dict[str, Any]] = identities,
                    mismatch: bool = mismatch,
                ) -> dict[str, Any]:
                    identity = dict(identities[pid])
                    if mismatch and pid == 812:
                        identity["start_ticks"] = "reused"
                    return identity

                with (
                    patch.object(rollout, "process_identity", side_effect=process),
                    patch.object(rollout, "listeners", return_value=listener_lines),
                    patch.object(os, "kill") as kill,
                ):
                    if mismatch:
                        with self.assertRaisesRegex(
                            RuntimeError, "identity does not match"
                        ):
                            rollout._stop_new_generation(evidence)
                        kill.assert_not_called()
                    else:
                        rollout._stop_new_generation(evidence)
                        self.assertEqual(
                            kill.call_args_list,
                            [
                                unittest.mock.call(811, signal.SIGTERM),
                                unittest.mock.call(812, signal.SIGTERM),
                            ],
                        )

    def test_partial_start_failure_stops_only_confirmed_backend(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            evidence = self._evidence_dir(Path(temp) / "evidence")
            origins = ["http://localhost:5174", "http://192.168.1.214:5174"]
            processes = [
                MagicMock(pid=901, poll=MagicMock(return_value=None)),
                MagicMock(pid=902, poll=MagicMock(return_value=None)),
            ]
            launched: list[tuple[list[str], Path]] = []
            identities: dict[int, dict[str, Any]] = {}

            def popen(
                command: list[str],
                *,
                cwd: Path,
                env: dict[str, str],
                stdout: Any,
                stderr: Any,
                start_new_session: bool,
            ) -> Any:
                del env, stdout, stderr, start_new_session
                launched.append((command, cwd))
                process = processes[len(launched) - 1]
                identities[process.pid] = {
                    "pid": process.pid,
                    "cwd": str(cwd),
                    "command": command,
                    "start_ticks": str(process.pid * 10),
                }
                return process

            def readiness(
                component: str, _identity: dict[str, Any], _origins: list[str]
            ) -> None:
                if component == "ui":
                    raise RuntimeError("UI failed readiness")

            with (
                patch.object(
                    rollout,
                    "_verify_start_proof",
                    return_value={
                        "runtime": "/retained/runtime",
                        "database": {"revision": rollout.NEW_REVISION},
                    },
                ),
                patch.object(rollout, "_code_commit", return_value="abc"),
                patch.object(rollout, "_require_free_listener"),
                patch.object(rollout, "_wait_listener"),
                patch.object(rollout, "_wait_readiness", side_effect=readiness),
                patch.object(
                    rollout,
                    "wait_process_identity",
                    side_effect=lambda process, _cwd, _command: identities[process.pid],
                ),
                patch.object(
                    rollout, "process_identity", side_effect=lambda pid: identities[pid]
                ),
                patch.object(
                    settings, "GAME_EVENT_LINKS_FILE", rollout.ORIGINAL_SIDECAR
                ),
                patch.object(
                    settings,
                    "GAME_EVENT_LINKS_SHA256",
                    rollout.ORIGINAL_SIDECAR_SHA256,
                ),
                patch.object(settings, "GAME_GUEST_COOKIE_NAME", "hdg_guest_real"),
                patch.object(
                    settings,
                    "GAME_DATA_DIR",
                    rollout.ORIGINAL_LIVE / "data/game/local-catalog-runtime",
                ),
                patch.object(settings, "FRONTEND_HOST", "http://localhost:5174"),
                patch.object(
                    settings,
                    "BACKEND_CORS_ORIGINS",
                    ["http://localhost:5174", "http://192.168.1.214:5174"],
                ),
                patch.object(subprocess, "Popen", side_effect=popen),
            ):
                with self.assertRaisesRegex(RuntimeError, "UI failed readiness"):
                    rollout.start_generation(evidence, origins)

            start = json.loads((evidence / "start.json").read_text())
            self.assertEqual(start["phase"], "start_failed")
            self.assertEqual(start["started"], {"backend": 901})
            self.assertTrue((evidence / "backend-process.json").is_file())
            self.assertFalse((evidence / "ui-process.json").exists())
            diagnostic = evidence / "ui-unconfirmed-902.json"
            self.assertTrue(diagnostic.is_file())
            diagnostic_before = diagnostic.read_bytes()

            backend_listener = [
                'LISTEN 0 128 127.0.0.1:8010 *:* users:(("owned",pid=901,fd=5))'
            ]
            with (
                patch.object(
                    rollout, "process_identity", side_effect=lambda pid: identities[pid]
                ),
                patch.object(rollout, "listeners", return_value=backend_listener),
                patch.object(os, "kill") as kill,
            ):
                rollout._stop_new_generation(evidence)

            kill.assert_called_once_with(901, signal.SIGTERM)
            self.assertEqual(diagnostic.read_bytes(), diagnostic_before)
            self.assertEqual(
                json.loads((evidence / "start.json").read_text())["phase"],
                "start_failed",
            )

    def test_partial_stop_rejects_inconsistent_ledgers_before_any_signal(self) -> None:
        cases = ("missing", "extra", "malformed", "mismatch")
        for case in cases:
            with (
                self.subTest(case=case),
                tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp,
            ):
                evidence = self._evidence_dir(Path(temp) / "evidence")
                self._private_json(
                    evidence,
                    "start.json",
                    {"phase": "start_failed", "started": {"backend": 911}},
                )
                backend_identity = {
                    "pid": 911,
                    "cwd": str(rollout.WORKTREE / "backend"),
                    "command": rollout.new_command("backend"),
                    "start_ticks": "9110",
                }
                ui_identity = {
                    "pid": 912,
                    "cwd": str(rollout.WORKTREE / "frontend"),
                    "command": rollout.new_command("ui"),
                    "start_ticks": "9120",
                }
                if case != "missing":
                    self._private_json(
                        evidence,
                        "backend-process.json",
                        {
                            "component": "backend",
                            "identity": (
                                "not-an-identity"
                                if case == "malformed"
                                else (
                                    {**backend_identity, "start_ticks": "reused"}
                                    if case == "mismatch"
                                    else backend_identity
                                )
                            ),
                        },
                    )
                if case == "extra":
                    self._private_json(
                        evidence,
                        "ui-process.json",
                        {"component": "ui", "identity": ui_identity},
                    )

                actual = {911: backend_identity, 912: ui_identity}

                def current_identity(
                    pid: int, identities: dict[int, dict[str, Any]] = actual
                ) -> dict[str, Any]:
                    return identities[pid]

                with (
                    patch.object(
                        rollout, "process_identity", side_effect=current_identity
                    ),
                    patch.object(
                        rollout,
                        "listeners",
                        return_value=[
                            'LISTEN 0 128 127.0.0.1:8010 *:* users:(("owned",pid=911,fd=5))',
                            'LISTEN 0 128 0.0.0.0:5174 *:* users:(("owned",pid=912,fd=5))',
                        ],
                    ),
                    patch.object(os, "kill") as kill,
                ):
                    with self.assertRaises(RuntimeError):
                        rollout._stop_new_generation(evidence)
                    kill.assert_not_called()

    def test_resume_requires_committed_phase_old_revision_and_empty_gameplay(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            evidence = self._evidence_dir(Path(temp) / "evidence")
            before = {
                "tables": {"item": {"count": 1, "sha256": "stable"}},
                "files": {"source": "stable"},
            }
            self._private_json(
                evidence,
                "reset.json",
                {
                    "phase": "reset_committed",
                    "database": rollout.DATABASE,
                    "schema_before": rollout.EXPECTED_OLD_REVISION,
                    "code_commit": "abc",
                },
            )
            self._private_json(evidence, "preservation.json", {"before_reset": before})
            engine = MagicMock()
            connection = MagicMock()
            connection.execute.return_value.scalar_one.return_value = 0
            manager = MagicMock()
            manager.__enter__.return_value = connection
            engine.connect.return_value = manager
            with (
                patch.object(rollout, "_code_commit", return_value="abc"),
                patch.object(
                    rollout,
                    "inspect_target",
                    return_value={
                        "database": {"revision": rollout.EXPECTED_OLD_REVISION}
                    },
                ),
                patch.object(
                    rollout,
                    "retained_table_digests_for_database",
                    return_value=before["tables"],
                ),
                patch.object(
                    rollout, "retained_table_digests", return_value=before["tables"]
                ),
                patch.object(
                    rollout, "local_source_hashes", return_value=before["files"]
                ),
                patch.object(
                    rollout, "_schema_revision", side_effect=[rollout.NEW_REVISION]
                ),
                patch.object(rollout, "create_engine", return_value=engine),
                patch.object(rollout, "run_local_migration") as migrate,
                patch.object(
                    rollout,
                    "inspect_database",
                    return_value={"revision": rollout.NEW_REVISION},
                ),
                patch.object(rollout, "_write_private") as write,
            ):
                rollout.resume_migration(evidence)
            migrate.assert_called_once_with(rollout.NEW_REVISION)
            write.assert_called_once()

    def test_resume_refuses_invalid_phase_revision_or_nonempty_gameplay(self) -> None:
        for phase, revision, remaining in (
            ("inspected", rollout.EXPECTED_OLD_REVISION, 0),
            ("reset_committed", "20261011_01", 0),
            ("reset_committed", rollout.EXPECTED_OLD_REVISION, 1),
        ):
            with (
                self.subTest(phase=phase, revision=revision, remaining=remaining),
                tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp,
            ):
                evidence = self._evidence_dir(Path(temp) / "evidence")
                before = {
                    "tables": {"item": {"count": 1, "sha256": "stable"}},
                    "files": {"source": "stable"},
                }
                self._private_json(
                    evidence,
                    "reset.json",
                    {
                        "phase": phase,
                        "database": rollout.DATABASE,
                        "schema_before": rollout.EXPECTED_OLD_REVISION,
                        "code_commit": "abc",
                    },
                )
                self._private_json(
                    evidence, "preservation.json", {"before_reset": before}
                )
                engine = MagicMock()
                connection = MagicMock()
                connection.execute.return_value.scalar_one.return_value = remaining
                manager = MagicMock()
                manager.__enter__.return_value = connection
                engine.connect.return_value = manager
                with (
                    patch.object(rollout, "_code_commit", return_value="abc"),
                    patch.object(
                        rollout,
                        "inspect_target",
                        return_value={"database": {"revision": revision}},
                    ),
                    patch.object(
                        rollout,
                        "retained_table_digests_for_database",
                        return_value=before["tables"],
                    ),
                    patch.object(
                        rollout,
                        "retained_table_digests",
                        return_value=before["tables"],
                    ),
                    patch.object(
                        rollout, "local_source_hashes", return_value=before["files"]
                    ),
                    patch.object(
                        rollout, "_schema_revision", side_effect=[rollout.NEW_REVISION]
                    ),
                    patch.object(rollout, "create_engine", return_value=engine),
                    patch.object(rollout, "run_local_migration") as migrate,
                ):
                    with self.assertRaises(RuntimeError):
                        rollout.resume_migration(evidence)
                    migrate.assert_not_called()


class MigrationRecoveryTestSupport(unittest.TestCase):
    provenance_paths = (
        "backend/tests/browser/three_lives_local_rollout.py",
        "backend/tests/browser/test_three_lives_local_rollout.py",
        "docs/beta/board-polish-three-lives.md",
    )

    def _git(self, *args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(self.git_worktree), *args], text=True
        ).strip()

    def _commit(self, message: str) -> str:
        subprocess.run(["git", "-C", str(self.git_worktree), "add", "-A"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.git_worktree),
                "-c",
                "user.name=Rollout Test Fixture",
                "-c",
                "user.email=rollout-fixture@example.invalid",
                "commit",
                "-m",
                message,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        return self._git("rev-parse", "HEAD")

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(synthetic_rollout_sources())
        temporary = tempfile.TemporaryDirectory(
            prefix="rollout-git-", dir="/tmp/opencode"
        )
        self.addCleanup(temporary.cleanup)
        self.git_worktree = Path(temporary.name) / "worktree"
        self.git_worktree.mkdir()
        self.git_worktree.chmod(0o700)
        subprocess.run(
            [
                "git",
                "init",
                "--quiet",
                "--initial-branch=applied",
                str(self.git_worktree),
            ],
            check=True,
        )
        for directory in (
            "backend/tests/browser",
            "docs/beta",
            "frontend/node_modules",
        ):
            (self.git_worktree / directory).mkdir(parents=True, exist_ok=True)
        for path in self.provenance_paths:
            (self.git_worktree / path).write_text("applied rollout baseline\n")
        self._commit("applied rollout")
        self.applied_commit = self._git("rev-parse", "HEAD")
        self._git("branch", "repair")
        self._git("checkout", "--quiet", "repair")
        for path in self.provenance_paths:
            (self.git_worktree / path).write_text("reviewed repair\n")
        self._commit("reviewed repair")
        self.repair_commit = self._git("rev-parse", "HEAD")

        worktree_patch = patch.object(rollout, "WORKTREE", self.git_worktree)
        worktree_patch.start()
        self.addCleanup(worktree_patch.stop)
        applied_patch = patch.object(
            rollout, "APPLIED_CODE_COMMIT", self.applied_commit
        )
        applied_patch.start()
        self.addCleanup(applied_patch.stop)
        code_commit_patch = patch.object(
            rollout, "_code_commit", return_value=self.repair_commit
        )
        code_commit_patch.start()
        self.addCleanup(code_commit_patch.stop)
        # Recovery/relaunch unit tests use a simulated stopped-service boundary;
        # guard-mismatch tests inject explicit process/listener state themselves.
        listeners_patch = patch.object(rollout, "listeners", return_value=[])
        self.simulated_listeners = listeners_patch.start()
        self.addCleanup(listeners_patch.stop)
        stopped_guard_patch = patch.object(rollout, "require_stopped_old_generation")
        self.simulated_stopped_guard = stopped_guard_patch.start()
        self.addCleanup(stopped_guard_patch.stop)

    def test_recovery_provenance_uses_an_owned_fixture_history(self) -> None:
        self.assertEqual(rollout.WORKTREE, self.git_worktree)
        current, paths = rollout._recovery_code_provenance(self.applied_commit)
        self.assertEqual(current, self.repair_commit)
        self.assertEqual(paths, sorted(self.provenance_paths))

    def test_recovery_provenance_rejects_product_path_in_real_git_diff(self) -> None:
        product = self.git_worktree / "backend/app/core/config.py"
        product.parent.mkdir(parents=True)
        product.write_text("product change\n")
        product_commit = self._commit("add forbidden product path")
        with self.assertRaisesRegex(RuntimeError, "changed product source"):
            rollout._recovery_code_provenance(self.applied_commit, product_commit)

    def test_recovery_provenance_rejects_missing_allowed_path_in_real_git_diff(
        self,
    ) -> None:
        self._git("checkout", "--quiet", "applied")
        for path in self.provenance_paths[:2]:
            (self.git_worktree / path).write_text("partial repair\n")
        incomplete_commit = self._commit("incomplete repair")
        with self.assertRaisesRegex(RuntimeError, "changed product source"):
            rollout._recovery_code_provenance(self.applied_commit, incomplete_commit)

    def test_recovery_provenance_rejects_unrelated_real_git_history(self) -> None:
        self._git("checkout", "--quiet", "--orphan", "unrelated")
        subprocess.run(
            [
                "git",
                "-C",
                str(self.git_worktree),
                "rm",
                "--quiet",
                "-r",
                "--cached",
                ".",
            ],
            check=True,
        )
        (self.git_worktree / "unrelated.txt").write_text("unrelated history\n")
        unrelated_commit = self._commit("unrelated root")
        with self.assertRaisesRegex(RuntimeError, "not descended"):
            rollout._recovery_code_provenance(self.applied_commit, unrelated_commit)

    def test_recovery_provenance_rejects_invalid_applied_commit(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "differs from recorded rollout"):
            rollout._recovery_code_provenance("f" * 40, self.repair_commit)

    def _test_target(self) -> Any:
        return patch.multiple(
            settings,
            POSTGRES_DB=rollout.TEST_DATABASE,
            GAME_EVENT_LINKS_FILE=rollout.ORIGINAL_SIDECAR,
            GAME_EVENT_LINKS_SHA256=rollout.ORIGINAL_SIDECAR_SHA256,
        )

    def _make_unverified_evidence(self, evidence: Path) -> bytes:
        evidence.mkdir(mode=0o700)
        evidence.chmod(0o700)
        with (
            patch.object(settings, "POSTGRES_DB", rollout.TEST_DATABASE),
            patch.object(settings, "GAME_EVENT_LINKS_FILE", rollout.ORIGINAL_SIDECAR),
            patch.object(
                settings,
                "GAME_EVENT_LINKS_SHA256",
                rollout.ORIGINAL_SIDECAR_SHA256,
            ),
        ):
            rollout.inspect_database(allow_test_database=True)
            tables = rollout.retained_table_digests_for_database()
            files = rollout.local_source_hashes(require_expected=True)
            engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
            try:
                with engine.connect() as connection:
                    gameplay = rollout.gameplay_counts(connection)
            finally:
                engine.dispose()
        if any(gameplay.values()):
            self.fail(f"Migration proof database gameplay is not empty: {gameplay}")
        before = {"tables": tables, "files": files}
        rollout._write_private(
            evidence,
            "inspection.json",
            {
                "database": {
                    "database": rollout.TEST_DATABASE,
                    "revision": rollout.EXPECTED_OLD_REVISION,
                },
                "services_stopped": True,
            },
        )
        phase = {
            "phase": "migration_completed_unverified",
            "database": rollout.TEST_DATABASE,
            "code_commit": self.applied_commit,
            "schema_before": rollout.EXPECTED_OLD_REVISION,
            "deleted": {
                "gameoperation": 473,
                "gamerun": 162,
                "dailydefinition": 8,
            },
            "remaining": {
                "gameoperation": 0,
                "gamerun": 0,
                "dailydefinition": 0,
            },
            "error_type": "RuntimeError",
        }
        rollout._write_private(evidence, "reset.json", phase)
        rollout._write_private(
            evidence,
            "preservation.json",
            {
                "before_reset": before,
                "after_delete": before,
                "after_commit": before,
            },
        )
        return (evidence / "reset.json").read_bytes()


class MigrationRecoveryTests(MigrationRecoveryTestSupport):
    def test_recovery_writes_separate_receipt_and_start_accepts_it(self) -> None:
        environment.require_guest_test_target(
            rollout.TEST_DATABASE, settings.POSTGRES_SERVER, settings.ENVIRONMENT
        )
        environment.require_owned_guest_database(rollout.TEST_DATABASE)
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            evidence = Path(temp) / "unverified"
            original_reset = self._make_unverified_evidence(evidence)
            with self._test_target():
                with self.assertRaisesRegex(
                    RuntimeError, "Private evidence file identity/mode"
                ):
                    rollout._verify_start_proof(
                        evidence,
                        [
                            "http://localhost:5174",
                            "http://192.168.1.214:5174",
                        ],
                        allow_test_database=True,
                    )
                with (
                    patch.object(rollout, "reset_gameplay") as reset_gameplay,
                    patch.object(rollout, "run_local_migration") as migrate,
                    patch.object(os, "kill") as kill,
                ):
                    receipt = rollout.verify_migration(
                        evidence, allow_test_database=True
                    )
                self.simulated_stopped_guard.assert_called()
                reset_gameplay.assert_not_called()
                migrate.assert_not_called()
                kill.assert_not_called()
                self.assertEqual((evidence / "reset.json").read_bytes(), original_reset)
                self.assertFalse((evidence / "migration.json").exists())
                receipt_path = evidence / "migration-verification.json"
                self.assertEqual(receipt_path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(receipt["phase"], "migration_verified_by_recovery")
                self.assertEqual(receipt["applied_code_commit"], self.applied_commit)
                self.assertIn("inspection.json", receipt["applied_evidence_sha256"])
                with (
                    patch.object(rollout, "_current_ip", return_value="192.168.1.214"),
                    patch.object(old, "require_origins"),
                    patch.object(rollout, "_require_free_listener"),
                    patch.object(rollout, "require_stopped_old_generation") as stopped,
                ):
                    proof = rollout._verify_start_proof(
                        evidence,
                        [
                            "http://localhost:5174",
                            "http://192.168.1.214:5174",
                        ],
                        allow_test_database=True,
                    )
                stopped.assert_called_once_with()
                self.assertEqual(proof["database"], receipt["database"])

                receipt_bytes = receipt_path.read_bytes()
                with self.assertRaisesRegex(RuntimeError, "already exists"):
                    rollout.verify_migration(evidence, allow_test_database=True)
                self.assertEqual(receipt_path.read_bytes(), receipt_bytes)
                self.assertEqual((evidence / "reset.json").read_bytes(), original_reset)

                inspection_path = evidence / "inspection.json"
                original_inspection = inspection_path.read_bytes()
                inspection_path.write_bytes(original_inspection + b" ")
                with (
                    patch.object(rollout, "inspect_database") as inspect,
                    self.assertRaises(RuntimeError),
                ):
                    rollout._verify_start_proof(
                        evidence,
                        [
                            "http://localhost:5174",
                            "http://192.168.1.214:5174",
                        ],
                        allow_test_database=True,
                    )
                inspect.assert_not_called()

    def test_recovery_rejects_wrong_phase_revision_and_applied_commit(self) -> None:
        for key, value in (
            ("phase", "reset_committed"),
            ("schema_before", "wrong_revision"),
            ("code_commit", "0" * 40),
        ):
            with (
                self.subTest(key=key),
                tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp,
            ):
                evidence = Path(temp) / "unverified"
                self._make_unverified_evidence(evidence)
                reset_path = evidence / "reset.json"
                phase = json.loads(reset_path.read_text())
                phase[key] = value
                reset_path.write_text(json.dumps(phase))
                reset_path.chmod(0o600)
                reset_bytes = reset_path.read_bytes()
                with (
                    self._test_target(),
                    patch.object(rollout, "inspect_database") as inspect,
                    self.assertRaises(RuntimeError),
                ):
                    rollout.verify_migration(evidence, allow_test_database=True)
                inspect.assert_not_called()
                self.assertEqual(reset_path.read_bytes(), reset_bytes)
                self.assertFalse((evidence / "migration-verification.json").exists())

    def test_recovery_refuses_nonempty_gameplay_and_changed_retained_baseline(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            evidence = Path(temp) / "nonempty"
            self._make_unverified_evidence(evidence)
            with (
                self._test_target(),
                patch.object(
                    rollout, "gameplay_counts", return_value={"gameoperation": 1}
                ),
                self.assertRaisesRegex(RuntimeError, "gameplay"),
            ):
                rollout.verify_migration(evidence, allow_test_database=True)
            self.assertFalse((evidence / "migration-verification.json").exists())

        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            evidence = Path(temp) / "mismatch"
            self._make_unverified_evidence(evidence)
            preservation_path = evidence / "preservation.json"
            preservation = json.loads(preservation_path.read_text())
            for phase in ("before_reset", "after_delete", "after_commit"):
                preservation[phase]["tables"]["user"]["sha256"] = "0" * 64
            preservation_path.write_text(json.dumps(preservation))
            preservation_path.chmod(0o600)
            with (
                self._test_target(),
                self.assertRaisesRegex(RuntimeError, "retained data changed"),
            ):
                rollout.verify_migration(evidence, allow_test_database=True)
            self.assertFalse((evidence / "migration-verification.json").exists())

    def test_recovery_changed_product_path_is_outside_exact_allowlist(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "changed product source"):
            rollout.validate_recovery_changed_paths(
                [
                    "backend/tests/browser/three_lives_local_rollout.py",
                    "backend/tests/browser/test_three_lives_local_rollout.py",
                    "docs/beta/board-polish-three-lives.md",
                    "backend/app/core/config.py",
                ]
            )

    def test_recovery_refuses_real_foreign_idle_pool_without_receipt(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            evidence = Path(temp) / "unverified"
            original_reset = self._make_unverified_evidence(evidence)
            with self._test_target():
                engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
                try:
                    with engine.connect() as connection:
                        connection.execute(text("SET TRANSACTION READ ONLY"))
                        connection.execute(text("SELECT 1")).scalar_one()
                    with self.assertRaisesRegex(
                        RuntimeError, "Database has active consumers"
                    ):
                        rollout.verify_migration(evidence, allow_test_database=True)
                    self.assertEqual(
                        (evidence / "reset.json").read_bytes(), original_reset
                    )
                    self.assertFalse(
                        (evidence / "migration-verification.json").exists()
                    )
                finally:
                    engine.dispose()


class PooledConnectionInspectionTests(unittest.TestCase):
    def test_real_idle_sqlalchemy_pool_blocks_independent_inspection_until_dispose(
        self,
    ) -> None:
        environment.require_guest_test_target(
            rollout.TEST_DATABASE, settings.POSTGRES_SERVER, settings.ENVIRONMENT
        )
        environment.require_owned_guest_database(rollout.TEST_DATABASE)
        with patch.object(settings, "POSTGRES_DB", rollout.TEST_DATABASE):
            baseline = rollout.inspect_database(allow_test_database=True)
            with environment._maintenance_connection() as maintenance:
                active_row = maintenance.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()",
                    (rollout.TEST_DATABASE,),
                ).fetchone()
                if active_row is None:
                    raise AssertionError("PostgreSQL activity count is missing")
                active_before = active_row[0]
            self.assertEqual(active_before, 0)

            engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
            with patch.object(settings, "POSTGRES_DB", rollout.TEST_DATABASE):
                try:
                    with engine.connect() as connection:
                        connection.execute(text("SET TRANSACTION READ ONLY"))
                        connection.execute(text("SELECT 1")).scalar_one()
                    with environment._maintenance_connection() as maintenance:
                        pooled_states = maintenance.execute(
                            "SELECT state FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()",
                            (rollout.TEST_DATABASE,),
                        ).fetchall()
                    self.assertEqual([row[0] for row in pooled_states], ["idle"])
                    with self.assertRaisesRegex(
                        RuntimeError, "Database has active consumers"
                    ):
                        rollout.inspect_database(
                            allow_test_database=True,
                            expected_revision=baseline["revision"],
                        )
                    verified = rollout.inspect_migration_after_pool_dispose(
                        engine, allow_test_database=True
                    )
                finally:
                    engine.dispose()

            self.assertEqual(verified, baseline)


class RelaunchLifecycleTests(MigrationRecoveryTestSupport):
    origins = ["http://localhost:5174", "http://192.168.1.214:5174"]
    step6_screenshots = {
        "live-freeplay-1920x900.png",
        "live-freeplay-1366x768.png",
        "live-freeplay-mobile-390x844.png",
        "live-freeplay-terminal-1366x768.png",
        "live-daily-1366x768.png",
    }

    def _record_successful_parent_start(self, evidence: Path) -> None:
        pids = {"backend": 2147483000, "ui": 2147483001}
        rollout._write_private(
            evidence,
            "start.json",
            {"phase": "started", "pids": pids, "origins": self.origins},
        )
        for component, pid in pids.items():
            rollout._write_private(
                evidence,
                f"{component}-process.json",
                {
                    "component": component,
                    "identity": {
                        "pid": pid,
                        "cwd": str(
                            rollout.WORKTREE
                            / ("backend" if component == "backend" else "frontend")
                        ),
                        "command": rollout.new_command(component),
                        "start_ticks": str(pid * 10),
                    },
                },
            )
            (evidence / f"{component}.log").write_bytes(b"owned test generation\n")
            (evidence / f"{component}.log").chmod(0o600)
        receipt = json.loads((evidence / rollout.RECOVERY_RECEIPT).read_text())
        retained_tables = receipt["retained_state"]["tables"]
        row_proof = {
            name: {
                "count": value["count"],
                "primary_key_sha256_to_row_sha256": {
                    hashlib.sha256(
                        f"{name}-{index}".encode()
                    ).hexdigest(): hashlib.sha256(
                        f"{name}-row-{index}".encode()
                    ).hexdigest()
                    for index in range(value["count"])
                },
            }
            for name, value in retained_tables.items()
        }
        rollout._write_private(
            evidence,
            "step6-pre-browser-baseline.json",
            {
                "head": receipt["verified_code_commit"],
                "revision": rollout.NEW_REVISION,
                "gameplay": {
                    "gameoperation": 0,
                    "gamerun": 0,
                    "dailydefinition": 0,
                },
                "retained_tables": row_proof,
            },
        )
        step6 = evidence / "step6"
        step6.mkdir(mode=0o700)
        (step6 / "results").mkdir(mode=0o775)
        # mkdir's mode is filtered by the runner umask; the provenance guard
        # checks this historical results mode exactly, not the host's default.
        (step6 / "results").chmod(0o775)
        rollout._write_private(
            step6,
            "step6-browser-summary.json",
            {
                "origin": "http://192.168.1.214:5174",
                "api": "http://127.0.0.1:8010",
                "options_protocol_version": 2,
                "guest_cookie_verified": True,
                "freeplay": {
                    "initial_lives": 3,
                    "mistake_lives": [2, 1, 0],
                    "terminal_status": "lost",
                    "screenshots": [
                        "live-freeplay-1920x900.png",
                        "live-freeplay-1366x768.png",
                        "live-freeplay-mobile-390x844.png",
                        "live-freeplay-terminal-1366x768.png",
                    ],
                },
                "daily": {
                    "initial_lives": 3,
                    "second_start_available": False,
                    "screenshot": "live-daily-1366x768.png",
                },
            },
        )
        rollout._write_private(step6, "package.json", {"name": "private-step6-proof"})
        for name, contents in {
            "playwright.config.ts": b"export default {};\n",
            "step6.spec.ts": b"test('retained proof', () => {});\n",
        }.items():
            path = step6 / name
            path.write_bytes(contents)
            path.chmod(0o600)
        rollout._write_private(
            step6 / "results", ".last-run.json", {"status": "passed"}
        )
        for name in self.step6_screenshots:
            path = step6 / name
            path.write_bytes(f"retained screenshot {name}\n".encode())
            path.chmod(0o600)
        (step6 / "node_modules").symlink_to(
            rollout.WORKTREE / "frontend/node_modules", target_is_directory=True
        )

    def _seed_legitimate_guest_run(self) -> Any:
        from sqlmodel import Session

        from app.game.guest_sessions import bootstrap_guest_session
        from app.game.run_service import start_freeplay
        from app.game.schemas import FreeplayStart

        engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
        owner_id = None
        try:
            with Session(engine) as session:
                release_id = session.execute(
                    text("SELECT release_id FROM catalogselection WHERE id=1")
                ).scalar_one()
                guest = bootstrap_guest_session(session, None, datetime.now(UTC))
                owner_id = guest.player.owner_id
                command = FreeplayStart.model_validate(
                    {
                        "protocol_version": 2,
                        "operation_id": str(uuid4()),
                        "catalog_release_id": release_id,
                        "config": {
                            "category_ids": ["battles"],
                            "start": {"value": 500, "era": "BCE"},
                            "end": {"value": 2026, "era": "CE"},
                            "min_gap": 1,
                        },
                    }
                )
                run = start_freeplay(session, owner_id, command)
                session.commit()
                run_id = run.run_id
        except Exception:
            if owner_id is not None:
                with Session(engine) as cleanup:
                    from app.models import User

                    owner = cleanup.get(User, owner_id)
                    if owner is not None:
                        cleanup.delete(owner)
                        cleanup.commit()
            raise
        finally:
            engine.dispose()
        return owner_id, run_id

    def _remove_guest_run(self, owner_id: Any) -> None:
        from sqlmodel import Session

        from app.models import User

        engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
        try:
            with Session(engine) as session:
                owner = session.get(User, owner_id)
                if owner is not None:
                    session.delete(owner)
                    session.commit()
        finally:
            engine.dispose()

    def test_relaunch_accepts_real_guest_and_gameplay_growth_and_binds_child(
        self,
    ) -> None:
        environment.require_guest_test_target(
            rollout.TEST_DATABASE, settings.POSTGRES_SERVER, settings.ENVIRONMENT
        )
        environment.require_owned_guest_database(rollout.TEST_DATABASE)
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            parent = Path(temp) / "parent"
            child = Path(temp) / "child"
            original_reset = self._make_unverified_evidence(parent)
            reviewed_head = subprocess.check_output(
                ["git", "-C", str(rollout.WORKTREE), "rev-parse", "HEAD"], text=True
            ).strip()
            with (
                self._test_target(),
                patch.object(rollout, "_code_commit", return_value=reviewed_head),
            ):
                rollout.verify_migration(parent, allow_test_database=True)
                self.simulated_stopped_guard.assert_called()
                self._record_successful_parent_start(parent)
                owner_id, run_id = self._seed_legitimate_guest_run()
                try:
                    with (
                        patch.object(
                            rollout, "_current_ip", return_value="192.168.1.214"
                        ),
                        patch.object(old, "require_origins"),
                        patch.object(rollout, "_require_free_listener"),
                        patch.object(rollout, "require_stopped_old_generation"),
                        patch.object(
                            rollout, "require_parent_process_absent"
                        ) as absent,
                    ):
                        proof = rollout._verify_relaunch_proof(
                            parent, self.origins, allow_test_database=True
                        )
                    self.simulated_listeners.assert_called()
                    self.assertEqual(
                        proof["database"]["revision"], rollout.NEW_REVISION
                    )
                    self.assertEqual(
                        proof["parent_start"]["pids"]["backend"], 2147483000
                    )
                    self.assertGreater(proof["gameplay"]["gamerun"], 0)
                    self.assertGreater(proof["guest_rows"]["user"], 0)
                    self.assertGreater(proof["guest_rows"]["guestsession"], 0)
                    absent.assert_any_call(2147483000)
                    absent.assert_any_call(2147483001)

                    with (
                        patch.object(rollout, "_current_ip", return_value="192.168.1.214"),
                        patch.object(
                            rollout, "_require_free_listener"
                        ) as free_listener,
                        patch.object(rollout, "_launch_generation") as launch,
                    ):
                        result = rollout.relaunch_generation(
                            parent,
                            child,
                            self.origins,
                            allow_test_database=True,
                        )
                    launch.assert_called_once()
                    self.assertEqual(
                        free_listener.call_args_list,
                        [
                            unittest.mock.call("127.0.0.1", 8010),
                            unittest.mock.call("0.0.0.0", 5174),
                        ],
                    )
                    self.assertEqual(result["phase"], "relaunch_prepared")
                    self.assertEqual(
                        (parent / "reset.json").read_bytes(), original_reset
                    )
                    self.assertEqual(
                        rollout._parent_evidence_hashes(parent),
                        proof["parent_sha256"],
                    )
                    binding = rollout._read_private_json(child, "relaunch.json")
                    self.assertEqual(binding["parent_evidence"], str(parent))
                    self.assertIn(
                        "migration-verification.json", binding["parent_sha256"]
                    )
                    self.assertEqual(
                        binding["recovery_verified_code_commit"],
                        json.loads((parent / rollout.RECOVERY_RECEIPT).read_text())[
                            "verified_code_commit"
                        ],
                    )
                    self.assertTrue(
                        set(binding["code_diff_paths_since_recovery"]).issubset(
                            {
                                "backend/tests/browser/three_lives_local_rollout.py",
                                "backend/tests/browser/test_three_lives_local_rollout.py",
                                "docs/beta/board-polish-three-lives.md",
                            }
                        )
                    )
                    self.assertTrue(
                        {f"step6/{name}" for name in self.step6_screenshots}.issubset(
                            binding["parent_sha256"]
                        )
                    )
                    self.assertIn("step6/package.json", binding["parent_sha256"])
                    self.assertIn(
                        "step6/playwright.config.ts", binding["parent_sha256"]
                    )
                    self.assertIn("step6/step6.spec.ts", binding["parent_sha256"])
                    self.assertIn(
                        "step6/results/.last-run.json", binding["parent_sha256"]
                    )
                    self.assertIn(
                        "step6/node_modules", binding["parent_artifact_identities"]
                    )
                finally:
                    self._remove_guest_run(owner_id)

    def test_relaunch_refuses_missing_or_unexpected_step6_artifacts_before_spawn(
        self,
    ) -> None:
        for mutation in (
            "missing-screenshot",
            "unexpected-nested-file",
            "aliased-dependency",
        ):
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp,
                self._test_target(),
            ):
                parent, child = Path(temp) / "parent", Path(temp) / "child"
                self._make_unverified_evidence(parent)
                head = subprocess.check_output(
                    ["git", "-C", str(rollout.WORKTREE), "rev-parse", "HEAD"],
                    text=True,
                ).strip()
                with patch.object(rollout, "_code_commit", return_value=head):
                    rollout.verify_migration(parent, allow_test_database=True)
                self._record_successful_parent_start(parent)
                step6 = parent / "step6"
                if mutation == "missing-screenshot":
                    (step6 / "live-freeplay-mobile-390x844.png").unlink()
                elif mutation == "unexpected-nested-file":
                    unexpected = step6 / "unreviewed.txt"
                    unexpected.write_text("unexpected")
                    unexpected.chmod(0o600)
                else:
                    dependency_link = step6 / "node_modules"
                    dependency_link.unlink()
                    dependency_link.symlink_to("/tmp", target_is_directory=True)
                with (
                    patch.object(rollout, "_code_commit", return_value=head),
                    patch.object(rollout, "_current_ip", return_value="192.168.1.214"),
                    patch.object(old, "require_origins"),
                    patch.object(rollout, "require_stopped_old_generation"),
                    patch.object(rollout, "require_parent_process_absent"),
                    patch.object(rollout, "_require_free_listener"),
                    patch.object(rollout, "_launch_generation") as launch,
                ):
                    with self.assertRaises(RuntimeError):
                        rollout.relaunch_generation(
                            parent, child, self.origins, allow_test_database=True
                        )
                self.assertFalse(child.exists())
                launch.assert_not_called()

    def test_relaunch_detects_step6_tampering_after_parent_snapshot_before_child(
        self,
    ) -> None:
        environment.require_guest_test_target(
            rollout.TEST_DATABASE, settings.POSTGRES_SERVER, settings.ENVIRONMENT
        )
        environment.require_owned_guest_database(rollout.TEST_DATABASE)
        with (
            tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp,
            self._test_target(),
        ):
            parent, child = Path(temp) / "parent", Path(temp) / "child"
            self._make_unverified_evidence(parent)
            head = subprocess.check_output(
                ["git", "-C", str(rollout.WORKTREE), "rev-parse", "HEAD"],
                text=True,
            ).strip()
            with patch.object(rollout, "_code_commit", return_value=head):
                rollout.verify_migration(parent, allow_test_database=True)
            self._record_successful_parent_start(parent)
            screenshot = parent / "step6/live-freeplay-1920x900.png"
            original_source_hashes = rollout.local_source_hashes

            def tamper_after_source_scan(*args: Any, **kwargs: Any) -> dict[str, str]:
                hashes = original_source_hashes(*args, **kwargs)
                screenshot.write_bytes(screenshot.read_bytes() + b"tampered")
                return hashes

            with (
                patch.object(rollout, "_code_commit", return_value=head),
                patch.object(rollout, "_current_ip", return_value="192.168.1.214"),
                patch.object(old, "require_origins"),
                patch.object(rollout, "require_stopped_old_generation"),
                patch.object(rollout, "require_parent_process_absent"),
                patch.object(rollout, "_require_free_listener"),
                patch.object(
                    rollout, "local_source_hashes", side_effect=tamper_after_source_scan
                ),
                patch.object(rollout, "_launch_generation") as launch,
            ):
                with self.assertRaisesRegex(RuntimeError, "changed during validation"):
                    rollout.relaunch_generation(
                        parent, child, self.origins, allow_test_database=True
                    )
            self.assertFalse(child.exists())
            launch.assert_not_called()

    def test_relaunch_refusals_happen_before_child_creation_or_spawn(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            parent = Path(temp) / "parent"
            child = Path(temp) / "child"
            self._make_unverified_evidence(parent)
            reviewed_head = subprocess.check_output(
                ["git", "-C", str(rollout.WORKTREE), "rev-parse", "HEAD"], text=True
            ).strip()
            with (
                self._test_target(),
                patch.object(rollout, "_code_commit", return_value=reviewed_head),
            ):
                rollout.verify_migration(parent, allow_test_database=True)
                self._record_successful_parent_start(parent)
                with (
                    patch.object(rollout, "_current_ip", return_value="192.168.1.214"),
                    patch.object(old, "require_origins"),
                    patch.object(rollout, "require_stopped_old_generation"),
                    patch.object(rollout, "require_parent_process_absent"),
                    patch.object(rollout, "_require_free_listener"),
                    patch.object(rollout, "_launch_generation") as launch,
                ):
                    with self.assertRaises(RuntimeError):
                        rollout.relaunch_generation(
                            parent,
                            child,
                            [
                                "http://localhost:5174",
                                "http://192.168.1.99:5174",
                            ],
                            allow_test_database=True,
                        )
                    self.assertFalse(child.exists())
                    launch.assert_not_called()

    def test_relaunch_cli_routes_parent_child_and_origins(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            parent, child = Path(temp) / "parent", Path(temp) / "child"
            with patch.object(rollout, "relaunch_generation") as relaunch:
                self.assertEqual(
                    rollout.main(
                        [
                            "relaunch",
                            "--parent-evidence-dir",
                            str(parent),
                            "--evidence-dir",
                            str(child),
                            "--origin",
                            self.origins[0],
                            "--origin",
                            self.origins[1],
                        ]
                    ),
                    0,
                )
            relaunch.assert_called_once_with(parent, child, self.origins)

    def test_relaunch_refuses_parent_code_source_port_consumer_and_pid_reuse(
        self,
    ) -> None:
        refusals = (
            "parent-running",
            "pid-reused",
            "foreign-parent",
            "source-changed",
            "port",
            "consumer",
            "changed-code",
            "bad-ledger",
        )
        for refusal in refusals:
            with (
                self.subTest(refusal=refusal),
                tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp,
                self._test_target(),
            ):
                parent, child = Path(temp) / "parent", Path(temp) / "child"
                self._make_unverified_evidence(parent)
                head = subprocess.check_output(
                    ["git", "-C", str(rollout.WORKTREE), "rev-parse", "HEAD"],
                    text=True,
                ).strip()
                with patch.object(rollout, "_code_commit", return_value=head):
                    rollout.verify_migration(parent, allow_test_database=True)
                self._record_successful_parent_start(parent)
                if refusal == "bad-ledger":
                    (parent / "backend-process.json").write_text("{}")
                    (parent / "backend-process.json").chmod(0o600)
                elif refusal == "foreign-parent":
                    reset = json.loads((parent / "reset.json").read_text())
                    reset["database"] = "unowned_database"
                    (parent / "reset.json").write_text(json.dumps(reset))
                    (parent / "reset.json").chmod(0o600)
                code_commit = "0" * 40 if refusal == "changed-code" else head
                with (
                    patch.object(rollout, "_code_commit", return_value=code_commit),
                    patch.object(rollout, "_current_ip", return_value="192.168.1.214"),
                    patch.object(old, "require_origins"),
                    patch.object(rollout, "require_stopped_old_generation"),
                    patch.object(rollout, "require_parent_process_absent") as absent,
                    patch.object(rollout, "_require_free_listener") as free_listener,
                    patch.object(rollout, "inspect_database") as inspect,
                    patch.object(rollout, "local_source_hashes") as source_hashes,
                    patch.object(rollout, "process_identity") as process_identity,
                    patch.object(rollout, "_launch_generation") as launch,
                ):
                    inspect.return_value = {
                        "database": rollout.TEST_DATABASE,
                        "revision": rollout.NEW_REVISION,
                    }
                    source_hashes.return_value = json.loads(
                        (parent / rollout.RECOVERY_RECEIPT).read_text()
                    )["retained_state"]["files"]
                    process_identity.side_effect = ProcessLookupError
                    if refusal == "parent-running":
                        absent.side_effect = RuntimeError("prior process is active")
                    elif refusal == "pid-reused":
                        process_identity.side_effect = None
                        process_identity.return_value = {"pid": 2147483000}
                        absent.side_effect = RuntimeError("prior PID was reused")
                    elif refusal == "source-changed":
                        source_hashes.return_value = {"changed": "0" * 64}
                    elif refusal == "port":
                        free_listener.side_effect = RuntimeError("port occupied")
                    elif refusal == "consumer":
                        inspect.side_effect = RuntimeError(
                            "Database has active consumers"
                        )
                    with self.assertRaises(RuntimeError):
                        rollout.relaunch_generation(
                            parent, child, self.origins, allow_test_database=True
                        )
                    if refusal in {"parent-running", "pid-reused"}:
                        absent.assert_called()
                    if refusal == "port":
                        free_listener.assert_called_once_with("127.0.0.1", 8010)
                    self.assertFalse(child.exists())
                    launch.assert_not_called()

    def test_relaunch_refuses_occupied_parent_listener_before_child_or_spawn(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp,
            self._test_target(),
        ):
            parent, child = Path(temp) / "parent", Path(temp) / "child"
            self._make_unverified_evidence(parent)
            head = subprocess.check_output(
                ["git", "-C", str(rollout.WORKTREE), "rev-parse", "HEAD"],
                text=True,
            ).strip()
            with patch.object(rollout, "_code_commit", return_value=head):
                rollout.verify_migration(parent, allow_test_database=True)
            self._record_successful_parent_start(parent)
            occupied = [
                'LISTEN 0 128 127.0.0.1:8010 0.0.0.0:* users:(("foreign",pid=2460603,fd=8))'
            ]
            with (
                patch.object(rollout, "_code_commit", return_value=head),
                patch.object(rollout, "_current_ip", return_value="192.168.1.214"),
                patch.object(old, "require_origins"),
                patch.object(rollout, "require_parent_process_absent"),
                patch.object(rollout, "listeners", return_value=occupied) as listeners,
                patch.object(rollout, "_launch_generation") as launch,
            ):
                with self.assertRaisesRegex(RuntimeError, "listener remains occupied"):
                    rollout.relaunch_generation(
                        parent, child, self.origins, allow_test_database=True
                    )
            listeners.assert_called_once()
            self.assertFalse(child.exists())
            launch.assert_not_called()

    def test_parent_identity_guard_rejects_pid_reuse(self) -> None:
        with patch.object(
            rollout,
            "process_identity",
            return_value={"pid": 2147483000, "start_ticks": "new-identity"},
        ):
            with self.assertRaisesRegex(RuntimeError, "reused"):
                rollout.require_parent_process_absent(2147483000)

    def test_parent_identity_guard_refuses_unverifiable_pid(self) -> None:
        with patch.object(
            rollout, "process_identity", side_effect=PermissionError("/proc/123")
        ):
            with self.assertRaisesRegex(RuntimeError, "could not be verified"):
                rollout.require_parent_process_absent(123)

    def test_relaunch_refuses_missing_parent_before_child_creation_or_spawn(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            parent, child = Path(temp) / "missing-parent", Path(temp) / "child"
            with patch.object(rollout, "_launch_generation") as launch:
                with self.assertRaises(RuntimeError):
                    rollout.relaunch_generation(parent, child, self.origins)
            self.assertFalse(child.exists())
            launch.assert_not_called()

    def test_relaunch_child_uses_existing_owned_stop_validation(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temp:
            evidence = Path(temp) / "child"
            evidence.mkdir(mode=0o700)
            pids = {"backend": 911, "ui": 912}
            rollout._write_private(
                evidence,
                "relaunch.json",
                {"phase": "relaunch_prepared", "parent_evidence": "/parent"},
            )
            rollout._write_private(
                evidence,
                "start.json",
                {"phase": "started", "pids": pids, "origins": self.origins},
            )
            identities: dict[int, dict[str, Any]] = {}
            for component, pid in pids.items():
                identity = {
                    "pid": pid,
                    "cwd": str(
                        rollout.WORKTREE
                        / ("backend" if component == "backend" else "frontend")
                    ),
                    "command": rollout.new_command(component),
                    "start_ticks": f"{pid}0",
                }
                identities[pid] = identity
                rollout._write_private(
                    evidence,
                    f"{component}-process.json",
                    {"component": component, "identity": identity},
                )
            listeners = [
                'LISTEN 0 128 127.0.0.1:8010 *:* users:(("owned",pid=911,fd=5))',
                'LISTEN 0 128 0.0.0.0:5174 *:* users:(("owned",pid=912,fd=5))',
            ]
            with (
                patch.object(rollout, "process_identity", side_effect=identities.get),
                patch.object(rollout, "listeners", return_value=listeners),
                patch.object(os, "kill") as kill,
            ):
                rollout._stop_new_generation(evidence)
            self.assertEqual(
                kill.call_args_list,
                [
                    unittest.mock.call(912, signal.SIGTERM),
                    unittest.mock.call(911, signal.SIGTERM),
                ],
            )


class ScopedGameplayResetTests(unittest.TestCase):
    engine: Engine

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(synthetic_rollout_sources())

    @classmethod
    def setUpClass(cls) -> None:
        environment.require_guest_test_target(
            DATABASE, settings.POSTGRES_SERVER, settings.ENVIRONMENT
        )
        environment.require_owned_guest_database(DATABASE)
        with environment._maintenance_connection() as connection:
            active_row = connection.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()",
                (DATABASE,),
            ).fetchone()
            assert active_row is not None
            active = active_row[0]
        if active:
            raise RuntimeError("Unexpected consumers of migration proof database")
        cls.engine = create_engine(
            str(settings.SQLALCHEMY_DATABASE_URI).rsplit("/", 1)[0] + "/" + DATABASE
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def test_reset_deletes_only_gameplay_and_migrated_daily_is_fresh(self) -> None:
        from tests.api.routes.test_game_daily import release

        with self.engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        if revision != "20261015_01":
            self.fail(f"Expected clean current schema before proof, got {revision}")
        created_release_id = None
        created_user_id = None
        created_guest_id = None
        created_item_id = None
        created_daily_id = None
        original_selected_release = None
        environment.run_migration(DATABASE, "downgrade", "20261013_01")
        try:
            with tempfile.TemporaryDirectory(
                prefix="three-lives-reset-", dir="/tmp/opencode"
            ) as temp:
                with Session(self.engine) as session:
                    original_selected_release = session.execute(
                        text("SELECT release_id FROM catalogselection WHERE id=1")
                    ).scalar_one()
                    release_id = release(session, Path(temp) / "fixture")
                    user_id, guest_id = uuid4(), uuid4()
                    created_release_id, created_user_id, created_guest_id = (
                        release_id,
                        user_id,
                        guest_id,
                    )
                    event_ids = [
                        str(value)
                        for value in session.execute(
                            text(
                                "SELECT event_id FROM eventrevision WHERE release_id=:release ORDER BY event_id LIMIT 4"
                            ),
                            {"release": release_id},
                        )
                        .scalars()
                        .all()
                    ]
                    now = datetime.now(UTC)
                    session.execute(
                        text("""INSERT INTO "user" (id,email,hashed_password,full_name,is_active,is_superuser)
                        VALUES (:id,:email,'retained-fixture','Reset proof',true,false)"""),
                        {"id": user_id, "email": f"reset-proof-{user_id}@example.com"},
                    )
                    session.execute(
                        text("""INSERT INTO "user" (id,email,hashed_password,full_name,is_active,is_superuser,is_guest)
                        VALUES (:id,:email,'guest-retained-fixture','Guest reset proof',true,false,true)"""),
                        {
                            "id": guest_id,
                            "email": f"reset-guest-{guest_id}@example.com",
                        },
                    )
                    guest_public_id = uuid4()
                    guest_digest = hashlib.sha256(
                        b"reset guest token" + guest_id.bytes
                    ).hexdigest()
                    session.execute(
                        text("""INSERT INTO guestsession (token_digest,owner_id,public_id,created_at,expires_at)
                        VALUES (:digest,:owner,:public,:now,:expires)"""),
                        {
                            "digest": guest_digest,
                            "owner": guest_id,
                            "public": guest_public_id,
                            "now": now,
                            "expires": now.replace(year=now.year + 1),
                        },
                    )
                    created_item_id = uuid4()
                    session.execute(
                        text("""INSERT INTO item (id,title,description,owner_id)
                        VALUES (:id,'reset retained sentinel','unrelated data',:owner)"""),
                        {"id": created_item_id, "owner": user_id},
                    )
                    run_ids = [uuid4(), uuid4(), uuid4()]
                    rules = {
                        "category_ids": ["battles"],
                        "start_year_index": -500,
                        "end_year_index": 3000,
                        "min_gap": 1,
                    }
                    for run_id, status in zip(
                        run_ids, ("active", "lost", "won"), strict=True
                    ):
                        pending = event_ids[1] if status == "active" else None
                        session.execute(
                            text("""INSERT INTO gamerun
                            (id,owner_id,mode,catalog_release_id,seed,generation_version,rules,pool,"order",timeline,pending_event_id,status,streak,revision,created_at,updated_at)
                            VALUES (:id,:owner,'freeplay',:release,:seed,1,:rules,:pool,:order,:timeline,:pending,:status,0,0,:now,:now)"""),
                            {
                                "id": run_id,
                                "owner": user_id,
                                "release": release_id,
                                "seed": b"r" * 32,
                                "rules": json.dumps(rules),
                                "pool": json.dumps(event_ids),
                                "order": json.dumps(event_ids),
                                "timeline": json.dumps(event_ids[:1]),
                                "pending": pending,
                                "status": status,
                                "now": now,
                            },
                        )
                        session.execute(
                            text("""INSERT INTO gameoperation (id,owner_id,operation_id,scope,run_id,payload_digest,outcome,created_at)
                            VALUES (:id,:owner,:operation,'freeplay',:run,:digest,'{}'::jsonb,:now)"""),
                            {
                                "id": uuid4(),
                                "owner": user_id,
                                "operation": uuid4(),
                                "run": run_id,
                                "digest": hashlib.sha256(
                                    f"legacy {status}".encode()
                                ).hexdigest(),
                                "now": now,
                            },
                        )
                    session.execute(
                        text("""INSERT INTO dailydefinition
                        (id,day,catalog_release_id,seed,generation_version,rules,pool,"order",anchor_event_id,created_at)
                        VALUES (:id,:day,:release,:seed,1,:rules,:pool,:order,:anchor,:now)"""),
                        {
                            "id": uuid4(),
                            "day": date(2402, 1, 1),
                            "release": release_id,
                            "seed": b"d" * 32,
                            "rules": json.dumps(
                                {
                                    "category_ids": ["battles"],
                                    "start_year_index": -500,
                                    "end_year_index": 3000,
                                    "min_gap": 1,
                                }
                            ),
                            "pool": json.dumps(event_ids),
                            "order": json.dumps(event_ids),
                            "anchor": event_ids[0],
                            "now": now,
                        },
                    )
                    session.commit()
                    retained_before = _retained_table_digests(session)
                    guest_rows_before = (
                        session.execute(
                            text(
                                "SELECT to_jsonb(g)::text FROM guestsession g ORDER BY token_digest"
                            )
                        )
                        .scalars()
                        .all()
                    )
                    guest_digest_before = hashlib.sha256(
                        json.dumps(guest_rows_before).encode()
                    ).hexdigest()
                    hashes_before = rollout.local_source_hashes()
                    self.assertTrue(
                        hashes_before, "original source/media hashes must be captured"
                    )

                    before_failure = {
                        table: session.execute(
                            text(f'SELECT count(*) FROM "{table}"')
                        ).scalar_one()
                        for table in ("gameoperation", "gamerun", "dailydefinition")
                    }

                    class FailingConnection:
                        def begin_nested(self) -> Any:
                            return session.connection().begin_nested()

                        def execute(self, statement: Any) -> Any:
                            if 'DELETE FROM "gamerun"' in str(statement):
                                raise RuntimeError("injected mid-delete failure")
                            return session.connection().execute(statement)

                    with self.assertRaisesRegex(RuntimeError, "mid-delete"):
                        rollout.reset_gameplay(FailingConnection())
                    after_failure = {
                        table: session.execute(
                            text(f'SELECT count(*) FROM "{table}"')
                        ).scalar_one()
                        for table in ("gameoperation", "gamerun", "dailydefinition")
                    }
                    self.assertEqual(after_failure, before_failure)
                    deleted = rollout.reset_gameplay(session.connection())
                    session.commit()
                    counts = {
                        table: session.execute(
                            text(f'SELECT count(*) FROM "{table}"')
                        ).scalar_one()
                        for table in ("gameoperation", "gamerun", "dailydefinition")
                    }
                    retained_after = _retained_table_digests(session)
                    guest_rows_after = (
                        session.execute(
                            text(
                                "SELECT to_jsonb(g)::text FROM guestsession g ORDER BY token_digest"
                            )
                        )
                        .scalars()
                        .all()
                    )
                    guest_digest_after = hashlib.sha256(
                        json.dumps(guest_rows_after).encode()
                    ).hexdigest()
                    self.assertEqual(
                        set(deleted), {"gameoperation", "gamerun", "dailydefinition"}
                    )
                    self.assertEqual(
                        deleted,
                        {"gameoperation": 3, "gamerun": 3, "dailydefinition": 1},
                    )
                    self.assertEqual(
                        counts, {"gameoperation": 0, "gamerun": 0, "dailydefinition": 0}
                    )
                    self.assertEqual(retained_after, retained_before)
                    self.assertEqual(guest_digest_after, guest_digest_before)
                    self.assertEqual(rollout.local_source_hashes(), hashes_before)
            environment.run_migration(DATABASE, "upgrade", "20261015_01")
            from app.game.daily_service import start_daily
            from app.game.schemas import DailyStart

            with Session(self.engine) as session:
                owner = created_user_id
                if owner is None:
                    raise AssertionError("fixture owner must have been recorded")
                daily_day = datetime.now(UTC).date()
                self.assertEqual(
                    session.execute(
                        text("SELECT count(*) FROM dailydefinition WHERE day=:day"),
                        {"day": daily_day},
                    ).scalar_one(),
                    0,
                )
                first = start_daily(
                    session,
                    owner,
                    DailyStart(protocol_version=2, operation_id=uuid4()),
                    datetime.now(UTC),
                )
                second = start_daily(
                    session,
                    owner,
                    DailyStart(protocol_version=2, operation_id=uuid4()),
                    datetime.now(UTC),
                )
                self.assertEqual(first.run_id, second.run_id)
                self.assertEqual(first.initial_lives, 3)
                self.assertEqual(first.lives_remaining, 3)
                created_daily_id = session.execute(
                    text("SELECT daily_definition_id FROM gamerun WHERE id=:run"),
                    {"run": first.run_id},
                ).scalar_one()
        finally:
            with self.engine.connect() as connection:
                current = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
            if current == "20261013_01":
                environment.run_migration(DATABASE, "upgrade", "20261015_01")
            # Remove only this test's identified fixtures so the owned proof DB
            # returns to its prior retained rows without broad cleanup.
            if created_user_id is not None:
                with Session(self.engine) as cleanup:
                    cleanup.execute(
                        text("DELETE FROM gameoperation WHERE owner_id=:owner"),
                        {"owner": created_user_id},
                    )
                    cleanup.execute(
                        text("DELETE FROM gamerun WHERE owner_id=:owner"),
                        {"owner": created_user_id},
                    )
                    if created_release_id is not None:
                        cleanup.execute(
                            text(
                                "DELETE FROM dailydefinition WHERE catalog_release_id=:release"
                            ),
                            {"release": created_release_id},
                        )
                    if created_daily_id is not None:
                        cleanup.execute(
                            text("DELETE FROM dailydefinition WHERE id=:id"),
                            {"id": created_daily_id},
                        )
                    cleanup.execute(
                        text("DELETE FROM guestsession WHERE owner_id=:owner"),
                        {"owner": created_guest_id},
                    )
                    if created_item_id is not None:
                        cleanup.execute(
                            text("DELETE FROM item WHERE id=:id"),
                            {"id": created_item_id},
                        )
                    cleanup.execute(
                        text('DELETE FROM "user" WHERE id=:id'), {"id": created_user_id}
                    )
                    cleanup.execute(
                        text('DELETE FROM "user" WHERE id=:id'),
                        {"id": created_guest_id},
                    )
                    if created_release_id is not None:
                        cleanup.execute(
                            text(
                                "UPDATE catalogselection SET release_id=:release WHERE id=1"
                            ),
                            {"release": original_selected_release},
                        )
                        cleanup.execute(
                            text("DELETE FROM eventrevision WHERE release_id=:release"),
                            {"release": created_release_id},
                        )
                        cleanup.execute(
                            text(
                                "DELETE FROM catalogcategory WHERE release_id=:release"
                            ),
                            {"release": created_release_id},
                        )
                        cleanup.execute(
                            text("DELETE FROM mediaasset WHERE release_id=:release"),
                            {"release": created_release_id},
                        )
                        cleanup.execute(
                            text("DELETE FROM catalogrelease WHERE id=:release"),
                            {"release": created_release_id},
                        )
                    cleanup.commit()

    def test_delete_failure_rolls_back_all_three_tables(self) -> None:
        connection = MagicMock()
        nested = MagicMock()
        nested.__enter__.return_value = nested
        nested.__exit__.return_value = False
        connection.begin_nested.return_value = nested
        connection.execute.side_effect = [
            MagicMock(rowcount=1),
            RuntimeError("injected"),
        ]
        with self.assertRaises(RuntimeError):
            rollout.reset_gameplay(connection)
        self.assertTrue(nested.__exit__.called)
        self.assertIsNotNone(nested.__exit__.call_args.args[0])

    def test_delete_order_is_dependency_scoped(self) -> None:
        connection = MagicMock()
        nested = MagicMock()
        nested.__enter__.return_value = nested
        nested.__exit__.return_value = False
        connection.begin_nested.return_value = nested
        connection.execute.side_effect = [
            MagicMock(rowcount=2),
            MagicMock(rowcount=3),
            MagicMock(rowcount=1),
            MagicMock(rowcount=4),
        ]
        deleted = rollout.reset_gameplay(connection)
        statements = [str(call.args[0]) for call in connection.execute.call_args_list]
        delete_order = [
            table
            for statement in statements
            for table in ("gameoperation", "gamerun", "dailydefinition")
            if f'DELETE FROM "{table}"' in statement
        ]
        self.assertEqual(delete_order, ["gameoperation", "gamerun", "dailydefinition"])
        self.assertEqual(
            deleted,
            {"gameoperation": 3, "gamerun": 1, "dailydefinition": 4},
        )


if __name__ == "__main__":
    unittest.main()
