"""Bounded offline ingestion of one approved, immutable chronology download.

The year is the reported historical civil year, not a Gregorian day conversion.
Rules are deliberately incomplete milestone heuristics, not historical proof.
"""

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.content.adapters.base import RawCandidate
from app.content.adapters.selected import digest, issue
from app.content.schemas import (
    CategoryRecord,
    EventRecord,
    SourceCitation,
    ValidationIssue,
)
from app.content.validation import validate_event

SOURCE_ID = "wikipedia_onthisday"
REPOSITORY = "mneedham/wikipedia-onthisday"
COMMIT = "9f30eae49675c8e71453b332f83a6b6b3bb297d4"
PINNED_FILES = {
    "events.jsonl": "0fd539accf6ee5f31ddbf374ce24398381f5ac51def4309ce4c93e46daed30db",
    "README.md": "966e77b3b2c3d24da0ffdc1c16ff95c8c8c7de2e4b2aa53a190e8cf9490a0c05",
    "NOTICE.md": "a1800c7e700710aae3b1129235dfb666757cc95410dc587aadc72acd7085c883",
}
SNAPSHOT_FILES = (*PINNED_FILES, "download-receipt.json")
SNAPSHOT_PREFIX = "source-snapshots/onthisday/"
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 4096
MAX_ROWS = 20000
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
TEXT_LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
PROJECT_URL = "https://github.com/mneedham/wikipedia-onthisday"
TEXT_CREDIT = (
    "Catalog text: adapted from Wikipedia contributors via mneedham/wikipedia-onthisday; "
    "CC BY-SA 4.0. Changes: automatic selection, category assignment and year-only presentation. "
    "Application code is separately MIT licensed; no endorsement or legal clearance claimed."
)
CATALOG_LICENSE = (
    "Catalog text adapted from Wikipedia contributors: Creative Commons "
    "Attribution-ShareAlike 4.0 International (CC BY-SA 4.0).\n"
    + TEXT_LICENSE_URL
    + "\n"
    "This notice concerns catalog content, not application code (MIT) or images.\n"
    "Original representative fallback artwork: CC0 1.0; see media.json.\n"
    "Selected-source original milestone prompts and structured data retain their citation rights notices.\n"
    "No legal clearance or endorsement is asserted.\n"
)
CATALOG_NOTICE = (
    "# Catalog text attribution\n\n" + TEXT_CREDIT + "\n\n"
    "Dataset author/project: " + PROJECT_URL + "\n"
    "License: " + TEXT_LICENSE_URL + "\n"
    "Download lineage, pinned commit, original README/NOTICE and unmodified JSONL "
    "are retained privately in source-snapshots/onthisday/. "
    "Revealed citations link the actual Wikipedia calendar pages; their history links "
    "identify contributors. The source is a pinned dataset, not a claim of pinned "
    "Wikipedia article revisions. Wikipedia does not endorse this project.\n"
)

# Ordered specific milestones; actions, not bare subject mentions. No birth rule:
# this events-only snapshot's "is born" occurrences are figurative/animal cloning.
RULES = (
    ("deaths", r"^[^.;]{1,180}\b(?:dies|is assassinated|is executed)\b"),
    (
        "battles",
        r"\b(?:battle of|siege of)\b.{0,160}\b(?:begins|ends|defeat\w*|attack\w*|victory|capture\w*|surrender\w*)\b",
    ),
    (
        "inventions",
        r"\b(?:patents|is patented|receives a patent|is issued (?:\w+ )?patent)\b",
    ),
    ("literature", r"\b(?:publishes|is published)\b"),
    ("arts", r"\b(?:premieres|premiere of)\b"),
    (
        "exploration",
        r"\b(?:spacecraft|satellite|space shuttle|space probe|apollo|vostok|soyuz|expedition)\b.{0,160}\b(?:launch\w*|land\w*|reaches|arrives|begins|departs|returns)\b",
    ),
    (
        "politics",
        r"\b(?:declares independence|ratifies|is elected|is crowned|is sworn in|signs (?:the |a )?treaty|adopts (?:the |a )?constitution|becomes president)\b",
    ),
)
UNCERTAIN = re.compile(
    r"\b(?:circa|approximately|possibly|probably|allegedly|reportedly|uncertain|disputed|"
    r"traditionally|according to legend|by some accounts|date unknown|sometime|"
    r"following year|previous year|next year)\b|\b(?:c|ca)\.\s*\d|\b\d{3,4}\s*[–—/]\s*\d{2,4}\b",
    re.I,
)
UNSAFE = re.compile(r"[<>\[\]{}]|https?://|www\.|[\x00-\x1f\x7f]")
PAST_REFERENCE = re.compile(r"\b(?:after|before|anniversary of|commemorat\w*)\b", re.I)


