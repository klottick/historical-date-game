"""Guarded, local-only gameplay reset for the three-life generation.

Inspection is read-only. Apply is a one-way reset/migration phase: on failure it
records the last completed phase and never restarts the old generation.
"""

import argparse
import hashlib
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast
from urllib.request import urlopen

import psycopg
from sqlalchemy import create_engine, text

from app.core.config import settings
from tests.browser import guest_local_rollout as old
from tests.browser import guest_test_environment as environment

DATABASE = "historical_date_game_catalog_test"
TEST_DATABASE = "historical_date_game_lives_migration_test"
EXPECTED_OLD_REVISION = "20261013_01"
NEW_REVISION = "20261015_01"
APPLIED_CODE_COMMIT = "4d669a5b0249a0346f8b8a6fc0eaf7909d9cc912"
RECOVERY_RECEIPT = "migration-verification.json"
WORKTREE = environment.WORKTREE
ORIGINAL_WORKTREE = Path(
    "/home/klottick/repos/historical-date-game/.worktrees/board-redesign"
)
ORIGINAL_WORKTREE_HEAD = "f53be772f4284b94020a082dab6a09c10ecb8ca4"
ORIGINAL_PRIVATE = ORIGINAL_WORKTREE / ".superpowers/sdd/2026-10-14-game-board-redesign"
ORIGINAL_INTEGRATION = ORIGINAL_PRIVATE / "integration"
ORIGINAL_EVIDENCE = ORIGINAL_PRIVATE / "local-activation"
ORIGINAL_LIVE = Path("/home/klottick/repos/historical-date-game/.worktrees/beta")
ORIGINAL_RELEASE_ID = "jsonl-trial-2026-10-12-review-r1"
ORIGINAL_F1_COMMENT = (
    "F1 beta followup afc85a5 execution-owned disposable DB created 2026-10-12; "
    "approved full pytest cleanup"
)
ORIGINAL_SIDECAR = ORIGINAL_INTEGRATION / "task-5/event-links.json"
ORIGINAL_SIDECAR_SHA256 = (
    "53da618a7ca6efc621296b0da429fa4c83caa906f3683b9375cb7c99302f9fcd"
)
ORIGINAL_NODE = Path("/tmp/opencode/node-v26.11.1-linux-x64/bin/node")
LIVE_GUEST_COOKIE_NAME = "hdg_guest_real"
DELIVERY_EVIDENCE = Path("/tmp/opencode/three-life-local-20261015T150302Z-task7")
STEP6_FIXED_FILES = {
    "package.json",
    "playwright.config.ts",
    "step6.spec.ts",
    "step6-browser-summary.json",
    "results/.last-run.json",
}
STEP6_FREEPLAY_SCREENSHOTS = (
    "live-freeplay-1920x900.png",
    "live-freeplay-1366x768.png",
    "live-freeplay-mobile-390x844.png",
    "live-freeplay-terminal-1366x768.png",
)
STEP6_DAILY_SCREENSHOT = "live-daily-1366x768.png"


def require_local_target(*, allow_test_database: bool = False) -> None:
    allowed = {DATABASE}
    if allow_test_database:
        allowed.add(TEST_DATABASE)
    if (
        settings.POSTGRES_DB not in allowed
        or settings.POSTGRES_SERVER != "127.0.0.1"
        or settings.POSTGRES_PORT != 5433
        or settings.ENVIRONMENT != "local"
    ):
        raise RuntimeError("Exact local rollout database/settings required")
    require_runtime_configuration(settings.POSTGRES_DB)
    if settings.POSTGRES_DB == TEST_DATABASE:
        environment.require_guest_test_target(
            TEST_DATABASE, settings.POSTGRES_SERVER, settings.ENVIRONMENT
        )
        environment.require_owned_guest_database(TEST_DATABASE)


def require_runtime_configuration(database: str) -> None:
    """Require the pinned old-generation selectors only for the LIVE target."""
    if database != DATABASE:
        return
    expected_runtime = ORIGINAL_LIVE / "data/game/local-catalog-runtime"
    expected_origins = {
        "http://localhost:5174",
        "http://192.168.1.214:5174",
    }
    if (
        settings.GAME_EVENT_LINKS_FILE != ORIGINAL_SIDECAR
        or settings.GAME_EVENT_LINKS_SHA256 != ORIGINAL_SIDECAR_SHA256
        or settings.GAME_GUEST_COOKIE_NAME != LIVE_GUEST_COOKIE_NAME
        or settings.GAME_DATA_DIR != expected_runtime
        or settings.FRONTEND_HOST != "http://localhost:5174"
        or {str(origin).rstrip("/") for origin in settings.BACKEND_CORS_ORIGINS}
        != expected_origins
    ):
        raise RuntimeError("Exact original sidecar/runtime settings required")


def require_original_checkout() -> None:
    if (
        ORIGINAL_EVIDENCE != ORIGINAL_PRIVATE / "local-activation"
        or ORIGINAL_INTEGRATION != ORIGINAL_PRIVATE / "integration"
        or ORIGINAL_LIVE
        != Path("/home/klottick/repos/historical-date-game/.worktrees/beta")
        or not ORIGINAL_WORKTREE.is_absolute()
        or ORIGINAL_WORKTREE.resolve(strict=True) != ORIGINAL_WORKTREE
        or not (ORIGINAL_WORKTREE / ".git").is_file()
        or ORIGINAL_EVIDENCE.resolve(strict=True) != ORIGINAL_EVIDENCE
        or ORIGINAL_EVIDENCE.stat().st_mode & 0o777 != 0o700
    ):
        raise RuntimeError("Exact original serving checkout/evidence path required")
    root = subprocess.check_output(
        ["git", "-C", str(ORIGINAL_WORKTREE), "rev-parse", "--show-toplevel"],
        text=True,
    ).strip()
    head = subprocess.check_output(
        ["git", "-C", str(ORIGINAL_WORKTREE), "rev-parse", "HEAD"], text=True
    ).strip()
    status = subprocess.check_output(
        [
            "git",
            "-C",
            str(ORIGINAL_WORKTREE),
            "status",
            "--porcelain",
            "--untracked-files=all",
        ],
        text=True,
    ).splitlines()
    if root != str(ORIGINAL_WORKTREE) or head != ORIGINAL_WORKTREE_HEAD:
        raise RuntimeError("Original serving checkout revision/path changed")
    if any(line[:2] != " M" or line[3:] != ".env" for line in status):
        raise RuntimeError("Original serving checkout has unexpected changes")
    for component in ("backend", "ui"):
        ledger = ORIGINAL_EVIDENCE / f"{component}-process.json"
        if ledger.resolve(strict=True) != ledger:
            raise RuntimeError("Original process ledger path is aliased")


def _code_commit() -> str:
    root = subprocess.check_output(
        ["git", "-C", str(WORKTREE), "rev-parse", "--show-toplevel"], text=True
    ).strip()
    if (
        root != str(WORKTREE)
        or Path(__file__).resolve()
        != WORKTREE / "backend/tests/browser/three_lives_local_rollout.py"
    ):
        raise RuntimeError("Exact implementation worktree required")
    status = subprocess.check_output(
        ["git", "-C", str(WORKTREE), "status", "--porcelain", "--untracked-files=all"],
        text=True,
    ).splitlines()
    if any(line[3:] != ".env" or line[:2] != " M" for line in status):
        raise RuntimeError("Implementation tree has unreviewed changes")
    return subprocess.check_output(
        ["git", "-C", str(WORKTREE), "rev-parse", "HEAD"], text=True
    ).strip()


def validate_recovery_changed_paths(paths: list[str]) -> None:
    allowed = {
        "backend/tests/browser/three_lives_local_rollout.py",
        "backend/tests/browser/test_three_lives_local_rollout.py",
        "docs/beta/board-polish-three-lives.md",
    }
    if set(paths) != allowed:
        raise RuntimeError("Recovery changed product source or unexpected paths")


