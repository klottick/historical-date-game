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


@pytest.mark.parametrize("initial", ["unsupported-milestone", "missing-entity"])
def test_unresolved_alias_promotes_to_proven_exact_and_migrates_legacy_state(
    tmp_path: Path, initial: str
) -> None:
    data = json.loads(FIXTURE.read_text())
    data["records"] = data["records"][:1]
    unresolved = copy.deepcopy(data)
    if initial == "unsupported-milestone":
        unresolved["records"][0]["milestone"] = "unsupported-research-milestone"
    else:
        unresolved["records"][0]["entity_id"] = ""
    work = tmp_path / "work"
    assert (
        import_snapshot(
            SelectedSourceAdapter(), snapshot(tmp_path, unresolved), work
        ).quarantined
        == 1
    )
    # Model an existing 618bca1 workspace, even after the new writer stops saving
    # unresolved aliases: the read boundary must migrate this legacy state.
    pointer = json.loads((work / "current.json").read_text())
    state_path = work / pointer["generation"] / "state.json"
    state = json.loads(state_path.read_text())
    key = '["wikidata","synthetic-birth"]'
    state["aliases"][key] = {
        "identity_key": "unresolved:" + key,
        "event_id": "00000000-0000-0000-0000-000000000001",
    }
    state_path.write_text(json.dumps(state))
    report = import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), work)
    assert (report.imported, report.quarantined) == (1, 0)
    event = active(work, "candidates.jsonl")[0]
    assert event["identity_key"] == "wikidata:Q900001:birth"
    pointer = json.loads((work / "current.json").read_text())
    aliases = json.loads((work / pointer["generation"] / "aliases.json").read_text())
    assert aliases[key] == {
        "identity_key": event["identity_key"],
        "event_id": event["event_id"],
    }
    assert (
        import_snapshot(
            SelectedSourceAdapter(), snapshot(tmp_path, data), work
        ).imported
        == 0
    )


@pytest.mark.parametrize(
    "text",
    [
        "{{Infobox person\n| name = Synthetic Ada\n}}\n<!-- obsolete example\n| birth_date = 1800\n-->",
        "{{Unrelated example\n| birth_date = 1800\n}}",
        "{{Infobox person\n| notes = {{Unrelated example\n| birth_date = 1800\n}}\n}}",
        "<nowiki>{{Infobox person\n| birth_date = 1800\n}}</nowiki>",
        "{{Documentation\n| example = {{Infobox person\n| birth_date = 1800\n}}\n}}",
    ],
)
def test_inactive_or_unrelated_wiki_fields_cannot_substantiate_birth(
    tmp_path: Path, text: str
) -> None:
    data = json.loads(FIXTURE.read_text())
    data["records"] = data["records"][:1]
    data["page"]["revisions"][0]["slots"]["main"]["content"] = text
    work = tmp_path / "work"
    report = import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), work)
    assert (report.imported, report.quarantined) == (0, 1)
    quarantined = active(work, "quarantine.jsonl")[0]
    assert "unresolved_wikipedia_date" in quarantined["issue_codes"]
    assert (
        quarantined["raw"][0]["payload"]["page"]["revisions"][0]["slots"]["main"][
            "content"
        ]
        == text
    )


@pytest.mark.parametrize(
    "scope",
    ["wikidata-day", "wikipedia-day", "wikidata-month", "day-conflict-with-year-wiki"],
)
def test_same_year_finer_date_conflicts_quarantine(tmp_path: Path, scope: str) -> None:
    data = json.loads(FIXTURE.read_text())
    data["records"] = data["records"][:1]
    claim = data["entity"]["claims"]["P569"][0]
    value = claim["mainsnak"]["datavalue"]["value"]
    value["time"] = "+00000001800-01-02T00:00:00Z"
    value["precision"] = 11
    wiki = "1800-01-02"
    if scope == "wikipedia-day":
        wiki = "1800-11-12"
    else:
        other = copy.deepcopy(claim)
        other["id"] += "-second"
        other["mainsnak"]["datavalue"]["value"]["time"] = "+00000001800-02-03T00:00:00Z"
        if scope == "wikidata-month":
            value["precision"] = 10
            value["time"] = "+00000001800-01-00T00:00:00Z"
            other["mainsnak"]["datavalue"]["value"].update(
                time="+00000001800-02-00T00:00:00Z", precision=10
            )
            wiki = "1800-01"
        elif scope == "day-conflict-with-year-wiki":
            wiki = "1800"
        data["entity"]["claims"]["P569"].append(other)
    data["page"]["revisions"][0]["slots"]["main"]["content"] = (
        f"{{{{Infobox person\n| birth_date = {wiki}\n}}}}"
    )
    work = tmp_path / "work"
    report = import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), work)
    assert (report.imported, report.quarantined) == (0, 1)
    assert "conflicting_dates" in active(work, "quarantine.jsonl")[0]["issue_codes"]


