"""Safety contracts for the non-destructive owned browser launcher."""

import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from tests.browser import guest_test_environment as environment


def test_browser_targets_never_select_live_ports_or_databases() -> None:
    real = environment.browser_target("real")
    fixture = environment.browser_target("fixture")
    assert (
        real["database"],
        real["backend_port"],
        real["ui_port"],
        real["cookie"],
    ) == ("historical_date_game_guest_test", 8020, 5184, "hdg_guest_verification")
    assert (
        fixture["database"],
        fixture["backend_port"],
        fixture["ui_port"],
        fixture["cookie"],
    ) == ("historical_date_game_guest_fixture_test", 8021, 5173, "hdg_guest_fixture")
    with pytest.raises(ValueError):
        environment.browser_target("live")


def test_public_projection_refuses_unpinned_real_release(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("{}")
    with pytest.raises(RuntimeError, match="pinned manifest"):
        environment.verify_real_source(tmp_path)
    assert not (tmp_path / "media").exists()


def test_owned_process_refuses_foreign_cwd_and_pid_reuse() -> None:
    with pytest.raises(RuntimeError, match="process ownership"):
        environment.require_process_identity(
            {
                "pid": 1,
                "cwd": str(environment.WORKTREE / "backend"),
                "command": ["owned"],
                "start_ticks": "0",
            }
        )


def test_launcher_waits_for_exec_before_recording_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected: dict[str, Any] = {
        "pid": 123,
        "cwd": str(environment.WORKTREE / "frontend"),
        "command": ["node", "vite"],
        "start_ticks": "456",
    }
    identities = iter([{**expected, "command": [""]}, expected])
    monkeypatch.setattr(environment, "_process_identity", lambda _pid: next(identities))
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    process = SimpleNamespace(pid=123, poll=lambda: None)
    assert (
        environment.wait_process_identity(
            process, Path(expected["cwd"]), expected["command"]
        )
        == expected
    )


class SpawnIntercepted(Exception):
    """No subprocess is created by the launch-environment regression tests."""


def capture_launch_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, target: str
) -> tuple[list[str], dict[str, str]]:
    config = environment.browser_target(target)
    config["runtime"] = tmp_path / "runtime"
    config["runtime"].mkdir()
    (config["runtime"] / "seed.json").write_text("{}")
    monkeypatch.setattr(environment, "EVIDENCE", tmp_path / "evidence")
    monkeypatch.setattr(environment, "browser_target", lambda _target: config)
    # These guards connect to PostgreSQL/bind sockets; no real resources in units.
    monkeypatch.setattr(environment, "require_owned_guest_database", lambda _db: None)
    monkeypatch.setattr(environment, "_require_free_port", lambda _port: None)
    captured: dict[str, Any] = {}

    def intercept(command: list[str], **kwargs: Any) -> None:
        captured.update(command=command, env=kwargs["env"])
        raise SpawnIntercepted

    monkeypatch.setattr(subprocess, "Popen", intercept)
    with pytest.raises(SpawnIntercepted):
        environment.owned_process(target, "backend")
    return captured["command"], captured["env"]


