import hashlib
from pathlib import Path

import pytest

from app.core.config import settings
from tests.utils.browser_catalog import copy_assets, prepare


@pytest.mark.parametrize("database", ["historical_date_game", "other_test"])
def test_browser_catalog_refuses_unapproved_database_before_files_or_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, database: str
) -> None:
    monkeypatch.setattr(settings, "POSTGRES_DB", database)
    target = tmp_path / "game"
    with pytest.raises(RuntimeError, match="historical_date_game_test"):
        prepare(target)
    assert not target.exists()


def test_browser_assets_copy_exact_bytes_and_are_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"verified original asset"
    name = hashlib.sha256(data).hexdigest() + ".svg"
    (source / name).write_bytes(data)
    target = tmp_path / "mounted"
    assert copy_assets(source, target) == 1
    assert copy_assets(source, target) == 1
    assert (target / name).read_bytes() == data


def test_browser_assets_never_overwrite_different_frozen_bytes(tmp_path: Path) -> None:
    source, target = tmp_path / "source", tmp_path / "mounted"
    source.mkdir()
    target.mkdir()
    data = b"original asset"
    name = hashlib.sha256(data).hexdigest() + ".svg"
    (source / name).write_bytes(data)
    (target / name).write_bytes(b"existing different bytes")
    with pytest.raises(ValueError, match="immutable_asset_conflict"):
        copy_assets(source, target)
    assert (target / name).read_bytes() == b"existing different bytes"


def test_browser_assets_refuse_symlink_mount(tmp_path: Path) -> None:
    source, outside = tmp_path / "source", tmp_path / "outside"
    source.mkdir()
    outside.mkdir()
    target = tmp_path / "mounted"
    target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        copy_assets(source, target)
    assert list(outside.iterdir()) == []
