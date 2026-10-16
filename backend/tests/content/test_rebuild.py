"""Actual importer/media/publisher replay of synthetic upstream pins; no DB."""

import importlib
import importlib.util
import json
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.content.adapters.selected import SelectedSourceAdapter
from app.content.publish import canonical
from app.content.runtime import REQUIRED_FILES, sha256
from app.content.runtime_models import LockedSource
from tests.content.test_importer import snapshot
from tests.content.test_onthisday import fixture_snapshot, row
from tests.content.test_source_acquisition import lock_for, transport, tree_state


def rebuild() -> Any:
    assert importlib.util.find_spec("app.content.rebuild"), (
        "Missing full pipeline replay"
    )
    return importlib.import_module("app.content.rebuild")


def test_locked_context_resets() -> None:
    assert importlib.util.find_spec("app.content.build_context"), (
        "Missing evaluation context"
    )
    context = importlib.import_module("app.content.build_context")
    today = context.evaluation_date()
    with context.locked_evaluation(date(2000, 1, 1)):
        with pytest.raises(RuntimeError), context.locked_evaluation(date(1900, 1, 1)):
            assert context.evaluation_date() == date(1900, 1, 1)
            raise RuntimeError
        assert context.evaluation_date() == date(2000, 1, 1)
    assert context.evaluation_date() == today


def test_recipe_pins_shared_daily_acceptance_dependencies() -> None:
    fingerprints = rebuild().code_fingerprints()
    for name in ("daily_config.py", "rules.py", "types.py", "source-selection.json"):
        assert f"app/game/{name}" in fingerprints


def inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    module = rebuild()

    # >1000 actual accepted events: keep the production full beta verifier active.
    def name(number: int) -> str:
        return sha256(str(number).encode())[:40].translate(
            str.maketrans("0123456789", "ghijklmnop")
        )

    rows = [
        row(event=f"Inventor {name(n)} patents a mechanical calculator.")
        for n in range(1000)
    ]
    # This is a nonfixture beta replay, so its Daily subset must be playable.
    rows[0] = row(
        event=f"Inventor {name(0)} patents a mechanical calculator.",
        year=1799,
        date="1799-01-01",
    )
    rows += [row(event="Unclassified material remains accountable.")]
    rows += [
        row(
            event="Conflicted person patents a device.", year=year, date=f"{year}-01-01"
        )
        for year in (1800, 1801)
    ]
    _, root = fixture_snapshot(tmp_path, monkeypatch, rows)
    raws = list(SelectedSourceAdapter().fetch(snapshot(tmp_path)))
    raws += [
        type(raws[0])(raws[0].source_id, f"alias-{n}", raws[0].payload)
        for n in range(2)
    ]
    (root / "supplements.jsonl").write_bytes(
        b"".join(canonical(asdict(raw)) for raw in raws)
    )
    monkeypatch.setattr(module, "CHRONOLOGY_ROWS", len(rows))
    monkeypatch.setattr(module, "SUPPLEMENT_ROWS", len(raws))
    sources = tuple(
        LockedSource(
            path=p.name,
            sha256=sha256(p.read_bytes()),
            size=p.stat().st_size,
            url=None,
            role="supplements" if p.name == "supplements.jsonl" else "chronology",
        )
        for p in sorted(root.iterdir())
    )
    lock = lock_for().model_copy(
        update={
            "python": module.python_version(),
            "dependencies": module.dependency_versions(),
            "code_sha256": module.code_fingerprints(),
            "sources": sources,
        }
    )
    path = tmp_path / "recipe.json"
    path.write_bytes(canonical(lock.model_dump(mode="json")))
    return root, path


def test_whole_input_pipeline_reproduces_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = rebuild()
    root, path = inputs(tmp_path, monkeypatch)
    candidate = module.update_candidate(path, root, tmp_path / "candidate")
    assert candidate["matches"] is True
    sealed = tmp_path / "candidate/catalogue/releases/replay-v1/build.lock.json"
    expected = tmp_path / "candidate/catalogue"
    for name in ("first", "second"):
        result = module.reproduce(
            sealed, root, tmp_path / name, expected_catalogue=expected
        )
        assert result["matches"] is True and result["differing_files"] == []
        assert (
            result["added_event_ids"]
            == result["removed_event_ids"]
            == result["changed_event_ids"]
            == []
        )
        work = tmp_path / name / "workspace"
        pointer = json.loads((work / "current.json").read_bytes())
        generation = work / pointer["generation"]
        assert len((generation / "raw.jsonl").read_bytes().splitlines()) == 1008
        assert len((generation / "quarantine.jsonl").read_bytes().splitlines()) == 3
        assert (
            generation / "source-snapshots/onthisday/download-receipt.json"
        ).read_bytes() == (root / "download-receipt.json").read_bytes()
        assert not (tmp_path / name / "catalogue/default.json").exists()
    # Metadata bytes are NOT exempt from exact comparison. The same payloads
    # under a changed lock must produce a structured CLI failure.
    from app.content.rebuild_cli import main

    lock = module.load_lock(sealed)
    changed = lock.model_copy(
        update={"created_at": lock.created_at + timedelta(seconds=1)}
    )
    changed_path = tmp_path / "changed-lock.json"
    changed_path.write_bytes(canonical(changed.model_dump(mode="json")))
    assert (
        main(
            [
                "reproduce",
                "--lock",
                str(changed_path),
                "--sources",
                str(root),
                "--output",
                str(tmp_path / "metadata-mismatch"),
                "--expected",
                str(expected),
            ]
        )
        == 1
    )
    report = json.loads(capsys.readouterr().out)
    assert report["differing_files"] == ["build.lock.json", "runtime-manifest.json"]
    assert report["changed_event_ids"] == []
    assert path.read_bytes() != sealed.read_bytes()  # input recipe was not edited
    assert not (expected / "default.json").exists()


