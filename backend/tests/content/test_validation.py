import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.content.schemas import (
    CatalogManifest,
    CategoryRecord,
    EventRecord,
    FallbackRecord,
    MediaCatalog,
    MediaRecord,
    SourceCitation,
    SourceSelection,
    ValidationIssue,
    ValidationReceipt,
)
from app.content.validation import (
    candidate_digest,
    media_catalog_digest,
    validate_event,
    validate_receipt,
)

FIXTURES = Path(__file__).parents[1] / "fixtures/content/records.jsonl"
NOW = datetime(2026, 10, 11, tzinfo=UTC)
SOURCE_DIGESTS = ("a" * 64,)


@pytest.fixture
def event() -> EventRecord:
    return EventRecord.model_validate_json(FIXTURES.read_text().splitlines()[0])


@pytest.fixture
def taxonomy() -> tuple[CategoryRecord, ...]:
    path = Path(__file__).parents[2] / "app/content/taxonomy.json"
    return tuple(
        CategoryRecord.model_validate_json(json.dumps(row))
        for row in json.loads(path.read_text())
    )


@pytest.fixture
def catalog() -> MediaCatalog:
    media = MediaRecord(
        asset_id=UUID(int=11),
        sha256="b" * 64,
        filename=f"media/{'b' * 64}.webp",
        source_url="https://example.invalid/image",
        creator="Synthetic artist",
        rights_basis="CC0 synthetic",
        attribution="Synthetic artist, test only",
        license_url="https://example.invalid/license",
        adaptation_allowed=True,
        alt_text="An illustrated fictional clock",
        fit="contain",
        acquired_at=NOW,
        source_revision="synthetic-v1",
    )
    fallback = FallbackRecord(
        key="generic",
        filename=f"media/{'c' * 64}.svg",
        sha256="c" * 64,
        alt_text="Representative historical artwork",
        creator="Synthetic artist",
        rights_basis="CC0 synthetic",
    )
    return MediaCatalog(records=(media,), fallbacks={"generic": fallback})


def receipt_for(event: EventRecord, catalog: MediaCatalog) -> ValidationReceipt:
    return ValidationReceipt(
        event_id=event.event_id,
        candidate_sha256=candidate_digest(event),
        source_sha256=SOURCE_DIGESTS,
        policy_version="automated-v1",
        stage="content_media",
        media_catalog_sha256=media_catalog_digest(catalog),
        passed=True,
        checked_at=NOW,
        issue_codes=(),
    )


def codes(event: EventRecord, taxonomy: tuple[CategoryRecord, ...]) -> set[str]:
    issues = validate_event(event, taxonomy, 2026)
    assert all(issue.field and issue.message for issue in issues)
    return {issue.code for issue in issues}


def test_year_precision_categories_and_provenance(
    event: EventRecord, taxonomy: tuple[CategoryRecord, ...]
) -> None:
    assert validate_event(event, taxonomy, 2026) == ()
    bce = EventRecord.model_validate_json(FIXTURES.read_text().splitlines()[1])
    assert bce.year_index == 0
    assert validate_event(bce, taxonomy, 2026) == ()
    assert "missing_categories" in codes(
        event.model_copy(update={"category_ids": ()}), taxonomy
    )
    assert "unknown_category" in codes(
        event.model_copy(update={"category_ids": ("unknown",)}), taxonomy
    )
    assert "duplicate_category" in codes(
        event.model_copy(update={"category_ids": ("arts", "arts")}), taxonomy
    )
    assert "missing_provenance" in codes(
        event.model_copy(update={"sources": ()}), taxonomy
    )
    for field in SourceCitation.model_fields:
        if field != "acquired_at":
            source = event.sources[0].model_copy(update={field: ""})
            assert "missing_provenance" in codes(
                event.model_copy(update={"sources": (source,)}), taxonomy
            )
    for precision in ("approximate", "decade", "century"):
        assert "unsupported_precision" in codes(
            event.model_copy(update={"date_precision": precision}), taxonomy
        )
    assert "duplicate_source" in codes(
        event.model_copy(update={"sources": event.sources * 2}), taxonomy
    )


