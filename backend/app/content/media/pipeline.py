"""Event-specific lookup, recoverable staging and whole-batch final receipts.

The C3 pointer is never changed. media-staging.json is an atomic private draft
pointer; media-current.json is the sole C4 handoff commit point. Readers resolve
each once, never union generations. POSIX single-writer filesystem semantics.
"""

import fcntl
import hashlib
import json
import re
import time
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from html.parser import HTMLParser
from importlib.metadata import version as package_version
from pathlib import Path
from platform import python_version
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import NAMESPACE_URL, uuid5
from xml.etree import ElementTree

import httpx
from PIL import Image

from app.content.adapters.base import RawCandidate
from app.content.adapters.selected import SelectedSourceAdapter, digest
from app.content.importer import _jsonl, _sources, _sync_directory, _write
from app.content.media.download import UA, asset_sha256, download_image, immutable_write
from app.content.media.prepare import MAX_DIMENSION, MAX_PIXELS, prepare_image
from app.content.media.rights import (
    LICENSES,
    PD_BASES,
    RISK,
    MediaCandidate,
    check_candidate,
    composition_kind,
    date_bearing,
)
from app.content.schemas import (
    CategoryRecord,
    EventRecord,
    FallbackRecord,
    MediaCatalog,
    MediaRecord,
    SourceSelection,
    ValidationReceipt,
)
from app.content.validation import (
    VALIDATION_POLICY_VERSION,
    _answer_in_prompt,
    candidate_digest,
    media_catalog_digest,
    validate_event,
)

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
CC0_USAGE_TERMS = {
    "creative commons cc0 1.0 universal public domain dedication",
    "cc0 1.0 universal public domain dedication",
    "cc0 1.0 universal",
    "public domain dedication",
    "cc0",
}
FALLBACKS = dict(
    zip(
        (
            "births",
            "deaths",
            "battles",
            "inventions",
            "literature",
            "arts",
            "exploration",
            "politics",
        ),
        (
            "birth",
            "death",
            "battle",
            "invention",
            "book",
            "art",
            "exploration",
            "politics",
        ),
        strict=True,
    )
)
SVG_TAGS = {"svg", "rect", "circle", "path"}
SVG_ATTRIBUTES = {
    "viewBox",
    "role",
    "aria-label",
    "width",
    "height",
    "rx",
    "fill",
    "cx",
    "cy",
    "r",
    "d",
    "x",
    "y",
    "stroke",
    "stroke-width",
    "stroke-linecap",
}


def media_rules_digest() -> str:
    """Current offline rules/dependencies, independently recomputed for C5.

    The shared automated-v1 receipt schema stays unchanged. Its batch must also
    match this fingerprint before publication; a historical receipt alone is
    not proof under corrected rules or changed decoding/lookup dependencies.
    """
    content_root = Path(__file__).parents[1]
    sources = (
        *sorted(content_root.joinpath("media").glob("*.py")),
        *sorted(content_root.joinpath("fallbacks").glob("*.svg")),
        content_root / "schemas.py",
        content_root / "validation.py",
        content_root / "importer.py",
        content_root / "adapters" / "selected.py",
    )
    return digest(
        {
            "rules": "commons-media-v2",
            "source_sha256": {
                str(path.relative_to(content_root)): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in sources
            },
            "dependencies": {
                name: package_version(name)
                for name in ("pillow", "httpx", "pydantic", "mwparserfromhell")
            },
            "python": python_version(),
        }
    )


@dataclass(frozen=True)
class MediaDecision:
    media: MediaRecord | None
    fallback_key: str
    reason: str | None


def fallback_key(event: EventRecord) -> str:
    milestone = event.identity_key.rsplit(":", 1)[-1]
    if milestone in {"birth", "death"}:
        return milestone
    for category in event.category_ids:
        if category in FALLBACKS:
            return FALLBACKS[category]
    raise ValueError("unmapped_event_type")


def check_fallback(record: FallbackRecord, data: bytes) -> tuple[str, ...]:
    try:
        if len(data) > 64 * 1024 or b"<!" in data or b"<?" in data:
            raise ValueError("unsafe_svg")
        root = ElementTree.fromstring(data)
        if (
            root.tag != "{http://www.w3.org/2000/svg}svg"
            or root.get("viewBox") != "0 0 480 320"
        ):
            raise ValueError("unsafe_svg")
        for element in root.iter():
            tag = element.tag.removeprefix("{http://www.w3.org/2000/svg}")
            if (
                tag not in SVG_TAGS
                or set(element.attrib) - SVG_ATTRIBUTES
                or (element.text or "").strip()
            ):
                raise ValueError("unsafe_svg")
            for name, value in element.attrib.items():
                if (
                    "url(" in value
                    or "javascript" in value
                    or "http" in value
                    or (
                        name in {"fill", "stroke"}
                        and not re.fullmatch(r"#[a-fA-F0-9]{6}|none", value)
                    )
                ):
                    raise ValueError("unsafe_svg")
        if (
            record.key not in FALLBACKS.values()
            or record.key not in record.alt_text.lower()
            or not record.alt_text.startswith("Representative ")
            or record.rights_basis != "Original authored artwork; CC0 1.0"
            or date_bearing(record.alt_text + " " + record.creator)
            or RISK.search(record.alt_text + " " + record.creator)
            or record.key not in root.get("aria-label", "")
            or root.get("aria-label") != record.alt_text
        ):
            raise ValueError("fallback_provenance_or_mapping")
        if hashlib.sha256(data).hexdigest() != record.sha256:
            raise ValueError("asset_integrity")
    except ValueError, ElementTree.ParseError:
        return ("unsafe_fallback",)
    return ()


