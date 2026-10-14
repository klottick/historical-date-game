"""Conservative supplemental links. Pure resolution; bounded private acquisition.

Nothing here changes the sealed corpus or its selection policy. Missing evidence
is a source link, not a search request, guess, or review queue.
"""

import fcntl
import hashlib
import html
import os
import re
import time
from collections import Counter
from collections.abc import Mapping
from contextlib import AbstractContextManager
from html.parser import HTMLParser
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal, Self
from urllib.parse import unquote, urlsplit
from uuid import UUID

import httpx
from pydantic import model_validator

from app.content.adapters.onthisday import MONTHS, _json
from app.content.commons_transport import _retry_seconds, utc_now
from app.content.publish import _safe_root, canonical, verify_release
from app.content.schemas import SHA256, ContentModel, EventRecord, NonEmpty
from app.game.years import from_year_index

API_URL = "https://en.wikipedia.org/w/api.php"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
STOPWORDS = frozenset("a an and as at by for from in of on or the to with".split())
SUBJECTS = frozenset(
    "battle siege war treaty revolution election referendum invasion expedition mission flight landing eruption earthquake invention".split()
)


def safe_source_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
        _ = parts.port
        return bool(
            parts.scheme in {"http", "https"}
            and parts.hostname
            and parts.username is None
            and parts.password is None
            and not any(ord(c) < 33 or ord(c) == 127 for c in value)
            and "\\" not in value
        )
    except ValueError:
        return False


def wikipedia_title(value: str) -> str | None:
    if not safe_source_url(value):
        return None
    parts = urlsplit(value)
    decoded = unquote(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc != "en.wikipedia.org"
        or parts.query
        or parts.fragment
        or not decoded.startswith("/wiki/")
        or any(ord(c) < 33 or ord(c) == 127 for c in decoded)
        or any(c in decoded for c in "\\?#")
    ):
        return None
    title = decoded.removeprefix("/wiki/").replace("_", " ")
    return title if title and ":" not in title and "|" not in title else None


def calendar_title(title: str) -> bool:
    return bool(re.fullmatch(r"(?:" + "|".join(MONTHS) + r") [1-9][0-9]?", title))


def _ordinary_title(title: str) -> bool:
    return not (
        calendar_title(title)
        or re.fullmatch(r"\d+(?: (?:BC|BCE|AD|CE))?(?: in .*)?", title)
        or title.casefold().startswith(
            ("list of ", "lists of ", "calendar", "timeline of ")
        )
        or title in MONTHS
    )


class CanonicalPage(ContentModel):
    title: str
    url: str
    page_id: int | None
    revision_id: int | None
    namespace: int
    missing: bool
    disambiguation: bool
    categories: tuple[str, ...]


class EventLinkRecord(ContentModel):
    event_id: UUID
    kind: Literal["article", "source"]
    label: NonEmpty
    url: str
    source_url: str
    source_revision: int | None
    evidence_sha256: SHA256 | None
    reason: NonEmpty

    @model_validator(mode="after")
    def safe_links(self) -> Self:
        if not safe_source_url(self.source_url) or not safe_source_url(self.url):
            raise ValueError("unsafe_event_link")
        if self.kind == "article":
            title = wikipedia_title(self.url)
            if not title or not _ordinary_title(title) or not self.evidence_sha256:
                raise ValueError("unverified_article_link")
        elif self.url != self.source_url:
            raise ValueError("source_fallback_must_be_original")
        return self


class EventLinksFile(ContentModel):
    schema_version: Literal[1] = 1
    policy_version: Literal["event-links-v1"] = "event-links-v1"
    release_id: NonEmpty
    manifest_sha256: SHA256
    records: dict[UUID, EventLinkRecord]

    @model_validator(mode="after")
    def identities(self) -> Self:
        if any(key != record.event_id for key, record in self.records.items()):
            raise ValueError("event_link_identity_mismatch")
        return self


class LinkBuildSummary(ContentModel):
    total: int
    article: int
    source: int
    reasons: dict[str, int]
    sha256: str


def source_link(event: EventRecord, reason: str) -> EventLinkRecord | None:
    for source in event.sources:
        if safe_source_url(source.url):
            title = wikipedia_title(source.url)
            label = (
                "Wikipedia calendar source"
                if title and calendar_title(title)
                else "Wikipedia source"
                if title
                else "Source page"
            )
            return EventLinkRecord(
                event_id=event.event_id,
                kind="source",
                label=label,
                url=source.url,
                source_url=source.url,
                source_revision=None,
                evidence_sha256=None,
                reason=reason,
            )
    return None


