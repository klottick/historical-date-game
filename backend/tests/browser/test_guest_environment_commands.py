"""Safety contracts for the non-destructive owned browser launcher."""

from pathlib import Path
from types import SimpleNamespace

import pytest

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
    expected = {
        "pid": 123,
        "cwd": str(environment.WORKTREE / "frontend"),
        "command": ["node", "vite"],
        "start_ticks": "456",
    }
    identities = iter([{**expected, "command": [""]}, expected])
    monkeypatch.setattr(environment, "_process_identity", lambda _pid: next(identities))
    monkeypatch.setattr(environment.time, "sleep", lambda _seconds: None)
    process = SimpleNamespace(pid=123, poll=lambda: None)
    assert (
        environment.wait_process_identity(
            process, Path(expected["cwd"]), expected["command"]
        )
        == expected
    )
