"""Pure board lifecycle gates; no conftest, connections or live services."""

import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import UUID

import pytest


def rollout() -> ModuleType:
    assert importlib.util.find_spec("tests.browser.board_local_rollout") is not None, (
        "board rollout guard has not been implemented"
    )
    from tests.browser import board_local_rollout

    return board_local_rollout


def legacy_rollout() -> ModuleType:
    from tests.browser import guest_local_rollout

    return guest_local_rollout


def runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[ModuleType, ModuleType]:
    board = rollout()
    # Simulate namespace creation in this checkout; retain the real runtime pin.
    assert board.__file__ is not None
    checkout = Path(board.__file__).resolve().parents[3]
    monkeypatch.setattr(board, "WORKTREE", checkout)
    monkeypatch.setattr(board, "EVIDENCE", tmp_path / "evidence")
    guarded = board.guarded_rollout()
    assert guarded.EVIDENCE == board.EVIDENCE, "Board factory must propagate evidence"
    assert guarded.EVIDENCE != legacy_rollout().EVIDENCE, (
        "Board evidence must be separate"
    )
    monkeypatch.setattr(board, "guarded_rollout", lambda: guarded)
    # After real namespace creation, model coherent linked-worktree CLI pins.
    # Never depend on a retained beta sibling, hosted .git directory or live data.
    for field, name in [("LIVE", "live"), ("WORKTREE", "implementation")]:
        path = tmp_path / name
        path.mkdir()
        (path / ".git").write_text("gitdir: pure-test-fixture\n")
        monkeypatch.setattr(board, field, path)
        monkeypatch.setattr(guarded, field, path)
    (board.LIVE / "data/game/releases" / guarded.RELEASE_ID).mkdir(parents=True)
    (board.LIVE / "data/game/local-catalog-runtime").mkdir()
    # Keep the old guest rollout's reviewed migration generation. The lives
    # migration head is tested separately; it must not make the old runner adopt it.
    shutil.copytree(
        checkout / "backend/app/alembic",
        board.WORKTREE / "backend/app/alembic",
        ignore=shutil.ignore_patterns(
            "__pycache__", "20261015_01_add_three_life_counters.py"
        ),
    )
    for name, value in {
        "POSTGRES_DB": "historical_date_game_catalog_test",
        "POSTGRES_SERVER": "127.0.0.1",
        "POSTGRES_PORT": 5433,
        "ENVIRONMENT": "local",
    }.items():
        monkeypatch.setattr(guarded.settings, name, value)
    monkeypatch.setattr(
        guarded.psycopg, "connect", lambda **_: pytest.fail("live connection")
    )
    monkeypatch.setattr(guarded.os, "kill", lambda *_: pytest.fail("live signal"))
    return board, guarded


def arguments(*extra: str) -> list[str]:
    return [
        "--origin",
        "http://localhost:5174",
        "--origin",
        "http://192.168.1.214:5174",
        *extra,
    ]


def test_pure_runner_creates_namespace_in_current_checkout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    board, guarded = runner(monkeypatch, tmp_path)
    assert guarded.__file__ == legacy_rollout().__file__
    assert guarded is not legacy_rollout()
    assert guarded.WORKTREE == board.WORKTREE == tmp_path / "implementation"


