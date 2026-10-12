"""Synthetic provider envelopes only; transport is the sole network double."""

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.content.adapters.selected import SelectedSourceAdapter
from app.content.importer import import_snapshot
from app.content.schemas import EventRecord, ValidationReceipt
from app.content.validation import candidate_digest

FIXTURE = Path(__file__).parents[1] / "fixtures/content/source-snapshot.json"


def snapshot(tmp_path: Path, data: dict[str, Any] | None = None) -> Path:
    data = copy.deepcopy(data or json.loads(FIXTURE.read_text()))
    root = tmp_path / "snapshot"
    root.mkdir(exist_ok=True)
    requests = []
    for source, body in (
        ("wikidata", {"entities": {data["entity"]["id"]: data["entity"]}}),
        ("wikipedia_en", {"query": {"pages": [data["page"]]}}),
    ):
        raw = json.dumps(body).encode()
        name = f"{source}.json"
        (root / name).write_bytes(raw)
        params = (
            {
                "action": "query",
                "prop": "revisions",
                "revids": "101",
                "rvprop": "ids|content",
                "rvslots": "main",
            }
            if source == "wikidata"
            else {
                "action": "query",
                "prop": "revisions|pageprops",
                "revids": "202",
                "rvprop": "ids|content",
                "rvslots": "main",
            }
        )
        requests.append(
            {
                "source_id": source,
                "file": name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "params": params,
                "acquired_at": "2026-10-12T00:00:00Z",
            }
        )
    (root / "snapshot.json").write_text(
        json.dumps(
            {
                "snapshot_id": data["snapshot_id"],
                "requests": requests,
                "records": data["records"],
            }
        )
    )
    return root


def active(workspace: Path, filename: str) -> list[dict[str, Any]]:
    pointer = json.loads((workspace / "current.json").read_text())
    path = workspace / pointer["generation"] / filename
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_reimport_and_aliases_are_idempotent(tmp_path: Path) -> None:
    root = snapshot(tmp_path)
    workspace = tmp_path / "work"
    first = import_snapshot(SelectedSourceAdapter(), root, workspace)
    events = active(workspace, "candidates.jsonl")
    second = import_snapshot(SelectedSourceAdapter(), root, workspace)
    assert (first.imported, first.quarantined, first.duplicates) == (2, 0, 1)
    assert second.imported == 0
    assert active(workspace, "candidates.jsonl") == events
    assert len(events[0]["sources"]) == 2
    receipts = active(workspace, "receipts.jsonl")
    assert all(
        r["passed"] and r["stage"] == "content" and r["media_catalog_sha256"] is None
        for r in receipts
    )


def test_birth_and_death_remain_distinct(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path), workspace)
    events = active(workspace, "candidates.jsonl")
    assert {e["identity_key"] for e in events} == {
        "wikidata:Q900001:birth",
        "wikidata:Q900001:death",
    }
    assert {e["year_index"] for e in events} == {1800, 1870}
    assert len({e["event_id"] for e in events}) == 2
    assert {e["prompt"] for e in events} == {
        "Synthetic Ada is born",
        "Synthetic Ada dies",
    }


@pytest.mark.parametrize(
    "change,code",
    [
        ("year", "conflicting_dates"),
        ("circa", "unsupported_qualifiers"),
        ("range", "uncertain_date"),
        ("julian", "unresolved_calendar"),
        ("precision", "unsupported_precision"),
    ],
)
def test_date_conflicts_quarantined(tmp_path: Path, change: str, code: str) -> None:
    data = json.loads(FIXTURE.read_text())
    data["records"] = data["records"][:1]
    claim = data["entity"]["claims"]["P569"][0]
    value = claim["mainsnak"]["datavalue"]["value"]
    if change == "year":
        other = copy.deepcopy(claim)
        other["id"] += "-conflict"
        other["mainsnak"]["datavalue"]["value"]["time"] = "+00000001801-00-00T00:00:00Z"
        data["entity"]["claims"]["P569"].append(other)
    elif change == "circa":
        claim["qualifiers"] = {
            "P1480": [
                {
                    "snaktype": "value",
                    "datavalue": {
                        "value": {"id": "Q5727902"},
                        "type": "wikibase-entityid",
                    },
                }
            ]
        }
    elif change == "range":
        value["before"] = 1
    elif change == "julian":
        value["calendarmodel"] = "http://www.wikidata.org/entity/Q1985786"
    else:
        value["precision"] = 8
    work = tmp_path / "work"
    report = import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), work)
    assert (report.imported, report.quarantined) == (0, 1)
    assert code in active(work, "quarantine.jsonl")[0]["issue_codes"]
    assert not active(work, "receipts.jsonl")[0]["passed"]
    assert active(work, "candidates.jsonl") == []