@pytest.mark.parametrize(
    "prompt",
    [
        "The clock is installed in 1900.",
        "The clock is installed in 1,900 CE.",
        "The clock is installed in nineteen hundred.",
        "The clock of 1900s is installed.",
        "The clock is installed in 1 900 CE.",
        "The clock is installed in １９００.",
    ],
)
def test_prompt_answer_and_future_rejected(
    event: EventRecord, taxonomy: tuple[CategoryRecord, ...], prompt: str
) -> None:
    assert "answer_in_prompt" in codes(
        event.model_copy(update={"prompt": prompt}), taxonomy
    )
    assert "future_year" in codes(
        event.model_copy(update={"year_index": 2027}), taxonomy
    )
    for status in ("pending", "quarantined"):
        assert "not_approved" in codes(
            event.model_copy(update={"review_status": status}), taxonomy
        )
    assert "missing_prompt" in codes(
        event.model_copy(update={"prompt": "  "}), taxonomy
    )


def test_bce_prompt_leak(
    event: EventRecord, taxonomy: tuple[CategoryRecord, ...]
) -> None:
    bce = EventRecord.model_validate_json(FIXTURES.read_text().splitlines()[1])
    assert "answer_in_prompt" in codes(
        bce.model_copy(update={"prompt": "A gate is erected in 1 BCE."}), taxonomy
    )
    # Unrelated numerals are not answer years.
    assert (
        validate_event(
            event.model_copy(update={"prompt": "A town builds 2 clocks."}),
            taxonomy,
            2026,
        )
        == ()
    )


@pytest.mark.parametrize(
    ("year", "prompt", "expected_codes"),
    [
        (
            1905,
            "A fictional clock is installed in nineteen hundred and five.",
            {"answer_in_prompt"},
        ),
        (
            1905,
            "A fictional clock is installed in nineteen hundred five.",
            {"answer_in_prompt"},
        ),
        (
            1915,
            "A fictional clock is installed in nineteen hundred and fifteen.",
            {"answer_in_prompt"},
        ),
        (
            1999,
            "A fictional clock is installed in nineteen hundred and ninety-nine.",
            {"answer_in_prompt"},
        ),
        (
            1905,
            "A fictional clock is installed in nineteen oh five.",
            {"answer_in_prompt"},
        ),
        (1905, "A fictional clock is installed in nineteen hundred and six.", set()),
        (1905, "A fictional clock is installed in the 1900s.", {"answer_in_prompt"}),
        (1900, "A fictional clock is installed in the 1900s.", {"answer_in_prompt"}),
        (1909, "A fictional clock is installed in the 1900s.", {"answer_in_prompt"}),
        (1899, "A fictional clock is installed in the 1900s.", set()),
        (1910, "A fictional clock is installed in the 1900s.", set()),
        (1905, "A fictional clock is installed in the 1890s.", set()),
        (1905, "A fictional clock is installed in the 1910s.", set()),
        (1905, "A fictional clock is installed in the 1 900’s.", {"answer_in_prompt"}),
        (1905, "A fictional town installs a 1900series clock.", set()),
    ],
)
def test_written_year_or_containing_decade_quarantined(
    event: EventRecord,
    taxonomy: tuple[CategoryRecord, ...],
    year: int,
    prompt: str,
    expected_codes: set[str],
) -> None:
    payload = event.model_dump(mode="json")
    payload.update({"year_index": year, "prompt": prompt})
    payload["sources"][0].update(
        {
            "raw_date": f"{year} CE",
            "date_resolution": f"source-resolved:gregorian:year_index={year}",
        }
    )
    candidate = EventRecord.model_validate_json(json.dumps(payload))
    before = candidate.model_dump(mode="json")
    digest_before = candidate_digest(candidate)
    assert codes(candidate, taxonomy) == expected_codes
    assert candidate.prompt == prompt
    assert candidate.model_dump(mode="json") == before
    assert candidate_digest(candidate) == digest_before


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("calendar", "unknown", "unresolved_calendar"),
        ("calendar", "julian", "unresolved_calendar"),
        ("date_resolution", "", "unresolved_date"),
        ("date_resolution", "documented", "unresolved_date"),
        ("date_resolution", "The source says so", "unresolved_date"),
        (
            "date_resolution",
            "source-resolved:gregorian:year_index=1899",
            "unresolved_date",
        ),
        (
            "date_resolution",
            "source-resolved:julian:year_index=1900",
            "unresolved_date",
        ),
        ("raw_date", "circa 1900", "uncertain_date"),
        ("raw_date", "1900?", "uncertain_date"),
        ("raw_date", "1900/1901", "uncertain_date"),
        ("raw_date", "1900s", "uncertain_date"),
        ("raw_date", "before 1900", "uncertain_date"),
        ("raw_date", "spring 1900", "uncertain_date"),
        ("raw_date", "0 CE", "invalid_civil_year"),
        ("raw_date", "-1 BCE", "invalid_civil_year"),
        ("raw_date", "1900-02-30", "uncertain_date"),
    ],
)
def test_uncertain_calendar_requires_explicit_resolution(
    event: EventRecord,
    taxonomy: tuple[CategoryRecord, ...],
    field: str,
    value: str,
    code: str,
) -> None:
    source = event.sources[0].model_copy(update={field: value})
    assert code in codes(event.model_copy(update={"sources": (source,)}), taxonomy)


