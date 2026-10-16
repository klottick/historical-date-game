"""Pure runtime installation boundaries, using genuine small verified snapshots."""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.content.publish import canonical
from app.content.runtime import VerifiedRuntime, verify_runtime
from app.content.runtime_export import export_runtime
from tests.content.test_runtime import prepared, sha


def runtime_snapshot(
    tmp_path: Path, *, release_id: str | None = None, created_at: datetime | None = None
) -> tuple[Path, VerifiedRuntime]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    audit, root, lock = prepared(tmp_path)
    name = release_id or "runtime-" + uuid4().hex
    lock = lock.model_copy(
        update={"release_id": name, "created_at": created_at or lock.created_at}
    )
    export_runtime(audit, audit / "media", root, lock)
    release = root / "releases" / name
    data = (release / "runtime-manifest.json").read_bytes()
    (root / "default.json").write_bytes(
        canonical({"release_id": name, "manifest_sha256": sha(data)})
    )
    return root, verify_runtime(release, root / "media" / name)


class NoDatabase:
    def __getattr__(self, name: str) -> Any:
        pytest.fail("Database accessed before verification/provisioning: " + name)


@pytest.mark.parametrize("damage", ["missing", "payload", "asset", "beta"])
def test_runtime_install_rejects_before_database_access(
    tmp_path: Path, damage: str
) -> None:
    from app.game.runtime_catalog import install_runtime

    root, snapshot = runtime_snapshot(tmp_path)
    if damage == "missing":
        root = tmp_path / "missing-package"
    elif damage == "payload":
        (root / "releases" / snapshot.manifest.release_id / "events.jsonl").write_bytes(
            b"corrupt\n"
        )
    elif damage == "asset":
        (
            root / "media" / snapshot.manifest.release_id / next(iter(snapshot.assets))
        ).write_bytes(b"corrupt")
    expected = {
        "missing": "unreadable_artifact:default.json",
        "payload": "artifact_integrity_or_total_size",
        "asset": "artifact_integrity_or_total_size",
        "beta": "beta",
    }
    with pytest.raises(ValueError, match=expected[damage]):
        install_runtime(
            NoDatabase(), root, initialize_only=True, media_root=tmp_path / "external"
        )
    assert not (tmp_path / "external").exists()


def test_provisions_real_checked_assets_create_only(tmp_path: Path) -> None:
    from app.game.runtime_catalog import provision_assets

    root, snapshot = runtime_snapshot(tmp_path)
    # Once checked, consumption must not reopen source paths.
    source = root / "media" / snapshot.manifest.release_id
    for path in source.iterdir():
        path.unlink()
    target = tmp_path / "external/media"
    provision_assets(snapshot, target)
    destination = target / snapshot.manifest.release_id
    before = {}
    for name, data in snapshot.assets.items():
        path = destination / name
        assert path.read_bytes() == data and not path.is_symlink()
        before[name] = path.stat().st_ino
    provision_assets(snapshot, target)
    assert {p.name: p.stat().st_ino for p in destination.iterdir()} == before


@pytest.mark.parametrize("conflict", ["bytes", "symlink", "hardlink", "parent"])
def test_asset_conflicts_fail_without_overwriting(
    tmp_path: Path, conflict: str
) -> None:
    from app.game.runtime_catalog import provision_assets

    _, snapshot = runtime_snapshot(tmp_path)
    target = tmp_path / "external/media"
    destination = target / snapshot.manifest.release_id
    destination.mkdir(parents=True)
    name, data = next(iter(snapshot.assets.items()))
    other = tmp_path / "retained"
    other.write_bytes(data if conflict != "bytes" else b"retained wrong bytes")
    asset = destination / name
    if conflict == "bytes":
        asset.write_bytes(other.read_bytes())
    elif conflict == "symlink":
        asset.symlink_to(other)
    elif conflict == "hardlink":
        os.link(other, asset)
    else:
        destination.rmdir()
        destination.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        provision_assets(snapshot, target)
    assert other.read_bytes() == (
        data if conflict != "bytes" else b"retained wrong bytes"
    )
    if conflict == "bytes":
        assert asset.read_bytes() == b"retained wrong bytes"