def test_runner_rejects_legacy_factory_evidence_before_fixture_io(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    board = rollout()
    guest = legacy_rollout()
    real_factory = board.guarded_rollout

    def wrong_evidence_factory() -> ModuleType:
        guarded: ModuleType = real_factory()
        guarded.__dict__["EVIDENCE"] = guest.EVIDENCE
        return guarded

    monkeypatch.setattr(board, "guarded_rollout", wrong_evidence_factory)
    calls: list[bool] = []

    def unexpected_io(*_args: Any, **_kwargs: Any) -> None:
        calls.append(True)
        pytest.fail("Fixture I/O before factory evidence validation")

    monkeypatch.setattr(guest.psycopg, "connect", unexpected_io)
    monkeypatch.setattr(guest.os, "kill", unexpected_io)
    monkeypatch.setattr(guest.subprocess, "run", unexpected_io)
    monkeypatch.setattr(guest.subprocess, "Popen", unexpected_io)
    for method in ("mkdir", "chmod", "write_text", "write_bytes"):
        monkeypatch.setattr(Path, method, unexpected_io)
    before = dict(os.environ)
    target_fields = ("POSTGRES_DB", "POSTGRES_SERVER", "POSTGRES_PORT", "ENVIRONMENT")
    before_target = {name: getattr(guest.settings, name) for name in target_fields}
    with pytest.raises(AssertionError, match="Board factory must propagate evidence"):
        runner(monkeypatch, tmp_path)
    assert calls == []
    assert dict(os.environ) == before
    assert {
        name: getattr(guest.settings, name) for name in target_fields
    } == before_target
    assert list(tmp_path.iterdir()) == []


def test_simulated_cli_paths_do_not_depend_on_retained_sibling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(rollout(), "LIVE", tmp_path / "absent-hosted-beta")
    board, guarded = runner(monkeypatch, tmp_path)
    guarded.require_paths(board.LIVE, board.WORKTREE)
    assert board.LIVE.is_relative_to(tmp_path)
    assert board.WORKTREE.is_relative_to(tmp_path)
    assert not (tmp_path / "absent-hosted-beta").exists()


@pytest.mark.parametrize(
    "field,flag",
    [("LIVE", "--live-worktree"), ("WORKTREE", "--implementation-worktree")],
)
@pytest.mark.parametrize("change", ["wrong", "missing", "symlink", "git-directory"])
def test_simulated_pins_still_reject_invalid_paths_before_io(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    flag: str,
    change: str,
) -> None:
    board, guarded = runner(monkeypatch, tmp_path)
    path = getattr(board, field)
    if change == "git-directory":
        (path / ".git").unlink()
        (path / ".git").mkdir()
    else:
        invalid = tmp_path / "invalid"
        if change == "symlink":
            invalid.symlink_to(path, target_is_directory=True)
        path = invalid
        if change != "wrong":
            # Even an alias/missing path matching both pins must be refused.
            monkeypatch.setattr(board, field, path)
            monkeypatch.setattr(guarded, field, path)
    live = path if field == "LIVE" else board.LIVE
    implementation = path if field == "WORKTREE" else board.WORKTREE
    if change == "missing":
        with pytest.raises(FileNotFoundError):
            guarded.require_paths(live, implementation)
    else:
        with pytest.raises(
            RuntimeError, match="Exact real and implementation worktrees"
        ):
            guarded.require_paths(live, implementation)
    monkeypatch.setattr(
        guarded, "verify_real_source", lambda _: pytest.fail("past path guard")
    )
    monkeypatch.setattr(
        guarded, "inspect_database", lambda: pytest.fail("past path guard")
    )
    before = dict(os.environ)
    assert board.main(arguments(flag, str(path), "--action", "start", "--apply")) == 1
    assert dict(os.environ) == before
    assert not guarded.EVIDENCE.exists()
    if change == "missing":
        assert not path.exists()


def test_real_worktree_guard_rejects_before_namespace_or_io(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    board = rollout()
    guest = legacy_rollout()
    monkeypatch.setattr(board, "WORKTREE", tmp_path / "different-pinned-worktree")
    calls: list[bool] = []

    def unexpected_io(*_args: Any, **_kwargs: Any) -> None:
        calls.append(True)
        pytest.fail("I/O before worktree rejection")

    monkeypatch.setattr(board.importlib.util, "spec_from_file_location", unexpected_io)
    monkeypatch.setattr(guest.psycopg, "connect", unexpected_io)
    monkeypatch.setattr(guest.os, "kill", unexpected_io)
    monkeypatch.setattr(guest.subprocess, "run", unexpected_io)
    monkeypatch.setattr(guest.subprocess, "Popen", unexpected_io)
    for method in (
        "read_text",
        "read_bytes",
        "write_text",
        "write_bytes",
        "mkdir",
        "chmod",
    ):
        monkeypatch.setattr(Path, method, unexpected_io)
    before = dict(os.environ)
    with pytest.raises(RuntimeError, match="Exact board implementation worktree"):
        board.guarded_rollout()
    assert board.main(arguments("--action", "start", "--apply")) == 1
    assert calls == []
    assert dict(os.environ) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("POSTGRES_DB", "historical_date_game_board_test"),
        ("POSTGRES_DB", "historical_date_game_guest_test"),
        ("POSTGRES_SERVER", "localhost"),
        ("POSTGRES_SERVER", "::1"),
        ("POSTGRES_SERVER", "remote.example"),
        ("POSTGRES_PORT", 5432),
        ("ENVIRONMENT", "production"),
    ],
)
def test_wrong_live_database_or_endpoint_refused_before_connect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    board, guarded = runner(monkeypatch, tmp_path)
    monkeypatch.setattr(guarded.settings, field, value)
    monkeypatch.setattr(guarded, "require_paths", lambda *_: pytest.fail("past target"))
    assert board.main(arguments("--action", "start", "--apply")) == 1


