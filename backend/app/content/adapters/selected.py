"""Wikibase statements + exact English Wikipedia milestone corroboration.

New network requests use Action API revision content, never mutable extracts.
C1 legacy cache is read-only and digest-backed: its absent entity revision IDs
are not retrofitted, and its extracts are cited as acquired cache, not oldid text.
Only narrowly supported milestone/date grammars resolve; no prose guessing.
"""

import csv
import hashlib
import json
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode
from uuid import NAMESPACE_URL, uuid5

import httpx
import mwparserfromhell

from app.content.adapters.base import RawCandidate
from app.content.schemas import (
    CATEGORY_IDS,
    EventRecord,
    SourceCitation,
    ValidationIssue,
)

HOSTS = {"wikidata": "www.wikidata.org", "wikipedia_en": "en.wikipedia.org"}
GREGORIAN = {
    "http://www.wikidata.org/entity/Q1985727",
    "https://www.wikidata.org/entity/Q1985727",
    "gregorian",
    "proleptic-gregorian",
}
MILESTONES = {
    "birth": ("P569", "birth_date", "{title} is born", "births"),
    "death": ("P570", "death_date", "{title} dies", "deaths"),
    "publication": ("P577", "published", "{title} is published", "literature"),
    "inception": ("P571", "established", "{title} is established", "politics"),
    "start": ("P580", "start_date", "{title} begins", "battles"),
    "end": ("P582", "end_date", "{title} ends", "battles"),
    "launch": ("P619", "launch_date", "{title} is launched", "exploration"),
    "landing": ("P620", "landing_date", "{title} lands", "exploration"),
    "discovery": ("P575", "discovery_date", "{title} is discovered", "inventions"),
    "premiere": ("P1191", "premiere", "{title} premieres", "arts"),
    "invention": ("P575", "invention_year", "{title} is invented", "inventions"),
    "creation": ("P571", "year", "{title} is created", "arts"),
    "occurrence": ("P585", "date", "{title} takes place", "politics"),
}
# Only an active outer infobox of a supported entity type can provide fields.
# Unrelated templates, examples, tags, comments and nested infoboxes are not facts.
INFOBOX_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "birth": {
        "infobox person": ("birth_date",),
        "infobox officeholder": ("birth_date",),
    },
    "death": {
        "infobox person": ("death_date",),
        "infobox officeholder": ("death_date",),
    },
    "publication": {
        "infobox book": ("published", "pub_date", "publication_date", "release_date")
    },
    "inception": {
        "infobox organization": ("established", "formation"),
        "infobox company": ("foundation", "founded"),
    },
    "start": {"infobox military conflict": ("start_date", "date")},
    "end": {"infobox military conflict": ("end_date", "date")},
    "launch": {"infobox spaceflight": ("launch_date",)},
    "landing": {"infobox spaceflight": ("landing_date",)},
    "discovery": {},  # invention_year proves invention, not a second milestone
    "premiere": {"infobox musical composition": ("premiere",)},
    "invention": {"infobox electronic component": ("invention_year",)},
    "creation": {"infobox artwork": ("year",)},
    "occurrence": {"infobox event": ("date",), "infobox military conflict": ("date",)},
}
UA = "HistoricalDateGame/0.1 (https://github.com/klottick/historical-date-game) bounded-content-import"
MAX_BYTES = 8 * 1024 * 1024


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def issue(code: str, field: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, field=field, message=message)


def _path(root: Path, name: str) -> Path:
    target = root / name
    if not target.resolve().is_relative_to(root.resolve()) or target.is_symlink():
        raise ValueError("Snapshot path escapes root")
    return target


