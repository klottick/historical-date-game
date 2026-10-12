"""Versioned, fail-closed content and publication-receipt checks.

Resolution is a machine assertion supplied by acquisition, not free prose:
``source-resolved:<gregorian|proleptic-gregorian>:year_index=<integer>``.
It must match the event and the citation's Gregorian calendar family. Accepted
raw civil dates are positive years (optional CE/AD/BCE/BC), exact ISO
year-month[-day], or preserved signed Wikibase UTC timestamps (00 month/day
denotes year/month precision). Gregorian calendar URIs are retained verbatim.
Other formats, calendars, approximate dates, and ranges stay quarantined. C3
retains unresolved raw candidates outside EventRecord and B1 owns conversion;
this module neither converts civil years nor infers calendar corrections.

Receipts bind metadata, not actual image bytes. C4 freezes the entire media
batch; C5 independently verifies asset bytes and handles missing receipts.
"""

import hashlib
import json
import re
import unicodedata
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from app.content.schemas import (
    CategoryRecord,
    EventRecord,
    MediaCatalog,
    SourceCitation,
    ValidationIssue,
    ValidationReceipt,
)

VALIDATION_POLICY_VERSION = "automated-v1"


def _canonical_digest(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def candidate_digest(event: EventRecord) -> str:
    """Bind every private event field; retain sequence order in the candidate."""
    return _canonical_digest(event.model_dump(mode="json"))


def media_catalog_digest(catalog: MediaCatalog) -> str:
    """Bind all records/fallbacks, including unreferenced assets and rights facts."""
    payload = catalog.model_dump(mode="json")
    payload["records"] = sorted(
        payload["records"], key=lambda record: record["asset_id"]
    )
    return _canonical_digest(payload)


def _http_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return bool(
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not any(character.isspace() for character in value)
        )
    except ValueError:
        return False


def _raw_date(
    source: SourceCitation,
) -> tuple[int | None, bool, str | None, str | None]:
    """Read raw year/era/precision evidence, without deriving a game year index."""
    raw = source.raw_date.strip()
    civil = re.fullmatch(r"(-?\d+)(?:\s+(CE|AD|BCE|BC))?", raw, re.IGNORECASE)
    iso = re.fullmatch(r"(-?\d{4,})-(\d{2})(?:-(\d{2}))?", raw)
    wikibase = re.fullmatch(r"([+-])(\d{4,})-(\d{2})-(\d{2})T00:00:00Z", raw)
    if wikibase:
        year = int(wikibase[2])
        bce = wikibase[1] == "-"
        month, day = int(wikibase[3]), int(wikibase[4])
        if year == 0:
            return None, bce, None, "invalid_civil_year"
        if month == day == 0:
            return year, bce, "year", None
        if month == 0:
            return year, bce, None, "uncertain_date"
        try:
            date(year, month, day or 1)
        except ValueError:
            return year, bce, None, "uncertain_date"
        return year, bce, "day" if day else "month", None
    match = civil or iso
    if match is None:
        return None, False, None, "uncertain_date"
    year = int(match[1])
    if year <= 0:
        return None, False, None, "invalid_civil_year"
    if civil:
        return year, (civil[2] or "").upper() in {"BCE", "BC"}, "year", None
    assert iso is not None
    month = int(iso[2])
    day = int(iso[3] or "1")
    try:
        date(year, month, day)
    except ValueError:
        return year, False, None, "uncertain_date"
    return year, False, "day" if iso[3] else "month", None


_GREGORIAN_CALENDARS = {
    "gregorian",
    "proleptic-gregorian",
    "http://www.wikidata.org/entity/Q1985727",
    "https://www.wikidata.org/entity/Q1985727",
}


_SMALL = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS = (
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
)


def _number_words(number: int) -> str:
    if number < 20:
        return _SMALL[number]
    if number < 100:
        return _TENS[number // 10] + (" " + _SMALL[number % 10] if number % 10 else "")
    if number < 1000:
        return (
            _SMALL[number // 100]
            + " hundred"
            + (" " + _number_words(number % 100) if number % 100 else "")
        )
    return (
        _number_words(number // 1000)
        + " thousand"
        + (" " + _number_words(number % 1000) if number % 1000 else "")
    )


def _answer_in_prompt(event: EventRecord, civil_years: set[int]) -> bool:
    # Use positive raw civil years for BCE: no game-year conversion here.
    if event.year_index > 0:
        civil_years = civil_years | {event.year_index}
    prompt = unicodedata.normalize("NFKC", event.prompt).casefold()
    prompt = re.sub(r"(?<=\d)[,\s]+(?=\d{3}(?!\d))", "", prompt)
    prompt = re.sub(r"[-\s]+", " ", prompt)
    for year in civil_years:
        if re.search(rf"(?<!\d){year}(?!\d)", prompt):
            return True
        if year < 10000:
            alternatives = {_number_words(year)}
            if 1000 <= year < 10000:
                first, last = divmod(year, 100)
                alternatives.add(
                    _number_words(first)
                    + (" " + _number_words(last) if last else " hundred")
                )
                if 0 < last < 10:
                    alternatives.add(
                        _number_words(first) + " oh " + _number_words(last)
                    )
            for words in alternatives:
                # English optional "and" is immaterial for leak detection.
                normalized = re.sub(r"\band\s+", "", prompt)
                if re.search(rf"\b{re.escape(words)}\b", normalized):
                    return True
    return False


def validate_event(
    event: EventRecord,
    taxonomy: tuple[CategoryRecord, ...],
    current_year_index: int,
) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []

    def issue(code: str, field: str, message: str) -> None:
        issues.append(ValidationIssue(code=code, field=field, message=message))

    if event.review_status != "approved":
        issue(
            "not_approved",
            "review_status",
            "Machine validation has not approved this candidate",
        )
    if event.year_index > current_year_index:
        issue("future_year", "year_index", "Event year is later than the current year")
    if not event.prompt.strip():
        issue("missing_prompt", "prompt", "A nonempty answer-free prompt is required")
    for field in ("identity_key", "explanation", "fallback_key"):
        if not getattr(event, field).strip():
            issue("missing_content", field, "Required private/public content is empty")
    if not event.category_ids:
        issue(
            "missing_categories",
            "category_ids",
            "At least one taxonomy category is required",
        )
    known = {category.id for category in taxonomy}
    if any(category not in known for category in event.category_ids):
        issue(
            "unknown_category",
            "category_ids",
            "Category is absent from the current taxonomy",
        )
    if len(set(event.category_ids)) != len(event.category_ids):
        issue(
            "duplicate_category", "category_ids", "Category memberships must be unique"
        )
    if event.date_precision not in {"year", "month", "day"}:
        issue(
            "unsupported_precision",
            "date_precision",
            "Only exact source-resolved dates are supported",
        )
    if not event.sources:
        issue(
            "missing_provenance",
            "sources",
            "At least one complete source citation is required",
        )
    source_keys = [(source.source_id, source.record_id) for source in event.sources]
    if len(set(source_keys)) != len(source_keys):
        issue(
            "duplicate_source",
            "sources",
            "Repeated citations do not constitute independent provenance",
        )
    civil_years: set[int] = set()
    ranks = {"year": 1, "month": 2, "day": 3}
    for index, source in enumerate(event.sources):
        prefix = f"sources.{index}"
        for field in SourceCitation.model_fields:
            value = getattr(source, field)
            if isinstance(value, str) and not value.strip():
                issue(
                    "missing_provenance",
                    f"{prefix}.{field}",
                    "Citation provenance must be complete",
                )
        if not _http_url(source.url):
            issue(
                "invalid_source_url",
                f"{prefix}.url",
                "Citation requires an HTTP(S) source URL",
            )
        if source.calendar not in _GREGORIAN_CALENDARS:
            issue(
                "unresolved_calendar",
                f"{prefix}.calendar",
                "Unsupported calendar remains quarantined",
            )
        supported_resolutions = {
            f"source-resolved:{calendar}:year_index={event.year_index}"
            for calendar in ("gregorian", "proleptic-gregorian")
        }
        proleptic = f"source-resolved:proleptic-gregorian:year_index={event.year_index}"
        if (
            source.date_resolution not in supported_resolutions
            or source.calendar not in _GREGORIAN_CALENDARS
            or source.calendar == "proleptic-gregorian"
            and source.date_resolution != proleptic
        ):
            issue(
                "unresolved_date",
                f"{prefix}.date_resolution",
                "Explicit supported source resolution must match the canonical year",
            )
        civil_year, bce, precision, reason = _raw_date(source)
        if reason:
            issue(
                reason,
                f"{prefix}.raw_date",
                "Raw date is not an exact positive civil date",
            )
        if civil_year is not None:
            civil_years.add(civil_year)
            if (
                bce
                and (event.year_index > 0 or source.date_resolution != proleptic)
                or not bce
                and civil_year != event.year_index
            ):
                issue(
                    "unresolved_date",
                    f"{prefix}.raw_date",
                    "Source year/era contradicts the documented resolution",
                )
        if (
            precision is not None
            and ranks.get(event.date_precision, 0) > ranks[precision]
        ):
            issue(
                "unsupported_precision",
                "date_precision",
                "Claimed date precision exceeds source evidence",
            )
    if _answer_in_prompt(event, civil_years):
        issue(
            "answer_in_prompt", "prompt", "Answer year appears in the unanswered prompt"
        )
    return tuple(issues)


def validate_receipt(
    event: EventRecord,
    receipt: ValidationReceipt,
    source_digests: tuple[str, ...],
    media_catalog: MediaCatalog,
) -> tuple[ValidationIssue, ...]:
    """Compare private receipts against independent current acquisition/catalog facts."""
    issues: list[ValidationIssue] = []

    def issue(code: str, field: str, message: str) -> None:
        issues.append(ValidationIssue(code=code, field=field, message=message))

    if event.review_status != "approved":
        issue(
            "not_approved",
            "review_status",
            "Only machine-approved events may be published",
        )
    if receipt.stage != "content_media":
        issue(
            "receipt_stage", "stage", "Content-only receipts are not publication-ready"
        )
    if not receipt.passed or receipt.issue_codes:
        issue(
            "receipt_failed",
            "passed",
            "Receipt must pass without outstanding validation issues",
        )
    if receipt.policy_version != VALIDATION_POLICY_VERSION:
        issue(
            "receipt_policy",
            "policy_version",
            "Receipt policy is not the expected automated policy",
        )
    if receipt.event_id != event.event_id:
        issue("receipt_identity", "event_id", "Receipt belongs to a different event")
    if receipt.candidate_sha256 != candidate_digest(event):
        issue(
            "receipt_candidate",
            "candidate_sha256",
            "Receipt is stale for the current candidate",
        )
    if (
        not source_digests
        or receipt.source_sha256 != source_digests
        or any(not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in source_digests)
    ):
        issue(
            "receipt_sources",
            "source_sha256",
            "Receipt does not bind current source snapshots",
        )
    if receipt.media_catalog_sha256 != media_catalog_digest(media_catalog):
        issue(
            "receipt_media_catalog",
            "media_catalog_sha256",
            "Receipt does not bind the independently computed current media catalog",
        )
    return tuple(issues)