@pytest.mark.parametrize("change", ["worktree", "pid", "cwd", "argv", "port"])
def test_unknown_process_or_worktree_never_signalled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    change: str,
) -> None:
    board, guarded = runner(monkeypatch, tmp_path)
    if change == "worktree":
        assert (
            board.main(
                arguments(
                    "--implementation-worktree",
                    str(tmp_path),
                    "--action",
                    "stop",
                    "--apply",
                )
            )
            == 1
        )
        return
    monkeypatch.setattr(guarded, "EVIDENCE", tmp_path)
    record: dict[str, Any] = {
        "component": "backend",
        "identity": {
            "pid": 123,
            "cwd": str(guarded.WORKTREE / "backend"),
            "command": guarded.command("backend"),
            "start_ticks": "0",
        },
    }
    if change == "pid":
        from tests.browser.guest_test_environment import _process_identity

        record["identity"] = _process_identity(os.getpid())
        record["identity"]["start_ticks"] = "0"
    else:
        monkeypatch.setattr(guarded, "require_process_identity", lambda _: None)
        if change == "cwd":
            record["identity"]["cwd"] = str(tmp_path / "other-implementation/backend")
        elif change == "argv":
            record["identity"]["command"] = ["unknown"]
        monkeypatch.setattr(
            guarded.subprocess,
            "check_output",
            lambda *_a, **_k: (
                'LISTEN 0 100 127.0.0.1:8010 0.0.0.0:* users:(("python",pid=999,fd=7))\n'
            ),
        )
    with pytest.raises(RuntimeError):
        guarded.stop_owned(record)


def sidecar(
    tmp_path: Path, board: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, str, Path]:
    private = tmp_path / "integration"
    private.mkdir(mode=0o700)
    monkeypatch.setattr(board, "INTEGRATION", private)
    release = tmp_path / "release"
    release.mkdir()
    event_id = "00000000-0000-0000-0000-000000000001"
    source = "https://en.wikipedia.org/wiki/January_1"
    monkeypatch.setattr(board, "release_sources", lambda _: {UUID(event_id): {source}})
    body = {
        "schema_version": 1,
        "policy_version": "event-links-v1",
        "release_id": "jsonl-trial-2026-10-12-review-r1",
        "manifest_sha256": "804ec52ccfc3e19cd955913b05cbfd59158f562408e45c1916fa8626d3ac50d3",
        "records": {
            event_id: {
                "event_id": event_id,
                "kind": "source",
                "label": "Wikipedia calendar source",
                "url": source,
                "source_url": source,
                "source_revision": None,
                "evidence_sha256": None,
                "reason": "unresolved",
            }
        },
    }
    path = private / "event-links.json"
    path.write_text(json.dumps(body))
    path.chmod(0o600)
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), release