def _recovery_code_provenance(
    applied_commit: str, current_commit: str | None = None
) -> tuple[str, list[str]]:
    if applied_commit != APPLIED_CODE_COMMIT:
        raise RuntimeError("Recovery applied commit differs from recorded rollout")
    current = current_commit or _code_commit()
    if not current or current == applied_commit:
        raise RuntimeError("Recovery requires a separately reviewed repair commit")
    ancestry = subprocess.run(
        [
            "git",
            "-C",
            str(WORKTREE),
            "merge-base",
            "--is-ancestor",
            applied_commit,
            current,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if ancestry.returncode != 0:
        raise RuntimeError("Recovery commit is not descended from applied commit")
    changed = subprocess.check_output(
        ["git", "-C", str(WORKTREE), "diff", "--name-only", applied_commit, current],
        text=True,
    ).splitlines()
    validate_recovery_changed_paths(changed)
    return current, changed


def _verify_catalog_identity(
    ownership: tuple[str | None, str], catalog: tuple[Any, ...], revision: str
) -> None:
    comment, owner = ownership
    release_id, digest, manifest_bytes, count, fixture = catalog
    if revision in {"20261011_01", EXPECTED_OLD_REVISION}:
        if (
            comment != ORIGINAL_F1_COMMENT
            or owner != settings.POSTGRES_USER
            or str(release_id) != ORIGINAL_RELEASE_ID
            or digest != environment.MANIFEST_SHA
            or hashlib.sha256(manifest_bytes).hexdigest() != environment.MANIFEST_SHA
            or count != 1276
            or fixture is not False
        ):
            raise RuntimeError("Exact original database/catalog identity required")
        return
    if (
        revision != NEW_REVISION
        or comment != ORIGINAL_F1_COMMENT
        or owner != settings.POSTGRES_USER
        or str(release_id) != ORIGINAL_RELEASE_ID
        or digest != environment.MANIFEST_SHA
        or hashlib.sha256(manifest_bytes).hexdigest() != environment.MANIFEST_SHA
        or count != 1276
        or fixture is not False
    ):
        raise RuntimeError("Exact original catalog/schema identity required")


def inspect_database(
    *, allow_test_database: bool = False, expected_revision: str | None = None
) -> dict[str, Any]:
    require_local_target(allow_test_database=allow_test_database)
    database = settings.POSTGRES_DB
    with psycopg.connect(
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        dbname=database,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        connect_timeout=5,
    ) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        ownership = connection.execute(
            "SELECT shobj_description(oid, 'pg_database'), pg_get_userbyid(datdba) "
            "FROM pg_database WHERE datname=current_database()"
        ).fetchone()
        revision_row = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
        if ownership is None or revision_row is None:
            raise RuntimeError("Database ownership or migration revision missing")
        if database == DATABASE:
            if (
                ownership[0] != ORIGINAL_F1_COMMENT
                or ownership[1] != settings.POSTGRES_USER
            ):
                raise RuntimeError("Exact original local database ownership required")
            catalog = connection.execute(
                "SELECT r.id, r.manifest_sha256, r.manifest_bytes, r.event_count, r.fixture "
                "FROM catalogselection s JOIN catalogrelease r ON r.id=s.release_id WHERE s.id=1"
            ).fetchone()
            if catalog is None:
                raise RuntimeError("Selected local catalog missing")
            identity: dict[str, Any] = {
                "database": database,
                "comment": ownership[0],
                "owner": ownership[1],
                "release_id": str(catalog[0]),
                "manifest_sha256": catalog[1],
                "event_count": catalog[3],
                "fixture": catalog[4],
                "revision": revision_row[0],
            }
            _verify_catalog_identity(ownership, catalog, revision_row[0])
        else:
            identity = {"database": database, "revision": revision_row[0]}
    with psycopg.connect(
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        dbname="postgres",
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        connect_timeout=5,
    ) as maintenance:
        activity = maintenance.execute(
            "SELECT pid, usename, application_name FROM pg_stat_activity "
            "WHERE datname=%s AND pid<>pg_backend_pid()",
            (database,),
        ).fetchall()
    if activity:
        raise RuntimeError("Database has active consumers")
    if expected_revision is not None and identity.get("revision") != expected_revision:
        raise RuntimeError("Unexpected schema revision")
    return identity


def inspect_migration_after_pool_dispose(
    engine: Any, *, allow_test_database: bool = False
) -> dict[str, Any]:
    """Close this helper's pooled sessions before independent consumer inspection."""
    engine.dispose()
    return inspect_database(
        allow_test_database=allow_test_database,
        expected_revision=NEW_REVISION,
    )


def _original_evidence_hashes(evidence: Path) -> dict[str, str]:
    names = ("inspection.json", "reset.json", "preservation.json")
    result: dict[str, str] = {}
    for name in names:
        _read_private_json(evidence, name)
        result[name] = hashlib.sha256((evidence / name).read_bytes()).hexdigest()
    return result


def verify_migration(
    evidence: Path, *, allow_test_database: bool = False
) -> dict[str, Any]:
    """Write a separate read-only verification receipt; never alter reset history."""
    _private_directory(evidence, fresh=False)
    require_local_target(allow_test_database=allow_test_database)
    receipt_path = evidence / RECOVERY_RECEIPT
    if os.path.lexists(receipt_path):
        raise RuntimeError("Migration recovery receipt already exists")
    for name in (
        "migration.json",
        "start.json",
        "backend-process.json",
        "ui-process.json",
        "backend.log",
        "ui.log",
    ):
        if os.path.lexists(evidence / name):
            raise RuntimeError("Recovery evidence contains a later lifecycle phase")

    reset_path = evidence / "reset.json"
    applied_evidence_hashes = _original_evidence_hashes(evidence)
    original_reset_bytes = reset_path.read_bytes()
    phase = _read_private_json(evidence, "reset.json")
    preservation = _read_private_json(evidence, "preservation.json")
    inspection = _read_private_json(evidence, "inspection.json")
    if (
        not isinstance(phase, dict)
        or phase.get("phase") != "migration_completed_unverified"
        or phase.get("database") != settings.POSTGRES_DB
        or phase.get("schema_before") != EXPECTED_OLD_REVISION
        or phase.get("code_commit") != APPLIED_CODE_COMMIT
        or phase.get("error_type") != "RuntimeError"
        or phase.get("deleted")
        != {"gameoperation": 473, "gamerun": 162, "dailydefinition": 8}
        or phase.get("remaining")
        != {"gameoperation": 0, "gamerun": 0, "dailydefinition": 0}
    ):
        raise RuntimeError("Exact migration_completed_unverified phase required")
    if not isinstance(inspection, dict) or not isinstance(preservation, dict):
        raise RuntimeError("Original application evidence is invalid")
    initial_database = inspection.get("database")
    if (
        not isinstance(initial_database, dict)
        or initial_database.get("database") != settings.POSTGRES_DB
        or initial_database.get("revision") != EXPECTED_OLD_REVISION
        or inspection.get("services_stopped") is not True
    ):
        raise RuntimeError("Original pre-reset inspection evidence is invalid")
    if settings.POSTGRES_DB == DATABASE:
        initial_runtime = inspection.get("runtime")
        if (
            not isinstance(initial_runtime, dict)
            or initial_database.get("comment") != ORIGINAL_F1_COMMENT
            or initial_database.get("owner") != settings.POSTGRES_USER
            or initial_database.get("release_id") != ORIGINAL_RELEASE_ID
            or initial_database.get("manifest_sha256") != environment.MANIFEST_SHA
            or initial_database.get("event_count") != 1276
            or initial_database.get("fixture") is not False
            or initial_runtime.get("data_dir")
            != str(ORIGINAL_LIVE / "data/game/local-catalog-runtime")
            or initial_runtime.get("event_links_file") != str(ORIGINAL_SIDECAR)
            or initial_runtime.get("event_links_sha256") != ORIGINAL_SIDECAR_SHA256
            or initial_runtime.get("guest_cookie_name") != LIVE_GUEST_COOKIE_NAME
        ):
            raise RuntimeError(
                "Original catalog/runtime inspection identity is invalid"
            )
    before = preservation.get("before_reset")
    if (
        not isinstance(before, dict)
        or not isinstance(before.get("tables"), dict)
        or not isinstance(before.get("files"), dict)
    ):
        raise RuntimeError("Original retained-state baseline is missing")
    for name in ("after_delete", "after_commit"):
        snapshot = preservation.get(name)
        if not isinstance(snapshot, dict):
            raise RuntimeError("Original retained-state snapshot is missing")
        require_preservation_match(before, snapshot, f"recovery-{name}")
    after_migration = preservation.get("after_migration")
    if after_migration is not None:
        if not isinstance(after_migration, dict):
            raise RuntimeError("Original migration snapshot is invalid")
        require_preservation_match(before, after_migration, "recovery-after-migration")

    current_commit, changed_paths = _recovery_code_provenance(phase["code_commit"])
    require_stopped_old_generation()
    database_before = inspect_database(
        allow_test_database=allow_test_database, expected_revision=NEW_REVISION
    )
    engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            gameplay = gameplay_counts(connection)
            tables = retained_table_digests(connection)
    finally:
        engine.dispose()
    if gameplay != {"gameoperation": 0, "gamerun": 0, "dailydefinition": 0}:
        raise RuntimeError("gameplay is not empty after migration")
    current_state = {
        "tables": tables,
        "files": local_source_hashes(require_expected=True),
    }
    require_preservation_match(before, current_state, "recovery-current")
    database_after = inspect_database(
        allow_test_database=allow_test_database, expected_revision=NEW_REVISION
    )
    if database_after != database_before:
        raise RuntimeError("Database identity changed during recovery verification")
    require_stopped_old_generation()
    if (
        reset_path.read_bytes() != original_reset_bytes
        or _original_evidence_hashes(evidence) != applied_evidence_hashes
    ):
        raise RuntimeError(
            "Original apply evidence changed during recovery verification"
        )
    receipt = {
        "phase": "migration_verified_by_recovery",
        "database": database_after,
        "schema_revision": NEW_REVISION,
        "applied_code_commit": phase["code_commit"],
        "verified_code_commit": current_commit,
        "code_diff_paths": sorted(changed_paths),
        "applied_evidence_sha256": applied_evidence_hashes,
        "retained_state": current_state,
        "gameplay": gameplay,
    }
    _write_private(evidence, RECOVERY_RECEIPT, receipt)
    return receipt


def retained_table_digests(connection: Any) -> dict[str, dict[str, str | int]]:
    """Digest every public retained table, separately from gameplay/schema marker."""
    excluded = {"gameoperation", "gamerun", "dailydefinition", "alembic_version"}
    names = (
        connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name"
            )
        )
        .scalars()
        .all()
    )
    quote = connection.dialect.identifier_preparer.quote
    result: dict[str, dict[str, str | int]] = {}
    for name in names:
        if name in excluded:
            continue
        rows = (
            connection.execute(
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


def require_preservation_match(
    before: dict[str, Any], after: dict[str, Any], phase: str
) -> None:
    if before.get("tables") != after.get("tables") or before.get("files") != after.get(
        "files"
    ):
        raise RuntimeError(f"retained data changed {phase}")


def process_identity(pid: int) -> dict[str, Any]:
    root = Path(f"/proc/{pid}")
    return {
        "pid": pid,
        "cwd": str((root / "cwd").resolve(strict=True)),
        "command": (root / "cmdline").read_bytes().decode().rstrip("\0").split("\0"),
        "start_ticks": (root / "stat").read_text().rsplit(")", 1)[1].split()[19],
    }


def wait_process_identity(
    process: Any, cwd: Path, command: list[str]
) -> dict[str, Any]:
    return environment.wait_process_identity(process, cwd, command)


def require_process_identity(
    record: dict[str, Any], *, expected_cwd: str, expected_argv: list[str]
) -> None:
    try:
        actual = process_identity(int(record["pid"]))
    except OSError, ValueError, KeyError:
        raise RuntimeError("Recorded process is no longer verifiable") from None
    if (
        actual != record
        or actual["cwd"] != expected_cwd
        or actual["command"] != expected_argv
    ):
        raise RuntimeError("Recorded process identity does not match")


def listeners() -> list[str]:
    return subprocess.check_output(["ss", "-H", "-ltnp"], text=True).splitlines()


def require_listener(address: str, pid: int) -> None:
    matches = [line for line in listeners() if line.split()[3] == address]
    if len(matches) != 1 or f"pid={pid}," not in matches[0]:
        raise RuntimeError("Listener address/PID ownership mismatch")


def require_stopped_old_generation() -> None:
    # Original-generation ledgers are read only. A live recorded identity or any
    # listener on either service port is a blocker; never adopt or signal it here.
    require_original_checkout()
    for component, address in (("backend", "127.0.0.1:8010"), ("ui", "0.0.0.0:5174")):
        ledger = ORIGINAL_EVIDENCE / f"{component}-process.json"
        if (
            not ledger.is_file()
            or ledger.is_symlink()
            or ledger.stat().st_mode & 0o777 != 0o600
            or ledger.stat().st_nlink != 1
        ):
            raise RuntimeError("Original process ownership ledger is missing")
        record = json.loads(ledger.read_text())
        identity = record.get("identity")
        expected_cwd = str(
            ORIGINAL_WORKTREE / ("backend" if component == "backend" else "frontend")
        )
        if (
            record.get("component") != component
            or not isinstance(identity, dict)
            or set(identity) != {"pid", "cwd", "command", "start_ticks"}
            or identity.get("cwd") != expected_cwd
            or identity.get("command") != original_command(component)
            or not isinstance(identity.get("pid"), int)
            or not isinstance(identity.get("start_ticks"), str)
        ):
            raise RuntimeError("Original process ownership ledger is invalid")
        try:
            current = process_identity(identity["pid"])
        except OSError, ValueError, KeyError:
            current = None
        if current == identity:
            raise RuntimeError("Original owned service is still running")
        if current is not None:
            raise RuntimeError("Recorded PID is occupied by a stale/foreign process")
        if any(line.split()[3] == address for line in listeners()):
            raise RuntimeError("Expected original service port to be stopped")


def inspect_target() -> dict[str, object]:
    require_local_target()
    retained_sources = local_source_hashes(require_expected=True)
    proof = inspect_database(expected_revision=EXPECTED_OLD_REVISION)
    if proof.get("revision") != EXPECTED_OLD_REVISION:
        raise RuntimeError("Expected old schema revision 20261013_01")
    require_stopped_old_generation()
    return {
        "database": proof,
        "services_stopped": True,
        "runtime": {
            "catalog_release_id": ORIGINAL_RELEASE_ID,
            "data_dir": str(ORIGINAL_LIVE / "data/game/local-catalog-runtime"),
            "event_links_file": str(settings.GAME_EVENT_LINKS_FILE),
            "event_links_sha256": settings.GAME_EVENT_LINKS_SHA256,
            "guest_cookie_name": settings.GAME_GUEST_COOKIE_NAME,
            "source_file_count": len(retained_sources),
        },
    }


def reset_gameplay(connection: Any) -> dict[str, int]:
    """Delete only dependent gameplay rows, atomically, under explicit locks."""
    counts: dict[str, int] = {}
    with connection.begin_nested():
        connection.execute(
            text(
                "LOCK TABLE gameoperation, gamerun, dailydefinition IN SHARE ROW EXCLUSIVE MODE"
            )
        )
        for table in ("gameoperation", "gamerun", "dailydefinition"):
            result = connection.execute(text(f'DELETE FROM "{table}"'))
            counts[table] = max(int(result.rowcount or 0), 0)
    return counts


def local_source_hashes(*, require_expected: bool = False) -> dict[str, str]:
    """Hash original source/media trees without writing to either tree."""
    release = ORIGINAL_LIVE / "data/game/releases" / ORIGINAL_RELEASE_ID
    runtime = ORIGINAL_LIVE / "data/game/local-catalog-runtime"
    result: dict[str, str] = {}
    for root in (release, runtime):
        if not root.exists() and not require_expected:
            continue
        if not root.is_dir() or root.is_symlink() or root.resolve(strict=True) != root:
            raise RuntimeError(
                "Original catalog/source/media directory is missing or aliased"
            )
        entries = sorted(root.rglob("*"))
        if any(path.is_symlink() for path in entries):
            raise RuntimeError("Source/media tree contains an aliased path")
        for path in (p for p in entries if p.is_file()):
            if not path.resolve().is_relative_to(root.resolve()):
                raise RuntimeError("Source/media tree contains an aliased file")
            result[str(path.relative_to(ORIGINAL_LIVE))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    sidecar = settings.GAME_EVENT_LINKS_FILE
    sidecar_digest = settings.GAME_EVENT_LINKS_SHA256
    if settings.POSTGRES_DB == DATABASE:
        require_runtime_configuration(DATABASE)
        if sidecar != ORIGINAL_SIDECAR or sidecar_digest != ORIGINAL_SIDECAR_SHA256:
            raise RuntimeError("Exact original event-link sidecar required")
    if (sidecar is None) != (sidecar_digest is None):
        raise RuntimeError("Event-link sidecar path/digest must be supplied together")
    if sidecar is not None and sidecar_digest is not None:
        if (
            not sidecar.is_absolute()
            or sidecar.is_symlink()
            or sidecar.resolve(strict=True) != sidecar
            or not sidecar.is_file()
            or sidecar.stat().st_mode & 0o777 != 0o600
            or sidecar.stat().st_nlink != 1
            or sidecar.stat().st_size > 32 * 1024 * 1024
            or (
                settings.POSTGRES_DB == DATABASE
                and not sidecar.is_relative_to(ORIGINAL_INTEGRATION)
            )
        ):
            raise RuntimeError("Event-link sidecar must remain a private file")
        if settings.POSTGRES_DB == DATABASE:
            for parent in (sidecar.parent, *sidecar.parent.parents):
                if parent == ORIGINAL_INTEGRATION.parent:
                    break
                if (
                    parent.resolve(strict=True) != parent
                    or parent.stat().st_mode & 0o777 != 0o700
                ):
                    raise RuntimeError(
                        "Event-link sidecar directories must remain private"
                    )
        actual = hashlib.sha256(sidecar.read_bytes()).hexdigest()
        if actual != sidecar_digest:
            raise RuntimeError("Event-link sidecar digest mismatch")
        result["event-link-sidecar"] = actual
    if require_expected and not result:
        raise RuntimeError("Original catalog/source/media files are missing")
    return result


def _private_directory(directory: Path, *, fresh: bool) -> None:
    if not directory.is_absolute() or directory.resolve() != directory:
        raise RuntimeError("Evidence path must be absolute and non-aliased")
    if fresh:
        directory.mkdir(mode=0o700)
        directory.chmod(0o700)
    elif not directory.is_dir() or directory.stat().st_mode & 0o777 != 0o700:
        raise RuntimeError("Evidence directory must be an existing private directory")
    if directory.stat().st_mode & 0o777 != 0o700:
        raise RuntimeError("Evidence directory must be private (0700)")


def _write_private(directory: Path, name: str, value: Any) -> None:
    path = directory / name
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, indent=2)


def _read_private_json(directory: Path, name: str) -> Any:
    path = directory / name
    if (
        path.is_symlink()
        or not path.is_file()
        or path.resolve(strict=True) != path
        or path.stat().st_mode & 0o777 != 0o600
        or path.stat().st_nlink != 1
    ):
        raise RuntimeError("Private evidence file identity/mode is invalid")
    return json.loads(path.read_text())


def _apply(evidence: Path) -> None:
    _private_directory(evidence, fresh=True)
    code_commit = _code_commit()
    proof = inspect_target()
    _write_private(evidence, "inspection.json", proof)
    engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
    phase: dict[str, Any] = {
        "phase": "reset_started",
        "database": DATABASE,
        "code_commit": code_commit,
        "schema_before": EXPECTED_OLD_REVISION,
    }
    _write_private(evidence, "reset.json", phase)
    preservation: dict[str, Any] = {}
    try:
        with engine.begin() as connection:
            revision = _schema_revision(connection)
            if revision != EXPECTED_OLD_REVISION:
                raise RuntimeError("Reset transaction requires the exact old revision")
            before = {
                "tables": retained_table_digests(connection),
                "files": local_source_hashes(require_expected=True),
            }
            preservation["before_reset"] = before
            _write_private(evidence, "preservation.json", preservation)
            deleted = reset_gameplay(connection)
            after_delete = {
                "tables": retained_table_digests(connection),
                "files": local_source_hashes(require_expected=True),
            }
            preservation["after_delete"] = after_delete
            _replace_private(evidence, "preservation.json", preservation)
            require_preservation_match(before, after_delete, "before-commit")
            remaining = gameplay_counts(connection)
            if any(remaining.values()):
                raise RuntimeError("Gameplay tables are not empty after scoped reset")
            phase = {
                **phase,
                "phase": "reset_delete_verified_uncommitted",
                "deleted": deleted,
                "remaining": remaining,
            }
            _replace_private(evidence, "reset.json", phase)
        phase = {
            "phase": "reset_committed",
            "deleted": deleted,
            "database": DATABASE,
            "code_commit": code_commit,
            "schema_before": EXPECTED_OLD_REVISION,
            "remaining": {"gameoperation": 0, "gamerun": 0, "dailydefinition": 0},
        }
        _replace_private(evidence, "reset.json", phase)
        with engine.connect() as connection:
            if _schema_revision(connection) != EXPECTED_OLD_REVISION:
                raise RuntimeError("Unexpected schema revision after gameplay reset")
            after_commit = {
                "tables": retained_table_digests(connection),
                "files": local_source_hashes(require_expected=True),
            }
            preservation["after_commit"] = after_commit
            _replace_private(evidence, "preservation.json", preservation)
            require_preservation_match(before, after_commit, "after-commit")
            if any(gameplay_counts(connection).values()):
                raise RuntimeError("Gameplay tables changed after reset commit")
        run_local_migration(NEW_REVISION)
        phase = {**phase, "phase": "migration_completed_unverified"}
        _replace_private(evidence, "reset.json", phase)
        migrated = inspect_migration_after_pool_dispose(engine)
        with engine.connect() as connection:
            after_migration = {
                "tables": retained_table_digests(connection),
                "files": local_source_hashes(require_expected=True),
            }
            preservation["after_migration"] = after_migration
            _replace_private(evidence, "preservation.json", preservation)
            require_preservation_match(before, after_migration, "after-migration")
            if _schema_revision(connection) != NEW_REVISION:
                raise RuntimeError(
                    "Migration revision marker did not reach expected head"
                )
            if any(gameplay_counts(connection).values()):
                raise RuntimeError("Gameplay tables changed during migration")
        _write_private(evidence, "migration.json", migrated)
        _replace_private(
            evidence,
            "reset.json",
            {**phase, "phase": "migration_verified", "schema_after": NEW_REVISION},
        )
    except Exception as error:
        _replace_private(
            evidence,
            "reset.json",
            {**phase, "error_type": type(error).__name__},
        )
        raise
    finally:
        engine.dispose()


def _schema_revision(connection: Any) -> str:
    return str(
        connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    )


def gameplay_counts(connection: Any) -> dict[str, int]:
    return {
        table: int(
            connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
        )
        for table in ("gameoperation", "gamerun", "dailydefinition")
    }


def _replace_private(directory: Path, name: str, value: Any) -> None:
    temp = directory / f".{name}.new"
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, indent=2)
    os.replace(temp, directory / name)


def run_local_migration(revision: str) -> None:
    if revision != NEW_REVISION:
        raise RuntimeError("Only the reviewed three-life head may be applied")
    require_local_target()
    env = dict(
        os.environ,
        POSTGRES_DB=DATABASE,
        POSTGRES_SERVER="127.0.0.1",
        POSTGRES_PORT="5433",
        ENVIRONMENT="local",
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=WORKTREE / "backend",
        env=env,
        check=True,
    )


def _stop_new_generation(evidence: Path) -> None:
    _private_directory(evidence, fresh=False)
    start = _read_private_json(evidence, "start.json")
    phase = start.get("phase")
    if phase == "started":
        confirmed = start.get("pids")
        required = {"backend", "ui"}
    elif phase == "start_failed":
        confirmed = start.get("started")
        required = set()
    else:
        raise RuntimeError(
            "Successful or partial start evidence required for owned stop"
        )
    if (
        not isinstance(confirmed, dict)
        or not set(confirmed).issubset({"backend", "ui"})
        or not set(confirmed).issuperset(required)
        or (phase == "start_failed" and not confirmed)
        or any(type(pid) is not int or pid <= 0 for pid in confirmed.values())
    ):
        raise RuntimeError("Confirmed start component set is invalid")
    expected_ledgers = {f"{component}-process.json" for component in confirmed}
    available_ledgers = {path.name for path in evidence.glob("*-process.json")}
    if available_ledgers != expected_ledgers:
        raise RuntimeError("Available process ledgers do not match confirmed start set")
    records: list[tuple[str, dict[str, Any]]] = []
    for component, address in (("ui", "0.0.0.0:5174"), ("backend", "127.0.0.1:8010")):
        if component not in confirmed:
            continue
        path = evidence / f"{component}-process.json"
        record = _read_private_json(evidence, path.name)
        cwd = str(WORKTREE / ("backend" if component == "backend" else "frontend"))
        expected_argv = new_command(component)
        identity = record.get("identity")
        if (
            record.get("component") != component
            or not isinstance(identity, dict)
            or type(identity.get("pid")) is not int
            or identity.get("pid") != confirmed[component]
        ):
            raise RuntimeError("New-generation process ledger invalid")
        require_process_identity(
            identity, expected_cwd=cwd, expected_argv=expected_argv
        )
        require_listener(address, int(identity["pid"]))
        records.append((component, identity))
    # Both owners are proven before either individual process is signalled.
    for _component, record in records:
        os.kill(int(record["pid"]), signal.SIGTERM)


def _current_ip() -> str:
    return old.current_ip()


def _validate_recovery_receipt(
    evidence: Path,
    phase: dict[str, Any],
    preservation: dict[str, Any],
    receipt: dict[str, Any],
    current_commit: str,
) -> dict[str, Any]:
    verified_commit = receipt.get("verified_code_commit")
    if not isinstance(verified_commit, str):
        raise RuntimeError("Recovery receipt verified commit is invalid")
    _recovery_code_provenance(phase.get("code_commit", ""), current_commit)
    ancestry = subprocess.run(
        [
            "git",
            "-C",
            str(WORKTREE),
            "merge-base",
            "--is-ancestor",
            verified_commit,
            current_commit,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if ancestry.returncode != 0:
        raise RuntimeError("Current helper is not descended from verified recovery")
    followup_paths = subprocess.check_output(
        [
            "git",
            "-C",
            str(WORKTREE),
            "diff",
            "--name-only",
            verified_commit,
            current_commit,
        ],
        text=True,
    ).splitlines()
    if not set(followup_paths).issubset(
        {
            "backend/tests/browser/three_lives_local_rollout.py",
            "backend/tests/browser/test_three_lives_local_rollout.py",
            "docs/beta/board-polish-three-lives.md",
        }
    ):
        raise RuntimeError("Recovery follow-up changed gameplay/product source")
    if (
        phase.get("phase") != "migration_completed_unverified"
        or phase.get("database") != settings.POSTGRES_DB
        or phase.get("schema_before") != EXPECTED_OLD_REVISION
        or phase.get("code_commit") != APPLIED_CODE_COMMIT
        or phase.get("error_type") != "RuntimeError"
        or phase.get("deleted")
        != {"gameoperation": 473, "gamerun": 162, "dailydefinition": 8}
        or phase.get("remaining")
        != {"gameoperation": 0, "gamerun": 0, "dailydefinition": 0}
        or receipt.get("phase") != "migration_verified_by_recovery"
        or receipt.get("schema_revision") != NEW_REVISION
        or receipt.get("applied_code_commit") != phase.get("code_commit")
        or receipt.get("code_diff_paths")
        != sorted(
            {
                "backend/tests/browser/three_lives_local_rollout.py",
                "backend/tests/browser/test_three_lives_local_rollout.py",
                "docs/beta/board-polish-three-lives.md",
            }
        )
        or receipt.get("applied_evidence_sha256") != _original_evidence_hashes(evidence)
        or receipt.get("retained_state") != preservation.get("before_reset")
        or receipt.get("gameplay")
        != {"gameoperation": 0, "gamerun": 0, "dailydefinition": 0}
        or os.path.lexists(evidence / "migration.json")
    ):
        raise RuntimeError("Recovery receipt/provenance does not match apply evidence")
    database = receipt.get("database")
    if not isinstance(database, dict) or database.get("revision") != NEW_REVISION:
        raise RuntimeError("Recovery receipt database identity is invalid")
    return database


def _evidence_identity(path: Path, info: os.stat_result) -> dict[str, int | str]:
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": stat.S_IMODE(info.st_mode),
        "uid": info.st_uid,
        "gid": info.st_gid,
        "links": info.st_nlink,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
        "path": str(path),
    }


def _require_evidence_directory(path: Path, expected_mode: int) -> dict[str, int | str]:
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != expected_mode
        or path.resolve(strict=True) != path
    ):
        raise RuntimeError("Parent browser evidence directory identity/mode is invalid")
    return _evidence_identity(path, info)


def _parent_evidence_snapshot(evidence: Path) -> dict[str, Any]:
    expected_root_entries = {
        "inspection.json",
        "reset.json",
        "preservation.json",
        RECOVERY_RECEIPT,
        "start.json",
        "backend-process.json",
        "ui-process.json",
        "backend.log",
        "ui.log",
        "step6-pre-browser-baseline.json",
        "step6",
    }
    if {entry.name for entry in evidence.iterdir()} != expected_root_entries:
        raise RuntimeError(
            "Parent evidence contains missing or unexpected lifecycle artifacts"
        )
    step6 = evidence / "step6"
    summary_path = step6 / "step6-browser-summary.json"
    summary_info = summary_path.lstat()
    if (
        not stat.S_ISREG(summary_info.st_mode)
        or summary_info.st_uid != os.getuid()
        or stat.S_IMODE(summary_info.st_mode) != 0o600
        or summary_info.st_nlink != 1
        or summary_path.resolve(strict=True) != summary_path
    ):
        raise RuntimeError("Parent browser summary identity/mode is invalid")
    summary_bytes = summary_path.read_bytes()
    summary_after = summary_path.lstat()
    if _evidence_identity(summary_path, summary_info) != _evidence_identity(
        summary_path, summary_after
    ):
        raise RuntimeError("Parent browser summary changed during inspection")
    summary = json.loads(summary_bytes)
    freeplay_screenshots = summary.get("freeplay", {}).get("screenshots")
    daily_screenshot = summary.get("daily", {}).get("screenshot")
    if (
        freeplay_screenshots != list(STEP6_FREEPLAY_SCREENSHOTS)
        or daily_screenshot != STEP6_DAILY_SCREENSHOT
    ):
        raise RuntimeError("Targeted browser screenshot manifest is invalid")

    expected_step6_entries = (
        (STEP6_FIXED_FILES - {"results/.last-run.json"})
        | set(STEP6_FREEPLAY_SCREENSHOTS)
        | {STEP6_DAILY_SCREENSHOT, "node_modules", "results"}
    )
    if {entry.name for entry in step6.iterdir()} != expected_step6_entries:
        raise RuntimeError(
            "Step 6 evidence tree contains missing or unexpected artifacts"
        )
    results = step6 / "results"
    if {entry.name for entry in results.iterdir()} != {".last-run.json"}:
        raise RuntimeError(
            "Step 6 results tree contains missing or unexpected artifacts"
        )

    root = evidence
    identities: dict[str, Any] = {
        ".": _require_evidence_directory(root, 0o700),
        "step6": _require_evidence_directory(step6, 0o700),
        "step6/results": _require_evidence_directory(results, 0o775),
    }
    node_modules = step6 / "node_modules"
    link_info = node_modules.lstat()
    expected_dependency_path = WORKTREE / "frontend/node_modules"
    link_target = os.readlink(node_modules)
    dependency_info = expected_dependency_path.lstat()
    if (
        not stat.S_ISLNK(link_info.st_mode)
        or link_info.st_uid != os.getuid()
        or link_info.st_nlink != 1
        or stat.S_IMODE(link_info.st_mode) != 0o777
        or link_target != str(expected_dependency_path)
        or stat.S_ISLNK(dependency_info.st_mode)
        or not stat.S_ISDIR(dependency_info.st_mode)
        or dependency_info.st_uid != os.getuid()
        or expected_dependency_path.resolve(strict=True) != expected_dependency_path
        or node_modules.resolve(strict=True) != expected_dependency_path
    ):
        raise RuntimeError("Step 6 dependency link target/type/identity is invalid")
    identities["step6/node_modules"] = {
        **_evidence_identity(node_modules, link_info),
        "link_target": link_target,
        "target_identity": _evidence_identity(
            expected_dependency_path, dependency_info
        ),
    }

    names = (
        "inspection.json",
        "reset.json",
        "preservation.json",
        RECOVERY_RECEIPT,
        "start.json",
        "backend-process.json",
        "ui-process.json",
        "backend.log",
        "ui.log",
        "step6-pre-browser-baseline.json",
        *(
            f"step6/{name}"
            for name in sorted(STEP6_FIXED_FILES - {"results/.last-run.json"})
        ),
        *(f"step6/{name}" for name in sorted(STEP6_FREEPLAY_SCREENSHOTS)),
        f"step6/{STEP6_DAILY_SCREENSHOT}",
        "step6/results/.last-run.json",
    )
    hashes: dict[str, str] = {}
    for name in names:
        path = evidence / name
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or path.resolve(strict=True) != path
        ):
            raise RuntimeError("Parent evidence file identity/mode is invalid")
        contents = (
            summary_bytes
            if name == "step6/step6-browser-summary.json"
            else path.read_bytes()
        )
        after = path.lstat()
        if _evidence_identity(path, before) != _evidence_identity(path, after):
            raise RuntimeError("Parent evidence file changed during inspection")
        hashes[name] = hashlib.sha256(contents).hexdigest()
        identities[name] = _evidence_identity(path, after)
    return {"sha256": hashes, "identities": identities}