def test_common_year_precision_is_not_overstated(tmp_path: Path) -> None:
    data = json.loads(FIXTURE.read_text())
    data["records"] = data["records"][:1]
    value = data["entity"]["claims"]["P569"][0]["mainsnak"]["datavalue"]["value"]
    value.update(time="+00000001800-01-02T00:00:00Z", precision=11)
    work = tmp_path / "work"
    assert (
        import_snapshot(
            SelectedSourceAdapter(), snapshot(tmp_path, data), work
        ).imported
        == 1
    )
    assert active(work, "candidates.jsonl")[0]["date_precision"] == "year"


def test_date_template_cannot_hide_a_conflicting_day(tmp_path: Path) -> None:
    data = json.loads(FIXTURE.read_text())
    data["records"] = data["records"][:1]
    data["entity"]["claims"]["P569"][0]["mainsnak"]["datavalue"]["value"].update(
        time="+00000001800-01-02T00:00:00Z", precision=11
    )
    data["page"]["revisions"][0]["slots"]["main"]["content"] = (
        "{{Infobox person\n| birth_date = {{birth date|1800|2|3}}\n}}"
    )
    work = tmp_path / "work"
    assert (
        import_snapshot(
            SelectedSourceAdapter(), snapshot(tmp_path, data), work
        ).quarantined
        == 1
    )
    assert "conflicting_dates" in active(work, "quarantine.jsonl")[0]["issue_codes"]


FIELD_EXAMPLES = json.loads(
    (FIXTURE.parent / "selected-provider-fields.json").read_text()
)["examples"]


def modeled_fields(example: dict[str, Any]) -> dict[str, Any]:
    data = json.loads(FIXTURE.read_text())
    data["records"] = data["records"][:1]
    data["records"][0].update(
        milestone=example["milestone"], category_ids=[example["category"]]
    )
    claim = data["entity"]["claims"]["P569"][0]
    claim["mainsnak"]["property"] = example["property"]
    claim["mainsnak"]["datavalue"]["value"].update(
        time=example["time"], precision=example["precision"]
    )
    data["entity"]["claims"] = {example["property"]: [claim]}
    data["page"]["revisions"][0]["slots"]["main"]["content"] = (
        f"{{{{{example['infobox']}\n| {example['field']} = {example['value']}\n}}}}"
    )
    return data


@pytest.mark.parametrize(
    "example", FIELD_EXAMPLES, ids=[e["category"] for e in FIELD_EXAMPLES]
)
def test_evidenced_ordinary_infobox_category_paths(
    tmp_path: Path, example: dict[str, Any]
) -> None:
    data = modeled_fields(example)
    work = tmp_path / "work"
    report = import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), work)
    assert (report.imported, report.quarantined) == (1, 0)
    event = active(work, "candidates.jsonl")[0]
    assert event["year_index"] == example["year_index"]
    assert event["category_ids"] == [example["category"]]
    assert event["prompt"] == "Synthetic Ada " + example["verb"]
    assert event["date_precision"] == "year"  # truthful C2 raw-year citation cap


@pytest.mark.parametrize(
    "value,start,end",
    [
        ("4–7 June 1942", "+1942-06-04T00:00:00Z", "+1942-06-07T00:00:00Z"),
        (
            "23 August 1942 – 2 February 1943",
            "+1942-08-23T00:00:00Z",
            "+1943-02-02T00:00:00Z",
        ),
    ],
)
@pytest.mark.parametrize("milestone", ["start", "end"])
def test_conflict_date_field_selects_exact_endpoint(
    tmp_path: Path, value: str, start: str, end: str, milestone: str
) -> None:
    example = dict(
        FIELD_EXAMPLES[2],
        value=value,
        milestone=milestone,
        property="P580" if milestone == "start" else "P582",
        time=start if milestone == "start" else end,
    )
    work = tmp_path / "work"
    assert (
        import_snapshot(
            SelectedSourceAdapter(), snapshot(tmp_path, modeled_fields(example)), work
        ).imported
        == 1
    )
    event = active(work, "candidates.jsonl")[0]
    assert event["year_index"] == (
        1943 if milestone == "end" and end.startswith("+1943") else 1942
    )
    assert event["prompt"] == "Synthetic Ada " + (
        "begins" if milestone == "start" else "ends"
    )


@pytest.mark.parametrize(
    "value",
    [
        "c. 4–7 June 1942",
        "1942–1943",
        "7–4 June 1942",
        "4–7 June 1942 (Old Style)",
        "4–7 June 1942 or 1943",
        "{{Example|date=4–7 June 1942}}",
    ],
)
def test_ambiguous_or_inactive_conflict_dates_quarantine(
    tmp_path: Path, value: str
) -> None:
    example = dict(FIELD_EXAMPLES[2], value=value)
    work = tmp_path / "work"
    assert (
        import_snapshot(
            SelectedSourceAdapter(), snapshot(tmp_path, modeled_fields(example)), work
        ).quarantined
        == 1
    )