def _year(raw: str) -> tuple[int, Literal["year", "month", "day"]]:
    match = re.fullmatch(r"([+-])(\d{4,})-(\d{2})-(\d{2})T00:00:00Z", raw)
    if match:
        magnitude = int(match[2])
        month, day = int(match[3]), int(match[4])
        if magnitude == 0 or (month == 0 and day != 0):
            raise ValueError("invalid civil date")
        if month:
            date(magnitude, month, day or 1)
        return (
            1 - magnitude if match[1] == "-" else magnitude,
            "day" if day else "month" if month else "year",
        )
    civil = re.fullmatch(r"(\d+)(?:\s+(BCE|BC|CE|AD))?", raw, re.I)
    iso = re.fullmatch(r"(\d{4,})-(\d{2})(?:-(\d{2}))?", raw)
    if civil and int(civil[1]) > 0:
        magnitude = int(civil[1])
        return (
            1 - magnitude if (civil[2] or "").upper() in {"BCE", "BC"} else magnitude,
            "year",
        )
    if iso:
        date(int(iso[1]), int(iso[2]), int(iso[3] or "1"))
        return int(iso[1]), "day" if iso[3] else "month"
    raise ValueError("unsupported exact date")


@dataclass(frozen=True)
class _SourceDate:
    raw_date: str
    parts: tuple[int, ...]


def _source_date(raw: str, precision: str | None = None) -> _SourceDate:
    year, actual = _year(raw)
    rank = {"year": 1, "month": 2, "day": 3}
    count = min(rank[actual], rank[precision or actual])
    match = re.fullmatch(r"[+-]?\d{4,}-(\d{2})(?:-(\d{2}))?(?:T00:00:00Z)?", raw)
    parts: tuple[int, ...] = (year,)
    if count > 1 and match:
        parts += (int(match[1]),)
        if count > 2:
            parts += (int(match[2]),)
    return _SourceDate(raw, parts)


def _dates_conflict(dates: list[tuple[int, ...]]) -> bool:
    # Pairwise common precision prevents a year-only source from concealing
    # contradictory day/month claims elsewhere in the same identity.
    return any(
        left[: min(len(left), len(right))] != right[: min(len(left), len(right))]
        for i, left in enumerate(dates)
        for right in dates[i + 1 :]
    )


_MONTHS = {
    name.casefold(): number
    for number, name in enumerate(
        (
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
        ),
        1,
    )
}


def _clean_value(value: str) -> str:
    """Ignore inactive comments/footnotes, not arbitrary markup or field text."""
    if len(value.encode()) > 16384:
        raise ValueError("Infobox field exceeds bounded date grammar")
    output = []
    for node in mwparserfromhell.parse(value).nodes:
        if isinstance(node, mwparserfromhell.nodes.Comment):
            output.append(" ")  # never join separated digits into invented raw dates
            continue
        if (
            isinstance(node, mwparserfromhell.nodes.Tag)
            and str(node.tag).casefold() == "ref"
        ):
            output.append(" ")
            continue
        if isinstance(node, mwparserfromhell.nodes.HTMLEntity) and str(node) in {
            "&nbsp;",
            "&#160;",
        }:
            output.append(" ")
        elif (
            isinstance(node, mwparserfromhell.nodes.Wikilink)
            and str(node.title).strip() == "UTC"
            and (node.text is None or str(node.text).strip() == "UTC")
        ):
            output.append("UTC")
        elif isinstance(
            node, (mwparserfromhell.nodes.Text, mwparserfromhell.nodes.Template)
        ):
            output.append(str(node))
        else:
            raise ValueError("Unsupported active date-field markup")
    cleaned = "".join(output).strip()
    if len(cleaned) > 512:
        raise ValueError("Infobox date is not a bounded supported grammar")
    return cleaned


def _english_date(value: str, *, utc_time: bool = False) -> _SourceDate:
    tail = r"(?:,\s*(?P<hour>\d{2}):(?P<minute>\d{2}))?" if utc_time else ""
    match = re.fullmatch(
        r"(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]+)\s+(?P<year>\d{1,4})" + tail, value
    ) or re.fullmatch(
        r"(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s*(?P<year>\d{1,4})" + tail, value
    )
    if match is None or match["month"].casefold() not in _MONTHS:
        raise ValueError("Unsupported exact English date")
    parts = int(match["year"]), _MONTHS[match["month"].casefold()], int(match["day"])
    date(*parts)
    if (
        utc_time
        and match["hour"] is not None
        and (int(match["hour"]) > 23 or int(match["minute"]) > 59)
    ):
        raise ValueError("Invalid UTC time")
    return _SourceDate(match["year"], parts)