def _parent_evidence_hashes(evidence: Path) -> dict[str, str]:
    return cast(dict[str, str], _parent_evidence_snapshot(evidence)["sha256"])


def require_parent_process_absent(pid: int) -> None:
    try:
        process_identity(pid)
    except FileNotFoundError:
        return
    except (OSError, ValueError, KeyError) as error:
        raise RuntimeError(
            "Prior generation PID identity could not be verified"
        ) from error
    raise RuntimeError("Prior generation PID is still present or has been reused")


def _verify_relaunch_proof(
    parent: Path,
    origins: list[str],
    *,
    allow_test_database: bool = False,
) -> dict[str, Any]:
    _private_directory(parent, fresh=False)
    original_snapshot = _parent_evidence_snapshot(parent)
    original_hashes = original_snapshot["sha256"]
    phase = _read_private_json(parent, "reset.json")
    preservation = _read_private_json(parent, "preservation.json")
    receipt = _read_private_json(parent, RECOVERY_RECEIPT)
    parent_start = _read_private_json(parent, "start.json")
    if (
        phase.get("phase") != "migration_completed_unverified"
        or phase.get("database") != settings.POSTGRES_DB
        or phase.get("code_commit") != APPLIED_CODE_COMMIT
        or set(parent_start) != {"phase", "pids", "origins"}
        or parent_start.get("phase") != "started"
        or not isinstance(parent_start.get("pids"), dict)
        or set(parent_start["pids"]) != {"backend", "ui"}
        or any(
            type(pid) is not int or pid <= 0 for pid in parent_start["pids"].values()
        )
        or len(set(parent_start["pids"].values())) != 2
        or parent_start.get("origins") != origins
    ):
        raise RuntimeError("Exact successful recovery/start parent evidence required")
    if settings.POSTGRES_DB == DATABASE and parent != DELIVERY_EVIDENCE:
        raise RuntimeError("Exact original delivery evidence parent required")
    current_commit = _code_commit()
    database_from_receipt = _validate_recovery_receipt(
        parent, phase, preservation, receipt, current_commit
    )
    current_code_diff = subprocess.check_output(
        [
            "git",
            "-C",
            str(WORKTREE),
            "diff",
            "--name-only",
            receipt["verified_code_commit"],
            current_commit,
        ],
        text=True,
    ).splitlines()
    baseline = json.loads((parent / "step6-pre-browser-baseline.json").read_text())
    browser_summary = json.loads(
        (parent / "step6/step6-browser-summary.json").read_text()
    )
    expected_gameplay = {
        "gameoperation": 0,
        "gamerun": 0,
        "dailydefinition": 0,
    }
    table_proof = baseline.get("retained_tables")
    if (
        baseline.get("head") != receipt.get("verified_code_commit")
        or baseline.get("revision") != NEW_REVISION
        or baseline.get("gameplay") != expected_gameplay
        or not isinstance(table_proof, dict)
        or set(table_proof) != set(receipt["retained_state"]["tables"])
        or any(
            not isinstance(table_proof[name], dict)
            or table_proof[name].get("count")
            != receipt["retained_state"]["tables"][name].get("count")
            or not isinstance(
                table_proof[name].get("primary_key_sha256_to_row_sha256"), dict
            )
            or len(table_proof[name]["primary_key_sha256_to_row_sha256"])
            != table_proof[name].get("count")
            for name in table_proof
        )
        or browser_summary.get("origin") != "http://192.168.1.214:5174"
        or browser_summary.get("api") != "http://127.0.0.1:8010"
        or browser_summary.get("options_protocol_version") != 2
        or browser_summary.get("guest_cookie_verified") is not True
        or browser_summary.get("freeplay", {}).get("terminal_status") != "lost"
        or browser_summary.get("freeplay", {}).get("mistake_lives") != [2, 1, 0]
        or browser_summary.get("daily", {}).get("initial_lives") != 3
        or browser_summary.get("daily", {}).get("second_start_available") is not False
    ):
        raise RuntimeError("Original targeted Step 6 proof chain is invalid")
    address = _current_ip()
    old.require_origins(origins, address)
    for component in ("backend", "ui"):
        pid = parent_start["pids"].get(component)
        if type(pid) is not int or pid <= 0:
            raise RuntimeError("Prior start PID set is invalid")
        record = _read_private_json(parent, f"{component}-process.json")
        identity = record.get("identity")
        expected_cwd = str(
            WORKTREE / ("backend" if component == "backend" else "frontend")
        )
        if (
            record.get("component") != component
            or not isinstance(identity, dict)
            or set(identity) != {"pid", "cwd", "command", "start_ticks"}
            or identity.get("pid") != pid
            or identity.get("cwd") != expected_cwd
            or identity.get("command") != new_command(component)
            or not isinstance(identity.get("start_ticks"), str)
            or not identity.get("start_ticks", "").isdigit()
        ):
            raise RuntimeError("Prior successful process ledger is invalid")
        require_parent_process_absent(pid)
        if any(
            line.split()[3] in {"127.0.0.1:8010", "0.0.0.0:5174"}
            for line in listeners()
        ):
            raise RuntimeError("Prior generation listener remains occupied")

    require_local_target(allow_test_database=allow_test_database)
    database = inspect_database(
        allow_test_database=allow_test_database, expected_revision=NEW_REVISION
    )
    if database != database_from_receipt:
        raise RuntimeError("Current catalog/database identity differs from recovery")
    before = preservation.get("before_reset")
    expected_tables = receipt.get("retained_state", {}).get("tables")
    if not isinstance(before, dict) or not isinstance(expected_tables, dict):
        raise RuntimeError("Original retained catalog baseline is missing")
    current_tables = retained_table_digests_for_database()
    mutable_tables = {"user", "guestsession"}
    if (
        set(current_tables) != set(expected_tables)
        or any(
            current_tables[name] != expected_tables[name]
            for name in set(expected_tables) - mutable_tables
        )
        or any(
            current_tables[name]["count"] < expected_tables[name]["count"]
            for name in mutable_tables
        )
    ):
        raise RuntimeError("Retained catalog tables changed since reviewed launch")
    source_files = local_source_hashes(require_expected=True)
    expected_files = receipt.get("retained_state", {}).get("files")
    if source_files != expected_files:
        raise RuntimeError("Original catalog/runtime source files changed")
    engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            gameplay = gameplay_counts(connection)
            guest_rows = {
                "user": int(
                    connection.execute(
                        text('SELECT count(*) FROM "user" WHERE is_guest=true')
                    ).scalar_one()
                ),
                "guestsession": int(
                    connection.execute(
                        text("SELECT count(*) FROM guestsession")
                    ).scalar_one()
                ),
            }
    finally:
        engine.dispose()
    if original_snapshot != _parent_evidence_snapshot(parent):
        raise RuntimeError("Parent recovery/start evidence changed during validation")
    final_database = inspect_database(
        allow_test_database=allow_test_database, expected_revision=NEW_REVISION
    )
    if final_database != database:
        raise RuntimeError("Database identity changed during relaunch preflight")
    require_stopped_old_generation()
    _require_free_listener("127.0.0.1", 8010)
    _require_free_listener("0.0.0.0", 5174)
    runtime = ORIGINAL_LIVE / "data/game/local-catalog-runtime"
    if runtime.resolve(strict=True) != runtime or not runtime.is_dir():
        raise RuntimeError("Original catalog runtime is missing or aliased")
    return {
        "database": database,
        "runtime": str(runtime),
        "origins": origins,
        "parent_start": parent_start,
        "parent_evidence": str(parent),
        "parent_sha256": original_hashes,
        "parent_artifact_identities": original_snapshot["identities"],
        "applied_code_commit": receipt["applied_code_commit"],
        "recovery_verified_code_commit": receipt["verified_code_commit"],
        "verified_code_commit": current_commit,
        "code_diff_paths_since_recovery": sorted(current_code_diff),
        "source_files": source_files,
        "gameplay": gameplay,
        "guest_rows": guest_rows,
    }