@pytest.mark.parametrize(
    ("raw_date", "precision"),
    [("1900 CE", "year"), ("1900-02", "month"), ("1900-02-28", "day")],
)
def test_resolved_exact_source_precision(
    event: EventRecord,
    taxonomy: tuple[CategoryRecord, ...],
    raw_date: str,
    precision: str,
) -> None:
    source = event.sources[0].model_copy(update={"raw_date": raw_date})
    assert (
        validate_event(
            event.model_copy(
                update={"sources": (source,), "date_precision": precision}
            ),
            taxonomy,
            2026,
        )
        == ()
    )


def test_claimed_precision_requires_source_precision(
    event: EventRecord, taxonomy: tuple[CategoryRecord, ...]
) -> None:
    assert "unsupported_precision" in codes(
        event.model_copy(update={"date_precision": "day"}), taxonomy
    )


@pytest.mark.parametrize(
    ("raw_date", "calendar", "precision"),
    [
        (
            "+00000001900-00-00T00:00:00Z",
            "http://www.wikidata.org/entity/Q1985727",
            "year",
        ),
        ("+00000001900-02-00T00:00:00Z", "gregorian", "month"),
        (
            "+00000001900-02-28T00:00:00Z",
            "https://www.wikidata.org/entity/Q1985727",
            "day",
        ),
    ],
)
def test_resolved_wikibase_raw_provenance(
    event: EventRecord,
    taxonomy: tuple[CategoryRecord, ...],
    raw_date: str,
    calendar: str,
    precision: str,
) -> None:
    source = event.sources[0].model_copy(
        update={"raw_date": raw_date, "calendar": calendar}
    )
    assert (
        validate_event(
            event.model_copy(
                update={"sources": (source,), "date_precision": precision}
            ),
            taxonomy,
            2026,
        )
        == ()
    )
    # Raw evidence stays unchanged, never rewritten to make it pass.
    assert source.raw_date == raw_date
    assert source.calendar == calendar


def test_wikibase_bce_is_raw_encoding_not_negative_civil_input(
    taxonomy: tuple[CategoryRecord, ...],
) -> None:
    bce = EventRecord.model_validate_json(FIXTURES.read_text().splitlines()[1])
    source = bce.sources[0].model_copy(
        update={
            "raw_date": "-00000000001-00-00T00:00:00Z",
            "calendar": "http://www.wikidata.org/entity/Q1985727",
        }
    )
    assert (
        validate_event(bce.model_copy(update={"sources": (source,)}), taxonomy, 2026)
        == ()
    )


@pytest.mark.parametrize(
    "raw_date",
    [
        "+00000000000-00-00T00:00:00Z",
        "+00000001900-00-01T00:00:00Z",
        "+00000001900-13-00T00:00:00Z",
        "+00000001900-02-30T00:00:00Z",
        "+00000001900-00-00T00:00:00Z circa",
        "+00000001900-00-00T00:00:00+01:00",
    ],
)
def test_invalid_wikibase_raw_dates_quarantined(
    event: EventRecord, taxonomy: tuple[CategoryRecord, ...], raw_date: str
) -> None:
    source = event.sources[0].model_copy(update={"raw_date": raw_date})
    assert codes(event.model_copy(update={"sources": (source,)}), taxonomy) & {
        "uncertain_date",
        "invalid_civil_year",
    }