def test_update_invalidates_receipt_and_keeps_identity(tmp_path: Path) -> None:
    work = tmp_path / "work"
    root = snapshot(tmp_path)
    import_snapshot(SelectedSourceAdapter(), root, work)
    before = active(work, "candidates.jsonl")
    receipt = active(work, "receipts.jsonl")
    data = json.loads(FIXTURE.read_text())
    data["entity"]["labels"]["en"]["value"] = "Synthetic Ada Revised"
    data["page"]["title"] = "Synthetic Ada Revised"
    import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), work)
    after = active(work, "candidates.jsonl")
    assert {e["event_id"] for e in before} == {e["event_id"] for e in after}
    assert receipt != active(work, "receipts.jsonl")
    for event_data, receipt_data in zip(
        after, active(work, "receipts.jsonl"), strict=True
    ):
        event = EventRecord.model_validate_json(json.dumps(event_data))
        current = ValidationReceipt.model_validate_json(json.dumps(receipt_data))
        assert current.candidate_sha256 == candidate_digest(event)


def test_changed_date_failure_removes_old_pass(tmp_path: Path) -> None:
    work = tmp_path / "work"
    import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path), work)
    data = json.loads(FIXTURE.read_text())
    data["entity"]["claims"]["P569"][0]["mainsnak"]["datavalue"]["value"]["before"] = 1
    import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), work)
    assert len(active(work, "candidates.jsonl")) == 1
    assert all(
        e["identity_key"].endswith(":death") for e in active(work, "candidates.jsonl")
    )
    assert any(not r["passed"] for r in active(work, "receipts.jsonl"))


@pytest.mark.parametrize("magnitude,want", [(1, 0), (490, -489)])
def test_bce_magnitude_raw_encoding_is_retained(
    tmp_path: Path, magnitude: int, want: int
) -> None:
    data = json.loads(FIXTURE.read_text())
    data["records"] = data["records"][:1]
    value = data["entity"]["claims"]["P569"][0]["mainsnak"]["datavalue"]["value"]
    value["time"] = f"-{magnitude:011d}-00-00T00:00:00Z"
    data["page"]["revisions"][0]["slots"]["main"]["content"] = (
        f"{{{{Infobox person\n| birth_date = {magnitude} BCE\n}}}}"
    )
    # Avoid the deliberately conservative C2 small-number prompt leak check.
    data["entity"]["labels"]["en"]["value"] = "Synthetic Ada"
    work = tmp_path / "work"
    import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), work)
    event = active(work, "candidates.jsonl")[0]
    assert event["year_index"] == want
    assert event["sources"][0]["raw_date"] == value["time"]
    assert (
        event["sources"][0]["date_resolution"]
        == f"source-resolved:proleptic-gregorian:year_index={want}"
    )


def test_fetch_retry_cache_and_pinned_requests(tmp_path: Path) -> None:
    root = snapshot(tmp_path)
    responses = {
        name: (root / name).read_bytes()
        for name in ("wikidata.json", "wikipedia_en.json")
    }
    for name in responses:
        (root / name).unlink()
    requests: list[httpx.Request] = []
    waits: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.params["maxlag"] == "5"
        assert "HistoricalDateGame" in request.headers["User-Agent"]
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        name = (
            "wikidata.json"
            if request.url.host == "www.wikidata.org"
            else "wikipedia_en.json"
        )
        return httpx.Response(200, content=responses[name])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = SelectedSourceAdapter(client=client, sleep=waits.append)
        assert len(list(adapter.fetch(root))) == 3
        assert len(list(adapter.fetch(root))) == 3
    assert len(requests) == 3
    assert max(waits) >= 7
    assert requests[-1].url.params["revids"] == "202"
    assert requests[1].url.params["revids"] == "101"


def test_fetch_digest_tamper_fails_closed(tmp_path: Path) -> None:
    root = snapshot(tmp_path)
    (root / "wikidata.json").write_text("{}")
    with pytest.raises(ValueError, match="digest"):
        list(SelectedSourceAdapter().fetch(root))


def test_fetch_maxlag_and_retry_exhaustion(tmp_path: Path) -> None:
    root = snapshot(tmp_path)
    (root / "wikidata.json").unlink()
    waits: list[float] = []
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"error": {"code": "maxlag", "lag": 8}})
        )
    ) as client:
        with pytest.raises(RuntimeError, match="retry"):
            list(SelectedSourceAdapter(client=client, sleep=waits.append).fetch(root))
    assert max(waits) >= 8
    assert not (root / "wikidata.json").exists()


