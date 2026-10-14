"""Owner-authorized LOCAL cold start; inspection is the default. No reset/seed/restore.

The owner explicitly waived the old backup/restore gate. This is not production
activation. Existing processes are never adopted; only this helper's exact owned
PID/start-time/cwd/argv records may be stopped.
"""

import argparse
import hashlib
import ipaddress
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import psycopg

from app.core.config import settings
from tests.browser.guest_test_environment import (
    MANIFEST_SHA,
    NODE,
    WORKTREE,
    browser_email_policy,
    require_process_identity,
    verify_real_source,
    wait_process_identity,
)

LIVE = WORKTREE.parent / "beta"
RELEASE_ID = "jsonl-trial-2026-10-12-review-r1"
DATABASE = "historical_date_game_catalog_test"
F1_COMMENT = "F1 beta followup afc85a5 execution-owned disposable DB created 2026-10-12; approved full pytest cleanup"
EVIDENCE = (
    WORKTREE
    / ".superpowers/sdd/2026-10-13-historical-date-game-guest-play/task-6-evidence"
)


def announce(message: str) -> None:
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def require_target() -> None:
    if (
        settings.POSTGRES_DB != DATABASE
        or settings.POSTGRES_SERVER not in {"127.0.0.1", "localhost", "::1"}
        or settings.POSTGRES_PORT != 5433
        or settings.ENVIRONMENT != "local"
    ):
        raise RuntimeError("Exact local real database on loopback:5433 required")


def require_paths(live: Path, implementation: Path) -> None:
    for supplied, expected in ((live, LIVE), (implementation, WORKTREE)):
        if (
            not supplied.is_absolute()
            or supplied != expected
            or supplied.resolve(strict=True) != supplied
            or not (supplied / ".git").is_file()
        ):
            raise RuntimeError("Exact real and implementation worktrees required")


def current_ip() -> str:
    route = json.loads(
        subprocess.check_output(["ip", "-j", "-4", "route", "get", "1.1.1.1"])
    )
    return str(route[0]["prefsrc"])


def require_origins(origins: list[str], ip: str) -> None:
    address = ipaddress.ip_address(ip)
    if address.is_loopback or address.is_unspecified or address.is_multicast:
        raise RuntimeError("Current nonloopback interface IP required")
    if len(origins) != 2 or set(origins) != {
        "http://localhost:5174",
        f"http://{ip}:5174",
    }:
        raise RuntimeError("Only exact localhost and current LAN origins allowed")


def require_database_identity(identity: dict[str, Any]) -> None:
    if (
        identity["comment"] != F1_COMMENT
        or identity["owner"] != settings.POSTGRES_USER
        or identity["release_id"] != RELEASE_ID
        or identity["digest"] != MANIFEST_SHA
        or hashlib.sha256(identity["manifest_bytes"]).hexdigest() != MANIFEST_SHA
        or identity["count"] != 1276
        or identity["fixture"] is not False
        or identity["revision"] not in {"20261011_01", "20261013_01"}
    ):
        raise RuntimeError("Exact F1 ownership/schema/selected release bytes required")


def inspect_database() -> dict[str, Any]:
    require_target()  # Before any connection; this is NOT the pytest DB guard.
    with psycopg.connect(
        host=settings.POSTGRES_SERVER,
        port=5433,
        dbname=DATABASE,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        connect_timeout=5,
    ) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        ownership = connection.execute(
            "SELECT shobj_description(oid, 'pg_database'), pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()"
        ).fetchone()
        catalog = connection.execute(
            "SELECT r.id, r.manifest_sha256, r.manifest_bytes, r.event_count, r.fixture FROM catalogselection s JOIN catalogrelease r ON r.id=s.release_id WHERE s.id=1"
        ).fetchone()
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
        if ownership is None or catalog is None or revision is None:
            raise RuntimeError("Real ownership/catalog/schema missing")
        identity = dict(
            zip(
                (
                    "comment",
                    "owner",
                    "release_id",
                    "digest",
                    "manifest_bytes",
                    "count",
                    "fixture",
                    "revision",
                ),
                (*ownership, *catalog, revision[0]),
                strict=True,
            )
        )
        require_database_identity(identity)
        del identity["manifest_bytes"]
        return identity