def download_url(name: str) -> str:
    return f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}/{name}"


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _json(body: bytes) -> Any:
    try:
        return json.loads(
            body,
            object_pairs_hook=_object,
            parse_constant=lambda _: (_ for _ in ()).throw(
                ValueError("Nonfinite JSON")
            ),
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Malformed chronology JSON") from exc


def snapshot_bytes(root: Path) -> dict[str, bytes]:
    """Validate all bytes and lineage BEFORE yielding any candidate or committing."""
    bodies = {}
    for name in SNAPSHOT_FILES:
        path = root / name
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
            raise ValueError("Unsafe or missing chronology snapshot path")
        limit = MAX_FILE_BYTES if name == "events.jsonl" else 64 * 1024
        if path.stat().st_size > limit:
            raise ValueError("Chronology file byte bound")
        bodies[name] = path.read_bytes()
        if len(bodies[name]) > limit:
            raise ValueError("Chronology file byte bound")
        if (
            name in PINNED_FILES
            and hashlib.sha256(bodies[name]).hexdigest() != PINNED_FILES[name]
        ):
            raise ValueError("Unknown chronology snapshot SHA")
    receipt = _json(bodies["download-receipt.json"])
    if not isinstance(receipt, dict) or set(receipt) != {
        "repository",
        "commit",
        "retrieved_at",
        "files",
    }:
        raise ValueError("Invalid chronology download receipt")
    if receipt["repository"] != REPOSITORY or receipt["commit"] != COMMIT:
        raise ValueError("Unknown chronology repository/commit")
    try:
        acquired = datetime.fromisoformat(receipt["retrieved_at"])
        if acquired.utcoffset() is None:
            raise ValueError("Naive chronology acquisition time")
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid chronology acquisition time") from exc
    if not isinstance(receipt["files"], dict) or set(receipt["files"]) != set(
        PINNED_FILES
    ):
        raise ValueError("Incomplete chronology attribution receipt")
    for name, sha in PINNED_FILES.items():
        item = receipt["files"][name]
        if (
            not isinstance(item, dict)
            or item
            != {
                "sha256": sha,
                "bytes": len(bodies[name]),
                "status": 200,
                "url": download_url(name),
            }
            or type(item.get("bytes")) is not int
            or type(item.get("status")) is not int
        ):
            raise ValueError("Chronology download lineage mismatch")
    return bodies


def semantic_text(text: str) -> str:
    return re.sub(r"\W+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()


def raw_identity(raw: RawCandidate) -> str:
    row = raw.payload.get("row")
    if (
        isinstance(row, dict)
        and isinstance(row.get("event"), str)
        and type(row.get("year")) is int
    ):
        return (
            f"onthisday:{digest([semantic_text(row['event']), row['year']])}:chronology"
        )
    return f"unresolved:{raw.source_id}:{raw.record_id}"


def classify(text: str) -> tuple[str, str] | None:
    # Multiple sentences / retroactive references can associate another milestone
    # with the row date. Reject instead of trimming or rewriting the dataset body.
    if PAST_REFERENCE.search(text) or re.search(r"[.!?]\s+[A-Z]", text):
        return None
    for category, rule in RULES:
        match = re.search(rule, text, re.I)
        if match:
            if category == "inventions" and re.search(
                r"letters patent|patent medicine", text, re.I
            ):
                continue
            if category == "literature" and not re.search(
                r"\b(?:novel|book|poem|poetry|newspaper|journal|edition|issue|magazine|literary|publishes (?:his|her|their))\b",
                text,
                re.I,
            ):
                continue
            if category == "arts" and not re.search(
                r"\b(?:opera|symphony|ballet|film|play|musical|concert|theatre|theater)\b",
                text,
                re.I,
            ):
                continue
            return category, match[0]
    return None


class OnThisDayAdapter:
    def fetch(self, snapshot_dir: Path) -> Iterable[RawCandidate]:
        bodies = snapshot_bytes(snapshot_dir)
        receipt = _json(bodies["download-receipt.json"])
        lines = bodies["events.jsonl"].splitlines()
        if not lines or len(lines) > MAX_ROWS:
            raise ValueError("Chronology row bound")
        rows = []
        for line in lines:
            if not line or len(line) > MAX_LINE_BYTES:
                raise ValueError("Chronology line byte bound")
            row = _json(line)
            if not isinstance(row, dict):
                raise ValueError("Chronology row must be an object")
            rows.append(row)
        # Row shape/source problems are accountable quarantines, syntax failures
        # stop the entire generation. Ordering/line number is never an identity.
        for row in rows:
            yield RawCandidate(
                SOURCE_ID,
                digest(row),
                {
                    "row": row,
                    "repository": REPOSITORY,
                    "commit": COMMIT,
                    "evidence": [
                        {
                            "source_id": SOURCE_ID,
                            "sha256": PINNED_FILES["events.jsonl"],
                            "acquired_at": receipt["retrieved_at"],
                            "snapshot_id": f"{REPOSITORY}@{COMMIT}",
                            "url": download_url("events.jsonl"),
                        }
                    ],
                },
            )

    def normalize(self, raw: RawCandidate) -> EventRecord | tuple[ValidationIssue, ...]:
        def fail(code: str, field: str = "row") -> tuple[ValidationIssue, ...]:
            return (issue(code, field, "Chronology rule failed: " + code),)

        p: dict[str, Any] = raw.payload
        if raw.source_id != SOURCE_ID or set(p) != {
            "row",
            "repository",
            "commit",
            "evidence",
        }:
            return fail("adapter_mismatch")
        row = p["row"]
        if not isinstance(row, dict) or raw.record_id != digest(row):
            return fail("invalid_row")
        if p["repository"] != REPOSITORY or p["commit"] != COMMIT:
            return fail("missing_provenance")
        evidence = p["evidence"]
        if (
            not isinstance(evidence, list)
            or len(evidence) != 1
            or not isinstance(evidence[0], dict)
        ):
            return fail("missing_provenance")
        e = evidence[0]
        if set(e) != {"source_id", "sha256", "acquired_at", "snapshot_id", "url"} or (
            e["source_id"] != SOURCE_ID
            or e["sha256"] != PINNED_FILES["events.jsonl"]
            or e["snapshot_id"] != f"{REPOSITORY}@{COMMIT}"
            or e["url"] != download_url("events.jsonl")
        ):
            return fail("missing_provenance")
        try:
            acquired = datetime.fromisoformat(e["acquired_at"])
            if acquired.utcoffset() is None:
                return fail("missing_provenance")
        except ValueError, TypeError:
            return fail("missing_provenance")
        if (
            row.get("category") != "history"
            or row.get("source") != "Wikipedia contributors"
        ):
            return fail("excluded_source")
        numbers = {"year", "month", "day"}
        strings = {"date", "event", "category", "source", "source_url", "license"}
        if (
            set(row) != numbers | strings
            or any(type(row[n]) is not int for n in numbers)
            or any(type(row[s]) is not str for s in strings)
        ):
            return fail("invalid_row")
        if row["license"] != "CC BY-SA 4.0":
            return fail("invalid_license")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["date"]):
            return fail("invalid_date")
        try:
            parts = tuple(map(int, row["date"].split("-")))
            # Check civil component validity against a leap reference year; never
            # declare the historical date a proleptic Gregorian instant.
            date(2000, parts[1], parts[2])
            if parts[0] < 1:
                return fail("invalid_date")
        except ValueError, IndexError:
            return fail("invalid_date")
        if parts != (row["year"], row["month"], row["day"]):
            return fail("date_mismatch")
        if row["year"] > datetime.now(UTC).year:
            return fail("future_year")
        now = datetime.now(UTC)
        if parts > (now.year, now.month, now.day):
            return fail("future_event")
        if (
            row["source_url"]
            != f"https://en.wikipedia.org/wiki/{MONTHS[row['month'] - 1]}_{row['day']}"
        ):
            return fail("source_url_mismatch")
        text = row["event"]
        if not 12 <= len(text.encode()) <= 2048 or UNSAFE.search(text):
            return fail("unsafe_prompt")
        if UNCERTAIN.search(text):
            return fail("uncertain_event")
        explicit_years = re.findall(
            r"\b(?:in|during|since|year)\s+(\d{3,4})\b", text, re.I
        )
        if any(int(year) != row["year"] for year in explicit_years):
            return fail("contradictory_event_year")
        classified = classify(text)
        if classified is None:
            return fail("unresolved_category")
        category, evidence_text = classified
        identity = raw_identity(raw)
        event = EventRecord(
            event_id=uuid5(NAMESPACE_URL, identity),
            identity_key=identity,
            prompt=text,
            year_index=row["year"],
            category_ids=(category,),
            region_ids=(),
            explanation=f"{text}\nReported civil year in the retained chronology; not a Gregorian day conversion. Category heuristic: {category} ({evidence_text}).",
            sources=(
                SourceCitation(
                    source_id=SOURCE_ID,
                    record_id=raw.record_id,
                    url=row["source_url"],
                    rights_basis=TEXT_CREDIT + " License: " + TEXT_LICENSE_URL,
                    raw_date=row["date"],
                    calendar="historical-civil-year",
                    acquired_at=acquired,
                    snapshot_id=e["snapshot_id"]
                    + ":sha256="
                    + e["sha256"]
                    + ";download="
                    + e["url"],
                    date_resolution=f"source-resolved:historical-civil-year:year_index={row['year']}",
                ),
            ),
            date_precision="year",
            review_status="approved",
            media_asset_id=None,
            fallback_key=category,
        )
        issues = validate_event(
            event,
            (CategoryRecord(id=category, label=category),),
            datetime.now(UTC).year,
        )
        return issues or event