def _verify_start_proof(
    evidence: Path,
    origins: list[str],
    *,
    allow_test_database: bool = False,
) -> dict[str, Any]:
    _private_directory(evidence, fresh=False)
    if os.path.lexists(evidence / "start.json"):
        raise RuntimeError("Start phase evidence already exists; refusing restart")
    for component in ("backend", "ui"):
        if os.path.lexists(evidence / f"{component}.log") or os.path.lexists(
            evidence / f"{component}-process.json"
        ):
            raise RuntimeError("Start outputs already exist; refusing adoption/restart")
    phase = _read_private_json(evidence, "reset.json")
    preservation = _read_private_json(evidence, "preservation.json")
    code_commit = _code_commit()
    before = preservation.get("before_reset")
    if not isinstance(before, dict):
        raise RuntimeError("Complete retained-state proof required before start")
    if phase.get("phase") == "migration_verified":
        migration = _read_private_json(evidence, "migration.json")
        if (
            phase.get("database") != DATABASE
            or phase.get("schema_after") != NEW_REVISION
            or migration.get("revision") != NEW_REVISION
        ):
            raise RuntimeError("Verified reset/migration proof required before start")
        if phase.get("code_commit") != code_commit:
            raise RuntimeError("Current implementation differs from applied code proof")
        after_migration = preservation.get("after_migration")
        if not isinstance(after_migration, dict):
            raise RuntimeError("Complete retained-state proof required before start")
        require_preservation_match(before, after_migration, "start-proof")
        migration_identity = migration
    elif phase.get("phase") == "migration_completed_unverified":
        receipt = _read_private_json(evidence, RECOVERY_RECEIPT)
        migration_identity = _validate_recovery_receipt(
            evidence, phase, preservation, receipt, code_commit
        )
        require_preservation_match(
            before, receipt["retained_state"], "recovery-start-proof"
        )
    else:
        raise RuntimeError("Verified reset/migration proof required before start")
    database = inspect_database(
        allow_test_database=allow_test_database,
        expected_revision=NEW_REVISION,
    )
    if database != migration_identity:
        raise RuntimeError("Database identity differs from migration evidence")
    runtime = ORIGINAL_LIVE / "data/game/local-catalog-runtime"
    if runtime.resolve(strict=True) != runtime or not runtime.is_dir():
        raise RuntimeError("Original catalog runtime is missing or aliased")
    if retained_table_digests_for_database() != before.get(
        "tables"
    ) or local_source_hashes(require_expected=True) != before.get("files"):
        raise RuntimeError("Retained-state proof no longer matches current target")
    require_stopped_old_generation()
    address = _current_ip()
    old.require_origins(origins, address)
    _require_free_listener("127.0.0.1", 8010)
    _require_free_listener("0.0.0.0", 5174)
    return {"database": database, "runtime": str(runtime), "origins": origins}