def test_compare_reports_record_and_file_differences() -> None:
    module = rebuild()
    expected = {
        "events.jsonl": canonical({"event_id": "same", "prompt": "old"})
        + canonical({"event_id": "removed"}),
        "build.lock.json": b"old",
        "runtime-manifest.json": b"old",
        "media/x.svg": b"old",
    }
    actual = {
        "events.jsonl": canonical({"event_id": "same", "prompt": "new"})
        + canonical({"event_id": "added"}),
        "build.lock.json": b"new",
        "runtime-manifest.json": b"new",
        "media/new.svg": b"new",
    }
    result = module.compare_payloads(expected, actual)
    assert result["added_event_ids"] == ["added"]
    assert result["removed_event_ids"] == ["removed"]
    assert result["changed_event_ids"] == ["same"]
    assert set(result["differing_files"]) == set(expected) | set(actual)
    assert result["matches"] is False


@pytest.mark.parametrize(
    "change",
    [
        "code",
        "context",
        "python",
        "dependencies",
        "empty-code",
        "empty-sources",
        "input",
    ],
)
def test_replay_rejects_changed_code_or_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    module = rebuild()
    root, path = inputs(tmp_path, monkeypatch)
    data = json.loads(path.read_bytes())
    data["payload_sha256"] = dict.fromkeys(
        REQUIRED_FILES - {"build.lock.json"}, "a" * 64
    )
    if change == "code":
        data["code_sha256"]["app/content/build_context.py"] = "0" * 64
    elif change == "context":
        data["code_sha256"].pop("app/content/build_context.py")
    elif change == "python":
        data["python"] = "0.0.0"
    elif change == "dependencies":
        data["dependencies"] = {}
    elif change == "empty-code":
        data["code_sha256"] = {}
    elif change == "empty-sources":
        data["sources"] = []
    else:
        (root / "events.jsonl").write_bytes(b"changed")
    path.write_bytes(canonical(data))
    expected_error = {
        "code": "locked_code",
        "context": "locked_code",
        "python": "locked_python",
        "dependencies": "locked_dependencies",
        "empty-code": "locked_code",
        "empty-sources": "locked_source",
        "input": "artifact_size|source_size|source_digest",
    }[change]
    with pytest.raises(ValueError, match=expected_error):
        module.reproduce(path, root, tmp_path / "rejected", expected_catalogue=None)
    assert not (tmp_path / "rejected/workspace").exists()


def test_context_changes_rule_fingerprints_and_date_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rebuild()
    from app.content.adapters.router import rules_digest
    from app.content.build_context import locked_evaluation
    from app.content.media.pipeline import media_rules_digest
    from app.content.schemas import EventRecord

    adapter, root = fixture_snapshot(tmp_path, monkeypatch, [row()])
    raw = list(adapter.fetch(root))[0]
    with locked_evaluation(date(1800, 1, 1)):
        assert isinstance(adapter.normalize(raw), EventRecord)
        fingerprints = (rules_digest(), media_rules_digest())
    with locked_evaluation(date(1799, 12, 31)):
        assert not isinstance(adapter.normalize(raw), EventRecord)
        assert fingerprints[0] != rules_digest()
        assert fingerprints[1] != media_rules_digest()


def test_replay_rejects_symlink_source_root_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = rebuild()
    root, path = inputs(tmp_path, monkeypatch)
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    (root / "events.jsonl").write_bytes(b"broken")
    with pytest.raises(ValueError, match="symlink_path"):
        module.update_candidate(path, alias, tmp_path / "out")