def _normalize(text: str) -> str:
    return " ".join(
        re.sub(r"\[(?:\d+|citation needed|[a-z])\]", "", html.unescape(text)).split()
    )


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\w+", text.casefold()))


def _contiguous(subject: str, prompt: str, minimum: int) -> bool:
    words, context = _tokens(subject), _tokens(prompt)
    return sum(word not in STOPWORDS for word in words) >= minimum and any(
        context[i : i + len(words)] == words for i in range(len(context))
    )


def _canonical_subject(page: CanonicalPage, prompt: str, minimum: int) -> bool:
    # Canonical redirects may add articles ("the"), but may not turn a specific
    # event into a generic topic or a differently named event.
    words = tuple(word for word in _tokens(page.title) if word not in STOPWORDS)
    context = tuple(word for word in _tokens(prompt) if word not in STOPWORDS)
    return len(words) >= minimum and any(
        context[i : i + len(words)] == words for i in range(len(context))
    )


def _biography(page: CanonicalPage) -> bool:
    return any(
        category.removeprefix("Category:") == "Living people"
        or re.search(r"\b(?:births|deaths)$", category)
        for category in page.categories
    )


def _validated(page: CanonicalPage) -> bool:
    title = wikipedia_title(page.url)
    return bool(
        title == page.title
        and _ordinary_title(page.title)
        and page.namespace == 0
        and not page.missing
        and not page.disambiguation
        and page.page_id is not None
        and page.page_id > 0
        and page.revision_id is not None
        and page.revision_id > 0
        and page.categories
        and not any(
            re.search(
                r"Category:(?:Countries|Cities|Towns|Geography|Continents|Sovereign states)\b",
                c,
            )
            for c in page.categories
        )
    )


class _Entry(ContentModel):
    section: str
    text: str
    links: tuple[tuple[str, str], ...]


class _CalendarParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[_Entry] = []
        self.section = ""
        self.heading = False
        self.depth = 0
        self.sup = 0
        self.text: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.anchor: str | None = None
        self.anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "h2":
            self.section = ""
            self.heading = True
        if self.heading and attributes.get("id") in {"Events", "Births", "Deaths"}:
            self.section = str(attributes["id"])
        if tag == "li":
            self.depth += 1
            if self.depth == 1:
                self.text, self.links = [], []
        if tag == "sup":
            self.sup += 1
        if tag == "a" and self.depth == 1 and not self.sup:
            href = attributes.get("href", "") or ""
            if href.startswith("/wiki/"):
                href = "https://en.wikipedia.org" + href
            title = wikipedia_title(href)
            self.anchor = title
            self.anchor_text = []

    def handle_data(self, data: str) -> None:
        if self.depth == 1 and not self.sup:
            self.text.append(data)
            if self.anchor is not None:
                self.anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2":
            self.heading = False
        if tag == "sup":
            self.sup = max(0, self.sup - 1)
        if tag == "a" and self.anchor is not None:
            self.links.append((self.anchor, _normalize("".join(self.anchor_text))))
            self.anchor = None
        if tag == "li" and self.depth:
            if self.depth == 1 and self.section:
                self.entries.append(
                    _Entry(
                        section=self.section,
                        text=_normalize("".join(self.text)),
                        links=tuple(self.links),
                    )
                )
            self.depth -= 1


def _matching_entry(event: EventRecord, page_html: str | None) -> _Entry | None:
    if page_html is None:
        return None
    parser = _CalendarParser()
    parser.feed(page_html)
    civil = from_year_index(event.year_index)
    matches = []
    for entry in parser.entries:
        match = re.fullmatch(r"(\d+)(?:\s+(BC|BCE|AD|CE))?\s*[–—-]\s*(.+)", entry.text)
        if not match or int(match[1]) != civil.value:
            continue
        era = "BCE" if match[2] in {"BC", "BCE"} else "CE"
        if era == civil.era and _normalize(match[3]) == _normalize(event.prompt):
            matches.append(entry)
    return matches[0] if len(matches) == 1 else None


