"""Pure boundary checks: never initialize or clean a database."""

import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.core.config import settings
from tests.browser import real_catalog_probe as probe


@pytest.mark.parametrize(
    ("database", "host", "environment"),
    [
        ("historical_date_game_test", "127.0.0.1", "local"),
        ("production", "localhost", "local"),
        ("historical_date_game_catalog_test", "remote.example", "local"),
        ("historical_date_game_catalog_test", "localhost", "production"),
    ],
)
def test_probe_rejects_nonisolated_target_before_db(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    database: str,
    host: str,
    environment: str,
) -> None:
    monkeypatch.setattr(settings, "POSTGRES_DB", database)
    monkeypatch.setattr(settings, "POSTGRES_SERVER", host)
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    session, verify, activate, exercise = (Mock() for _ in range(4))
    monkeypatch.setattr(probe, "Session", session)
    monkeypatch.setattr(probe, "verify_release", verify)
    monkeypatch.setattr(probe, "activate_catalog", activate)
    monkeypatch.setattr(probe, "_exercise_services", exercise)
    with pytest.raises(RuntimeError):
        probe.run_probe(tmp_path, tmp_path, tmp_path / "report.json")
    for boundary in (session, verify, activate, exercise):
        boundary.assert_not_called()


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_probe_accepts_isolated_local_target(host: str) -> None:
    probe.require_local_probe_target("historical_date_game_catalog_test", host, "local")


def local_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "POSTGRES_DB", "historical_date_game_catalog_test")
    monkeypatch.setattr(settings, "POSTGRES_SERVER", "127.0.0.1")
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")


def test_probe_rejects_invalid_release_before_activation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    local_target(monkeypatch)
    session, activate = Mock(), Mock()
    monkeypatch.setattr(probe, "Session", session)
    monkeypatch.setattr(probe, "activate_catalog", activate)
    monkeypatch.setattr(
        probe, "verify_release", Mock(side_effect=ValueError("invalid"))
    )
    with pytest.raises(ValueError, match="invalid"):
        probe.run_probe(
            tmp_path / "release", tmp_path / "media", tmp_path / "report.json"
        )
    session.assert_not_called()
    activate.assert_not_called()
    assert not (tmp_path / "report.json").exists()


def test_probe_failure_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "report.json"
    report.write_text('{"passed": true}')
    monkeypatch.setattr(
        probe,
        "run_probe",
        Mock(side_effect=RuntimeError("password=secret pending_year=1234")),
    )
    assert (
        probe.main(
            [
                "--release",
                str(tmp_path / "release"),
                "--media",
                str(tmp_path / "media"),
                "--report",
                str(report),
            ]
        )
        == 1
    )
    assert json.loads(report.read_text()) == {"passed": False, "error": "probe_failed"}
    assert "secret" not in capsys.readouterr().err


def test_probe_report_has_no_credentials_or_future_answers(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    probe._write_report(
        report,
        {
            "passed": True,
            "release_id": "real-catalog",
            "event_count": 1276,
            "checks": {"pending_privacy": True},
            "password": "secret",
            "seed": "private-seed",
            "order": ["unused-event"],
            "pending_year": 1234,
            "answers": {"event": 1234},
            "database_uri": "postgresql://secret",
        },
    )
    assert json.loads(report.read_text()) == {
        "passed": True,
        "release_id": "real-catalog",
        "event_count": 1276,
        "checks": {"pending_privacy": True},
    }
    assert report.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("root_name", ["release", "media"])
def test_probe_cannot_overwrite_release_or_public_media(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, root_name: str
) -> None:
    local_target(monkeypatch)
    release, media = tmp_path / "release", tmp_path / "media"
    release.mkdir()
    media.mkdir()
    report = tmp_path / root_name / "manifest.json"
    report.write_text("immutable bytes")
    session, verify = Mock(), Mock()
    monkeypatch.setattr(probe, "Session", session)
    monkeypatch.setattr(probe, "verify_release", verify)
    assert (
        probe.main(
            ["--release", str(release), "--media", str(media), "--report", str(report)]
        )
        == 1
    )
    assert report.read_text() == "immutable bytes"
    session.assert_not_called()
    verify.assert_not_called()


def test_probe_refuses_disabled_runtime_assertions() -> None:
    code = """
from tests.browser.real_catalog_probe import require_local_probe_target
try:
    require_local_probe_target('historical_date_game_catalog_test', '127.0.0.1', 'local')
except RuntimeError:
    pass
else:
    raise SystemExit(1)
"""
    result = subprocess.run([sys.executable, "-O", "-c", code], capture_output=True)
    assert result.returncode == 0


def test_probe_daily_day_avoids_suite_dates_and_used_days() -> None:
    assert probe._unused_probe_day(set()) == datetime(2300, 1, 1, 12, tzinfo=UTC)
    # An occupied successor also disqualifies a candidate; do not reset any day.
    assert probe._unused_probe_day({date(2300, 1, 2), date(2300, 1, 3)}) == datetime(
        2300, 1, 5, 12, tzinfo=UTC
    )