def _wiki_value(value: str) -> _SourceDate:
    """Finite exact literal/date-template grammar, never a search through prose."""
    try:
        return _source_date(value)
    except ValueError:
        pass
    code = mwparserfromhell.parse(value)
    templates = code.filter_templates(recursive=False)
    if not templates:
        return _english_date(value)
    if len(templates) != 1:
        raise ValueError("Ambiguous date templates")
    template = templates[0]
    extra = "".join(str(node) for node in code.nodes if node is not template).strip()
    name = str(template.name).strip().casefold().replace("_", " ")
    params = {str(p.name).strip(): str(p.value).strip() for p in template.params}
    if len(params) != len(template.params) or any(
        not all(isinstance(n, mwparserfromhell.nodes.Text) for n in p.value.nodes)
        for p in template.params
    ):
        raise ValueError("Duplicate/nested date template parameters")
    if name in {"start-date", "end-date"}:
        if (
            set(params) != {"1", "timezone"}
            or params["timezone"] != "yes"
            or extra not in {"", "UTC"}
        ):
            raise ValueError("Unresolved time/calendar convention")
        if re.search(r",\s*\d{2}:\d{2}$", params["1"]) and extra != "UTC":
            raise ValueError("Source clock requires an explicit UTC label")
        return _english_date(params["1"], utc_time=True)
    names = {
        "birth date",
        "birth date and age",
        "death date",
        "death date and age",
        "start date",
        "start date and age",
        "end date",
        "end date and age",
    }
    if name not in names or extra:
        raise ValueError("Unsupported active date template")
    keys = {"1", "2", "3", "df", "mf"}
    if name == "death date and age":
        keys.update(("4", "5", "6"))
    if (
        not set(params) <= keys
        or not {"1", "2", "3"} <= set(params)
        or any(
            params[k] not in {"y", "yes", "n", "no"}
            for k in ("df", "mf")
            if k in params
        )
    ):
        raise ValueError("Unsupported date template arguments")
    if not all(re.fullmatch(r"\d{1,4}", params[k]) for k in ("1", "2", "3")):
        raise ValueError("Date components are not exact civil numbers")
    parts = tuple(int(params[k]) for k in ("1", "2", "3"))
    date(*parts)
    if set(params) & {"4", "5", "6"}:
        if not {"4", "5", "6"} <= set(params) or not all(
            re.fullmatch(r"\d{1,4}", params[k]) for k in ("4", "5", "6")
        ):
            raise ValueError("Invalid supporting birth date")
        date(*(int(params[k]) for k in ("4", "5", "6")))
    return _SourceDate(params["1"], parts)


def _conflict_endpoint(value: str, milestone: str) -> _SourceDate:
    """Resolve exact ordered day endpoints only; vague year ranges are rejected."""
    shared = re.fullmatch(r"(\d{1,2})\s*[–—]\s*(.+)", value)
    if shared:
        end = _wiki_value(shared[2])
        if len(end.parts) != 3:
            raise ValueError("Conflict endpoint lacks an exact shared day/month/year")
        start = _SourceDate(end.raw_date, (*end.parts[:2], int(shared[1])))
        date(*start.parts)
    else:
        endpoints = re.split(r"\s*[–—]\s*", value)
        if len(endpoints) == 1:
            result = _wiki_value(value)
            if len(result.parts) != 3:
                raise ValueError("Conflict date is not an exact day")
            return result
        if len(endpoints) != 2:
            raise ValueError("Ambiguous conflict interval")
        start, end = (_wiki_value(part) for part in endpoints)
        if len(start.parts) != 3 or len(end.parts) != 3:
            raise ValueError("Conflict interval lacks exact endpoints")
    if start.parts > end.parts:
        raise ValueError("Reversed conflict interval")
    return start if milestone == "start" else end