@pytest.mark.parametrize(
    "change",
    [
        "digest",
        "public",
        "symlink",
        "hardlink",
        "mode",
        "release",
        "manifest",
        "event",
        "source",
        "duplicate",
    ],
)
def test_sidecar_digest_or_public_path_refused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    change: str,
) -> None:
    board = rollout()
    path, digest, release = sidecar(tmp_path, board, monkeypatch)
    if change == "digest":
        digest = "0" * 64
    elif change == "public":
        public = tmp_path / "frontend/public"
        public.mkdir(parents=True)
        destination = public / path.name
        path.rename(destination)
        path = destination
    elif change == "symlink":
        alias = path.parent / "alias.json"
        alias.symlink_to(path)
        path = alias
    elif change == "hardlink":
        os.link(path, path.parent / "hard.json")
    elif change == "mode":
        path.chmod(0o644)
    else:
        body = json.loads(path.read_text())
        if change == "release":
            body["release_id"] = "other"
        elif change == "manifest":
            body["manifest_sha256"] = "0" * 64
        elif change == "event":
            key, record = next(iter(body["records"].items()))
            del body["records"][key]
            record["event_id"] = "00000000-0000-0000-0000-000000000002"
            body["records"][record["event_id"]] = record
        elif change == "source":
            record = next(iter(body["records"].values()))
            record["source_url"] = record["url"] = (
                "https://en.wikipedia.org/wiki/January_2"
            )
        text = json.dumps(body)
        if change == "duplicate":
            text = text.replace(
                '"schema_version": 1', '"schema_version": 1, "schema_version": 1'
            )
        path.write_text(text)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises((RuntimeError, ValueError)):
        board.require_sidecar(path, digest, release)


def test_verified_private_sidecar_and_explicit_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    board = rollout()
    path, digest, release = sidecar(tmp_path, board, monkeypatch)
    board.require_sidecar(path, digest, release)
    board.require_sidecar(None, None, release)
    for file, sha in [(path, None), (None, digest)]:
        with pytest.raises(RuntimeError):
            board.require_sidecar(file, sha, release)


@pytest.mark.parametrize(
    "name",
    [
        "startup-env.json",
        "preflight.json",
        "migration.json",
        "backend.log",
        "ui.log",
        "backend-spawn.json",
        "ui-spawn.json",
        "backend-process.json",
        "ui-process.json",
    ],
)
def test_existing_generation_outputs_not_overwritten(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
) -> None:
    board, guarded = runner(monkeypatch, tmp_path)
    monkeypatch.setattr(guarded, "EVIDENCE", tmp_path)
    prior = tmp_path / name
    prior.symlink_to(tmp_path / "absent")
    monkeypatch.setattr(guarded, "current_ip", lambda: "192.168.1.214")
    monkeypatch.setattr(
        guarded, "verify_real_source", lambda _: pytest.fail("past output guard")
    )
    assert board.main(arguments("--action", "start", "--apply")) == 1
    assert prior.is_symlink()


@pytest.mark.parametrize(
    "extra", [[], ["--apply"], ["--action", "start"], ["--action", "stop"]]
)
def test_inspect_has_no_mutations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    extra: list[str],
) -> None:
    board, guarded = runner(monkeypatch, tmp_path)
    evidence = tmp_path / "absent"
    monkeypatch.setattr(guarded, "EVIDENCE", evidence)
    monkeypatch.setattr(guarded, "current_ip", lambda: "192.168.1.214")
    monkeypatch.setattr(
        guarded, "verify_real_source", lambda _: SimpleNamespace(files={})
    )
    monkeypatch.setattr(
        guarded, "inspect_database", lambda: {"revision": "20261013_01"}
    )
    monkeypatch.setattr(guarded, "require_free_port", lambda _: None)
    monkeypatch.setattr(guarded, "start", lambda *_a, **_k: pytest.fail("started"))
    before = dict(os.environ)
    monkeypatch.setattr(
        guarded.subprocess, "run", lambda *_a, **_k: pytest.fail("migration")
    )
    monkeypatch.setattr(
        guarded.subprocess, "Popen", lambda *_a, **_k: pytest.fail("spawn")
    )
    monkeypatch.setattr(Path, "mkdir", lambda *_a, **_k: pytest.fail("mkdir"))
    monkeypatch.setattr(Path, "chmod", lambda *_a, **_k: pytest.fail("chmod"))
    monkeypatch.setattr(guarded, "private_json", lambda *_: pytest.fail("file write"))
    assert board.main(arguments(*extra)) == 0
    assert dict(os.environ) == before
    assert not evidence.exists()