@pytest.mark.parametrize(
    "raw_date", ["1899 CE", "1899-02-01", "+00000001899-00-00T00:00:00Z", "1900 BCE"]
)
def test_resolution_cannot_contradict_raw_ce_year(
    event: EventRecord, taxonomy: tuple[CategoryRecord, ...], raw_date: str
) -> None:
    source = event.sources[0].model_copy(update={"raw_date": raw_date})
    assert "unresolved_date" in codes(
        event.model_copy(update={"sources": (source,)}), taxonomy
    )


def test_resolution_cannot_contradict_raw_bce_era(
    taxonomy: tuple[CategoryRecord, ...],
) -> None:
    bce = EventRecord.model_validate_json(FIXTURES.read_text().splitlines()[1])
    source = bce.sources[0].model_copy(update={"raw_date": "1 CE"})
    assert "unresolved_date" in codes(
        bce.model_copy(update={"sources": (source,)}), taxonomy
    )


@pytest.mark.parametrize(
    ("raw_date", "year_index", "expected_codes"),
    [
        ("1 BCE", 0, set()),
        ("44 BCE", -43, set()),
        ("2 BC", -1, set()),
        ("1 CE", 1, set()),
        ("1 BCE", -43, {"unresolved_date"}),
        ("44 BCE", 0, {"unresolved_date"}),
        ("2 BCE", -2, {"unresolved_date"}),
        ("1 CE", 0, {"unresolved_date"}),
        ("0 BCE", 0, {"invalid_civil_year"}),
        ("-1 BCE", 0, {"invalid_civil_year"}),
        ("-00000000044-00-00T00:00:00Z", -43, set()),
        ("-00000000001-00-00T00:00:00Z", -43, {"unresolved_date"}),
    ],
)
def test_raw_civil_magnitude_matches_resolved_index(
    event: EventRecord,
    taxonomy: tuple[CategoryRecord, ...],
    raw_date: str,
    year_index: int,
    expected_codes: set[str],
) -> None:
    payload = event.model_dump(mode="json")
    payload["year_index"] = year_index
    source = payload["sources"][0]
    source["raw_date"] = raw_date
    source["calendar"] = "proleptic-gregorian"
    source["date_resolution"] = (
        f"source-resolved:proleptic-gregorian:year_index={year_index}"
    )
    candidate = EventRecord.model_validate_json(json.dumps(payload))
    before = candidate.model_dump(mode="json")
    digest_before = candidate_digest(candidate)
    assert codes(candidate, taxonomy) == expected_codes
    assert candidate.model_dump(mode="json") == before
    assert candidate_digest(candidate) == digest_before


def test_conflicting_bce_citations_quarantined(
    event: EventRecord,
    taxonomy: tuple[CategoryRecord, ...],
) -> None:
    payload = event.model_dump(mode="json")
    payload["year_index"] = -43
    first = payload["sources"][0]
    first.update(
        {
            "raw_date": "44 BCE",
            "calendar": "proleptic-gregorian",
            "date_resolution": "source-resolved:proleptic-gregorian:year_index=-43",
        }
    )
    payload["sources"].append(
        first | {"record_id": "contradictory", "raw_date": "1 BCE"}
    )
    candidate = EventRecord.model_validate_json(json.dumps(payload))
    before = candidate.model_dump(mode="json")
    issues = validate_event(candidate, taxonomy, 2026)
    assert {(issue.code, issue.field) for issue in issues} == {
        ("unresolved_date", "sources.1.raw_date"),
    }
    assert candidate.model_dump(mode="json") == before


def test_passed_content_receipt_not_publication_ready(
    event: EventRecord, catalog: MediaCatalog
) -> None:
    receipt = receipt_for(event, catalog).model_copy(
        update={"stage": "content", "media_catalog_sha256": None}
    )
    issues = validate_receipt(event, receipt, SOURCE_DIGESTS, catalog)
    assert {issue.code for issue in issues} >= {
        "receipt_stage",
        "receipt_media_catalog",
    }


