"""Pure rollout gates: never use the destructive DB fixture or a live connection."""

import hashlib
import json
import os
import socket
import subprocess
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


def rollout() -> ModuleType:
    from tests.browser import guest_local_rollout

    return guest_local_rollout


@pytest.fixture(autouse=True)
def valid_local_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    r = rollout()
    for field, value in {
        "POSTGRES_DB": "historical_date_game_catalog_test",
        "POSTGRES_SERVER": "127.0.0.1",
        "POSTGRES_PORT": 5433,
        "ENVIRONMENT": "local",
    }.items():
        monkeypatch.setattr(r.settings, field, value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("POSTGRES_DB", "historical_date_game_guest_test"),
        ("POSTGRES_DB", "historical_date_game_test"),
        ("POSTGRES_SERVER", "remote.example"),
        ("POSTGRES_SERVER", "localhost"),
        ("POSTGRES_SERVER", "::1"),
        ("POSTGRES_PORT", 5432),
        ("ENVIRONMENT", "production"),
    ],
)
def test_bad_target_refused_before_connection(
    monkeypatch: pytest.MonkeyPatch, field: str, value: Any
) -> None:
    r = rollout()
    monkeypatch.setattr(r.settings, field, value)
    monkeypatch.setattr(r.psycopg, "connect", lambda **_: pytest.fail("connected"))
    with pytest.raises(RuntimeError):
        r.inspect_database()


def test_intended_ipv4_target_reaches_only_exact_connection_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = rollout()

    class ConnectionBoundaryReached(Exception):
        pass

    def connect(**kwargs: Any) -> None:
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 5433
        assert kwargs["dbname"] == "historical_date_game_catalog_test"
        raise ConnectionBoundaryReached

    monkeypatch.setattr(r.psycopg, "connect", connect)
    with pytest.raises(ConnectionBoundaryReached):
        r.inspect_database()


@pytest.mark.parametrize("host", ["localhost", "::1"])
def test_hostname_and_ipv6_refused_before_start_inspection_or_migration(
    monkeypatch: pytest.MonkeyPatch,
    host: str,
) -> None:
    r = rollout()
    monkeypatch.setattr(r.settings, "POSTGRES_SERVER", host)
    monkeypatch.setattr(
        r, "require_paths", lambda *_: pytest.fail("crossed target guard")
    )
    monkeypatch.setattr(r.psycopg, "connect", lambda **_: pytest.fail("connected"))
    monkeypatch.setattr(
        r.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("migration attempted"),
    )
    with pytest.raises(RuntimeError):
        r.start({"origins": []})


@pytest.mark.parametrize(
    "change",
    [
        {"comment": None},
        {"comment": "F1 unrelated disposable test"},
        {"owner": "other"},
        {"release_id": "fixture"},
        {"digest": "0" * 64},
        {"manifest_bytes": b"tampered"},
        {"count": 8},
        {"fixture": True},
        {"revision": "unknown"},
    ],
)
def test_database_identity_requires_exact_f1_and_selected_bytes(
    monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]
) -> None:
    r = rollout()
    digest = hashlib.sha256(b"manifest").hexdigest()
    monkeypatch.setattr(r, "MANIFEST_SHA", digest)
    identity = {
        "comment": r.F1_COMMENT,
        "owner": r.settings.POSTGRES_USER,
        "release_id": r.RELEASE_ID,
        "digest": digest,
        "manifest_bytes": b"manifest",
        "count": 1276,
        "fixture": False,
        "revision": "20261011_01",
    }
    r.require_database_identity(identity)
    identity.update(change)
    with pytest.raises(RuntimeError):
        r.require_database_identity(identity)


def test_paths_are_pinned_and_aliases_rejected(tmp_path: Path) -> None:
    r = rollout()
    r.require_paths(r.LIVE, r.WORKTREE)
    for live, implementation in [(tmp_path, r.WORKTREE), (r.LIVE, tmp_path)]:
        with pytest.raises(RuntimeError):
            r.require_paths(live, implementation)
    alias = tmp_path / "alias"
    alias.symlink_to(r.WORKTREE, target_is_directory=True)
    with pytest.raises(RuntimeError):
        r.require_paths(r.LIVE, alias)