def _wiki_date(page: dict[str, Any], milestone: str) -> _SourceDate:
    """Return an exact raw date/positive civil-year substring, not rewritten prose."""
    revision = page.get("revisions", [{}])[0]
    text = revision.get("slots", {}).get("main", {}).get("content")
    if text is not None:
        if len(text.encode()) > MAX_BYTES:
            raise ValueError("Wikitext exceeds bounded parse input")
        boxes = [
            box
            for box in mwparserfromhell.parse(text).filter_templates(recursive=False)
            if str(box.name).strip().casefold().replace("_", " ")
            in INFOBOX_FIELDS[milestone]
        ]
        if len(boxes) != 1:
            raise ValueError("missing/ambiguous supported top-level infobox")
        box = boxes[0]
        fields = INFOBOX_FIELDS[milestone][
            str(box.name).strip().casefold().replace("_", " ")
        ]
        values = [
            (str(param.name).strip().casefold(), str(param.value).strip())
            for param in box.params
            if str(param.name).strip().casefold() in fields and str(param.value).strip()
        ]
        if len(values) != 1:
            raise ValueError("missing/ambiguous exact infobox milestone")
        field, value = values[0]
        value = _clean_value(value)
        if field == "date" and milestone in {"start", "end"}:
            return _conflict_endpoint(value, milestone)
        return _wiki_value(value)
    # C1 cache-only extract support is intentionally limited to an exact lifespan.
    # Require the first parentheses after the title: never take unrelated years.
    if milestone not in {"birth", "death"}:
        raise ValueError("cache extract lacks a scoped supported milestone")
    extract = page.get("extract", "")
    match = re.match(r"^[^(\n]{1,160}\(([^()]+)\)", extract)
    if match is None:
        raise ValueError("missing exact lifespan")
    parts = re.split(r"\s*[–—]\s*", match[1])
    if len(parts) != 2:
        raise ValueError("ambiguous lifespan")
    part = parts[0 if milestone == "birth" else 1].strip()
    match_date = re.fullmatch(
        r"(?:\d{1,2}\s+[A-Za-z]+\s+|[A-Za-z]+\s+\d{1,2},?\s+)?(\d{1,4}(?:\s+(?:BCE|BC|CE|AD))?)",
        part,
    )
    if match_date is None:
        raise ValueError("uncertain/unsupported lifespan")
    # A shared BCE suffix would otherwise turn the first year into CE.
    if (
        milestone == "birth"
        and re.search(r"\b(?:BCE|BC)\b", parts[1])
        and not re.search(r"\b(?:BCE|BC)\b", parts[0])
    ):
        raise ValueError("implicit shared era remains unresolved")
    return _wiki_value(part)