def test_complete_matching_content_media_receipt(
    event: EventRecord, catalog: MediaCatalog
) -> None:
    assert (
        validate_receipt(event, receipt_for(event, catalog), SOURCE_DIGESTS, catalog)
        == ()
    )


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("stage", "content", "receipt_stage"),
        ("passed", False, "receipt_failed"),
        ("policy_version", "automated-v0", "receipt_policy"),
        ("event_id", UUID(int=999), "receipt_identity"),
        ("candidate_sha256", "d" * 64, "receipt_candidate"),
        ("source_sha256", ("d" * 64,), "receipt_sources"),
        ("source_sha256", (), "receipt_sources"),
        ("media_catalog_sha256", None, "receipt_media_catalog"),
        ("media_catalog_sha256", "d" * 64, "receipt_media_catalog"),
        ("issue_codes", ("uncertain_date",), "receipt_failed"),
    ],
)
def test_invalid_receipts_rejected(
    event: EventRecord, catalog: MediaCatalog, field: str, value: Any, code: str
) -> None:
    receipt = receipt_for(event, catalog).model_copy(update={field: value})
    assert code in {
        i.code for i in validate_receipt(event, receipt, SOURCE_DIGESTS, catalog)
    }


def test_stale_candidate_and_independent_source_digests(
    event: EventRecord, catalog: MediaCatalog
) -> None:
    receipt = receipt_for(event, catalog)
    changed = event.model_copy(
        update={"explanation": "Corrected synthetic explanation"}
    )
    assert "receipt_candidate" in {
        i.code for i in validate_receipt(changed, receipt, SOURCE_DIGESTS, catalog)
    }
    assert "receipt_sources" in {
        i.code for i in validate_receipt(event, receipt, ("e" * 64,), catalog)
    }
    assert "receipt_sources" in {
        i.code for i in validate_receipt(event, receipt, (), catalog)
    }
    changed = event.model_copy(update={"review_status": "quarantined"})
    assert "not_approved" in {
        i.code
        for i in validate_receipt(
            changed, receipt_for(changed, catalog), SOURCE_DIGESTS, catalog
        )
    }


MEDIA_CHANGES: dict[str, Any] = {
    "asset_id": UUID(int=99),
    "sha256": "d" * 64,
    "filename": f"media/{'d' * 64}.webp",
    "source_url": "https://example.invalid/revised",
    "creator": "Revised artist",
    "rights_basis": "Revised rights",
    "attribution": "Revised credit",
    "license_url": None,
    "adaptation_allowed": False,
    "alt_text": "Revised alt",
    "fit": "cover",
    "acquired_at": datetime(2026, 10, 12, tzinfo=UTC),
    "source_revision": "v2",
}
FALLBACK_CHANGES: dict[str, Any] = {
    "key": "other",
    "filename": f"media/{'e' * 64}.svg",
    "sha256": "e" * 64,
    "alt_text": "Revised alt",
    "creator": "Revised artist",
    "rights_basis": "Revised rights",
}


@pytest.mark.parametrize("field", MEDIA_CHANGES)
def test_current_media_catalog_digest_rejects_changed_metadata(
    event: EventRecord, catalog: MediaCatalog, field: str
) -> None:
    assert set(MEDIA_CHANGES) == set(MediaRecord.model_fields)
    changed = catalog.model_copy(
        update={
            "records": (
                catalog.records[0].model_copy(update={field: MEDIA_CHANGES[field]}),
            )
        }
    )
    assert candidate_digest(event) == receipt_for(event, catalog).candidate_sha256
    assert "receipt_media_catalog" in {
        i.code
        for i in validate_receipt(
            event, receipt_for(event, catalog), SOURCE_DIGESTS, changed
        )
    }