def retained_table_digests_for_database() -> dict[str, dict[str, str | int]]:
    engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            return retained_table_digests(connection)
    finally:
        engine.dispose()


def _require_free_listener(host: str, port: int) -> None:
    with socket.socket() as listener:
        listener.bind((host, port))


def _wait_listener(address: str, pid: int) -> None:
    for _ in range(100):
        matches = [
            line
            for line in listeners()
            if len(line.split()) > 3 and line.split()[3] == address
        ]
        if matches:
            if len(matches) == 1 and f"pid={pid}," in matches[0]:
                return
            raise RuntimeError("New service listener is foreign or ambiguous")
        time.sleep(0.1)
    raise RuntimeError("New service did not bind its exact listener")


def _wait_readiness(component: str, record: dict[str, Any], origins: list[str]) -> None:
    del origins  # Origins were validated and bound into the child environment.
    url = (
        "http://127.0.0.1:8010/api/v1/utils/health-check/"
        if component == "backend"
        else "http://127.0.0.1:5174/"
    )
    for _ in range(200):
        require_process_identity(
            record,
            expected_cwd=str(
                WORKTREE / ("backend" if component == "backend" else "frontend")
            ),
            expected_argv=new_command(component),
        )
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("New service readiness timed out")


def _start_environment(proof: dict[str, Any], origins: list[str]) -> dict[str, str]:
    require_runtime_configuration(DATABASE)
    env = dict(
        os.environ,
        POSTGRES_DB=DATABASE,
        POSTGRES_SERVER="127.0.0.1",
        POSTGRES_PORT="5433",
        ENVIRONMENT="local",
        FRONTEND_HOST="http://localhost:5174",
        BACKEND_CORS_ORIGINS=json.dumps(origins),
        GAME_GUEST_COOKIE_NAME=LIVE_GUEST_COOKIE_NAME,
        GAME_DATA_DIR=str(proof["runtime"]),
        GAME_EVENT_LINKS_FILE=str(ORIGINAL_SIDECAR),
        GAME_EVENT_LINKS_SHA256=ORIGINAL_SIDECAR_SHA256,
        PUBLIC_REGISTRATION_ENABLED="false",
    )
    for field in (
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "SECRET_KEY",
        "FIRST_SUPERUSER",
        "FIRST_SUPERUSER_PASSWORD",
        "PROJECT_NAME",
    ):
        env[field] = str(getattr(settings, field))
    return env