def test_packaged_data_default_is_absolute_and_explicit_override_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.core.config import Settings

    monkeypatch.delenv("GAME_DATA_DIR", raising=False)
    required = {
        "PROJECT_NAME": "test",
        "POSTGRES_SERVER": "unused",
        "POSTGRES_USER": "test",
        "FIRST_SUPERUSER": "test@example.com",
        "FIRST_SUPERUSER_PASSWORD": "test-password",
    }
    config = Settings(_env_file=None, **required)
    assert config.GAME_DATA_DIR == Path(__file__).resolve().parents[2] / "catalogue"
    assert config.GAME_DATA_DIR.is_absolute()
    monkeypatch.setenv("GAME_DATA_DIR", str(tmp_path / "retained"))
    assert Settings(_env_file=None, **required).GAME_DATA_DIR == tmp_path / "retained"


@pytest.mark.parametrize("fail_at", [None, "migration", "accounts"])
def test_prestart_initializes_only_after_successful_migration_and_accounts(
    tmp_path: Path, fail_at: str | None
) -> None:
    backend = Path(__file__).resolve().parents[2]
    commands = tmp_path / "bin"
    commands.mkdir()
    log = tmp_path / "commands.jsonl"
    # Executable stand-ins keep this test completely offline and non-destructive.
    for name in ("python", "alembic"):
        executable = commands / name
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "with open(os.environ['COMMAND_LOG'], 'a') as f: "
            "f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "step = 'migration' if sys.argv[0].endswith('alembic') else "
            "'accounts' if sys.argv[1:] == ['app/initial_data.py'] else ''\n"
            "sys.exit(9 if step == os.environ.get('FAIL_AT') else 0)\n"
        )
        executable.chmod(0o755)
    result = subprocess.run(
        ["bash", str(backend / "scripts/prestart.sh")],
        cwd=backend,
        env={
            **os.environ,
            "PATH": f"{commands}:{os.environ['PATH']}",
            "COMMAND_LOG": str(log),
            "FAIL_AT": fail_at or "never",
        },
        capture_output=True,
        text=True,
    )
    expected = [["app/backend_pre_start.py"], ["upgrade", "head"]]
    if fail_at != "migration":
        expected.append(["app/initial_data.py"])
    if fail_at is None:
        expected.append(["-m", "app.game.runtime_catalog", "initialize"])
    assert [json.loads(line) for line in log.read_text().splitlines()] == expected
    assert result.returncode == (0 if fail_at is None else 9)


def test_docker_copies_only_runtime_catalogue() -> None:
    # Build-context contract; Task 4/5 exercise the actual image with the real tree.
    dockerfile = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text()
    assert "COPY ./catalogue /app/catalogue" in dockerfile
    assert "COPY ./data" not in dockerfile


def test_runtime_cli_missing_package_does_not_connect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.core.db import engine
    from app.game.runtime_catalog import main

    def forbidden_connect(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("Missing package must fail before connecting")

    monkeypatch.setattr(engine, "connect", forbidden_connect)
    assert main(["initialize", "--catalogue", str(tmp_path / "missing")]) == 1
    assert "unreadable_artifact:default.json" in capsys.readouterr().err


def test_audit_activation_does_not_accept_runtime_format(tmp_path: Path) -> None:
    from app.game.catalog_repository import CatalogError, activate_catalog

    root, snapshot = runtime_snapshot(tmp_path)
    name = snapshot.manifest.release_id
    with pytest.raises(CatalogError, match="catalog_verification_failed"):
        activate_catalog(
            NoDatabase(),
            root / "releases" / name,
            root / "media" / name,
            require_beta=False,
        )