def test_real_wikidata_revision_slot_and_wikipedia_template(tmp_path: Path) -> None:
    data = json.loads(FIXTURE.read_text())
    data["page"]["revisions"][0]["slots"]["main"]["content"] = (
        "{{Infobox person\n| birth_date = {{birth date|1800|1|2}}\n| death_date = 1870\n}}"
    )
    root = snapshot(tmp_path, data)
    body = json.dumps(
        {
            "query": {
                "pages": [
                    {
                        "pageid": 900001,
                        "title": "Q900001",
                        "revisions": [
                            {
                                "revid": 101,
                                "slots": {
                                    "main": {
                                        "contentmodel": "wikibase-item",
                                        "content": json.dumps(data["entity"]),
                                    }
                                },
                            }
                        ],
                    }
                ]
            }
        }
    ).encode()
    (root / "wikidata.json").write_bytes(body)
    manifest = json.loads((root / "snapshot.json").read_text())
    manifest["requests"][0]["sha256"] = hashlib.sha256(body).hexdigest()
    (root / "snapshot.json").write_text(json.dumps(manifest))
    work = tmp_path / "work"
    assert import_snapshot(SelectedSourceAdapter(), root, work).imported == 2
    assert active(work, "candidates.jsonl")[0]["year_index"] == 1800


def test_suspected_fuzzy_aliases_quarantine_both_facts(tmp_path: Path) -> None:
    data = json.loads(FIXTURE.read_text())
    data["records"] = data["records"][:1]
    work = tmp_path / "work"
    assert (
        import_snapshot(
            SelectedSourceAdapter(), snapshot(tmp_path, data), work
        ).imported
        == 1
    )
    other = copy.deepcopy(data)
    other["entity"]["id"] = "Q900002"
    other["page"]["pageprops"]["wikibase_item"] = "Q900002"
    other["page"]["pageid"] = 900002
    other["records"][0]["entity_id"] = "Q900002"
    other["records"][0]["record_id"] = "second-entity"
    other["entity"]["labels"]["en"]["value"] = "Synthetic Adá"
    report = import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, other), work)
    assert report.quarantined == 2
    assert active(work, "candidates.jsonl") == []
    assert all(
        "suspected_duplicate" in r["issue_codes"]
        for r in active(work, "quarantine.jsonl")
    )


def test_source_year_conflict_across_persistent_batches(tmp_path: Path) -> None:
    data = json.loads(FIXTURE.read_text())
    data["records"] = data["records"][:1]
    work = tmp_path / "work"
    import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), work)
    data["records"][0]["record_id"] = "conflicting-alias"
    data["entity"]["claims"]["P569"][0]["mainsnak"]["datavalue"]["value"]["time"] = (
        "+00000001801-00-00T00:00:00Z"
    )
    data["page"]["revisions"][0]["slots"]["main"]["content"] = (
        "{{Infobox person\n| birth_date = 1801\n}}"
    )
    report = import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), work)
    assert report.quarantined == 2
    assert active(work, "candidates.jsonl") == []
    assert "conflicting_dates" in active(work, "quarantine.jsonl")[0]["issue_codes"]


def test_answer_leaking_source_label_is_not_erased(tmp_path: Path) -> None:
    data = json.loads(FIXTURE.read_text())
    data["entity"]["labels"]["en"]["value"] = "Synthetic Ada 1800"
    data["records"] = data["records"][:1]
    work = tmp_path / "work"
    report = import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), work)
    assert report.quarantined == 1
    quarantine = active(work, "quarantine.jsonl")[0]
    assert "answer_in_prompt" in quarantine["issue_codes"]
    assert quarantine["candidate"]["prompt"] == "Synthetic Ada 1800 is born"


def test_crash_before_pointer_commit_keeps_old_generation_and_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = json.loads(FIXTURE.read_text())
    work = tmp_path / "work"
    root = snapshot(tmp_path, data)
    import_snapshot(SelectedSourceAdapter(), root, work)
    old_pointer = (work / "current.json").read_bytes()
    old_candidates = active(work, "candidates.jsonl")
    data["entity"]["labels"]["en"]["value"] = "Revised Synthetic Ada"
    root = snapshot(tmp_path, data)
    original = Path.replace

    def crash(path: Path, target: Path) -> Path:
        if path.name == "current.json.tmp":
            raise OSError("synthetic commit crash")
        return original(path, target)

    with monkeypatch.context() as context:
        context.setattr(Path, "replace", crash)
        with pytest.raises(OSError, match="commit crash"):
            import_snapshot(SelectedSourceAdapter(), root, work)
    assert (work / "current.json").read_bytes() == old_pointer
    assert active(work, "candidates.jsonl") == old_candidates
    assert import_snapshot(SelectedSourceAdapter(), root, work).imported == 2
    assert {e["event_id"] for e in active(work, "candidates.jsonl")} == {
        e["event_id"] for e in old_candidates
    }