def start_generation(evidence: Path, origins: list[str]) -> None:
    proof = _verify_start_proof(evidence, origins)
    _launch_generation(evidence, origins, proof)


def relaunch_generation(
    parent: Path,
    evidence: Path,
    origins: list[str],
    *,
    allow_test_database: bool = False,
) -> dict[str, Any]:
    proof = _verify_relaunch_proof(
        parent, origins, allow_test_database=allow_test_database
    )
    if (
        not evidence.is_absolute()
        or evidence.exists()
        or evidence.is_symlink()
        or not evidence.parent.is_dir()
        or evidence.parent.resolve(strict=True) != evidence.parent
        or not evidence.resolve().is_relative_to(Path("/tmp/opencode"))
        or evidence.resolve().is_relative_to(parent)
    ):
        raise RuntimeError("Fresh private child evidence directory required")
    _private_directory(evidence, fresh=True)
    child = {
        "phase": "relaunch_prepared",
        "parent_evidence": proof["parent_evidence"],
        "parent_sha256": proof["parent_sha256"],
        "parent_artifact_identities": proof["parent_artifact_identities"],
        "applied_code_commit": proof["applied_code_commit"],
        "recovery_verified_code_commit": proof["recovery_verified_code_commit"],
        "verified_code_commit": proof["verified_code_commit"],
        "code_diff_paths_since_recovery": proof["code_diff_paths_since_recovery"],
        "database": proof["database"],
        "runtime": proof["runtime"],
        "origins": origins,
        "gameplay": proof["gameplay"],
        "guest_rows": proof["guest_rows"],
    }
    _write_private(evidence, "relaunch.json", child)
    _launch_generation(evidence, origins, proof)
    return child