@pytest.mark.parametrize(
    "attack",
    [
        "count",
        "accepted-row",
        "extra-field",
        "missing-evidence",
        "duplicate-key",
        "source-type",
        "milestone-type",
        "evidence-fields",
        "evidence-time",
    ],
)
def test_source_only_scope_is_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack: str
) -> None:
    module = rebuild()
    root, _ = inputs(tmp_path, monkeypatch)
    path = root / "supplements.jsonl"
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    if attack == "count":
        rows.pop()
    elif attack == "accepted-row":
        rows[0] = {"event_id": "not-raw", "year_index": 1800}
    elif attack == "extra-field":
        rows[0]["payload"]["review_status"] = "approved"
    elif attack == "missing-evidence":
        rows[0]["payload"]["evidence"] = []
    elif attack == "source-type":
        rows[0]["source_id"] = []
    elif attack == "milestone-type":
        rows[0]["payload"]["milestone"] = []
    elif attack == "evidence-fields":
        rows[0]["payload"]["evidence"][0] = {"not": "evidence"}
    elif attack == "evidence-time":
        rows[0]["payload"]["evidence"][0]["acquired_at"] = "not-a-time"
    else:
        rows[1] = rows[0]
    path.write_bytes(b"".join(canonical(row) for row in rows))
    with pytest.raises(ValueError):
        module._supplements(root)


def test_cli_acquire_failure_is_structured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rebuild()
    from app.content.rebuild_cli import main

    _, path = inputs(tmp_path, monkeypatch)
    assert (
        main(["acquire", "--lock", str(path), "--output", str(tmp_path / "out")]) == 1
    )
    error = json.loads(capsys.readouterr().err)
    assert "source_dir" in error["error"]


def test_replay_outputs_must_be_ignored_and_create_only(tmp_path: Path) -> None:
    from app.content.source_acquisition import REPOSITORY_ROOT, safe_output

    with pytest.raises(ValueError, match="ignored"):
        safe_output(REPOSITORY_ROOT / "backend/new-build-output")
    with pytest.raises(ValueError, match="exists"):
        safe_output(tmp_path)
    assert (
        safe_output(REPOSITORY_ROOT / "data/catalogue-build/new-output").name
        == "new-output"
    )


@pytest.mark.parametrize("protected", ["source", "expected"])
def test_replay_canonical_containment_precedes_all_mutations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, protected: str
) -> None:
    module = rebuild()
    root, path = inputs(tmp_path, monkeypatch)
    data = json.loads(path.read_bytes())
    data["payload_sha256"] = dict.fromkeys(
        REQUIRED_FILES - {"build.lock.json"}, "a" * 64
    )
    path.write_bytes(canonical(data))
    expected = tmp_path / "expected"
    expected.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    target = root if protected == "source" else expected
    spelling = other / ".." / target.name / "new-run"
    calls = []
    transport(monkeypatch, lambda request: calls.append(request))
    before = tree_state(tmp_path)
    error = (
        "output_inside_source_dir"
        if protected == "source"
        else "output_inside_expected_catalogue"
    )
    with pytest.raises(ValueError, match=error):
        module.reproduce(
            path,
            root,
            spelling,
            expected_catalogue=expected if protected == "expected" else None,
        )
    assert calls == []
    assert tree_state(tmp_path) == before


@pytest.mark.parametrize(
    "change,error",
    [
        ("python", "locked_python"),
        ("code", "locked_code"),
        ("empty-code", "locked_code"),
        ("dependencies", "locked_dependencies"),
        ("sources", "locked_source"),
    ],
)
def test_cli_acquire_validates_recipe_before_transport_or_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    change: str,
    error: str,
) -> None:
    import httpx

    from app.content.rebuild_cli import main

    root, path = inputs(tmp_path, monkeypatch)
    data = json.loads(path.read_bytes())
    for source in data["sources"]:
        source["url"] = (
            "https://raw.githubusercontent.com/org/repo/pin/" + source["path"]
        )
    if change == "python":
        data["python"] = "0.0.0"
    elif change == "code":
        data["code_sha256"]["app/content/build_context.py"] = "0" * 64
    elif change == "empty-code":
        data["code_sha256"] = {}
    elif change == "dependencies":
        data["dependencies"] = {}
    else:
        data["sources"] = data["sources"][:1]
    path.write_bytes(canonical(data))
    bodies = {p.name: p.read_bytes() for p in root.iterdir()}
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=bodies[request.url.path.rsplit("/", 1)[-1]])

    transport(monkeypatch, handler)
    before = tree_state(tmp_path)
    status = main(["acquire", "--lock", str(path), "--output", str(tmp_path / "out")])
    assert calls == []
    assert tree_state(tmp_path) == before
    assert status == 1
    assert error in json.loads(capsys.readouterr().err)["error"]


def test_cli_acquire_accepts_new_recipe_without_payload_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.content.rebuild_cli import main

    root, path = inputs(tmp_path, monkeypatch)
    before = tree_state(root)
    calls = []
    transport(monkeypatch, lambda request: calls.append(request))
    output = tmp_path / "checked-inputs"
    assert (
        main(
            [
                "acquire",
                "--lock",
                str(path),
                "--output",
                str(output),
                "--source-dir",
                str(root),
            ]
        )
        == 0
    )
    assert calls == []
    assert tree_state(root) == before
    assert json.loads(capsys.readouterr().out)["sources"] == str(output)
    assert {p.name: p.read_bytes() for p in output.iterdir()} == {
        p.name: p.read_bytes() for p in root.iterdir()
    }