def test_start_delegates_migration_free_with_sidecar_env_restored(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    board, guarded = runner(monkeypatch, tmp_path)
    monkeypatch.setenv("GAME_EVENT_LINKS_FILE", "/ambient/private.json")
    monkeypatch.setenv("GAME_EVENT_LINKS_SHA256", "0" * 64)
    monkeypatch.setattr(
        guarded, "inspect", lambda *_: {"database": {"revision": "20261013_01"}}
    )
    called = []

    def start(_proof: dict[str, Any], *, upgrade_schema: bool = True) -> None:
        assert upgrade_schema is False
        assert os.environ["GAME_EVENT_LINKS_FILE"] == ""
        assert os.environ["GAME_EVENT_LINKS_SHA256"] == ""
        called.append(True)

    monkeypatch.setattr(guarded, "start", start)
    before = dict(os.environ)
    assert board.main(arguments("--action", "start", "--apply")) == 0
    assert called == [True]
    assert dict(os.environ) == before


def test_wrong_schema_blocks_board_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    board, guarded = runner(monkeypatch, tmp_path)
    monkeypatch.setattr(
        guarded, "inspect", lambda *_: {"database": {"revision": "20261011_01"}}
    )
    monkeypatch.setattr(
        guarded, "start", lambda *_a, **_k: pytest.fail("wrong-schema launch")
    )
    assert board.main(arguments("--action", "start", "--apply")) == 1


def test_board_factory_clears_ambient_links_and_keeps_smtp_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board = rollout()
    guest = legacy_rollout()

    monkeypatch.delenv("GAME_EVENT_LINKS_FILE", raising=False)
    monkeypatch.delenv("GAME_EVENT_LINKS_SHA256", raising=False)
    monkeypatch.setattr(guest.settings, "GAME_EVENT_LINKS_FILE", Path("/ambient.json"))
    monkeypatch.setattr(guest.settings, "GAME_EVENT_LINKS_SHA256", "0" * 64)
    for field in guest.browser_email_policy("real"):
        monkeypatch.setattr(guest.settings, field, getattr(guest.settings, field))
    monkeypatch.setattr(
        guest.settings,
        "PUBLIC_REGISTRATION_ENABLED",
        guest.settings.PUBLIC_REGISTRATION_ENABLED,
    )
    monkeypatch.setattr(guest.settings, "SMTP_HOST", "remote.example")
    board.local_app()
    assert guest.settings.GAME_EVENT_LINKS_FILE is None
    assert guest.settings.GAME_EVENT_LINKS_SHA256 is None
    assert guest.settings.emails_enabled is False
    assert guest.settings.PUBLIC_REGISTRATION_ENABLED is False


def test_board_runner_keeps_old_generation_separate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    board, guarded = runner(monkeypatch, tmp_path)
    guest = legacy_rollout()

    assert guarded.EVIDENCE != guest.EVIDENCE
    assert guarded.EVIDENCE == board.EVIDENCE
    assert (
        guarded.command("backend")[3] == "tests.browser.board_local_rollout:local_app"
    )
    assert "--no-access-log" in guarded.command("backend")
    assert guest.command("backend")[3] == "tests.browser.guest_local_rollout:local_app"


@pytest.mark.parametrize("upgrade_schema", [True, False])
def test_start_schema_option_preserves_default_and_skips_unneeded_alembic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    upgrade_schema: bool,
) -> None:
    r = legacy_rollout()
    monkeypatch.setattr(r.ScriptDirectory, "get_heads", lambda _: ["20261013_01"])

    proof = {"origins": [], "runtime": str(tmp_path)}
    monkeypatch.setattr(r, "EVIDENCE", tmp_path)
    monkeypatch.setattr(r, "inspect", lambda *_: proof)
    monkeypatch.setattr(r, "inspect_database", lambda: {"revision": "20261013_01"})
    migrations = []

    def migration(argv: list[str], **_kwargs: Any) -> None:
        migrations.append(argv[-3:])

    monkeypatch.setattr(r.subprocess, "run", migration)

    def launch_boundary(_: int) -> None:
        assert migrations == (
            [["alembic", "upgrade", "head"]] if upgrade_schema else []
        )
        assert (
            json.loads((tmp_path / "migration.json").read_text())["revision"]
            == "20261013_01"
        )
        raise RuntimeError("pure launch boundary")

    monkeypatch.setattr(r, "require_free_port", launch_boundary)
    with pytest.raises(RuntimeError, match="pure launch boundary"):
        if upgrade_schema:
            r.start(proof)
        else:
            r.start(proof, upgrade_schema=False)