def test_wikipedia_calendar_annotation_is_not_guessed(tmp_path: Path) -> None:
    data = json.loads(FIXTURE.read_text())
    data["records"] = data["records"][:1]
    data["page"]["revisions"][0]["slots"]["main"]["content"] = (
        "{{Infobox person\n| birth_date = 1800 (Old Style)\n}}"
    )
    work = tmp_path / "work"
    assert (
        import_snapshot(
            SelectedSourceAdapter(), snapshot(tmp_path, data), work
        ).quarantined
        == 1
    )


def test_revision_slot_mismatch_never_gets_cached(tmp_path: Path) -> None:
    root = snapshot(tmp_path)
    (root / "wikidata.json").unlink()
    wrong = {
        "query": {
            "pages": [
                {"revisions": [{"revid": 999, "slots": {"main": {"content": "{}"}}}]}
            ]
        }
    }
    raw = json.dumps(wrong).encode()
    manifest = json.loads((root / "snapshot.json").read_text())
    manifest["requests"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
    (root / "snapshot.json").write_text(json.dumps(manifest))
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=raw))
    ) as client:
        with pytest.raises(ValueError, match="revision"):
            list(SelectedSourceAdapter(client=client, sleep=lambda _: None).fetch(root))
    assert not (root / "wikidata.json").exists()


def test_fetch_response_size_is_bounded(tmp_path: Path) -> None:
    from app.content.adapters.selected import MAX_BYTES

    root = snapshot(tmp_path)
    (root / "wikidata.json").unlink()
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"x" * (MAX_BYTES + 1))
        )
    ) as client:
        with pytest.raises(ValueError, match="byte limit"):
            list(SelectedSourceAdapter(client=client, sleep=lambda _: None).fetch(root))
    assert not (root / "wikidata.json").exists()


def test_taxonomy_change_invalidates_content_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    root = snapshot(tmp_path)
    import_snapshot(SelectedSourceAdapter(), root, work)
    original = Path.read_text

    def changed_taxonomy(path: Path, *args: Any, **kwargs: Any) -> str:
        text = original(path, *args, **kwargs)
        if path.name == "taxonomy.json":
            return json.dumps(
                [row for row in json.loads(text) if row["id"] != "births"]
            )
        return text

    monkeypatch.setattr(Path, "read_text", changed_taxonomy)
    report = import_snapshot(SelectedSourceAdapter(), root, work)
    assert report.quarantined == 2
    assert len(active(work, "candidates.jsonl")) == 1
    assert "unknown_category" in active(work, "quarantine.jsonl")[0]["issue_codes"]


def test_retargeted_source_alias_quarantines_old_and_new_identity(
    tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    data = json.loads(FIXTURE.read_text())
    data["records"] = data["records"][:2]
    import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), work)
    data["records"] = data["records"][:1]
    data["records"][0]["entity_id"] = "Q900002"
    data["entity"]["id"] = "Q900002"
    data["entity"]["labels"]["en"]["value"] = "Completely Different Person"
    data["page"]["pageprops"]["wikibase_item"] = "Q900002"
    import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), work)
    assert active(work, "candidates.jsonl") == []
    assert all(
        "conflicting_identity" in row["issue_codes"]
        for row in active(work, "quarantine.jsonl")
    )


def test_unresolved_milestones_do_not_create_exact_aliases(tmp_path: Path) -> None:
    data = json.loads(FIXTURE.read_text())
    data["records"] = data["records"][:2]
    for record in data["records"]:
        record["milestone"] = "unsupported-research-milestone"
    work = tmp_path / "work"
    import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), work)
    assert len(active(work, "receipts.jsonl")) == 2
    assert len({row["event_id"] for row in active(work, "quarantine.jsonl")}) == 2


def test_missing_english_label_uses_exact_linked_article_title(tmp_path: Path) -> None:
    data = json.loads(FIXTURE.read_text())
    data["entity"]["labels"] = {}
    work = tmp_path / "work"
    assert (
        import_snapshot(
            SelectedSourceAdapter(), snapshot(tmp_path, data), work
        ).imported
        == 2
    )
    assert {row["prompt"] for row in active(work, "candidates.jsonl")} == {
        "Synthetic Ada is born",
        "Synthetic Ada dies",
    }