def require_free_port(port: int) -> None:
    with socket.socket() as listener:
        listener.bind(("0.0.0.0", port))


def require_private_directory(directory: Path) -> None:
    if not directory.is_absolute() or directory.resolve() != directory:
        raise RuntimeError("Private output directory must not contain symlinks")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)


def private_json(path: Path, value: Any) -> None:
    # Exclusive fresh inode: never truncate preexisting hardlinks or symlinks.
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as output:
        json.dump(value, output, indent=2)


def require_startup_outputs(directory: Path) -> None:
    if directory.resolve() != directory:
        raise RuntimeError("Private startup directory must not alias another path")
    names = ["startup-env.json", "preflight.json", "migration.json"]
    for component in ("backend", "ui"):
        names.extend(
            [f"{component}.log", f"{component}-spawn.json", f"{component}-process.json"]
        )
    if any(os.path.lexists(directory / name) for name in names):
        raise RuntimeError("Prior startup output exists; no overwrite/adoption/restart")


def command(component: str) -> list[str]:
    if component == "backend":
        return [
            sys.executable,
            "-m",
            "uvicorn",
            "tests.browser.guest_local_rollout:local_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            "8010",
            "--no-access-log",
        ]
    if component == "ui":
        return [
            str(NODE),
            "node_modules/vite/bin/vite.js",
            "--config",
            "vite.real-catalog.config.ts",
            "--host",
            "0.0.0.0",
            "--port",
            "5174",
            "--strictPort",
        ]
    raise RuntimeError("Unknown component")


def local_app() -> Any:
    # Empty env values alone are unsafe: Settings can restore SMTP from .env.
    for field, value in browser_email_policy("real").items():
        setattr(settings, field, value)
    settings.PUBLIC_REGISTRATION_ENABLED = False
    from app.main import app

    return app


def require_owned_record(record: dict[str, Any]) -> None:
    require_process_identity(record["identity"])
    component = record["component"]
    cwd = WORKTREE / ("backend" if component == "backend" else "frontend")
    if record["identity"]["command"] != command(component) or record["identity"][
        "cwd"
    ] != str(cwd):
        raise RuntimeError("Unexpected owned service command/cwd")
    listeners = subprocess.check_output(["ss", "-H", "-ltnp"], text=True).splitlines()
    address = "127.0.0.1:8010" if component == "backend" else "0.0.0.0:5174"
    matching = [line for line in listeners if line.split()[3] == address]
    if len(matching) != 1 or f"pid={record['identity']['pid']}," not in matching[0]:
        raise RuntimeError("Service port/PID/bind ownership not proven")


def stop_owned(record: dict[str, Any]) -> None:
    require_owned_record(record)
    os.kill(record["identity"]["pid"], signal.SIGTERM)


def inspect(
    live: Path, implementation: Path, origins: list[str], cold: bool
) -> dict[str, Any]:
    require_target()
    require_paths(live, implementation)
    ip = current_ip()
    require_origins(origins, ip)
    if cold:
        require_startup_outputs(EVIDENCE)
    elif EVIDENCE.resolve() != EVIDENCE:
        raise RuntimeError("Private ledger directory must not alias another path")
    release = live / "data/game/releases" / RELEASE_ID
    if release.resolve(strict=True) != release:
        raise RuntimeError("Original source release must not alias another path")
    manifest = verify_real_source(release)
    runtime = live / "data/game/local-catalog-runtime"
    if runtime.resolve(strict=True) != runtime:
        raise RuntimeError("Original public runtime must not alias another path")
    for name, digest in manifest.files.items():
        if name.startswith("media/"):
            asset = runtime / "media" / RELEASE_ID / name.removeprefix("media/")
            if (
                asset.resolve(strict=True) != asset
                or hashlib.sha256(asset.read_bytes()).hexdigest() != digest
            ):
                raise RuntimeError("Original public media path/byte hash changed")
    identity = inspect_database()
    if cold:
        for port in (8010, 5174):
            require_free_port(port)
    else:
        for component in ("backend", "ui"):
            ledger = EVIDENCE / f"{component}-process.json"
            if ledger.exists():
                require_owned_record(json.loads(ledger.read_text()))
            else:
                require_free_port(8010 if component == "backend" else 5174)
    return {"database": identity, "ip": ip, "origins": origins, "runtime": str(runtime)}