def _article(
    event: EventRecord,
    page: CanonicalPage,
    source_url: str,
    reason: str,
    page_html: str | None,
) -> EventLinkRecord:
    evidence = canonical({"html": page_html, "canonical": page.model_dump(mode="json")})
    return EventLinkRecord(
        event_id=event.event_id,
        kind="article",
        label="Wikipedia article",
        url=page.url,
        source_url=source_url,
        source_revision=(
            None
            if calendar_title(wikipedia_title(source_url) or "")
            else page.revision_id
        ),
        evidence_sha256=hashlib.sha256(evidence).hexdigest(),
        reason=reason,
    )


def resolve_event_link(
    event: EventRecord,
    page_html: str | None,
    canonical_pages: Mapping[str, CanonicalPage],
) -> EventLinkRecord:
    fallback = source_link(event, "canonical_unavailable")
    if fallback is None:
        raise ValueError("event_has_no_safe_source")
    retained = []
    for source in event.sources:
        title = wikipedia_title(source.url)
        page = canonical_pages.get(title or "")
        if title and not calendar_title(title) and page and _validated(page):
            if (
                _contiguous(title, event.prompt, 2)
                and _canonical_subject(page, event.prompt, 2)
                and (
                    _biography(page)
                    and bool({"births", "deaths"} & set(event.category_ids))
                    or not _biography(page)
                    and bool(set(_tokens(title)) & SUBJECTS)
                )
            ):
                retained.append((page, source.url))
    if len({p.url for p, _ in retained}) == 1:
        page, source_url = retained[0]
        return _article(event, page, source_url, "verified_source_article", None)
    if retained:
        return fallback.model_copy(update={"reason": "ambiguous_subject"})
    calendar_sources = [
        source.url
        for source in event.sources
        if calendar_title(wikipedia_title(source.url) or "")
    ]
    entry = _matching_entry(event, page_html) if len(calendar_sources) == 1 else None
    if entry is None:
        reason = (
            "entry_unresolved" if page_html is not None else "canonical_unavailable"
        )
        return fallback.model_copy(update={"reason": reason})
    candidates: dict[str, tuple[int, CanonicalPage]] = {}
    missing_canonical = False
    for title, label in entry.links:
        if not _ordinary_title(title) or not _contiguous(label, event.prompt, 3):
            continue
        page = canonical_pages.get(title)
        if page is None:
            missing_canonical = True
            continue
        if not _validated(page) or not _canonical_subject(page, event.prompt, 3):
            continue
        if _biography(page):
            if (
                entry.section not in {"Births", "Deaths"}
                or entry.section.casefold() not in event.category_ids
            ):
                continue
        elif not (set(_tokens(title)) & SUBJECTS):
            continue
        candidates[page.url] = (sum(t not in STOPWORDS for t in _tokens(label)), page)
    if not candidates:
        return fallback.model_copy(
            update={
                "reason": "canonical_unavailable"
                if missing_canonical
                else "subject_unresolved"
            }
        )
    longest = max(length for length, _ in candidates.values())
    best = [page for length, page in candidates.values() if length == longest]
    if len(best) != 1:
        return fallback.model_copy(update={"reason": "ambiguous_subject"})
    return _article(
        event, best[0], calendar_sources[0], "verified_calendar_subject", page_html
    )


def _private_path(path: Path, release: Path) -> Path:
    path = _safe_root(path)
    if (
        path.is_relative_to(release)
        or any(part in {"public", "media"} for part in path.parts)
        or any((parent / "manifest.json").exists() for parent in path.parents)
    ):
        raise ValueError("event_links_must_remain_private")
    return path