@pytest.mark.parametrize("field", FALLBACK_CHANGES)
def test_every_fallback_field_bound(
    event: EventRecord, catalog: MediaCatalog, field: str
) -> None:
    assert set(FALLBACK_CHANGES) == set(FallbackRecord.model_fields)
    fallback = catalog.fallbacks["generic"].model_copy(
        update={field: FALLBACK_CHANGES[field]}
    )
    changed = catalog.model_copy(update={"fallbacks": {"generic": fallback}})
    assert "receipt_media_catalog" in {
        i.code
        for i in validate_receipt(
            event, receipt_for(event, catalog), SOURCE_DIGESTS, changed
        )
    }


def test_canonical_digest_stability_and_complete_catalog(
    event: EventRecord, catalog: MediaCatalog
) -> None:
    second = catalog.records[0].model_copy(update={"asset_id": UUID(int=12)})
    other = catalog.fallbacks["generic"].model_copy(update={"key": "other"})
    first = MediaCatalog(
        records=(*catalog.records, second),
        fallbacks={"generic": catalog.fallbacks["generic"], "other": other},
    )
    reversed_catalog = MediaCatalog(
        records=tuple(reversed(first.records)),
        fallbacks=dict(reversed(list(first.fallbacks.items()))),
    )
    assert media_catalog_digest(first) == media_catalog_digest(reversed_catalog)
    payload = first.model_dump(mode="json")
    expected = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    assert media_catalog_digest(first) == expected
    assert (
        media_catalog_digest(catalog) != expected
    )  # Unreferenced records are bound too.
    moved_key = catalog.model_copy(
        update={"fallbacks": {"renamed": catalog.fallbacks["generic"]}}
    )
    assert media_catalog_digest(moved_key) != media_catalog_digest(catalog)
    event_data = event.model_dump(mode="json")
    reordered = EventRecord.model_validate_json(
        json.dumps(dict(reversed(list(event_data.items()))))
    )
    expected_event = hashlib.sha256(
        json.dumps(
            event_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    assert candidate_digest(event) == candidate_digest(reordered) == expected_event


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("year_index", "1900"),
        ("year_index", True),
        ("category_ids", "arts"),
        ("unexpected", True),
    ],
)
def test_strict_event_contract(event: EventRecord, field: str, value: Any) -> None:
    payload = event.model_dump(mode="json") | {field: value}
    with pytest.raises(ValidationError):
        EventRecord.model_validate_json(json.dumps(payload))


def test_nested_provenance_is_required(event: EventRecord) -> None:
    for field in SourceCitation.model_fields:
        payload = event.model_dump(mode="json")
        del payload["sources"][0][field]
        with pytest.raises(ValidationError):
            EventRecord.model_validate_json(json.dumps(payload))


def test_source_selection_contract_and_taxonomy(
    taxonomy: tuple[CategoryRecord, ...],
) -> None:
    slugs = {
        "births",
        "deaths",
        "battles",
        "inventions",
        "literature",
        "arts",
        "exploration",
        "politics",
    }
    assert {category.id for category in taxonomy} == slugs
    assert all(category.label.strip() for category in taxonomy)
    good = {
        "source_ids": ["synthetic"],
        "allowed_media_hosts": ["example.invalid"],
        "decision_report": "docs/synthetic-decision.md",
        "daily_category_ids": ["arts"],
    }
    assert SourceSelection.model_validate_json(json.dumps(good)).source_ids == (
        "synthetic",
    )
    for field, value in [
        ("source_ids", []),
        ("source_ids", ["synthetic", "synthetic"]),
        ("allowed_media_hosts", ["https://example.invalid/image"]),
        ("allowed_media_hosts", ["*.example.invalid"]),
        ("decision_report", ""),
        ("daily_category_ids", []),
        ("daily_category_ids", ["unknown"]),
        ("daily_category_ids", ["arts", "arts"]),
        ("extra", "unsupported"),
    ]:
        with pytest.raises(ValidationError):
            SourceSelection.model_validate_json(json.dumps(good | {field: value}))


@pytest.mark.parametrize(
    "path",
    [
        "../secret",
        "/absolute",
        "media/../../secret",
        "media\\secret",
        "https://example.invalid/file",
        "media//file",
        "./events.jsonl",
    ],
)
def test_manifest_paths_cannot_escape(path: str) -> None:
    with pytest.raises(ValidationError):
        CatalogManifest(
            release_id="synthetic",
            created_at=NOW,
            event_count=1,
            fixture=True,
            files={path: "a" * 64},
        )