def test_persistent_aliases_cannot_hide_exact_day_conflict_with_year_citations(
    tmp_path: Path,
) -> None:
    data = json.loads(FIXTURE.read_text())
    data["records"] = data["records"][:1]
    claim = data["entity"]["claims"]["P569"][0]
    claim["mainsnak"]["datavalue"]["value"].update(
        time="+1800-01-02T00:00:00Z", precision=11
    )
    work = tmp_path / "work"
    assert (
        import_snapshot(
            SelectedSourceAdapter(), snapshot(tmp_path, data), work
        ).imported
        == 1
    )
    data["records"][0]["record_id"] = "second-exact-alias"
    claim["id"] = "Q900001$another-statement"
    claim["mainsnak"]["datavalue"]["value"]["time"] = "+1800-02-03T00:00:00Z"
    report = import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), work)
    assert report.quarantined == 2
    assert "conflicting_dates" in active(work, "quarantine.jsonl")[0]["issue_codes"]


def test_compatible_alias_dates_reduce_to_common_year_precision(tmp_path: Path) -> None:
    data = json.loads(FIXTURE.read_text())
    data["records"] = data["records"][:1]
    data["entity"]["claims"]["P569"][0]["mainsnak"]["datavalue"]["value"].update(
        time="+1800-01-02T00:00:00Z", precision=11
    )
    data["page"]["revisions"][0]["slots"]["main"]["content"] = (
        "{{Infobox person\n| birth_date = 1800-01-02\n}}"
    )
    work = tmp_path / "work"
    assert (
        import_snapshot(
            SelectedSourceAdapter(), snapshot(tmp_path, data), work
        ).imported
        == 1
    )
    data["records"][0]["record_id"] = "year-only-alias"
    data["page"]["revisions"][0]["slots"]["main"]["content"] = (
        "{{Infobox person\n| birth_date = 1800\n}}"
    )
    report = import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), work)
    assert report.quarantined == 0
    assert active(work, "candidates.jsonl")[0]["date_precision"] == "year"


def test_spaceflight_clock_without_source_utc_is_unresolved(tmp_path: Path) -> None:
    example = dict(
        FIELD_EXAMPLES[6], value="{{start-date|April 12, 1961, 06:07|timezone=yes}}"
    )
    work = tmp_path / "work"
    assert (
        import_snapshot(
            SelectedSourceAdapter(), snapshot(tmp_path, modeled_fields(example)), work
        ).quarantined
        == 1
    )


def test_invention_field_is_not_a_second_discovery_milestone(tmp_path: Path) -> None:
    example = dict(FIELD_EXAMPLES[3], milestone="discovery")
    work = tmp_path / "work"
    assert (
        import_snapshot(
            SelectedSourceAdapter(), snapshot(tmp_path, modeled_fields(example)), work
        ).quarantined
        == 1
    )


@pytest.mark.parametrize(
    "value", ["18<!-- inactive example -->00", "18<ref>citation</ref>00"]
)
def test_inactive_nodes_do_not_manufacture_a_raw_year_token(
    tmp_path: Path, value: str
) -> None:
    data = json.loads(FIXTURE.read_text())
    data["records"] = data["records"][:1]
    data["page"]["revisions"][0]["slots"]["main"]["content"] = (
        f"{{{{Infobox person\n| birth_date = {value}\n}}}}"
    )
    work = tmp_path / "work"
    assert (
        import_snapshot(
            SelectedSourceAdapter(), snapshot(tmp_path, data), work
        ).quarantined
        == 1
    )


@pytest.mark.parametrize("duplicate", ["", "   ", "<!-- no active value -->"])
@pytest.mark.parametrize("duplicate_first", [False, True])
def test_duplicate_infobox_field_quarantines_even_blank_or_comment_only(
    tmp_path: Path, duplicate: str, duplicate_first: bool
) -> None:
    data = json.loads(FIXTURE.read_text())
    data["records"] = data["records"][:1]
    values = [duplicate, "1800"] if duplicate_first else ["1800", duplicate]
    text = (
        "{{Infobox person\n"
        + "".join(f"| birth_date = {value}\n" for value in values)
        + "}}"
    )
    data["page"]["revisions"][0]["slots"]["main"]["content"] = text
    work = tmp_path / "work"
    report = import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), work)
    assert (report.imported, report.quarantined) == (0, 1)
    assert active(work, "candidates.jsonl") == []
    quarantine = active(work, "quarantine.jsonl")[0]
    assert "unresolved_wikipedia_date" in quarantine["issue_codes"]
    assert (
        quarantine["raw"][0]["payload"]["page"]["revisions"][0]["slots"]["main"][
            "content"
        ]
        == text
    )
    assert not active(work, "receipts.jsonl")[0]["passed"]


def test_single_valid_infobox_field_still_passes(tmp_path: Path) -> None:
    data = json.loads(FIXTURE.read_text())
    data["records"] = data["records"][:1]
    data["page"]["revisions"][0]["slots"]["main"]["content"] = (
        "{{Infobox person\n| birth_date = 1800\n}}"
    )
    work = tmp_path / "work"
    report = import_snapshot(SelectedSourceAdapter(), snapshot(tmp_path, data), work)
    assert (report.imported, report.quarantined) == (1, 0)
    assert active(work, "candidates.jsonl")[0]["year_index"] == 1800
    assert active(work, "receipts.jsonl")[0]["passed"]