def test_source_alias_refused_before_verifier_or_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    r = rollout()
    monkeypatch.setattr(r, "require_paths", lambda *_: None)
    monkeypatch.setattr(r, "current_ip", lambda: "192.168.1.214")
    source = tmp_path / "data/game/releases" / r.RELEASE_ID
    source.parent.mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()
    source.symlink_to(other, target_is_directory=True)
    monkeypatch.setattr(
        r,
        "verify_real_source",
        lambda _: pytest.fail("source alias crossed verification boundary"),
    )
    with pytest.raises(RuntimeError):
        r.inspect(
            tmp_path,
            r.WORKTREE,
            ["http://localhost:5174", "http://192.168.1.214:5174"],
            False,
        )


def test_tampered_public_media_refused_before_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    r = rollout()
    monkeypatch.setattr(r, "require_paths", lambda *_: None)
    monkeypatch.setattr(r, "current_ip", lambda: "192.168.1.214")
    (tmp_path / "data/game/releases" / r.RELEASE_ID).mkdir(parents=True)
    asset = (
        tmp_path / "data/game/local-catalog-runtime/media" / r.RELEASE_ID / "asset.svg"
    )
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"tampered")
    monkeypatch.setattr(
        r,
        "verify_real_source",
        lambda _: SimpleNamespace(
            files={"media/asset.svg": hashlib.sha256(b"reviewed").hexdigest()}
        ),
    )
    monkeypatch.setattr(
        r, "inspect_database", lambda: pytest.fail("DB crossed bad media guard")
    )
    with pytest.raises(RuntimeError):
        r.inspect(
            tmp_path,
            r.WORKTREE,
            ["http://localhost:5174", "http://192.168.1.214:5174"],
            False,
        )


@pytest.mark.parametrize("ip", ["127.0.0.1", "0.0.0.0", "192.168.1.213"])
def test_origin_requires_current_nonloopback_address(ip: str) -> None:
    r = rollout()
    with pytest.raises(RuntimeError):
        r.require_origins(
            ["http://localhost:5174", f"http://{ip}:5174"], "192.168.1.214"
        )


@pytest.mark.parametrize(
    "origins",
    [
        [],
        ["http://192.168.1.214:5174"],
        ["http://localhost:5174", "http://192.168.1.214:5174", "http://other:5174"],
        ["http://localhost:5174", "http://192.168.1.214:5174/"],
    ],
)
def test_origins_cannot_be_missing_wildcard_or_expanded(origins: list[str]) -> None:
    r = rollout()
    with pytest.raises(RuntimeError):
        r.require_origins(origins, "192.168.1.214")


def test_occupied_port_cannot_be_adopted() -> None:
    r = rollout()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with pytest.raises(OSError):
            r.require_free_port(listener.getsockname()[1])


def test_private_outputs_refuse_existing_symlink_and_hardlink(tmp_path: Path) -> None:
    r = rollout()
    original = tmp_path / "original"
    original.write_text("preserve")
    alias = tmp_path / "alias"
    alias.symlink_to(original)
    hard = tmp_path / "hard"
    os.link(original, hard)
    for path in [original, alias, hard]:
        with pytest.raises(FileExistsError):
            r.private_json(path, {"bad": True})
    assert original.read_text() == "preserve"
    fresh = tmp_path / "fresh"
    r.private_json(fresh, {"safe": True})
    assert json.loads(fresh.read_text()) == {"safe": True}
    assert fresh.stat().st_mode & 0o777 == 0o600


def test_private_directory_cannot_alias_public_media(tmp_path: Path) -> None:
    r = rollout()
    public = tmp_path / "public"
    public.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(public, target_is_directory=True)
    with pytest.raises(RuntimeError):
        r.require_private_directory(alias)


@pytest.mark.parametrize(
    "name", ["startup-env.json", "backend.log", "ui-process.json", "migration.json"]
)
def test_all_planned_outputs_must_be_absent_before_live_migration(
    tmp_path: Path, name: str
) -> None:
    r = rollout()
    r.require_startup_outputs(tmp_path)
    # Even a broken symlink must fail the create-only preflight, not just open().
    (tmp_path / name).symlink_to(tmp_path / "absent")
    with pytest.raises(RuntimeError):
        r.require_startup_outputs(tmp_path)


def test_no_apply_means_no_mutation_even_when_start_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = rollout()
    monkeypatch.setattr(r, "inspect", lambda *_: {"safe": True})
    monkeypatch.setattr(r, "start", lambda *_: pytest.fail("mutation without apply"))
    assert (
        r.main(
            [
                "--action",
                "start",
                "--live-worktree",
                str(r.LIVE),
                "--implementation-worktree",
                str(r.WORKTREE),
                "--origin",
                "http://localhost:5174",
                "--origin",
                "http://192.168.1.214:5174",
            ]
        )
        == 0
    )