def _launch_generation(
    evidence: Path, origins: list[str], proof: dict[str, Any]
) -> None:
    env = _start_environment(proof, origins)
    _write_private(
        evidence,
        "start.json",
        {
            "phase": "start_in_progress",
            "database": proof["database"],
            "origins": origins,
            "cookie_name": "hdg_guest_real",
            "runtime": proof["runtime"],
            "code_commit": _code_commit(),
        },
    )
    started: dict[str, int] = {}
    try:
        for component in ("backend", "ui"):
            host, port, address = (
                ("127.0.0.1", 8010, "127.0.0.1:8010")
                if component == "backend"
                else ("0.0.0.0", 5174, "0.0.0.0:5174")
            )
            _require_free_listener(host, port)
            cwd = WORKTREE / ("backend" if component == "backend" else "frontend")
            command = new_command(component)
            log_path = evidence / f"{component}.log"
            descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "ab") as output:
                process = subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=env,
                    stdout=output,
                    stderr=output,
                    start_new_session=True,
                )
            try:
                if process.poll() is not None:
                    raise RuntimeError(
                        "New service exited before ownership confirmation"
                    )
                identity = wait_process_identity(process, cwd, command)
                _wait_listener(address, process.pid)
                _wait_readiness(component, identity, origins)
                require_process_identity(
                    identity, expected_cwd=str(cwd), expected_argv=command
                )
                _write_private(
                    evidence,
                    f"{component}-process.json",
                    {"component": component, "identity": identity},
                )
                started[component] = process.pid
            except Exception:
                _write_private(
                    evidence,
                    f"{component}-unconfirmed-{process.pid}.json",
                    {
                        "component": component,
                        "pid": process.pid,
                        "cwd": str(cwd),
                        "command": command,
                        "ownership_confirmed": False,
                    },
                )
                raise
        _replace_private(
            evidence,
            "start.json",
            {"phase": "started", "pids": started, "origins": origins},
        )
    except Exception as error:
        _replace_private(
            evidence,
            "start.json",
            {
                "phase": "start_failed",
                "started": started,
                "error_type": type(error).__name__,
            },
        )
        raise