def _private_write(path: Path, body: bytes, *, create_only: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with NamedTemporaryFile(
        dir=path.parent, prefix=".event-links-", delete=False
    ) as temporary:
        temporary.write(body)
        temporary.flush()
        os.fsync(temporary.fileno())
        name = Path(temporary.name)
    try:
        if create_only:
            os.link(name, path)  # Atomic, and fails if another publisher won.
        else:
            name.replace(path)
    finally:
        name.unlink(missing_ok=True)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class EvidenceCache(AbstractContextManager["EvidenceCache"]):
    """One sequential client under a cache lock; no HTTP redirect following.

    A query with continuation is incomplete evidence and deliberately unresolved.
    Cached failures stay failures on subsequent/offline builds.
    """

    def __init__(self, root: Path, *, offline: bool) -> None:
        self.root = _safe_root(root)
        self.offline = offline
        self.client: httpx.Client | None = None
        self.last_request: float | None = None
        self.lock: Any = None

    def __enter__(self) -> Self:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = _safe_root(self.root / ".lock")
        self.lock = lock_path.open("a")
        lock_path.chmod(0o600)
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        if not self.offline:
            self.client = httpx.Client(
                timeout=10,
                follow_redirects=False,
                trust_env=False,
                headers={
                    "User-Agent": "HistoricalDateGame/1.0 (https://github.com/klottick/historical-date-game; offline event-link enrichment)"
                },
            )
        return self

    def __exit__(self, *args: Any) -> None:
        if self.client:
            self.client.close()
        if self.lock:
            self.lock.close()

    def _fetch(
        self, params: dict[str, str]
    ) -> tuple[dict[str, Any] | None, str | None]:
        assert self.client is not None
        reason = "acquisition_unavailable"
        for attempt in range(3):
            if self.last_request is not None:
                # Leave a full second after the prior response, even when that
                # response itself took longer than one second.
                time.sleep(1)
            self.last_request = time.monotonic()
            try:
                with self.client.stream("GET", API_URL, params=params) as response:
                    body = bytearray()
                    for chunk in response.iter_bytes(64 * 1024):
                        if (
                            len(body) + len(chunk) > MAX_RESPONSE_BYTES
                            or time.monotonic() - self.last_request > 10
                        ):
                            return None, "response_limits"
                        body.extend(chunk)
                    if response.status_code in {429, 503}:
                        reason = "provider_unavailable"
                        if attempt < 2:
                            time.sleep(_retry_seconds(response.headers, utc_now())[0])
                            continue
                        return None, reason
                    data = _json(bytes(body))
                    if not isinstance(data, dict):
                        return None, "malformed_evidence"
                    error = data.get("error", {})
                    if isinstance(error, dict) and error.get("code") in {
                        "maxlag",
                        "ratelimited",
                    }:
                        reason = "provider_unavailable"
                        if attempt < 2:
                            time.sleep(_retry_seconds(response.headers, utc_now())[0])
                            continue
                    if response.status_code != 200 or error:
                        return None, reason
                    return data, None
            except httpx.HTTPError:
                reason = "transport_unavailable"
            except ValueError, TypeError:
                return None, "malformed_evidence"
        return None, reason

    def _request(
        self, values: dict[str, str]
    ) -> tuple[dict[str, Any] | None, str | None]:
        params = {**values, "format": "json", "formatversion": "2", "maxlag": "5"}
        path = self.root / (hashlib.sha256(canonical(params)).hexdigest() + ".json")
        if path.exists():
            try:
                if (
                    path.is_symlink()
                    or path.stat().st_size > MAX_RESPONSE_BYTES + 1024 * 1024
                ):
                    raise ValueError("unsafe_cache")
                saved = _json(path.read_bytes())
                if saved["params"] != params:
                    raise ValueError("cache_parameters")
                data, reason = saved["response"], saved["reason"]
                if data is not None and not isinstance(data, dict):
                    raise ValueError("malformed_cache")
                if reason is not None and not isinstance(reason, str):
                    raise ValueError("malformed_cache")
                return data, reason
            except ValueError, OSError, KeyError, TypeError:
                return None, "cache_corrupt"
        if self.offline:
            return None, "offline_cache_miss"
        result, reason = self._fetch(params)
        _private_write(
            path,
            canonical({"params": params, "response": result, "reason": reason}),
            create_only=False,
        )
        return result, reason

    def calendar(self, title: str) -> tuple[str | None, int | None, str | None]:
        data, reason = self._request(
            {"action": "parse", "page": title, "prop": "text|revid"}
        )
        try:
            parsed = data["parse"] if data else {}
            if (
                parsed["title"] != title
                or not isinstance(parsed["text"], str)
                or type(parsed["revid"]) is not int
                or parsed["revid"] <= 0
            ):
                raise ValueError("incomplete_parse")
            return parsed["text"], parsed["revid"], None
        except ValueError, KeyError, TypeError:
            return None, None, reason or "incomplete_parse"

    def canonical(self, titles: list[str]) -> dict[str, CanonicalPage]:
        pages: dict[str, CanonicalPage] = {}
        titles = sorted(set(titles))
        for offset in range(0, len(titles), 50):
            batch = titles[offset : offset + 50]
            data, _ = self._request(
                {
                    "action": "query",
                    "titles": "|".join(batch),
                    "redirects": "1",
                    "prop": "info|pageprops|categories",
                    "inprop": "url",
                    "cllimit": "max",
                }
            )
            if not data or "continue" in data:
                continue
            try:
                query = data["query"]
                aliases = {
                    r["from"]: r["to"]
                    for group in ("normalized", "redirects")
                    for r in query.get(group, [])
                }
                returned = {}
                for row in query["pages"]:
                    # Absence of pageprops in MediaWiki means no properties,
                    # whereas absent categories is insufficient evidence.
                    if "categories" not in row:
                        continue
                    page = CanonicalPage(
                        title=row["title"],
                        url=row.get("canonicalurl", row.get("fullurl", "")),
                        page_id=row.get("pageid"),
                        revision_id=row.get("lastrevid"),
                        namespace=row["ns"],
                        missing="missing" in row,
                        disambiguation="disambiguation" in row.get("pageprops", {}),
                        categories=tuple(c["title"] for c in row["categories"]),
                    )
                    returned[page.title] = page
                for title in batch:
                    target, seen = title, set()
                    while target in aliases and target not in seen:
                        seen.add(target)
                        target = aliases[target]
                    if target in returned:
                        pages[title] = returned[target]
            except ValueError, KeyError, TypeError:
                continue
        return pages


def build_event_links(
    release: Path, cache: Path, output: Path, *, offline: bool
) -> LinkBuildSummary:
    release = _safe_root(release)
    cache, output = _private_path(cache, release), _private_path(output, release)
    if output.exists() or output.is_symlink():
        raise ValueError("event_links_output_exists")
    manifest = verify_release(release, release / "media")
    manifest_body = (release / "manifest.json").read_bytes()
    events = [
        EventRecord.model_validate_json(line)
        for line in (release / "events.jsonl").read_bytes().splitlines()
        if line.strip()
    ]
    records = {}
    with EvidenceCache(cache, offline=offline) as evidence:
        calendar_pages = {}
        titles = set()
        for event in events:
            for source in event.sources:
                title = wikipedia_title(source.url)
                if title and calendar_title(title):
                    if title not in calendar_pages:
                        calendar_pages[title] = evidence.calendar(title)
                elif title:
                    titles.add(title)
        for event in events:
            for source in event.sources:
                title = wikipedia_title(source.url)
                page_html = calendar_pages.get(title or "", (None, None, None))[0]
                entry = _matching_entry(event, page_html)
                if entry:
                    titles.update(
                        title for title, _ in entry.links if _ordinary_title(title)
                    )
        pages = evidence.canonical(sorted(titles))
        for event in events:
            title = next(
                (
                    wikipedia_title(s.url)
                    for s in event.sources
                    if calendar_title(wikipedia_title(s.url) or "")
                ),
                None,
            )
            page_html, revision, failure = calendar_pages.get(
                title or "", (None, None, None)
            )
            record = resolve_event_link(event, page_html, pages)
            if title:
                if calendar_title(wikipedia_title(record.source_url) or ""):
                    record = record.model_copy(update={"source_revision": revision})
                if failure and record.kind == "source":
                    record = record.model_copy(update={"reason": failure})
            records[event.event_id] = record
    envelope = EventLinksFile(
        release_id=manifest.release_id,
        manifest_sha256=hashlib.sha256(manifest_body).hexdigest(),
        records=records,
    )
    encoded = canonical(envelope.model_dump(mode="json"))
    validated = EventLinksFile.model_validate_json(encoded)
    if (
        set(validated.records) != {event.event_id for event in events}
        or len(events) != manifest.event_count
    ):
        raise ValueError("event_links_membership")
    if (release / "manifest.json").read_bytes() != manifest_body:
        raise ValueError("release_changed_during_enrichment")
    _private_write(output, encoded, create_only=True)
    counts = Counter(record.kind for record in records.values())
    return LinkBuildSummary(
        total=len(records),
        article=counts["article"],
        source=counts["source"],
        reasons=dict(sorted(Counter(r.reason for r in records.values()).items())),
        sha256=hashlib.sha256(encoded).hexdigest(),
    )