def test_wrong_schema_migration_free_path_refuses_before_writes_or_launch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    r = legacy_rollout()

    monkeypatch.setattr(
        r, "inspect", lambda *_: {"origins": [], "runtime": str(tmp_path)}
    )
    monkeypatch.setattr(r, "inspect_database", lambda: {"revision": "20261011_01"})
    monkeypatch.setattr(r.subprocess, "run", lambda *_a, **_k: pytest.fail("Alembic"))
    monkeypatch.setattr(r.subprocess, "Popen", lambda *_a, **_k: pytest.fail("launch"))
    monkeypatch.setattr(r, "require_private_directory", lambda _: pytest.fail("mkdir"))
    with pytest.raises(RuntimeError, match="schema"):
        r.start({"origins": []}, upgrade_schema=False)


def test_changed_migration_head_refuses_without_upgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guest = legacy_rollout()

    monkeypatch.setattr(
        guest.ScriptDirectory, "get_heads", lambda _: ["future_revision"]
    )
    with pytest.raises(RuntimeError, match="schema"):
        guest.require_current_schema({"revision": "20261013_01"})


def test_migration_free_post_check_still_refuses_changed_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    guest = legacy_rollout()
    monkeypatch.setattr(
        guest.ScriptDirectory, "get_heads", lambda _: ["20261013_01"]
    )
    monkeypatch.setattr(guest, "EVIDENCE", tmp_path)
    monkeypatch.setattr(
        guest, "inspect", lambda *_: {"origins": [], "runtime": str(tmp_path)}
    )
    reads = iter([{"revision": "20261013_01"}, {"revision": "20261011_01"}])
    monkeypatch.setattr(guest, "inspect_database", lambda: next(reads))
    monkeypatch.setattr(
        guest.subprocess, "run", lambda *_a, **_k: pytest.fail("Alembic")
    )
    monkeypatch.setattr(
        guest.subprocess, "Popen", lambda *_a, **_k: pytest.fail("launch")
    )
    with pytest.raises(RuntimeError, match="Unexpected upgraded schema"):
        guest.start({"origins": []}, upgrade_schema=False)
    assert (tmp_path / "startup-env.json").is_file()
    assert (tmp_path / "preflight.json").is_file()
    assert not (tmp_path / "migration.json").exists()


def test_stop_proves_both_records_before_either_signal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    board, guarded = runner(monkeypatch, tmp_path)
    monkeypatch.setattr(guarded, "EVIDENCE", tmp_path)
    monkeypatch.setattr(
        guarded, "inspect", lambda *_: {"database": {"revision": "20261013_01"}}
    )
    for component in ("ui", "backend"):
        (tmp_path / f"{component}-process.json").write_text(
            json.dumps({"component": component})
        )

    def require_record(record: dict[str, Any]) -> None:
        if record["component"] == "backend":
            raise RuntimeError("second service is unowned")

    monkeypatch.setattr(guarded, "require_owned_record", require_record)
    monkeypatch.setattr(
        guarded, "stop_owned", lambda _: pytest.fail("signal before both proofs")
    )
    assert board.main(arguments("--action", "stop", "--apply")) == 1


def test_sidecar_refused_by_main_before_database_or_env_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    board, guarded = runner(monkeypatch, tmp_path)
    path, _digest, _release = sidecar(tmp_path, board, monkeypatch)
    monkeypatch.setattr(
        guarded, "verify_real_source", lambda _: SimpleNamespace(files={})
    )
    before = dict(os.environ)
    assert (
        board.main(
            arguments(
                "--event-links-file",
                str(path),
                "--event-links-sha256",
                "0" * 64,
                "--action",
                "start",
                "--apply",
            )
        )
        == 1
    )
    assert dict(os.environ) == before