@pytest.mark.parametrize("target", ["real", "fixture"])
@pytest.mark.parametrize("external_source", ["ambient", "dotenv"])
def test_launch_email_policy_overrides_external_smtp_before_app_import(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target: str,
    external_source: str,
) -> None:
    # All inputs are synthetic; never read/print actual credentials or .env.
    external = {
        "SMTP_HOST": "smtp.external.example.com",
        "SMTP_PORT": "465",
        "SMTP_TLS": "true",
        "SMTP_SSL": "true",
        "SMTP_USER": "synthetic-external-login",
        "SMTP_PASSWORD": "synthetic-external-password",
        "EMAILS_FROM_EMAIL": "external@example.com",
    }
    dotenv = tmp_path / "synthetic.env"
    dotenv.write_text("\n".join(f"{key}={value}" for key, value in external.items()))
    base = {
        "PROJECT_NAME": "Synthetic SMTP regression",
        "SECRET_KEY": "synthetic-long-secret-never-used-by-a-server",
        "POSTGRES_SERVER": "127.0.0.1",
        "POSTGRES_USER": "synthetic",
        "FIRST_SUPERUSER": "synthetic@example.com",
        "FIRST_SUPERUSER_PASSWORD": "synthetic-long-password",
    }
    monkeypatch.setattr(
        os,
        "environ",
        base | (external if external_source == "ambient" else {}),
    )
    command, child_env = capture_launch_environment(monkeypatch, tmp_path, target)
    monkeypatch.setattr(os, "environ", child_env)
    child_settings = Settings(_env_file=dotenv)  # type: ignore[call-arg]
    monkeypatch.setattr(environment, "settings", child_settings)
    app_module = ModuleType("app.main")

    def app_import_boundary(_name: str) -> Any:
        # A real app import must not see unsafe mail settings. No app/DB imported.
        assert child_settings.emails_enabled is (target == "fixture")
        return object()

    monkeypatch.setattr(app_module, "__getattr__", app_import_boundary, raising=False)
    monkeypatch.setitem(sys.modules, "app.main", app_module)
    if "--factory" in command:
        module, factory = command[3].split(":")
        getattr(importlib.import_module(module), factory)()

    assert child_settings.emails_enabled is (target == "fixture")
    assert child_settings.SMTP_HOST == ("127.0.0.1" if target == "fixture" else None)
    assert child_settings.SMTP_TLS is False
    assert child_settings.SMTP_SSL is False
    assert child_settings.SMTP_USER is None
    assert child_settings.SMTP_PASSWORD is None
    assert child_env["SMTP_HOST"] == ("127.0.0.1" if target == "fixture" else "")
    assert child_env["SMTP_USER"] == child_env["SMTP_PASSWORD"] == ""
    if target == "fixture":
        assert child_settings.SMTP_PORT == 1025
        assert child_settings.EMAILS_FROM_EMAIL == "guest-verification@example.com"
    else:
        assert child_settings.EMAILS_FROM_EMAIL is None


def test_identity_timeout_retains_private_child_diagnostic_without_signalling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Install the no-DB/no-socket launch boundary and intercept the first spawn.
    capture_launch_environment(monkeypatch, tmp_path, "real")
    process = SimpleNamespace(pid=123, poll=lambda: None)
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        environment,
        "_process_identity",
        lambda _pid: {
            "pid": 123,
            "cwd": str(environment.WORKTREE / "backend"),
            "command": [""],
            "start_ticks": "456",
        },
    )
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    def forbid_signal(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("An unconfirmed child must never be signalled")

    monkeypatch.setattr(os, "kill", forbid_signal)
    with pytest.raises(RuntimeError, match="did not become verifiable"):
        environment.owned_process("real", "backend")
    diagnostic = tmp_path / "evidence" / "real-backend-unconfirmed-123.json"
    assert diagnostic.exists(), "Launch timeout orphaned the child without a diagnostic"
    assert diagnostic.stat().st_mode & 0o777 == 0o600
    record = json.loads(diagnostic.read_text())
    assert record["pid"] == 123
    assert record["parent_pid"] == os.getpid()
    assert record["cwd"] == str(environment.WORKTREE / "backend")
    assert record["expected_command"][3:5] == [
        "tests.browser.guest_test_environment:browser_app",
        "--factory",
    ]
    assert record["ownership_confirmed"] is False
    assert not (tmp_path / "evidence" / "real-backend-process.json").exists()


@pytest.mark.parametrize("target", ["", "live"])
def test_app_factory_refuses_missing_or_unknown_email_policy(
    monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    monkeypatch.setattr(os, "environ", {"HDG_GUEST_BROWSER_TARGET": target})
    with pytest.raises(ValueError, match="Unknown owned browser target"):
        environment.browser_app()