def test_manifest_and_digest_fields_are_strict(
    event: EventRecord, catalog: MediaCatalog
) -> None:
    manifest = CatalogManifest(
        release_id="synthetic",
        created_at=NOW,
        event_count=2,
        fixture=True,
        files={"events.jsonl": "a" * 64},
    )
    assert manifest.schema_version == 1
    for digest in ("bad", "A" * 64, "g" * 64):
        with pytest.raises(ValidationError):
            ValidationReceipt.model_validate_json(
                receipt_for(event, catalog).model_dump_json().replace("a" * 64, digest)
            )
    with pytest.raises(ValidationError):
        CatalogManifest(
            release_id="synthetic",
            created_at=NOW,
            event_count=-1,
            fixture=True,
            files={},
        )
    with pytest.raises(ValidationError):
        MediaCatalog(records=catalog.records * 2, fallbacks=catalog.fallbacks)
    with pytest.raises(ValidationError):
        MediaCatalog(
            records=catalog.records, fallbacks={"wrong": catalog.fallbacks["generic"]}
        )
    with pytest.raises(ValidationError):
        MediaRecord.model_validate_json(
            catalog.records[0]
            .model_dump_json()
            .replace("b" * 64 + ".webp", "c" * 64 + ".webp")
        )


def test_issue_contract_and_strict_manifest_version() -> None:
    issue = ValidationIssue(
        code="unknown_category", field="category_ids", message="Unknown category"
    )
    assert issue.model_dump() == {
        "code": "unknown_category",
        "field": "category_ids",
        "message": "Unknown category",
    }
    good = {
        "release_id": "synthetic",
        "created_at": NOW.isoformat(),
        "event_count": 0,
        "fixture": True,
        "files": {},
    }
    for version in (True, "1", 0, 2):
        with pytest.raises(ValidationError):
            CatalogManifest.model_validate_json(
                json.dumps(good | {"schema_version": version})
            )


@pytest.mark.parametrize("field", ["identity_key", "explanation", "fallback_key"])
def test_missing_required_event_content(
    event: EventRecord, taxonomy: tuple[CategoryRecord, ...], field: str
) -> None:
    assert "missing_content" in codes(event.model_copy(update={field: " \t"}), taxonomy)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "file:///private/file",
        "https://user:pass@example.invalid",
        "https://example.invalid/bad path",
        "https://[invalid",
    ],
)
def test_invalid_source_urls(
    event: EventRecord, taxonomy: tuple[CategoryRecord, ...], url: str
) -> None:
    source = event.sources[0].model_copy(update={"url": url})
    assert "invalid_source_url" in codes(
        event.model_copy(update={"sources": (source,)}), taxonomy
    )


def test_timezone_and_fallback_filename_contracts(
    event: EventRecord, catalog: MediaCatalog
) -> None:
    payload = event.model_dump(mode="json")
    payload["sources"][0]["acquired_at"] = "2026-10-11T00:00:00"
    with pytest.raises(ValidationError):
        EventRecord.model_validate_json(json.dumps(payload))
    with pytest.raises(ValidationError):
        FallbackRecord.model_validate_json(
            catalog.fallbacks["generic"]
            .model_dump_json()
            .replace("c" * 64 + ".svg", "c" * 64 + ".webp")
        )


def test_unicode_digests_and_unreferenced_catalog_changes(
    event: EventRecord, catalog: MediaCatalog
) -> None:
    changed_event = event.model_copy(update={"prompt": "A fictional café opens."})
    payload = changed_event.model_dump(mode="json")
    expected = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    assert candidate_digest(changed_event) == expected
    second = catalog.records[0].model_copy(
        update={"asset_id": UUID(int=12), "creator": "Synthetic café artist"}
    )
    full_catalog = catalog.model_copy(update={"records": (*catalog.records, second)})
    assert "receipt_media_catalog" in {
        i.code
        for i in validate_receipt(
            event, receipt_for(event, catalog), SOURCE_DIGESTS, full_catalog
        )
    }
    assert (
        validate_receipt(
            event, receipt_for(event, full_catalog), SOURCE_DIGESTS, full_catalog
        )
        == ()
    )