class SelectedSourceAdapter:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.sleep = sleep

    def alias_dates_conflict(self, raws: list[RawCandidate]) -> bool:
        """Compare semantically precise evidence across already normalized aliases.

        Event/citation precision may be capped at year by C2's supported raw
        citation grammar. That cap must not hide conflicting source day facts.
        """
        dates = []
        for raw in raws:
            payload: dict[str, Any] = raw.payload
            prop = MILESTONES[payload["milestone"]][0]
            for claim in payload["entity"]["claims"][prop]:
                value = claim["mainsnak"]["datavalue"]["value"]
                precision = {9: "year", 10: "month", 11: "day"}[value["precision"]]
                dates.append(_source_date(value["time"], precision).parts)
            dates.append(_wiki_date(payload["page"], payload["milestone"]).parts)
        return _dates_conflict(dates)

    @staticmethod
    def citation_dates_agree(
        left: SourceCitation, right: SourceCitation, precision: str
    ) -> bool:
        return not _dates_conflict(
            [
                _source_date(left.raw_date, precision).parts,
                _source_date(right.raw_date, precision).parts,
            ]
        )

    def _download(self, spec: dict[str, Any]) -> tuple[bytes, dict[str, object]]:
        source = spec["source_id"]
        params = {
            **spec["params"],
            "format": "json",
            "formatversion": "2",
            "maxlag": "5",
        }
        if (
            params.get("action") != "query"
            or not re.fullmatch(r"[1-9]\d*", str(params.get("revids", "")))
            or params.get("rvslots") != "main"
            or "content" not in params.get("rvprop", "")
        ):
            raise ValueError(
                "Network acquisition requires a single pinned content revision"
            )
        url = f"https://{HOSTS[source]}/w/api.php"
        owned = self.client is None
        client = self.client or httpx.Client(timeout=30, follow_redirects=False)
        try:
            for attempt in range(3):
                self.sleep(1.0)  # Serial, bounded; below User-Agent-only policy quota.
                try:
                    with client.stream(
                        "GET",
                        url,
                        params=params,
                        headers={"User-Agent": UA, "Accept-Encoding": "identity"},
                        timeout=30,
                    ) as response:
                        chunks = bytearray()
                        for chunk in response.iter_bytes():
                            chunks.extend(chunk)
                            if len(chunks) > MAX_BYTES:
                                raise ValueError(
                                    "Source response exceeds bounded byte limit"
                                )
                        body = bytes(chunks)
                        error = (
                            json.loads(body).get("error", {})
                            if response.status_code == 200
                            else {}
                        )
                        retry = (
                            response.status_code in {429, 503}
                            or error.get("code") == "maxlag"
                        )
                        if not retry:
                            response.raise_for_status()
                            if error:
                                raise ValueError("Provider API error")
                            return body, {
                                "url": str(response.url),
                                "http_status": response.status_code,
                                "headers": dict(response.headers),
                                "retrieved_at": datetime.now(UTC).isoformat(),
                                "sha256": hashlib.sha256(body).hexdigest(),
                                "user_agent": UA,
                            }
                        delay = max(2.0**attempt, float(error.get("lag", 0)))
                        retry_after = response.headers.get("Retry-After")
                        if retry_after:
                            try:
                                delay = max(delay, float(retry_after))
                            except ValueError:
                                delay = max(
                                    delay,
                                    (
                                        parsedate_to_datetime(retry_after)
                                        - datetime.now(UTC)
                                    ).total_seconds(),
                                )
                        if delay > 120:
                            raise RuntimeError(
                                "Retry-After exceeds bounded run; retry later"
                            )
                except httpx.TransportError:
                    delay = 2.0**attempt
                if attempt < 2:
                    self.sleep(delay)
            raise RuntimeError("Provider retry budget exhausted")
        finally:
            if owned:
                client.close()

    def _load(
        self, root: Path, spec: dict[str, Any], snapshot_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if spec["source_id"] not in HOSTS:
            raise ValueError("Unselected fact provider")
        target = _path(root, spec["file"])
        if not target.exists():
            body, metadata = self._download(spec)
            if hashlib.sha256(body).hexdigest() != spec["sha256"]:
                raise ValueError("Fetched source digest differs from snapshot")
            revision = str(spec.get("params", {}).get("revids", ""))
            data = json.loads(body)
            if "entities" in data:
                if not data["entities"] or any(
                    str(entity.get("lastrevid", "")) != revision
                    for entity in data["entities"].values()
                ):
                    raise ValueError("Fetched entity revision mismatch")
            else:
                pages = data.get("query", {}).get("pages", [])
                if (
                    len(pages) != 1
                    or len(pages[0].get("revisions", [])) != 1
                    or str(pages[0]["revisions"][0].get("revid", "")) != revision
                ):
                    raise ValueError("Fetched page revision mismatch")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_bytes(body)
            temporary.replace(target)
            target.with_suffix(target.suffix + ".meta.json").write_text(
                json.dumps(metadata, sort_keys=True)
            )
        body = target.read_bytes()
        if len(body) > MAX_BYTES or hashlib.sha256(body).hexdigest() != spec["sha256"]:
            raise ValueError("Cached source digest/size mismatch")
        metadata_path = target.with_suffix(target.suffix + ".meta.json")
        metadata = (
            json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
        )
        acquired = metadata.get("retrieved_at", spec.get("acquired_at"))
        if not acquired:
            raise ValueError("Source acquisition timestamp is required")
        evidence = {
            "source_id": spec["source_id"],
            "sha256": spec["sha256"],
            "acquired_at": acquired,
            "snapshot_id": snapshot_id,
            "url": metadata.get(
                "url",
                f"https://{HOSTS[spec['source_id']]}/w/api.php?{urlencode(spec.get('params', {}))}",
            ),
            "revision": str(spec.get("params", {}).get("revids", "")),
        }
        return json.loads(body), evidence

    def fetch(self, snapshot_dir: Path) -> Iterable[RawCandidate]:
        manifest_path = snapshot_dir / "snapshot.json"
        if not manifest_path.exists():
            yield from self._legacy(snapshot_dir)
            return
        manifest = json.loads(manifest_path.read_text())
        if len(manifest["requests"]) > 256 or len(manifest["records"]) > 2000:
            raise ValueError("Snapshot batch exceeds bounded acquisition budget")
        entities: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        pages: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        for spec in manifest["requests"]:
            data, evidence = self._load(snapshot_dir, spec, manifest["snapshot_id"])
            if spec["source_id"] == "wikidata" and "entities" in data:
                for qid, entity in data["entities"].items():
                    if (
                        evidence["revision"]
                        and str(entity.get("lastrevid", "")) != evidence["revision"]
                    ):
                        raise ValueError("Cached entity revision mismatch")
                    entities[qid] = entity, evidence
            else:
                for page in data.get("query", {}).get("pages", []):
                    revisions = page.get("revisions", [])
                    if (
                        len(revisions) != 1
                        or str(revisions[0].get("revid", "")) != evidence["revision"]
                    ):
                        raise ValueError("Source page revision mismatch")
                    if spec["source_id"] == "wikidata":
                        entity = json.loads(revisions[0]["slots"]["main"]["content"])
                        entities[entity["id"]] = entity, evidence
                    else:
                        qid = page.get("pageprops", {}).get("wikibase_item")
                        if qid:
                            pages[qid] = page, evidence
        for record in manifest["records"]:
            if record["source_id"] not in HOSTS:
                raise ValueError("Unselected candidate source")
            qid = record["entity_id"]
            entity, entity_evidence = entities.get(qid, ({}, {}))
            page, page_evidence = pages.get(qid, ({}, {}))
            yield RawCandidate(
                record["source_id"],
                record["record_id"],
                {
                    **record,
                    "entity": entity,
                    "page": page,
                    "evidence": [entity_evidence, page_evidence],
                    "snapshot_id": manifest["snapshot_id"],
                },
            )

    def _legacy(self, root: Path) -> Iterable[RawCandidate]:
        """C1 acquisition layout: raw response + metadata SHA, no audit decisions."""
        seeds_path = root / "seeds.tsv"
        if not seeds_path.exists():
            raise ValueError("Expected snapshot.json or a C1 cache with seeds.tsv")
        entities: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        pages: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        redirects: dict[str, str] = {}
        for pattern, source in (
            ("entities-*.json", "wikidata"),
            ("wiki-*.json", "wikipedia_en"),
        ):
            for file in sorted((root / "raw").glob(pattern)):
                if file.name.endswith(".meta.json"):
                    continue
                meta = json.loads(
                    file.with_suffix(file.suffix + ".meta.json").read_text()
                )
                if meta.get("http_status") != 200:
                    continue
                spec = {
                    "source_id": source,
                    "file": str(file.relative_to(root)),
                    "sha256": meta["sha256"],
                }
                data, evidence = self._load(root, spec, "c1-cache:" + digest(meta))
                for qid, entity in data.get("entities", {}).items():
                    entities[qid] = entity, evidence
                for redirect in data.get("query", {}).get("redirects", []):
                    redirects[redirect["from"]] = redirect["to"]
                for page in data.get("query", {}).get("pages", []):
                    pages[page["title"]] = page, evidence
        with seeds_path.open() as stream:
            seeds = list(csv.DictReader(stream, delimiter="\t"))
        if len(seeds) > 2000:
            raise ValueError("C1 seed budget exceeded")
        for number, seed in enumerate(seeds, 1):
            title = redirects.get(seed["title"], seed["title"])
            page, page_evidence = pages.get(title, ({}, {}))
            qid = page.get("pageprops", {}).get("wikibase_item", "")
            entity, entity_evidence = entities.get(qid, ({}, {}))
            # C1 non-biographical prompts lack structured milestone/edition scope.
            # Never repurpose their research year or prompt as resolved evidence.
            milestone = {"births": "birth", "deaths": "death"}.get(
                seed["category"], "unsupported-research-milestone"
            )
            yield RawCandidate(
                "wikidata",
                f"C1-{number:03}",
                {
                    "entity_id": qid,
                    "milestone": milestone,
                    "category_ids": [seed["category"]],
                    "region_ids": seed["region"].split(";"),
                    "entity": entity,
                    "page": page,
                    "evidence": [entity_evidence, page_evidence],
                    "snapshot_id": "c1-cache",
                },
            )

    def normalize(self, raw: RawCandidate) -> EventRecord | tuple[ValidationIssue, ...]:
        p: dict[str, Any] = raw.payload
        milestone = p.get("milestone", "")
        qid = p.get("entity_id", "")
        if raw.source_id not in HOSTS or not re.fullmatch(r"Q[1-9]\d*", qid):
            return (
                issue(
                    "unresolved_identity",
                    "entity_id",
                    "An exact selected-source entity is required",
                ),
            )
        if milestone not in MILESTONES:
            return (
                issue(
                    "unsupported_milestone",
                    "milestone",
                    "A supported explicit milestone, not a research prompt/year, is required",
                ),
            )
        prop, _, template, category = MILESTONES[milestone]
        entity = p.get("entity", {})
        page = p.get("page", {})
        evidence = p.get("evidence", [])
        if (
            entity.get("id") != qid
            or page.get("pageprops", {}).get("wikibase_item") != qid
            or len(evidence) != 2
            or not all(evidence)
        ):
            return (
                issue(
                    "missing_provenance",
                    "sources",
                    "Both selected providers must corroborate the exact entity",
                ),
            )
        claims = entity.get("claims", {}).get(prop, [])
        if not claims:
            return (
                issue("missing_date", "claims", "No statement for the exact milestone"),
            )
        issues: list[ValidationIssue] = []
        resolved: list[tuple[dict[str, Any], int, str]] = []
        dates: list[tuple[int, ...]] = []
        for claim in claims:
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if claim.get("qualifiers") or claim.get("rank") == "deprecated":
                issues.append(
                    issue(
                        "unsupported_qualifiers",
                        "claims",
                        "Qualifiers/deprecated assertions are not deterministic dispute resolution",
                    )
                )
            if not isinstance(value, dict) or "time" not in value:
                issues.append(
                    issue("uncertain_date", "claims", "Unknown/non-time date statement")
                )
                continue
            if value.get("calendarmodel") not in GREGORIAN:
                issues.append(
                    issue(
                        "unresolved_calendar",
                        "claims",
                        "No supported Gregorian resolution for this calendar",
                    )
                )
            if value.get("precision") not in {9, 10, 11}:
                issues.append(
                    issue(
                        "unsupported_precision",
                        "claims",
                        "Date precision must be year or finer",
                    )
                )
            if (
                value.get("before", 0)
                or value.get("after", 0)
                or value.get("timezone", 0)
            ):
                issues.append(
                    issue(
                        "uncertain_date",
                        "claims",
                        "Uncertainty/timezone cannot be silently discarded",
                    )
                )
            try:
                year, precision = _year(value["time"])
                expected = {9: "year", 10: "month", 11: "day"}.get(
                    value.get("precision", -1)
                )
                # Providers sometimes fill month/day even at coarser precision.
                if (
                    expected
                    and {"year": 0, "month": 1, "day": 2}[expected]
                    > {"year": 0, "month": 1, "day": 2}[precision]
                ):
                    issues.append(
                        issue(
                            "unsupported_precision",
                            "claims",
                            "Timestamp cannot justify declared precision",
                        )
                    )
                resolved.append((claim, year, expected or precision))
                dates.append(_source_date(value["time"], expected or precision).parts)
            except ValueError, TypeError:
                issues.append(
                    issue("uncertain_date", "claims", "Unsupported exact civil date")
                )
        if _dates_conflict(dates):
            issues.append(
                issue(
                    "conflicting_dates",
                    "claims",
                    "Conflicting exact dates at common precision remain quarantined regardless of rank",
                )
            )
        try:
            wiki_date = _wiki_date(page, milestone)
            wiki_raw = wiki_date.raw_date
            if _dates_conflict([*dates, wiki_date.parts]):
                issues.append(
                    issue(
                        "conflicting_dates",
                        "sources",
                        "Selected providers disagree at their common supported exact precision",
                    )
                )
        except ValueError, KeyError, TypeError:
            issues.append(
                issue(
                    "unresolved_wikipedia_date",
                    "page",
                    "Wikipedia lacks an exact supported milestone date",
                )
            )
        if issues:
            return tuple(issues)
        if not resolved:
            return (issue("missing_date", "claims", "No exact dates resolved"),)
        year = resolved[0][1]
        # Source year substrings from date templates are truthful raw citations,
        # not manufactured ISO strings. Their C2-supported citation precision
        # caps the emitted event, AFTER full exact source-date conflict checks.
        precision_rank = min(
            *(len(parts) for parts in dates),
            len(wiki_date.parts),
            {"year": 1, "month": 2, "day": 3}[_year(wiki_raw)[1]],
        )
        citations = []
        for claim, _, _ in resolved:
            value = claim["mainsnak"]["datavalue"]["value"]
            citations.append(
                self._citation(
                    evidence[0],
                    f"{qid}:{claim['id']}",
                    value["time"],
                    value["calendarmodel"],
                    year,
                )
            )
        citations.append(
            self._citation(
                evidence[1],
                f"{page['pageid']}:{milestone}",
                wiki_raw,
                "proleptic-gregorian",
                year,
            )
        )
        identity = f"wikidata:{qid}:{milestone}"
        title = entity.get("labels", {}).get("en", {}).get("value") or page.get(
            "title", ""
        )
        categories = tuple(p.get("category_ids", (category,)))
        if not title or not categories or not set(categories) <= set(CATEGORY_IDS):
            return (
                issue(
                    "missing_content",
                    "category_ids",
                    "A source label and supported categories are required",
                ),
            )
        return EventRecord(
            event_id=uuid5(NAMESPACE_URL, identity),
            identity_key=identity,
            prompt=template.format(title=title),
            year_index=year,
            category_ids=categories,
            region_ids=tuple(p.get("region_ids", ())),
            explanation=f"The {milestone} milestone of {title} is dated by the retained selected-source snapshots.",
            sources=tuple(citations),
            date_precision=("year", "month", "day")[precision_rank - 1],
            review_status="approved",
            media_asset_id=None,
            fallback_key=categories[0],
        )

    @staticmethod
    def _citation(
        evidence: dict[str, Any],
        record_id: str,
        raw_date: str,
        calendar: str,
        year: int,
    ) -> SourceCitation:
        family = (
            "proleptic-gregorian"
            if year <= 0 or calendar == "proleptic-gregorian"
            else "gregorian"
        )
        return SourceCitation(
            source_id=evidence["source_id"],
            record_id=record_id,
            url=evidence["url"],
            rights_basis="CC0 structured data"
            if evidence["source_id"] == "wikidata"
            else "CC BY-SA 4.0 source attribution; original generated prompt, not copied extract",
            raw_date=raw_date,
            calendar=calendar,
            acquired_at=datetime.fromisoformat(
                evidence["acquired_at"].replace("Z", "+00:00")
            ),
            snapshot_id=evidence["snapshot_id"] + ":sha256=" + evidence["sha256"],
            date_resolution=f"source-resolved:{family}:year_index={year}",
        )