def new_command(component: str) -> list[str]:
    if component == "backend":
        return [
            sys.executable,
            "-m",
            "uvicorn",
            "tests.browser.three_lives_local_rollout:local_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            "8010",
            "--no-access-log",
        ]
    if component == "ui":
        return [
            str(environment.NODE),
            "node_modules/vite/bin/vite.js",
            "--config",
            "vite.real-catalog.config.ts",
            "--host",
            "0.0.0.0",
            "--port",
            "5174",
            "--strictPort",
        ]
    raise RuntimeError("Unknown new-generation component")


def original_command(component: str) -> list[str]:
    if component == "backend":
        return [
            str(ORIGINAL_WORKTREE / "backend/.venv/bin/python"),
            "-m",
            "uvicorn",
            "tests.browser.board_local_rollout:local_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            "8010",
            "--no-access-log",
        ]
    if component == "ui":
        return [
            str(ORIGINAL_NODE),
            "node_modules/vite/bin/vite.js",
            "--config",
            "vite.real-catalog.config.ts",
            "--host",
            "0.0.0.0",
            "--port",
            "5174",
            "--strictPort",
        ]
    raise RuntimeError("Unknown original-generation component")


def local_app() -> Any:
    """Factory entrypoint reserved for the reviewed generation launcher."""
    if settings.POSTGRES_DB == DATABASE:
        require_runtime_configuration(DATABASE)
        settings.GAME_EVENT_LINKS_FILE = ORIGINAL_SIDECAR
        settings.GAME_EVENT_LINKS_SHA256 = ORIGINAL_SIDECAR_SHA256
        settings.GAME_GUEST_COOKIE_NAME = LIVE_GUEST_COOKIE_NAME
        settings.GAME_DATA_DIR = ORIGINAL_LIVE / "data/game/local-catalog-runtime"
    return old.local_app()


def resume_migration(evidence: Path) -> None:
    _private_directory(evidence, fresh=False)
    phase = _read_private_json(evidence, "reset.json")
    if phase.get("phase") != "reset_committed":
        raise RuntimeError("Only a recorded committed reset may resume migration")
    if (
        phase.get("database") != DATABASE
        or phase.get("schema_before") != EXPECTED_OLD_REVISION
    ):
        raise RuntimeError("Resume evidence target/revision is invalid")
    if phase.get("code_commit") != _code_commit():
        raise RuntimeError("Current implementation differs from reset proof")
    preservation = _read_private_json(evidence, "preservation.json")
    before = preservation.get("before_reset")
    if not isinstance(before, dict):
        raise RuntimeError("Committed reset preservation baseline is missing")
    proof = inspect_target()  # Fresh revision, ownership, sessions and stop proof.
    database_proof = proof.get("database")
    if (
        not isinstance(database_proof, dict)
        or database_proof.get("revision") != EXPECTED_OLD_REVISION
    ):
        raise RuntimeError("Resume requires the inspected old schema revision")
    current = {
        "tables": retained_table_digests_for_database(),
        "files": local_source_hashes(require_expected=True),
    }
    require_preservation_match(before, current, "before-resume")
    engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
    try:
        with engine.connect() as connection:
            remaining = gameplay_counts(connection)
        if any(remaining.values()):
            raise RuntimeError("Resume requires all gameplay tables to remain empty")
        phase = {**phase, "phase": "migration_resuming"}
        _replace_private(evidence, "reset.json", phase)
        run_local_migration(NEW_REVISION)
        phase = {**phase, "phase": "migration_completed_unverified"}
        _replace_private(evidence, "reset.json", phase)
        migrated = inspect_migration_after_pool_dispose(engine)
        with engine.connect() as connection:
            after = {
                "tables": retained_table_digests(connection),
                "files": local_source_hashes(require_expected=True),
            }
            preservation["after_migration"] = after
            _replace_private(evidence, "preservation.json", preservation)
            require_preservation_match(before, after, "after-resumed-migration")
            if _schema_revision(connection) != NEW_REVISION:
                raise RuntimeError("Resume migration revision marker mismatch")
            if any(gameplay_counts(connection).values()):
                raise RuntimeError("Gameplay changed during resume migration")
        _write_private(evidence, "migration.json", migrated)
        _replace_private(
            evidence,
            "reset.json",
            {**phase, "phase": "migration_verified", "schema_after": NEW_REVISION},
        )
    except Exception as error:
        if phase.get("phase") == "migration_resuming":
            phase = {**phase, "phase": "reset_committed"}
        _replace_private(
            evidence,
            "reset.json",
            {**phase, "error_type": type(error).__name__},
        )
        raise
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=False)
    sub.add_parser("inspect")
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--confirm-database")
    apply_parser.add_argument("--evidence-dir", type=Path, required=True)
    stop_parser = sub.add_parser("stop")
    stop_parser.add_argument("--evidence-dir", type=Path, required=True)
    start_parser = sub.add_parser("start")
    start_parser.add_argument("--evidence-dir", type=Path, required=True)
    start_parser.add_argument("--origin", action="append", required=True)
    resume_parser = sub.add_parser("resume-migration")
    resume_parser.add_argument("--evidence-dir", type=Path, required=True)
    verify_parser = sub.add_parser("verify-migration")
    verify_parser.add_argument("--evidence-dir", type=Path, required=True)
    relaunch_parser = sub.add_parser("relaunch")
    relaunch_parser.add_argument("--parent-evidence-dir", type=Path, required=True)
    relaunch_parser.add_argument("--evidence-dir", type=Path, required=True)
    relaunch_parser.add_argument("--origin", action="append", required=True)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.command in (None, "inspect"):
            sys.stdout.write(json.dumps(inspect_target(), indent=2) + "\n")
        elif args.command == "apply":
            require_local_target()
            if args.confirm_database != DATABASE:
                raise RuntimeError("Exact database confirmation required")
            _apply(args.evidence_dir)
        elif args.command == "stop":
            _stop_new_generation(args.evidence_dir)
        elif args.command == "start":
            start_generation(args.evidence_dir, args.origin)
        elif args.command == "resume-migration":
            require_local_target()
            resume_migration(args.evidence_dir)
        elif args.command == "verify-migration":
            verify_migration(args.evidence_dir)
        elif args.command == "relaunch":
            relaunch_generation(
                args.parent_evidence_dir, args.evidence_dir, args.origin
            )
        return 0
    except Exception as error:
        sys.stderr.write(
            f"Three-life rollout stopped ({type(error).__name__}); preserve private evidence/state; no auto-restart\n"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