def install_fallbacks(output_dir: Path) -> dict[str, FallbackRecord]:
    records = {}
    for key in FALLBACKS.values():
        data = (Path(__file__).parents[1] / "fallbacks" / f"{key}.svg").read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        record = FallbackRecord(
            key=key,
            filename=f"media/{sha}.svg",
            sha256=sha,
            alt_text=ElementTree.fromstring(data).get("aria-label", ""),
            creator="Historical Date Game original geometric illustrations",
            rights_basis="Original authored artwork; CC0 1.0",
        )
        if check_fallback(record, data):
            raise ValueError("invalid_packaged_fallback")
        immutable_write(output_dir / record.filename, data)
        records[key] = record
    return records


def _generation(workspace: Path, pointer_name: str) -> tuple[Path, dict[str, Any]]:
    pointer = json.loads((workspace / pointer_name).read_text())
    relative = Path(pointer["generation"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("unsafe_workspace_pointer")
    target = workspace / relative
    if not target.resolve().is_relative_to(workspace.resolve()):
        raise ValueError("unsafe_workspace_pointer")
    return target, pointer


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _inputs(
    workspace: Path,
) -> tuple[Path, dict[str, Any], list[EventRecord], list[RawCandidate]]:
    generation, pointer = _generation(workspace, "current.json")
    events = [
        EventRecord.model_validate_json(json.dumps(row))
        for row in _rows(generation / "candidates.jsonl")
    ]
    if len({e.event_id for e in events}) != len(events):
        raise ValueError("duplicate_event_ids")
    raws = [RawCandidate(**row) for row in _rows(generation / "raw.jsonl")]
    return generation, pointer, events, raws


def _event_raws(event: EventRecord, raws: list[RawCandidate]) -> list[RawCandidate]:
    return [
        raw
        for raw in raws
        if f"wikidata:{raw.payload.get('entity_id')}:{raw.payload.get('milestone')}"
        == event.identity_key
    ]


def _titles(raws: list[RawCandidate]) -> tuple[str, ...]:
    titles: set[str] = set()
    for raw in raws:
        payload: dict[str, Any] = raw.payload
        for claim in payload.get("entity", {}).get("claims", {}).get("P18", []):
            if claim.get("rank") == "deprecated" or claim.get("qualifiers"):
                continue
            snak = claim.get("mainsnak", {})
            value = snak.get("datavalue", {}).get("value")
            if (
                snak.get("snaktype") == "value"
                and isinstance(value, str)
                and 0 < len(value) <= 240
                and not any(c in value for c in "|\n\r{}[]")
            ):
                titles.add("File:" + value.replace("_", " "))
    return tuple(sorted(titles))[:3]


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                if href.startswith("//"):
                    href = "https:" + href
                elif href.startswith("/"):
                    href = "https://commons.wikimedia.org" + href
                parsed = urlsplit(href)
                if parsed.scheme != "https" or parsed.username or parsed.password:
                    raise ValueError("unsafe_required_credit_link")
                # Required linked attribution is never silently discarded.
                self.parts.append("(" + href + ")")


def _plain(value: str) -> str:
    parser = _PlainText()
    parser.feed(value)
    return " ".join(" ".join(parser.parts).split())


def _commons_metadata(
    workspace: Path, title: str, *, fetch: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = workspace / "media-cache" / "commons"
    stem = hashlib.sha256(title.encode()).hexdigest()
    target = root / f"{stem}.json"
    meta_path = root / f"{stem}.meta.json"
    if not target.exists():
        if not fetch:
            raise ValueError("missing_commons_snapshot")
        # Selected, exact P18 titles only. Serial, at most three per event; no
        # broad search, retry storm, redirects or credentials.
        time.sleep(1)
        with httpx.Client(
            timeout=10, follow_redirects=False, trust_env=False
        ) as client:
            data = bytearray()
            with client.stream(
                "GET",
                COMMONS_API,
                params={
                    "action": "query",
                    "format": "json",
                    "formatversion": "2",
                    "maxlag": "5",
                    "titles": title,
                    "prop": "imageinfo",
                    "iiprop": "url|timestamp|sha1|mime|extmetadata",
                    "iilimit": "1",
                },
                headers={"User-Agent": UA, "Accept-Encoding": "identity"},
            ) as response:
                if response.status_code != 200:
                    raise ValueError(f"commons_http_{response.status_code}")
                started = time.monotonic()
                for chunk in response.iter_bytes(64 * 1024):
                    if (
                        len(data) + len(chunk) > 1024 * 1024
                        or time.monotonic() - started > 20
                    ):
                        raise ValueError("commons_response_limits")
                    data.extend(chunk)
            body = bytes(data)
        metadata = {
            "sha256": hashlib.sha256(body).hexdigest(),
            "acquired_at": datetime.now(UTC).isoformat(),
            "endpoint": COMMONS_API,
        }
        immutable_write(target, body)
        immutable_write(meta_path, json.dumps(metadata, sort_keys=True).encode())
    if (
        target.is_symlink()
        or meta_path.is_symlink()
        or target.stat().st_size > 1024 * 1024
    ):
        raise ValueError("unsafe_commons_cache")
    body = target.read_bytes()
    metadata = json.loads(meta_path.read_text())
    if (
        metadata["sha256"] != hashlib.sha256(body).hexdigest()
        or metadata["endpoint"] != COMMONS_API
    ):
        raise ValueError("commons_snapshot_digest")
    data_json = json.loads(body)
    if "error" in data_json:
        raise ValueError("commons_api_error")
    return data_json, metadata


def _candidate(
    event: EventRecord,
    title: str,
    data: dict[str, Any],
    metadata: dict[str, Any],
    raws: list[RawCandidate],
) -> MediaCandidate:
    pages = data.get("query", {}).get("pages", [])
    if isinstance(pages, dict):
        pages = list(pages.values())
    if len(pages) != 1:
        raise ValueError("missing_commons_file")
    page = pages[0]
    if (
        page.get("title", "").replace("_", " ") != title
        or page.get("imagerepository") != "local"
    ):
        raise ValueError("non_commons_origin")
    infos = page.get("imageinfo", [])
    if len(infos) != 1:
        raise ValueError("missing_commons_file")
    info = infos[0]
    if info.get("mime") not in {"image/jpeg", "image/png", "image/webp"}:
        raise ValueError("unsupported_image_mime")
    fields = {
        key: _plain(str(value.get("value", "")))
        for key, value in info.get("extmetadata", {}).items()
    }
    if RISK.search(" ".join(key + " " + value for key, value in fields.items())):
        raise ValueError("unsafe_or_unresolved_file_metadata")
    if date_bearing(
        " ".join(
            value
            for key, value in fields.items()
            if key not in {"License", "LicenseShortName", "LicenseUrl", "UsageTerms"}
        )
    ):
        raise ValueError("date_bearing_metadata_or_required_credit")
    rights = fields.get("LicenseShortName", "")
    if rights == "CC0 1.0":
        rights = "CC0"
    if rights == "Public domain":
        rights = fields.get("License", "")
    if rights in PD_BASES and fields.get("Copyrighted") != "False":
        raise ValueError("license_conflict")
    if rights not in PD_BASES and rights not in LICENSES:
        raise ValueError("unsupported_rights")
    token = fields.get("License", "")
    expected_token = rights.lower().replace(" ", "-")
    supported_tokens = {expected_token, rights}
    if rights == "CC0":
        supported_tokens.add("cc-zero")
    if token and token not in supported_tokens:
        raise ValueError("license_conflict")
    if rights.startswith("CC BY") and fields.get("AttributionRequired") != "True":
        raise ValueError("license_conflict")
    if any(
        fields.get(key, "") for key in ("Restrictions", "Permission", "DeletionReason")
    ):
        raise ValueError("unresolved_rights_or_sensitivity")
    creator = fields.get("Artist", "")
    credit = fields.get("Credit", "")
    if (
        not creator
        or not credit
        or re.search(r"\b(unknown|anonymous)\b", creator, re.I)
    ):
        raise ValueError("missing_credit")
    if rights == "CC0":
        if (
            fields.get("Copyrighted") != "False"
            or fields.get("AttributionRequired") != "False"
        ):
            raise ValueError("license_conflict")
        # Dedication is not attribution/share-alike licensing. Accept only
        # explicit supported CC0/public-domain declarations, never arbitrary
        # terms merely because they lack an attribution requirement.
        if (
            fields.get("UsageTerms")
            and fields["UsageTerms"].casefold() not in CC0_USAGE_TERMS
        ):
            raise ValueError("license_conflict")
    elif fields.get("UsageTerms") and rights.startswith("CC BY"):
        terms = fields["UsageTerms"].casefold()
        expected = "share alike" if "BY-SA" in rights else "attribution"
        if expected not in terms or re.search(
            r"non.?commercial|no.?derivatives|all rights reserved", terms
        ):
            raise ValueError("license_conflict")
        if rights.startswith("CC BY") and rights.rsplit(" ", 1)[-1] not in terms:
            raise ValueError("license_conflict")
    origin = urlsplit(info.get("url", ""))
    if origin.hostname != "upload.wikimedia.org" or not origin.path.startswith(
        "/wikipedia/commons/"
    ):
        raise ValueError("non_commons_origin")
    source_url = info["descriptionurl"]
    if unquote(urlsplit(source_url).path).replace("_", " ") != "/wiki/" + title:
        raise ValueError("commons_title_conflict")
    # P18 is exact subject evidence, not a promise of an event photograph.
    # Editions, art rights and sensitive conflict/civic scenes need stronger
    # evidence than this adapter supports, so never infer them from a lead image.
    if set(event.category_ids) - {"births", "deaths", "inventions", "exploration"}:
        raise ValueError("unresolved_event_relevance_or_sensitivity")
    description = fields.get("ImageDescription", "")
    if "portrait photograph" in description.casefold() and not set(
        event.category_ids
    ) <= {"births", "deaths"}:
        raise ValueError("unresolved_event_relevance")
    revision = (
        info["timestamp"] + ";sha1=" + info["sha1"] + ";metadata=" + metadata["sha256"]
    )
    return MediaCandidate(
        asset_id=uuid5(NAMESPACE_URL, source_url + revision),
        source_url=source_url,
        creator=creator,
        rights_basis=rights,
        attribution=" / ".join(
            filter(
                None,
                (
                    creator,
                    credit,
                    fields.get("ObjectName"),
                    fields.get("Attribution"),
                    "Wikimedia Commons",
                    rights,
                ),
            )
        ),
        license_url=fields.get("LicenseUrl") or None,
        adaptation_allowed=True,
        alt_text="Subject-context "
        + (
            "portrait photograph"
            if "portrait photograph" in description.casefold()
            else "object photograph"
        ),
        fit="contain",
        acquired_at=datetime.fromisoformat(
            metadata["acquired_at"].replace("Z", "+00:00")
        ),
        source_revision=revision,
        repository="commons",
        download_url=info["url"],
        upstream_sha1=info["sha1"],
        metadata_sha256=metadata["sha256"],
        title=title,
        subject_name=_source_subject(raws),
        work_title=fields.get("ObjectName") or None,
        description=description,
        categories=tuple(fields.get("Categories", "").split("|")),
        entity_id=event.identity_key.split(":")[1],
        relevance="source-P18-subject-context",
    )


def _source_subject(raws: list[RawCandidate]) -> str:
    names = set()
    for raw in raws:
        payload: dict[str, Any] = raw.payload
        name = payload.get("entity", {}).get("labels", {}).get("en", {}).get(
            "value"
        ) or payload.get("page", {}).get("title")
        if not isinstance(name, str) or not 0 < len(name) <= 120:
            raise ValueError("unresolved_source_subject")
        names.add(name)
    if len(names) != 1:
        raise ValueError("unresolved_source_subject")
    return names.pop()


def _event_candidate_codes(event: EventRecord, item: MediaCandidate) -> tuple[str, ...]:
    codes = set(check_candidate(item))
    kind = composition_kind(item)
    categories = {
        "person": {"births", "deaths"},
        "object": {"inventions"},
        "ship": {"exploration"},
    }
    if kind is not None and not set(event.category_ids) <= categories[kind]:
        codes.add("unresolved_event_relevance")
    visible = " ".join(
        (
            item.creator,
            item.attribution,
            item.alt_text,
            unquote(item.source_url),
            item.title,
            item.description,
        )
    )
    civil_year = event.year_index if event.year_index > 0 else 1 - event.year_index
    if _answer_in_prompt(event.model_copy(update={"prompt": visible}), {civil_year}):
        codes.add("date_bearing_event_credit_or_metadata")
    return tuple(sorted(codes))


def _acquire(
    workspace: Path, candidate: MediaCandidate, selection: SourceSelection
) -> MediaCandidate:
    root = workspace / "media-cache" / "originals"
    root.mkdir(parents=True, exist_ok=True)
    original = root / f"{candidate.upstream_sha1}.bin"
    meta_path = original.with_suffix(".meta.json")
    if not original.exists():
        acquired_at = datetime.now(UTC)
        download_image(candidate.download_url, original, selection.allowed_media_hosts)
        if hashlib.sha1(original.read_bytes()).hexdigest() != candidate.upstream_sha1:
            raise ValueError("upstream_digest_mismatch")
        immutable_write(
            meta_path,
            json.dumps(
                {
                    "url": candidate.download_url,
                    "acquired_at": acquired_at.isoformat(),
                    "sha1": candidate.upstream_sha1,
                },
                sort_keys=True,
            ).encode(),
        )
    if original.is_symlink() or not meta_path.exists():
        raise ValueError("incomplete_original_cache")
    evidence = json.loads(meta_path.read_text())
    if (
        evidence["sha1"] != candidate.upstream_sha1
        or evidence["url"] != candidate.download_url
    ):
        raise ValueError("original_cache_conflict")
    return candidate.model_copy(
        update={"acquired_at": datetime.fromisoformat(evidence["acquired_at"])}
    )


def _commit_generation(
    workspace: Path,
    prefix: str,
    pointer: str,
    files: dict[str, str],
    extra: dict[str, Any],
) -> Path:
    sha = digest(files)
    relative = Path(prefix) / f"{sha}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}"
    target = workspace / relative
    target.mkdir(parents=True)
    for name, text in files.items():
        _write(target / name, text)
    _sync_directory(target)
    _sync_directory(target.parent)
    temporary = workspace / (pointer + ".tmp")
    _write(
        temporary,
        json.dumps(
            {"generation": str(relative), "batch_sha256": sha, **extra}, sort_keys=True
        ),
    )
    temporary.replace(workspace / pointer)
    _sync_directory(workspace)
    return target


def assign_media(
    event: EventRecord, selection: SourceSelection, workspace: Path
) -> MediaDecision:
    with (
        (workspace / ".import.lock").open("a") as content_lock,
        (workspace / ".media.lock").open("a") as lock,
    ):
        fcntl.flock(content_lock, fcntl.LOCK_EX)
        fcntl.flock(lock, fcntl.LOCK_EX)
        _, pointer, events, raws = _inputs(workspace)
        current = next(
            (item for item in events if item.event_id == event.event_id), None
        )
        if current != event:
            raise ValueError("stale_or_unknown_event")
        if set(selection.source_ids) != {
            "wikidata",
            "wikipedia_en",
        } or selection.allowed_media_hosts != ("upload.wikimedia.org",):
            raise ValueError("unsupported_media_selection")
        assignments: dict[str, Any] = {}
        decisions: dict[str, Any] = {}
        records: dict[str, MediaRecord] = {}
        rules_sha = media_rules_digest()
        assets = workspace / "media-assets"
        fallbacks = install_fallbacks(assets)
        if (workspace / "media-staging.json").exists():
            stage, staged_pointer = _generation(workspace, "media-staging.json")
            if (
                staged_pointer["content_generation"] == pointer["generation"]
                and staged_pointer.get("media_rules_sha256") == rules_sha
            ):
                assignments = json.loads((stage / "assignments.json").read_text())
                decisions = json.loads((stage / "decisions.json").read_text())
                catalog = MediaCatalog.model_validate_json(
                    (stage / "media.json").read_text()
                )
                records = {str(record.asset_id): record for record in catalog.records}
        attempts: list[dict[str, Any]] = []
        selected: MediaRecord | None = None
        evidence: MediaCandidate | None = None
        titles = _titles(_event_raws(event, raws))
        for title in titles:
            attempt: dict[str, Any] = {
                "title": title,
                "lookup": "exact-source-P18",
                "entity_id": event.identity_key.split(":")[1],
            }
            try:
                data, metadata = _commons_metadata(workspace, title, fetch=True)
                attempt["metadata_sha256"] = metadata["sha256"]
                # Preserve exact mandatory-credit metadata even when rejected.
                attempt["file_metadata"] = data
                item = _candidate(
                    event, title, data, metadata, _event_raws(event, raws)
                )
                attempt["candidate"] = item.model_dump(mode="json")
                codes = _event_candidate_codes(event, item)
                if codes:
                    raise ValueError(",".join(codes))
                item = _acquire(workspace, item, selection)
                original = (
                    workspace
                    / "media-cache"
                    / "originals"
                    / f"{item.upstream_sha1}.bin"
                )
                selected = prepare_image(original, assets, item)
                evidence = item
                attempt["outcome"] = "prepared"
                attempts.append(attempt)
                break
            except (ValueError, KeyError, TypeError, OSError, httpx.HTTPError) as exc:
                attempt["outcome"] = "fallback"
                attempt["reason"] = str(exc) or type(exc).__name__
                attempts.append(attempt)
        key = fallback_key(event)
        reason = (
            None
            if selected
            else (
                ";".join(str(a["reason"]) for a in attempts)
                or "no_selected_source_image_candidate"
            )
        )
        assigned = event.model_copy(
            update={
                "media_asset_id": selected.asset_id if selected else None,
                "fallback_key": key,
            }
        )
        assignments[str(event.event_id)] = assigned.model_dump(mode="json")
        if selected:
            records[str(selected.asset_id)] = selected
        decisions[str(event.event_id)] = {
            "event_id": str(event.event_id),
            "input_candidate_sha256": candidate_digest(event),
            "candidate_sha256": candidate_digest(assigned),
            "source_sha256": _sources(_event_raws(event, raws)),
            "policy_version": VALIDATION_POLICY_VERSION,
            "media_rules_sha256": rules_sha,
            "selection": selection.model_dump(mode="json"),
            "attempts": attempts,
            "candidate": evidence.model_dump(mode="json") if evidence else None,
            "fallback_key": key,
            "reason": reason,
        }
        referenced_ids = {
            assignment["media_asset_id"] for assignment in assignments.values()
        }
        catalog = MediaCatalog(
            records=tuple(
                record for key, record in records.items() if key in referenced_ids
            ),
            fallbacks=fallbacks,
        )
        _commit_generation(
            workspace,
            "media-staging",
            "media-staging.json",
            {
                "assignments.json": json.dumps(assignments, sort_keys=True),
                "decisions.json": json.dumps(decisions, sort_keys=True),
                "media.json": catalog.model_dump_json(),
            },
            {
                "content_generation": pointer["generation"],
                "content_input_sha256": pointer["input_sha256"],
                "media_rules_sha256": rules_sha,
            },
        )
        return MediaDecision(media=selected, fallback_key=key, reason=reason)


def _recheck_content(
    event: EventRecord, raws: list[RawCandidate], sources: dict[str, Any]
) -> set[str]:
    codes: set[str] = set()
    if not raws:
        return {"missing_current_sources"}
    adapter = SelectedSourceAdapter()
    normalized = []
    for raw in raws:
        source_key = json.dumps([raw.source_id, raw.record_id], separators=(",", ":"))
        if sources.get("records", {}).get(source_key, {}).get("raw_sha256") != digest(
            {
                "source_id": raw.source_id,
                "record_id": raw.record_id,
                "payload": raw.payload,
            }
        ):
            codes.add("source_integrity")
        result = adapter.normalize(raw)
        if isinstance(result, EventRecord):
            normalized.append(result)
        else:
            codes.update(issue.code for issue in result)
    if adapter.alias_dates_conflict(raws):
        codes.add("conflicting_dates")
    if normalized:
        for other in normalized:
            if any(
                getattr(other, field) != getattr(event, field)
                for field in (
                    "event_id",
                    "identity_key",
                    "prompt",
                    "year_index",
                    "explanation",
                )
            ):
                codes.add("current_content_mismatch")
        citations = {source for other in normalized for source in other.sources}
        if (
            set(event.sources) != citations
            or set(event.category_ids)
            != {c for other in normalized for c in other.category_ids}
            or set(event.region_ids)
            != {r for other in normalized for r in other.region_ids}
        ):
            codes.add("current_content_mismatch")
        ranks = {"year": 1, "month": 2, "day": 3}
        if event.date_precision != min(
            (other.date_precision for other in normalized), key=ranks.__getitem__
        ):
            codes.add("current_content_mismatch")
    return codes


def _check_assets(catalog: MediaCatalog, assets: Path) -> set[str]:
    codes: set[str] = set()
    if set(catalog.fallbacks) != set(FALLBACKS.values()):
        codes.add("incomplete_fallback_catalog")
    for record in _catalog_assets(catalog):
        path = assets / record.filename
        try:
            if asset_sha256(path) != record.sha256:
                codes.add("asset_integrity")
                continue
            if isinstance(record, FallbackRecord):
                codes.update(check_fallback(record, path.read_bytes()))
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(path) as image:
                        if (
                            image.format != "WEBP"
                            or image.width * image.height > MAX_PIXELS
                            or max(image.size) > MAX_DIMENSION
                            or image.getexif()
                            or set(image.info) - {"loop", "background"}
                            or getattr(image, "n_frames", 1) != 1
                        ):
                            codes.add("unsafe_prepared_image")
                        image.load()
        except (
            OSError,
            ValueError,
            Image.DecompressionBombWarning,
            Image.DecompressionBombError,
        ):
            codes.add("asset_integrity")
    return codes


def _catalog_assets(catalog: MediaCatalog) -> tuple[MediaRecord | FallbackRecord, ...]:
    return (*catalog.records, *catalog.fallbacks.values())


def _recheck_media(
    workspace: Path,
    event: EventRecord,
    original: EventRecord,
    raws: list[RawCandidate],
    decision: dict[str, Any],
    catalog: MediaCatalog,
) -> set[str]:
    codes: set[str] = set()
    if (
        decision["input_candidate_sha256"] != candidate_digest(original)
        or decision["candidate_sha256"] != candidate_digest(event)
        or tuple(decision["source_sha256"]) != _sources(raws)
        or decision["policy_version"] != VALIDATION_POLICY_VERSION
    ):
        codes.add("stale_media_decision")
    if (
        event.fallback_key != fallback_key(event)
        or event.fallback_key not in catalog.fallbacks
    ):
        codes.add("fallback_mapping")
    else:
        fallback = catalog.fallbacks[event.fallback_key]
        civil_year = event.year_index if event.year_index > 0 else 1 - event.year_index
        if _answer_in_prompt(
            event.model_copy(
                update={"prompt": fallback.alt_text + " " + fallback.creator}
            ),
            {civil_year},
        ):
            codes.add("date_bearing_fallback_metadata")
    if event.media_asset_id is None:
        if not decision.get("reason") or decision.get("candidate"):
            codes.add("missing_fallback_evidence")
        return codes
    try:
        evidence = MediaCandidate.model_validate_json(json.dumps(decision["candidate"]))
        if not re.fullmatch(r"[0-9a-f]{40}", evidence.upstream_sha1):
            raise ValueError("invalid_original_digest")
        codes.update(_event_candidate_codes(event, evidence))
        if (
            evidence.title not in _titles(raws)
            or evidence.entity_id != event.identity_key.split(":")[1]
        ):
            codes.add("unresolved_relevance")
        data, metadata = _commons_metadata(workspace, evidence.title, fetch=False)
        rebuilt = _candidate(original, evidence.title, data, metadata, raws)
        rebuilt = rebuilt.model_copy(update={"acquired_at": evidence.acquired_at})
        if rebuilt != evidence:
            codes.add("current_media_evidence_mismatch")
        selection = SourceSelection.model_validate_json(
            json.dumps(decision["selection"])
        )
        if selection.allowed_media_hosts != ("upload.wikimedia.org",) or set(
            selection.source_ids
        ) != {"wikidata", "wikipedia_en"}:
            codes.add("unsupported_media_selection")
        # Re-decode the digest-bound original and independently recompute the
        # derivative record; this also rechecks optional metadata and SHA-1.
        record = next(
            record
            for record in catalog.records
            if record.asset_id == event.media_asset_id
        )
        original_path = (
            workspace / "media-cache" / "originals" / f"{evidence.upstream_sha1}.bin"
        )
        acquisition = json.loads(original_path.with_suffix(".meta.json").read_text())
        if (
            acquisition["sha1"] != evidence.upstream_sha1
            or acquisition["url"] != evidence.download_url
            or datetime.fromisoformat(acquisition["acquired_at"])
            != evidence.acquired_at
        ):
            codes.add("original_acquisition_mismatch")
        with TemporaryDirectory(prefix="media-recheck-") as temporary:
            regenerated = prepare_image(original_path, Path(temporary), evidence)
        if record != regenerated:
            codes.add("media_record_mismatch")
    except ValueError, KeyError, TypeError, OSError, StopIteration:
        codes.add("invalid_media_evidence")
    return codes


def finalize_media_receipts(workspace: Path) -> tuple[ValidationReceipt, ...]:
    """Freeze the complete catalog, then recheck EVERY event and actual asset.

    Failed receipts are persisted too; no changed C3 input or incomplete staging
    can advance the final pointer. Never reuse C3 or previous C4 pass flags.
    """
    with (
        (workspace / ".import.lock").open("a") as content_lock,
        (workspace / ".media.lock").open("a") as lock,
    ):
        fcntl.flock(content_lock, fcntl.LOCK_EX)
        fcntl.flock(lock, fcntl.LOCK_EX)
        content, pointer, originals, raws = _inputs(workspace)
        stage, stage_pointer = _generation(workspace, "media-staging.json")
        assignments = json.loads((stage / "assignments.json").read_text())
        decisions = json.loads((stage / "decisions.json").read_text())
        ids = {str(event.event_id) for event in originals}
        if (
            stage_pointer["content_generation"] != pointer["generation"]
            or stage_pointer["content_input_sha256"] != pointer["input_sha256"]
            or set(assignments) != ids
            or set(decisions) != ids
            or not ids
        ):
            raise ValueError("complete_current_media_batch_required")
        events = [
            EventRecord.model_validate_json(json.dumps(assignments[str(e.event_id)]))
            for e in originals
        ]
        # Typed independent serialization freezes the entire catalog before any
        # receipt check; all catalog fields, even unreferenced ones, are bound.
        catalog = MediaCatalog.model_validate_json((stage / "media.json").read_text())
        frozen = catalog.model_dump_json()
        catalog = MediaCatalog.model_validate_json(frozen)
        catalog_sha = media_catalog_digest(catalog)
        rules_sha = media_rules_digest()
        now = datetime.now(UTC)
        # Freeze the bytes too, before any validation receipt. Later corruption
        # of shared draft assets cannot change this generation's checked bytes.
        relative = (
            Path("media-generations")
            / f"{catalog_sha}-{now.strftime('%Y%m%dT%H%M%S%f')}"
        )
        target = workspace / relative
        target.mkdir(parents=True)
        for record in _catalog_assets(catalog):
            source = workspace / "media-assets" / record.filename
            if source.exists() and not source.is_symlink():
                asset_sha256(source)  # bounds before the read/copy
                immutable_write(target / record.filename, source.read_bytes())
        # C5 must reconstruct rights/provenance from this frozen generation,
        # never from the mutable acquisition cache. Snapshot only selected files.
        private_files: dict[str, str] = {}
        snapshot_codes: set[str] = set()
        for decision in decisions.values():
            if not decision.get("candidate"):
                continue
            try:
                evidence = MediaCandidate.model_validate_json(
                    json.dumps(decision["candidate"])
                )
                if not re.fullmatch(r"[0-9a-f]{40}", evidence.upstream_sha1):
                    raise ValueError("invalid_original_digest")
                stem = hashlib.sha256(evidence.title.encode()).hexdigest()
                for name in (
                    f"media-cache/commons/{stem}.json",
                    f"media-cache/commons/{stem}.meta.json",
                    f"media-cache/originals/{evidence.upstream_sha1}.bin",
                    f"media-cache/originals/{evidence.upstream_sha1}.meta.json",
                ):
                    source = workspace / name
                    if any(p.is_symlink() for p in (source, *source.parents)):
                        raise ValueError("unsafe_private_snapshot")
                    data = source.read_bytes()
                    immutable_write(target / name, data)
                    private_files[name] = hashlib.sha256(data).hexdigest()
            except ValueError, OSError:
                snapshot_codes.add("incomplete_private_media_snapshot")
        taxonomy_data = json.loads(
            Path(__file__).parents[1].joinpath("taxonomy.json").read_text()
        )
        taxonomy = tuple(
            CategoryRecord.model_validate_json(json.dumps(row)) for row in taxonomy_data
        )
        sources = json.loads((content / "sources.json").read_text())
        global_codes = _check_assets(catalog, target) | snapshot_codes
        if stage_pointer.get("media_rules_sha256") != rules_sha or any(
            decision.get("media_rules_sha256") != rules_sha
            for decision in decisions.values()
        ):
            global_codes.add("stale_media_rules")
        if sources.get("input_sha256") != pointer["input_sha256"]:
            global_codes.add("source_integrity")
        if tuple(sources.get("source_sha256", [])) != _sources(raws):
            global_codes.add("source_integrity")
        referenced = {e.media_asset_id for e in events if e.media_asset_id is not None}
        if referenced != {r.asset_id for r in catalog.records}:
            global_codes.add("unreviewed_catalog_record")
        receipts = []
        for original, event in zip(originals, events, strict=True):
            codes = set(global_codes)
            # Assignments may change only media references, never event content.
            if (
                event.model_copy(
                    update={
                        "media_asset_id": original.media_asset_id,
                        "fallback_key": original.fallback_key,
                    }
                )
                != original
            ):
                codes.add("assignment_content_changed")
            event_raws = _event_raws(event, raws)
            codes.update(
                issue.code for issue in validate_event(event, taxonomy, now.year)
            )
            codes.update(_recheck_content(event, event_raws, sources))
            codes.update(
                _recheck_media(
                    target,
                    event,
                    original,
                    event_raws,
                    decisions[str(original.event_id)],
                    catalog,
                )
            )
            for other in events:
                if (
                    other.event_id == event.event_id
                    or other.identity_key.rsplit(":", 1)[-1]
                    != event.identity_key.rsplit(":", 1)[-1]
                ):
                    continue
                a = re.sub(r"\W+", " ", event.prompt.casefold()).strip()
                b = re.sub(r"\W+", " ", other.prompt.casefold()).strip()
                if (
                    other.identity_key == event.identity_key
                    or SequenceMatcher(None, a, b).ratio() >= 0.90
                ):
                    codes.add("suspected_duplicate")
            receipts.append(
                ValidationReceipt(
                    event_id=event.event_id,
                    candidate_sha256=candidate_digest(event),
                    source_sha256=_sources(event_raws),
                    policy_version=VALIDATION_POLICY_VERSION,
                    stage="content_media",
                    media_catalog_sha256=catalog_sha,
                    passed=not codes,
                    checked_at=now,
                    issue_codes=tuple(sorted(codes)),
                )
            )
        # Final generation owns a snapshot of every artifact and byte: C5 never
        # needs to read a mutable draft or a newer C3 generation mid-publication.
        files = {
            "events.jsonl": _jsonl([e.model_dump(mode="json") for e in events]),
            "media.json": frozen,
            "validation.json": json.dumps(
                [r.model_dump(mode="json") for r in receipts], sort_keys=True
            ),
            "receipts.jsonl": _jsonl([r.model_dump(mode="json") for r in receipts]),
            "decisions.json": json.dumps(decisions, sort_keys=True),
            "source-selection.json": json.dumps(
                next(iter(decisions.values()))["selection"], sort_keys=True
            ),
            "taxonomy.json": json.dumps(taxonomy_data, sort_keys=True),
            "sources.json": (content / "sources.json").read_text(),
            "raw.jsonl": (content / "raw.jsonl").read_text(),
            "aliases.json": (content / "aliases.json").read_text(),
            "candidates.jsonl": (content / "candidates.jsonl").read_text(),
        }
        for name, text in files.items():
            _write(target / name, text)
        file_hashes = {
            name: hashlib.sha256(text.encode()).hexdigest()
            for name, text in files.items()
        }
        file_hashes.update(
            {
                r.filename: asset_sha256(target / r.filename)
                for r in _catalog_assets(catalog)
                if (target / r.filename).exists()
            }
        )
        file_hashes.update(private_files)
        _write(
            target / "batch.json",
            json.dumps(
                {
                    "content_generation": pointer["generation"],
                    "content_input_sha256": pointer["input_sha256"],
                    "media_catalog_sha256": catalog_sha,
                    "media_rules_sha256": rules_sha,
                    "files": file_hashes,
                    "passed": all(r.passed for r in receipts),
                    "event_count": len(events),
                },
                sort_keys=True,
            ),
        )
        _sync_directory(target)
        _sync_directory(target.parent)
        temporary = workspace / "media-current.json.tmp"
        _write(
            temporary,
            json.dumps(
                {
                    "generation": str(relative),
                    "content_generation": pointer["generation"],
                    "content_input_sha256": pointer["input_sha256"],
                    "media_catalog_sha256": catalog_sha,
                    "media_rules_sha256": rules_sha,
                },
                sort_keys=True,
            ),
        )
        temporary.replace(workspace / "media-current.json")
        _sync_directory(workspace)
        return tuple(receipts)