def test_supplied_sidecar_environment_restored_on_failed_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    board, guarded = runner(monkeypatch, tmp_path)
    path, digest, _release = sidecar(tmp_path, board, monkeypatch)
    monkeypatch.setattr(
        guarded, "verify_real_source", lambda _: SimpleNamespace(files={})
    )
    monkeypatch.setattr(
        guarded, "inspect", lambda *_: {"database": {"revision": "20261013_01"}}
    )
    monkeypatch.delenv("GAME_EVENT_LINKS_FILE", raising=False)
    monkeypatch.delenv("GAME_EVENT_LINKS_SHA256", raising=False)

    def refuse_start(_proof: dict[str, Any], *, upgrade_schema: bool) -> None:
        assert not upgrade_schema
        assert os.environ["GAME_EVENT_LINKS_FILE"] == str(path)
        assert os.environ["GAME_EVENT_LINKS_SHA256"] == digest
        raise RuntimeError("controlled startup failure")

    monkeypatch.setattr(guarded, "start", refuse_start)
    before = dict(os.environ)
    assert (
        board.main(
            arguments(
                "--event-links-file",
                str(path),
                "--event-links-sha256",
                digest,
                "--action",
                "start",
                "--apply",
            )
        )
        == 1
    )
    assert dict(os.environ) == before


def test_supplied_sidecar_inspection_preserves_files_and_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    board, guarded = runner(monkeypatch, tmp_path)
    path, digest, _release = sidecar(tmp_path, board, monkeypatch)
    monkeypatch.setattr(guarded, "EVIDENCE", tmp_path / "absent")
    monkeypatch.setattr(guarded, "current_ip", lambda: "192.168.1.214")
    monkeypatch.setattr(
        guarded, "verify_real_source", lambda _: SimpleNamespace(files={})
    )
    monkeypatch.setattr(
        guarded, "inspect_database", lambda: {"revision": "20261013_01"}
    )
    monkeypatch.setattr(guarded, "require_free_port", lambda _: None)
    before_env = dict(os.environ)
    before_bytes, before_stat = path.read_bytes(), path.stat()
    monkeypatch.setattr(Path, "mkdir", lambda *_a, **_k: pytest.fail("mkdir"))
    monkeypatch.setattr(Path, "chmod", lambda *_a, **_k: pytest.fail("chmod"))
    monkeypatch.setattr(guarded, "private_json", lambda *_: pytest.fail("write"))
    assert (
        board.main(
            arguments(
                "--event-links-file",
                str(path),
                "--event-links-sha256",
                digest,
            )
        )
        == 0
    )
    assert dict(os.environ) == before_env
    assert path.read_bytes() == before_bytes
    assert path.stat().st_ino == before_stat.st_ino
    assert path.stat().st_mode == before_stat.st_mode
    assert not (tmp_path / "absent").exists()


def test_release_sources_reads_exact_retained_ids_and_urls(tmp_path: Path) -> None:
    board = rollout()
    record = {
        "event_id": "00000000-0000-0000-0000-000000000001",
        "identity_key": "fixture",
        "prompt": "A retained event",
        "year_index": 100,
        "category_ids": ["exploration"],
        "region_ids": [],
        "explanation": "Retained provenance",
        "sources": [
            {
                "source_id": "onthisday",
                "record_id": "retained",
                "url": "https://en.wikipedia.org/wiki/January_1",
                "rights_basis": "CC BY-SA 4.0",
                "raw_date": "100",
                "calendar": "gregorian",
                "acquired_at": "2026-10-14T00:00:00Z",
                "snapshot_id": "fixture",
                "date_resolution": "year",
            }
        ],
        "date_precision": "year",
        "review_status": "approved",
        "media_asset_id": None,
        "fallback_key": "exploration",
    }
    (tmp_path / "events.jsonl").write_text(json.dumps(record) + "\n")
    assert board.release_sources(tmp_path) == {
        UUID("00000000-0000-0000-0000-000000000001"): {
            "https://en.wikipedia.org/wiki/January_1"
        }
    }