def test_bad_inspection_blocks_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    r = rollout()

    def refuse(*_: Any) -> None:
        raise RuntimeError("ownership refused")

    monkeypatch.setattr(r, "inspect", refuse)
    monkeypatch.setattr(
        r, "start", lambda *_: pytest.fail("mutation after guard failure")
    )
    assert (
        r.main(
            [
                "--apply",
                "--action",
                "start",
                "--live-worktree",
                str(r.LIVE),
                "--implementation-worktree",
                str(r.WORKTREE),
                "--origin",
                "http://localhost:5174",
                "--origin",
                "http://192.168.1.214:5174",
            ]
        )
        == 1
    )


def test_stop_refuses_changed_pid_before_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = rollout()
    monkeypatch.setattr(
        r,
        "require_process_identity",
        lambda _: (_ for _ in ()).throw(RuntimeError("changed PID")),
    )
    monkeypatch.setattr(r.os, "kill", lambda *_: pytest.fail("unverified kill"))
    with pytest.raises(RuntimeError):
        r.stop_owned({"identity": {"pid": 123}})


def test_wrong_service_cwd_or_command_cannot_be_signalled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = rollout()
    # The lower /proc proof alone does not permit another service's argv/cwd.
    monkeypatch.setattr(r, "require_process_identity", lambda _: None)
    monkeypatch.setattr(r.os, "kill", lambda *_: pytest.fail("unverified kill"))
    for cwd, argv in [
        (str(r.WORKTREE / "frontend"), r.command("backend")),
        (str(r.WORKTREE / "backend"), ["other-service"]),
    ]:
        with pytest.raises(RuntimeError):
            r.stop_owned(
                {
                    "component": "backend",
                    "identity": {"pid": 123, "cwd": cwd, "command": argv},
                }
            )


def test_matching_command_still_requires_owned_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = rollout()
    monkeypatch.setattr(r, "require_process_identity", lambda _: None)
    monkeypatch.setattr(
        r.subprocess,
        "check_output",
        lambda *_args, **_kwargs: (
            'LISTEN 0 100 127.0.0.1:8010 0.0.0.0:* users:(("python",pid=999,fd=7))\n'
        ),
    )
    monkeypatch.setattr(r.os, "kill", lambda *_: pytest.fail("unverified kill"))
    with pytest.raises(RuntimeError):
        r.stop_owned(
            {
                "component": "backend",
                "identity": {
                    "pid": 123,
                    "cwd": str(r.WORKTREE / "backend"),
                    "command": r.command("backend"),
                },
            }
        )


def test_unowned_actual_pid_cannot_be_signalled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = rollout()
    from tests.browser.guest_test_environment import _process_identity

    record: dict[str, Any] = {
        "component": "backend",
        "identity": _process_identity(os.getpid()),
    }
    record["identity"]["start_ticks"] = "0"
    monkeypatch.setattr(r.os, "kill", lambda *_: pytest.fail("unverified kill"))
    with pytest.raises(RuntimeError):
        r.stop_owned(record)


def test_failed_migration_cannot_launch_services(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    r = rollout()
    proof = {
        "origins": ["http://localhost:5174", "http://192.168.1.214:5174"],
        "runtime": str(tmp_path),
    }
    monkeypatch.setattr(r, "EVIDENCE", tmp_path)
    monkeypatch.setattr(r, "inspect", lambda *_: proof)

    def fail_migration(*args: Any, **_kwargs: Any) -> None:
        assert args[0][-3:] == ["alembic", "upgrade", "head"]
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(r.subprocess, "run", fail_migration)
    monkeypatch.setattr(
        r.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("launched after migration failure"),
    )
    with pytest.raises(subprocess.CalledProcessError):
        r.start(proof)


def test_factory_disables_ambient_smtp_and_public_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = rollout()
    for field, value in {
        "SMTP_HOST": "remote.example",
        "SMTP_USER": "ambient",
        "SMTP_PASSWORD": "ambient",
        "EMAILS_FROM_EMAIL": "ambient@example.com",
        "SMTP_PORT": 2525,
        "SMTP_TLS": True,
        "SMTP_SSL": True,
        "PUBLIC_REGISTRATION_ENABLED": True,
    }.items():
        monkeypatch.setattr(r.settings, field, value)
    r.local_app()
    assert r.settings.emails_enabled is False
    assert r.settings.SMTP_USER is None
    assert r.settings.SMTP_PASSWORD is None
    assert r.settings.PUBLIC_REGISTRATION_ENABLED is False