def start(proof: dict[str, Any]) -> None:
    # Recheck all applicable guards immediately before the first write.
    announce("Stage: final cold-start guard inspection")
    proof = inspect(LIVE, WORKTREE, proof["origins"], True)
    require_private_directory(EVIDENCE)
    env = dict(
        os.environ,
        POSTGRES_DB=DATABASE,
        POSTGRES_SERVER="127.0.0.1",
        POSTGRES_PORT="5433",
        ENVIRONMENT="local",
        FRONTEND_HOST="http://localhost:5174",
        BACKEND_CORS_ORIGINS=json.dumps(proof["origins"]),
        GAME_GUEST_COOKIE_NAME="hdg_guest_real",
        GAME_DATA_DIR=proof["runtime"],
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
    private_json(EVIDENCE / "startup-env.json", env)
    private_json(EVIDENCE / "preflight.json", proof)
    # Additive upgrade only. No downgrade, activation, reseal, seed or cleanup.
    announce("Stage: additive live migration")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=WORKTREE / "backend",
        env=env,
        check=True,
    )
    announce("Stage: post-migration read-only identity inspection")
    after = inspect_database()
    if after["revision"] != "20261013_01":
        raise RuntimeError("Unexpected upgraded schema; preserve state and report")
    private_json(EVIDENCE / "migration.json", after)
    for component in ("backend", "ui"):
        announce(f"Stage: owned {component} launch/readiness")
        require_free_port(8010 if component == "backend" else 5174)
        require_origins(proof["origins"], current_ip())
        cwd = WORKTREE / ("backend" if component == "backend" else "frontend")
        argv = command(component)
        with os.fdopen(
            os.open(
                EVIDENCE / f"{component}.log",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            ),
            "w",
        ) as output:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                stdout=output,
                stderr=output,
                start_new_session=True,
            )
        # Never signal/adopt an unconfirmed child; retain its PID as diagnostics.
        private_json(
            EVIDENCE / f"{component}-spawn.json",
            {"pid": process.pid, "cwd": str(cwd), "command": argv},
        )
        record = {
            "component": component,
            "identity": wait_process_identity(process, cwd, argv),
        }
        private_json(EVIDENCE / f"{component}-process.json", record)
        url = (
            "http://127.0.0.1:8010/api/v1/utils/health-check/"
            if component == "backend"
            else "http://127.0.0.1:5174/"
        )
        for _ in range(200):
            if process.poll() is not None:
                raise RuntimeError(f"{component} exited; preserve logs/state")
            try:
                with urlopen(url, timeout=1) as response:
                    if response.status == 200:
                        require_owned_record(record)
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError(f"{component} readiness timed out; preserve state")
        announce(f"Owned {component} ready PID {process.pid}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action", choices=["inspect", "start", "stop"], default="inspect"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--live-worktree", type=Path, required=True)
    parser.add_argument("--implementation-worktree", type=Path, required=True)
    parser.add_argument("--origin", action="append", required=True)
    args = parser.parse_args(argv)
    try:
        announce("Stage: read-only guard inspection")
        proof = inspect(
            args.live_worktree,
            args.implementation_worktree,
            args.origin,
            args.action == "start",
        )
        if not args.apply or args.action == "inspect":
            announce("Inspection passed; dry-run only; no DB/process changes")
        elif args.action == "start":
            start(proof)
        else:
            # Prove BOTH identities before signalling either; no broad kill.
            records = [
                json.loads((EVIDENCE / f"{component}-process.json").read_text())
                for component in ("ui", "backend")
            ]
            for record in records:
                require_owned_record(record)
            for record in records:
                stop_owned(record)
            announce("SIGTERM sent only to verified owned services; ledgers retained")
    except Exception as error:
        # Never echo connection exceptions (DSNs/credentials) or process env.
        sys.stderr.write(
            f"Local rollout stopped ({type(error).__name__}); preserve private evidence/state; no automatic recovery\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
