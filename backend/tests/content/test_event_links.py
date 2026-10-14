"""Canned evidence exercises conservative resolution, acquisition and publication."""

import asyncio
import hashlib
import importlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from app.content.publish import publish_release
from app.content.schemas import EventRecord, SourceCitation
from tests.content.test_publish import final_batch

SOURCE = "https://en.wikipedia.org/wiki/January_1"
ARTICLE = "https://en.wikipedia.org/wiki/Battle_of_Red_River"
PROMPT = "The Battle of Red River begins."
HTML = '<h2 id="Events">Events</h2><ul><li><a href="/wiki/1800">1800</a> – The <a href="/wiki/Battle_of_Red_River">Battle of Red River</a> begins.<sup class="reference">[1]</sup></li></ul>'


def links() -> Any:
    return importlib.import_module("app.content.event_links")


def event(**changes: Any) -> EventRecord:
    return EventRecord(
        event_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        identity_key="synthetic-event",
        prompt=PROMPT,
        year_index=1800,
        category_ids=("battles",),
        region_ids=(),
        explanation="Synthetic evidence, not a historical claim.",
        sources=(
            SourceCitation(
                source_id="wikipedia_en",
                record_id="fixture",
                url=SOURCE,
                rights_basis="CC BY-SA 4.0",
                raw_date="1800",
                calendar="gregorian",
                acquired_at=datetime(2026, 10, 14, tzinfo=UTC),
                snapshot_id="fixture",
                date_resolution="source-resolved:gregorian:year_index=1800",
            ),
        ),
        date_precision="year",
        review_status="approved",
        media_asset_id=None,
        fallback_key="battles",
    ).model_copy(update=changes)


def page(**changes: Any) -> Any:
    return links().CanonicalPage(
        **{
            "title": "Battle of Red River",
            "url": ARTICLE,
            "page_id": 42,
            "revision_id": 101,
            "namespace": 0,
            "missing": False,
            "disambiguation": False,
            "categories": ("Category:Battles",),
            **changes,
        }
    )


def assert_source(record: Any, url: str = SOURCE) -> None:
    assert (record.kind, record.label, record.url) == (
        "source",
        "Wikipedia calendar source",
        url,
    )


def test_unique_matching_entry_resolves_article() -> None:
    record = links().resolve_event_link(event(), HTML, {"Battle of Red River": page()})
    assert (record.kind, record.label, record.url) == (
        "article",
        "Wikipedia article",
        ARTICLE,
    )
    assert record.event_id == event().event_id
    assert record.source_url == SOURCE
    assert record.source_revision is None  # Pure HTML input carries no source revision.
    assert record.evidence_sha256 and len(record.evidence_sha256) == 64


def test_ambiguous_subject_uses_source() -> None:
    html = HTML.replace(
        " begins.",
        ' and the <a href="/wiki/Siege_of_Blue_River">Siege of Blue River</a> begin.',
    )
    prompt = "The Battle of Red River and the Siege of Blue River begin."
    pages = {
        "Battle of Red River": page(),
        "Siege of Blue River": page(
            title="Siege of Blue River",
            url="https://en.wikipedia.org/wiki/Siege_of_Blue_River",
        ),
    }
    assert_source(links().resolve_event_link(event(prompt=prompt), html, pages))


@pytest.mark.parametrize(
    "competitor", ["Siege of Blue River", "Siege of Blue River Valley"]
)
@pytest.mark.parametrize("evidence", ["absent", "incomplete", "invalid_ids"])
def test_unresolved_equal_or_longer_competitor_preserves_uncertainty(
    competitor: str, evidence: str
) -> None:
    prompt = f"The Battle of Red River and the {competitor} begin."
    html = HTML.replace(
        " begins.",
        f' and the <a href="/wiki/{competitor.replace(" ", "_")}">{competitor}</a> begin.',
    )
    pages = {"Battle of Red River": page()}
    if evidence != "absent":
        pages[competitor] = page(
            title=competitor,
            url="https://en.wikipedia.org/wiki/" + competitor.replace(" ", "_"),
            categories=() if evidence == "incomplete" else ("Category:Battles",),
            page_id=0 if evidence == "invalid_ids" else 42,
            revision_id=0 if evidence == "invalid_ids" else 101,
        )
    record = links().resolve_event_link(event(prompt=prompt), html, pages)
    assert_source(record)
    assert record.reason == "canonical_unavailable"


@pytest.mark.parametrize(
    "title", ["January 1", "1800", "List of battles", "United States of America"]
)
def test_calendar_year_and_country_links_are_not_event_articles(title: str) -> None:
    prompt = f"The {title} begins."
    html = f'<h2 id="Events">Events</h2><li>1800 – The <a href="/wiki/{title.replace(" ", "_")}">{title}</a> begins.</li>'
    assert_source(
        links().resolve_event_link(
            event(prompt=prompt),
            html,
            {
                title: page(
                    title=title,
                    url="https://en.wikipedia.org/wiki/" + title.replace(" ", "_"),
                    categories=("Category:Countries in North America",),
                )
            },
        )
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"missing": True},
        {"disambiguation": True},
        {"namespace": 1},
        {"url": "https://evil.example/wiki/Battle_of_Red_River"},
        {"url": "https://en.wikipedia.org@evil.example/wiki/Battle_of_Red_River"},
        {"url": "javascript:alert(1)"},
        {"url": ARTICLE + "?redirect=evil"},
        {"categories": ()},
        {"categories": ("Category:1800 births",)},
    ],
)
def test_redirect_disambiguation_missing_and_unsafe_url_fall_back(
    changes: dict[str, Any],
) -> None:
    assert_source(
        links().resolve_event_link(
            event(), HTML, {"Battle of Red River": page(**changes)}
        )
    )


def test_verified_redirect_uses_returned_canonical_url_not_invented_slug() -> None:
    canonical = "https://en.wikipedia.org/wiki/Battle_of_the_Red_River"
    record = links().resolve_event_link(
        event(),
        HTML,
        {"Battle of Red River": page(title="Battle of the Red River", url=canonical)},
    )
    assert record.kind == "article" and record.url == canonical


@pytest.mark.parametrize("title", ["War", "Battle of Green Mountain"])
def test_redirect_cannot_substitute_a_generic_or_unrelated_canonical_topic(
    title: str,
) -> None:
    assert_source(
        links().resolve_event_link(
            event(),
            HTML,
            {
                "Battle of Red River": page(
                    title=title,
                    url="https://en.wikipedia.org/wiki/" + title.replace(" ", "_"),
                )
            },
        )
    )


def test_missing_canonical_evidence_keeps_specific_unresolved_reason() -> None:
    record = links().resolve_event_link(event(), HTML, {})
    assert_source(record)
    assert record.reason == "canonical_unavailable"


@pytest.mark.parametrize(
    "html",
    [
        HTML + HTML,
        HTML.replace("1800", "1801"),
        HTML.replace("begins", "ends"),
        HTML.replace('id="Events"', 'id="Holidays"'),
    ],
)
def test_entry_must_match_exact_year_wording_and_context(html: str) -> None:
    assert_source(
        links().resolve_event_link(event(), html, {"Battle of Red River": page()})
    )


def test_bce_and_birth_entry_use_civil_year_and_biography_evidence() -> None:
    title = "Synthetic Ada Meridian"
    prompt = title + ", synthetic cartographer (d. 70)."
    html = f'<h2><span id="Births">Births</span></h2><li>44 BC – <a href="/wiki/Synthetic_Ada_Meridian">{title}</a>, synthetic cartographer (d. 70).</li>'
    record = links().resolve_event_link(
        event(prompt=prompt, year_index=-43, category_ids=("births",)),
        html,
        {
            title: page(
                title=title,
                url="https://en.wikipedia.org/wiki/Synthetic_Ada_Meridian",
                categories=("Category:44 BC births",),
            )
        },
    )
    assert record.kind == "article"
    assert_source(
        links().resolve_event_link(
            event(prompt=prompt, year_index=-44, category_ids=("births",)),
            html,
            {title: page()},
        )
    )


def test_verified_retained_article_source_is_reused() -> None:
    original = event()
    original = original.model_copy(
        update={"sources": (original.sources[0].model_copy(update={"url": ARTICLE}),)}
    )
    record = links().resolve_event_link(original, None, {"Battle of Red River": page()})
    assert (record.kind, record.label, record.url) == (
        "article",
        "Wikipedia article",
        ARTICLE,
    )


def test_calendar_evidence_records_actual_calendar_citation_not_first_dataset_source() -> (
    None
):
    original = event()
    dataset = original.sources[0].model_copy(
        update={"url": "https://example.org/dataset"}
    )
    original = original.model_copy(update={"sources": (dataset, original.sources[0])})
    record = links().resolve_event_link(original, HTML, {"Battle of Red River": page()})
    assert record.kind == "article"
    assert record.source_url == SOURCE


def test_generic_retained_topic_is_not_an_event_article() -> None:
    original = event(prompt="A war begins.")
    original = original.model_copy(
        update={
            "sources": (
                original.sources[0].model_copy(
                    update={"url": "https://en.wikipedia.org/wiki/War"}
                ),
            )
        }
    )
    record = links().resolve_event_link(
        original,
        None,
        {"War": page(title="War", url="https://en.wikipedia.org/wiki/War")},
    )
    assert (record.kind, record.label, record.url) == (
        "source",
        "Wikipedia source",
        "https://en.wikipedia.org/wiki/War",
    )


def test_unique_longest_subject_wins_without_fuzzy_wording() -> None:
    title = "Battle of Red River Valley"
    prompt = f"The {title} begins after the Battle of Red River."
    html = f'<h2 id="Events">Events</h2><li>1800 – The <a href="/wiki/Battle_of_Red_River_Valley">{title}</a> begins after the <a href="/wiki/Battle_of_Red_River">Battle of Red River</a>.</li>'
    record = links().resolve_event_link(
        event(prompt=prompt),
        html,
        {
            title: page(
                title=title,
                url="https://en.wikipedia.org/wiki/Battle_of_Red_River_Valley",
            ),
            "Battle of Red River": page(),
        },
    )
    assert record.kind == "article"
    assert record.url == "https://en.wikipedia.org/wiki/Battle_of_Red_River_Valley"


def synthetic_release(tmp_path: Path) -> Path:
    workspace, _ = final_batch(tmp_path)
    publish_release(workspace, tmp_path / "releases", "links-fixture", fixture=True)
    return tmp_path / "releases" / "links-fixture"


@pytest.mark.parametrize("destination", ["release", "public", "media", "cache"])
def test_build_cannot_write_inside_release_or_public_media(
    tmp_path: Path, destination: str
) -> None:
    release = synthetic_release(tmp_path)
    cache = tmp_path / "cache"
    output = {
        "release": release / "links.json",
        "public": tmp_path / "public" / "links.json",
        "media": tmp_path / "media" / "links.json",
        "cache": tmp_path / "safe.json",
    }[destination]
    if destination == "cache":
        cache = release / "cache"
    with pytest.raises(ValueError):
        links().build_event_links(release, cache, output, offline=True)
    assert not output.exists()


def test_build_cannot_write_inside_another_sealed_release(tmp_path: Path) -> None:
    release = synthetic_release(tmp_path)
    other = tmp_path / "other-sealed"
    other.mkdir()
    (other / "manifest.json").write_text("sealed sentinel")
    output = other / "links.json"
    with pytest.raises(ValueError):
        links().build_event_links(release, tmp_path / "cache", output, offline=True)
    assert not output.exists()
    assert (other / "manifest.json").read_text() == "sealed sentinel"


@pytest.mark.parametrize("offline", [True, False])
def test_cache_cannot_be_another_sealed_release_root(
    tmp_path: Path, offline: bool
) -> None:
    release = synthetic_release(tmp_path)
    sealed = tmp_path / "other-sealed"
    sealed.mkdir(mode=0o755)
    (sealed / "manifest.json").write_bytes(b"immutable manifest")
    (sealed / ".lock").write_bytes(b"immutable lock-name artifact")
    (sealed / ".lock").chmod(0o644)

    def snapshot() -> dict[str, tuple[int, bytes | None]]:
        return {
            str(p.relative_to(sealed)): (
                p.stat().st_mode,
                p.read_bytes() if p.is_file() else None,
            )
            for p in (sealed, *sealed.rglob("*"))
        }

    before = snapshot()
    with pytest.raises(ValueError, match="event_links_must_remain_private"):
        links().build_event_links(
            release, sealed, tmp_path / "links.json", offline=offline
        )
    assert snapshot() == before
    assert not (tmp_path / "links.json").exists()


def test_direct_evidence_cache_cannot_touch_a_sealed_root(tmp_path: Path) -> None:
    sealed = tmp_path / "sealed"
    sealed.mkdir(mode=0o755)
    (sealed / "manifest.json").write_bytes(b"sealed sentinel")
    before = {
        str(p): (p.stat().st_mode, p.read_bytes() if p.is_file() else None)
        for p in (sealed, *sealed.rglob("*"))
    }
    with pytest.raises(ValueError, match="event_links_must_remain_private"):
        with links().EvidenceCache(sealed, offline=True):
            pass
    assert before == {
        str(p): (p.stat().st_mode, p.read_bytes() if p.is_file() else None)
        for p in (sealed, *sealed.rglob("*"))
    }


def test_cache_lock_symlink_does_not_touch_an_unowned_file(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    unowned = tmp_path / "unowned"
    unowned.write_bytes(b"do not change")
    unowned.chmod(0o644)
    (cache_root / ".lock").symlink_to(unowned)
    with pytest.raises(ValueError):
        with links().EvidenceCache(cache_root, offline=True):
            pass
    assert unowned.read_bytes() == b"do not change"
    assert unowned.stat().st_mode & 0o777 == 0o644


def test_offline_build_is_deterministic_create_only_and_preserves_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = synthetic_release(tmp_path)
    before = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in release.rglob("*")
        if p.is_file()
    }

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("offline acquisition used transport")

    monkeypatch.setattr(httpx.Client, "stream", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "stream", forbidden)
    monkeypatch.setattr(links(), "acquire", forbidden)
    output = tmp_path / "private" / "links.json"
    first = links().build_event_links(release, tmp_path / "cache", output, offline=True)
    second = links().build_event_links(
        release, tmp_path / "cache", tmp_path / "second.json", offline=True
    )
    assert (first.total, first.article, first.source) == (2, 0, 2)
    assert first == second
    assert first.reasons == {"canonical_unavailable": 2}
    assert first.sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    payload = json.loads(output.read_bytes())
    assert payload["release_id"] == "links-fixture"
    assert len(payload["records"]) == 2
    assert output.stat().st_mode & 0o777 == 0o600
    assert output.parent.stat().st_mode & 0o777 == 0o700
    with pytest.raises(ValueError):
        links().build_event_links(release, tmp_path / "cache", output, offline=True)
    assert before == {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in release.rglob("*")
        if p.is_file()
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.content.event_links_cli",
            "build",
            "--release",
            str(release),
            "--cache",
            str(tmp_path / "cache"),
            "--output",
            str(tmp_path / "cli.json"),
            "--offline",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["source"] == 2


def test_canned_online_builder_reuses_evidence_and_reports_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.content.importer import import_snapshot
    from app.content.media import pipeline
    from tests.content.test_media import SELECTION
    from tests.content.test_onthisday import fixture_snapshot, row

    adapter, snapshot_root = fixture_snapshot(
        tmp_path, monkeypatch, [row(event=PROMPT)]
    )
    workspace = tmp_path / "work"
    import_snapshot(adapter, snapshot_root, workspace)
    pipeline.assign_chronology_media(SELECTION, workspace)
    assert all(r.passed for r in pipeline.finalize_media_receipts(workspace))
    publish_release(workspace, tmp_path / "releases", "calendar-fixture", fixture=True)
    release = tmp_path / "releases" / "calendar-fixture"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["action"] == "parse":
            return httpx.Response(
                200, json={"parse": {"title": "January 1", "revid": 991, "text": HTML}}
            )
        assert request.url.params["titles"] == "Battle of Red River"
        return httpx.Response(
            200,
            json={
                "batchcomplete": True,
                "query": {
                    "pages": [
                        {
                            "pageid": 42,
                            "lastrevid": 202,
                            "ns": 0,
                            "title": "Battle of Red River",
                            "canonicalurl": ARTICLE,
                            "categories": [{"title": "Category:Battles"}],
                        }
                    ]
                },
            },
        )

    install_transport(monkeypatch, handler)
    cache = tmp_path / "cache"
    first = links().build_event_links(
        release, cache, tmp_path / "online.json", offline=False
    )
    second = links().build_event_links(
        release, cache, tmp_path / "offline.json", offline=True
    )
    assert (first.total, first.article, first.source) == (1, 1, 0)
    assert first.reasons == {"verified_calendar_subject": 1}
    assert first == second
    record = next(
        iter(json.loads((tmp_path / "online.json").read_bytes())["records"].values())
    )
    assert record["source_revision"] == 991


def test_corrupt_cache_reason_cannot_break_source_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_transport(
        monkeypatch,
        lambda request: httpx.Response(503, json={"error": {"code": "maxlag"}}),
    )
    monkeypatch.setattr(links().time, "sleep", lambda delay: None)
    cache_root = tmp_path / "cache"
    with links().EvidenceCache(cache_root, offline=False) as cache:
        assert cache.calendar("January 1")[0] is None
    saved_file = next(cache_root.glob("*.json"))
    saved = json.loads(saved_file.read_bytes())
    saved["reason"] = {"corrupt": True}
    saved_file.write_text(json.dumps(saved))
    with links().EvidenceCache(cache_root, offline=True) as cache:
        assert cache.calendar("January 1") == (None, None, "cache_corrupt")


def test_non_json_throttle_still_honors_retry_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    count = 0
    sleeps: list[float] = []
    monkeypatch.setattr(links().time, "sleep", sleeps.append)

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(
            503, text="temporarily unavailable", headers={"Retry-After": "9"}
        )

    install_transport(monkeypatch, handler)
    with links().EvidenceCache(tmp_path / "cache", offline=False) as cache:
        assert cache.calendar("January 1")[0] is None
    assert count == 3
    assert sum(delay >= 9 for delay in sleeps) == 2


def install_transport(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )
    asynchronous = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: asynchronous(**kwargs, transport=httpx.MockTransport(handler)),
    )
    install_local_reader(monkeypatch)


def install_local_reader(
    monkeypatch: pytest.MonkeyPatch, runner: asyncio.Runner | None = None
) -> None:
    """Reader/business-policy unit tests; separate tests cover real child IPC."""
    transport = importlib.import_module("app.content.event_links_transport")

    def read(params: dict[str, str]) -> tuple[httpx.Response, bytes | None]:
        if runner is not None:
            return runner.run(transport.read_response(params))
        with asyncio.Runner() as owned:
            return owned.run(transport.read_response(params))

    monkeypatch.setattr(links(), "acquire", read)


@pytest.mark.parametrize(
    "response",
    [
        {"query": None},
        {"query": []},
        {"query": {"pages": ["categories"]}},
        {"query": {"pages": [], "redirects": [None]}},
    ],
)
@pytest.mark.parametrize("offline", [False, True])
def test_malformed_canonical_online_and_cache_publish_safe_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, Any],
    offline: bool,
) -> None:
    from app.content.importer import import_snapshot
    from app.content.media import pipeline
    from app.content.publish import canonical
    from tests.content.test_media import SELECTION
    from tests.content.test_onthisday import fixture_snapshot, row

    adapter, snapshot_root = fixture_snapshot(
        tmp_path, monkeypatch, [row(event=PROMPT)]
    )
    workspace = tmp_path / "work"
    import_snapshot(adapter, snapshot_root, workspace)
    pipeline.assign_chronology_media(SELECTION, workspace)
    assert all(r.passed for r in pipeline.finalize_media_receipts(workspace))
    publish_release(workspace, tmp_path / "releases", "malformed-fixture", fixture=True)
    release = tmp_path / "releases" / "malformed-fixture"
    cache_root = tmp_path / "cache"
    if offline:
        cache_root.mkdir(mode=0o700)
        for params, body in [
            (
                {"action": "parse", "page": "January 1", "prop": "text|revid"},
                {"parse": {"title": "January 1", "text": HTML, "revid": 991}},
            ),
            (
                {
                    "action": "query",
                    "titles": "Battle of Red River",
                    "redirects": "1",
                    "prop": "info|pageprops|categories",
                    "inprop": "url",
                    "cllimit": "max",
                },
                response,
            ),
        ]:
            params.update({"format": "json", "formatversion": "2", "maxlag": "5"})
            (
                cache_root / (hashlib.sha256(canonical(params)).hexdigest() + ".json")
            ).write_bytes(
                canonical({"params": params, "response": body, "reason": None})
            )

    def handler(request: httpx.Request) -> httpx.Response:
        assert not offline, "offline cache must never invoke transport"
        if request.url.params["action"] == "parse":
            return httpx.Response(
                200, json={"parse": {"title": "January 1", "text": HTML, "revid": 991}}
            )
        return httpx.Response(200, json=response)

    install_transport(monkeypatch, handler)
    monkeypatch.setattr(links().time, "sleep", lambda _delay: None)
    output = tmp_path / "links.json"
    summary = links().build_event_links(release, cache_root, output, offline=offline)
    assert (summary.total, summary.article, summary.source) == (1, 0, 1)
    assert summary.reasons == {"canonical_unavailable": 1}
    record = next(iter(json.loads(output.read_bytes())["records"].values()))
    assert (record["kind"], record["label"], record["url"]) == (
        "source",
        "Wikipedia calendar source",
        SOURCE,
    )


def test_canned_acquisition_caches_canonical_redirect_and_parse_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = links()
    requests: list[httpx.Request] = []
    sleeps: list[float] = []
    monkeypatch.setattr(api.time, "sleep", sleeps.append)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert str(request.url).startswith("https://en.wikipedia.org/w/api.php?")
        assert request.url.params["maxlag"] == "5"
        assert "HistoricalDateGame" in request.headers["User-Agent"]
        assert set(request.extensions["timeout"].values()) == {10}
        if request.url.params["action"] == "parse":
            assert request.url.params["prop"] == "text|revid"
            return httpx.Response(
                200, json={"parse": {"title": "January 1", "revid": 991, "text": HTML}}
            )
        assert len(request.url.params["titles"].split("|")) <= 50
        assert request.url.params["prop"] == "info|pageprops|categories"
        return httpx.Response(
            200,
            json={
                "batchcomplete": True,
                "query": {
                    "redirects": [
                        {"from": "Old battle title", "to": "Battle of Red River"}
                    ],
                    "pages": [
                        {
                            "pageid": 42,
                            "lastrevid": 101,
                            "ns": 0,
                            "title": "Battle of Red River",
                            "canonicalurl": ARTICLE,
                            "pageprops": {},
                            "categories": [{"ns": 14, "title": "Category:Battles"}],
                        }
                    ],
                },
            },
        )

    install_transport(monkeypatch, handler)
    with api.EvidenceCache(tmp_path / "cache", offline=False) as cache:
        html, revision, reason = cache.calendar("January 1")
        pages = cache.canonical(["Old battle title"])
    assert html == HTML and revision == 991 and reason is None
    assert pages["Old battle title"].url == ARTICLE
    assert len(requests) == 2 and sleeps and sleeps[0] >= 0.9
    with api.EvidenceCache(tmp_path / "cache", offline=True) as cache:
        assert cache.calendar("January 1") == (HTML, 991, None)
        assert cache.canonical(["Old battle title"]) == pages
    assert len(requests) == 2


@pytest.mark.parametrize(
    "mode", ["retry", "redirect", "oversized", "continuation", "malformed"]
)
def test_acquisition_bounds_fail_closed_and_cache_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    api = links()
    count = 0
    sleeps: list[float] = []
    monkeypatch.setattr(api.time, "sleep", sleeps.append)

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if mode == "retry":
            return httpx.Response(
                503, headers={"Retry-After": "7"}, json={"error": {"code": "maxlag"}}
            )
        if mode == "redirect":
            return httpx.Response(302, headers={"Location": "https://evil.example/"})
        if mode == "oversized":
            return httpx.Response(200, content=b" " * (5 * 1024 * 1024 + 1))
        if mode == "malformed":
            return httpx.Response(200, json={"parse": {"text": 5}})
        return httpx.Response(
            200,
            json={
                "continue": {"clcontinue": "42|more", "continue": "||"},
                "query": {
                    "pages": [
                        {
                            "ns": 0,
                            "pageid": 42,
                            "lastrevid": 101,
                            "title": "Battle of Red River",
                            "canonicalurl": ARTICLE,
                            "categories": [{"title": "Category:Battles"}],
                        }
                    ]
                },
            },
        )

    install_transport(monkeypatch, handler)
    with api.EvidenceCache(tmp_path / "cache", offline=False) as cache:
        if mode == "continuation":
            assert cache.canonical(["Battle of Red River"]) == {}
        else:
            assert cache.calendar("January 1")[0] is None
    expected = 3 if mode == "retry" else 1
    assert count == expected
    if mode == "retry":
        assert sum(delay >= 7 for delay in sleeps) == 2
    with api.EvidenceCache(tmp_path / "cache", offline=True) as cache:
        assert cache.calendar("January 1")[0] is None
    assert count == expected


def test_canonical_acquisition_splits_more_than_fifty_titles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sizes.append(len(request.url.params["titles"].split("|")))
        return httpx.Response(200, json={"batchcomplete": True, "query": {"pages": []}})

    install_transport(monkeypatch, handler)
    monkeypatch.setattr(links().time, "sleep", lambda _delay: None)
    with links().EvidenceCache(tmp_path / "cache", offline=False) as cache:
        assert cache.canonical([f"Synthetic battle {i}" for i in range(51)]) == {}
    assert sizes == [50, 1]


def test_slow_request_still_leaves_one_second_before_next_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [0.0]
    sleeps: list[float] = []

    def sleep(delay: float) -> None:
        sleeps.append(delay)
        clock[0] += delay

    def handler(request: httpx.Request) -> httpx.Response:
        clock[0] += 2
        return httpx.Response(
            200,
            json={
                "parse": {
                    "title": request.url.params["page"],
                    "text": HTML,
                    "revid": 991,
                }
            },
        )

    monkeypatch.setattr(links().time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(links().time, "sleep", sleep)
    install_transport(monkeypatch, handler)
    with links().EvidenceCache(tmp_path / "cache", offline=False) as cache:
        assert cache.calendar("January 1")[0] == HTML
        assert cache.calendar("January 2")[0] == HTML
    assert sleeps == [1.0]


@pytest.mark.parametrize("phase", ["headers", "slow_trickle"])
def test_absolute_acquisition_deadline_cancels_headers_and_stream_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    # Both transport interfaces model the same delayed provider so RED exercises
    # the old sync reader, while GREEN exercises native cancellable async reads.
    state = {"finished": False, "closed": False, "requests": 0}

    class Stream(httpx.SyncByteStream, httpx.AsyncByteStream):
        def __iter__(self) -> Any:
            for _ in range(24):
                time.sleep(0.5)
                yield b" "
            state["finished"] = True

        async def __aiter__(self) -> Any:
            for _ in range(24):
                await asyncio.sleep(0.5)
                yield b" "
            state["finished"] = True

        def close(self) -> None:
            state["closed"] = True

        async def aclose(self) -> None:
            state["closed"] = True

    class Transport(httpx.BaseTransport, httpx.AsyncBaseTransport):
        def handle_request(self, _request: httpx.Request) -> httpx.Response:
            state["requests"] += 1
            if phase == "headers":
                try:
                    time.sleep(11)
                    state["finished"] = True
                    return httpx.Response(200, content=b"{}")
                finally:
                    state["closed"] = True
            return httpx.Response(200, stream=Stream())

        async def handle_async_request(self, _request: httpx.Request) -> httpx.Response:
            state["requests"] += 1
            if phase == "headers":
                try:
                    await asyncio.sleep(11)
                    state["finished"] = True
                    return httpx.Response(200, content=b"{}")
                finally:
                    state["closed"] = True
            return httpx.Response(200, stream=Stream())

    sync, asynchronous = httpx.Client, httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: sync(**kwargs, transport=Transport())
    )
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: asynchronous(**kwargs, transport=Transport()),
    )
    install_local_reader(monkeypatch)
    threads = {thread.ident for thread in threading.enumerate()}
    started = time.monotonic()
    with links().EvidenceCache(tmp_path / "cache", offline=False) as cache:
        result = cache.calendar("January 1")
    elapsed = time.monotonic() - started
    assert elapsed < 10.8, (
        f"{phase} acquisition took {elapsed:.2f}s, beyond the 10s deadline"
    )
    assert result == (None, None, "response_deadline")
    assert state == {"finished": False, "closed": True, "requests": 1}
    assert {thread.ident for thread in threading.enumerate()} == threads
    with links().EvidenceCache(tmp_path / "cache", offline=True) as cache:
        assert cache.calendar("January 1") == result
    assert state["requests"] == 1


@pytest.mark.parametrize("phase", ["headers", "slow_trickle"])
def test_native_http_transport_deadline_closes_loopback_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    # Exercise pinned httpx/httpcore parsing and native cancellable socket reads,
    # not just a canned completed Response. The URL rewrite exists only here.
    state = {"port": 0, "requests": 0, "closed": 0, "finished": False}
    tasks: set[asyncio.Task[Any]] = set()

    async def provider(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        assert task is not None
        tasks.add(task)
        try:
            await reader.readuntil(b"\r\n\r\n")
            state["requests"] += 1
            if phase == "headers":
                await asyncio.sleep(11)
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
                await writer.drain()
            else:
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 24\r\n\r\n")
                await writer.drain()
                for _ in range(24):
                    await asyncio.sleep(0.5)
                    writer.write(b" ")
                    await writer.drain()
            state["finished"] = True
        finally:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()
            state["closed"] += 1

    async def start_server() -> asyncio.Server:
        server = await asyncio.start_server(provider, "127.0.0.1", 0)
        state["port"] = server.sockets[0].getsockname()[1]
        return server

    async def stop_server(server: asyncio.Server) -> None:
        server.close()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await server.wait_closed()

    class LoopbackTransport(httpx.AsyncHTTPTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            assert str(request.url).startswith("https://en.wikipedia.org/w/api.php?")
            request.url = request.url.copy_with(
                scheme="http", host="127.0.0.1", port=state["port"]
            )
            return await super().handle_async_request(request)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=LoopbackTransport()),
    )
    threads = {thread.ident for thread in threading.enumerate()}
    with asyncio.Runner() as runner:
        install_local_reader(monkeypatch, runner)
        with links().EvidenceCache(tmp_path / "cache", offline=False) as cache:
            server = runner.run(start_server())
            started = time.monotonic()
            try:
                result = cache.calendar("January 1")
            finally:
                runner.run(stop_server(server))
            elapsed = time.monotonic() - started
    assert result == (None, None, "response_deadline")
    assert elapsed < 10.8, f"native {phase} read took {elapsed:.2f}s"
    assert state["requests"] == state["closed"] == 1 and state["finished"] is False
    assert all(task.done() for task in tasks)
    assert {thread.ident for thread in threading.enumerate()} == threads


def install_worker_fixture(
    monkeypatch: pytest.MonkeyPatch, mode: str, marker: Path
) -> list[subprocess.Popen[bytes]]:
    """Launch the real parent IPC/lifecycle against a controlled child provider."""
    original = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def spawn(command: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        assert command[-2:] == ["-m", "app.content.event_links_transport"]
        assert all(child.returncode is not None for child in children)
        child = original(
            [
                sys.executable,
                "-m",
                "tests.content.event_links_worker",
                mode,
                str(marker),
            ],
            **kwargs,
        )
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", spawn)
    return children


def assert_workers_reaped(children: list[subprocess.Popen[bytes]]) -> None:
    assert children
    for child in children:
        assert child.returncode is not None
        assert child.stdin is not None and child.stdin.closed
        assert child.stdout is not None and child.stdout.closed
        with pytest.raises(ChildProcessError):
            os.waitpid(child.pid, os.WNOHANG)


def test_native_dns_stall_is_killed_and_reaped_before_cache_unlock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fcntl

    marker = tmp_path / "dns"
    children = install_worker_fixture(monkeypatch, "dns", marker)

    def stalled_dns(host: Any, *_args: Any, **_kwargs: Any) -> Any:
        # RED: the old client invokes this in the parent executor. GREEN: only
        # the independently killable child invokes its identical DNS fixture.
        assert host in ("en.wikipedia.org", b"en.wikipedia.org")
        marker.with_suffix(".started").write_text("native hostname resolver")
        time.sleep(12)
        marker.with_suffix(".finished").write_text("resolver finished")
        raise socket.gaierror("controlled stall, no external DNS")

    monkeypatch.setattr(socket, "getaddrinfo", stalled_dns)
    threads = {thread.ident for thread in threading.enumerate()}
    started = time.monotonic()
    with links().EvidenceCache(tmp_path / "cache", offline=False) as cache:
        result = cache.calendar("January 1")
    elapsed = time.monotonic() - started
    assert elapsed < 11.2, f"DNS acquisition/cleanup took {elapsed:.2f}s beyond 10+1s"
    assert result == (None, None, "response_deadline")
    assert marker.with_suffix(".started").exists()
    assert marker.with_suffix(".dns").read_text() == "en.wikipedia.org"
    assert not marker.with_suffix(".finished").exists()
    assert len(children) == 1 and children[0].returncode == -9
    assert_workers_reaped(children)
    assert {thread.ident for thread in threading.enumerate()} == threads
    with (tmp_path / "cache" / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with links().EvidenceCache(tmp_path / "cache", offline=True) as cache:
        assert cache.calendar("January 1") == result
    assert len(children) == 1
    assert_source(links().resolve_event_link(event(), None, {}))


@pytest.mark.parametrize(
    "phase", ["headers", "slow_trickle", "startup", "partial_output_stall"]
)
def test_isolated_attempt_bounds_native_reads_startup_and_pipe_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    # Losing the process-level deadline/reap or failing to drain a full stdout
    # pipe must fail this test, not merely a test of completed canned responses.
    marker = tmp_path / phase
    children = install_worker_fixture(monkeypatch, phase, marker)
    transport = importlib.import_module("app.content.event_links_transport")
    threads = {thread.ident for thread in threading.enumerate()}
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        transport.acquire({"action": "parse", "page": "January 1", "maxlag": "5"})
    elapsed = time.monotonic() - started
    assert elapsed < 11.2, (
        f"{phase} acquisition/cleanup took {elapsed:.2f}s beyond 10+1s"
    )
    assert marker.with_suffix(".started").exists()
    assert not marker.with_suffix(".finished").exists()
    if phase in {"headers", "slow_trickle"}:
        assert marker.with_suffix(".request").exists()
    assert len(children) == 1 and children[0].returncode == -9
    assert_workers_reaped(children)
    assert {thread.ident for thread in threading.enumerate()} == threads


@pytest.mark.parametrize(
    "mode",
    [
        "success",
        "oversize",
        "redirect",
        "throttle",
        "transport_error",
        "crash",
        "malformed_ipc",
    ],
)
def test_worker_ipc_keeps_response_limits_retries_and_source_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    marker = tmp_path / mode
    children = install_worker_fixture(monkeypatch, mode, marker)
    # Guard the old parent reader against any real network if boundary is absent.
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(
            **kwargs,
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={})
            ),
        ),
    )
    sleeps: list[float] = []
    monkeypatch.setattr(links().time, "sleep", sleeps.append)
    with links().EvidenceCache(tmp_path / "cache", offline=False) as cache:
        os.set_inheritable(cache.lock.fileno(), True)
        text, revision, reason = cache.calendar("January 1")
    if mode == "success":
        assert text == "x" * (4 * 1024 * 1024) and revision == 991 and reason is None
    else:
        assert text is revision is None
        assert (
            reason
            == {
                "oversize": "response_limits",
                "redirect": "acquisition_unavailable",
                "throttle": "provider_unavailable",
                "transport_error": "transport_unavailable",
                "crash": "transport_unavailable",
                "malformed_ipc": "malformed_evidence",
            }[mode]
        )
        assert_source(links().resolve_event_link(event(), text, {}))
    assert len(children) == (
        3 if mode in {"throttle", "transport_error", "crash"} else 1
    )
    if mode == "throttle":
        assert sleeps == [7.0, 1, 7.0, 1]
    assert_workers_reaped(children)
    with links().EvidenceCache(tmp_path / "cache", offline=True) as cache:
        assert cache.calendar("January 1") == (text, revision, reason)
    assert all(child.returncode is not None for child in children)


def test_acquisition_worker_launch_is_independent_of_callers_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    children = install_worker_fixture(monkeypatch, "success", tmp_path / "cwd")
    monkeypatch.chdir(tmp_path)
    transport = importlib.import_module("app.content.event_links_transport")
    response, body = transport.acquire(
        {"action": "parse", "page": "January 1", "maxlag": "5"}
    )
    assert response.status_code == 200 and body is not None
    assert json.loads(body)["parse"]["revid"] == 991
    assert_workers_reaped(children)


def test_parent_interrupt_drains_and_reaps_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    children = install_worker_fixture(monkeypatch, "startup", tmp_path / "interrupt")
    original_spawn = subprocess.Popen
    timeouts: list[float] = []

    def spawn(command: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        child = original_spawn(command, **kwargs)
        communicate = child.communicate

        def interrupted(**values: Any) -> Any:
            timeouts.append(values["timeout"])
            if len(timeouts) == 1:
                with pytest.raises(subprocess.TimeoutExpired):
                    communicate(input=values["input"], timeout=0.3)
                raise KeyboardInterrupt
            return communicate(**values)

        monkeypatch.setattr(child, "communicate", interrupted)
        return child

    monkeypatch.setattr(subprocess, "Popen", spawn)
    transport = importlib.import_module("app.content.event_links_transport")
    with pytest.raises(KeyboardInterrupt):
        transport.acquire({"action": "parse", "page": "January 1", "maxlag": "5"})
    assert len(timeouts) == 2 and 0 <= timeouts[0] <= 10 and 0 <= timeouts[1] <= 1
    assert len(children) == 1 and children[0].returncode == -9
    assert_workers_reaped(children)


def test_worker_start_failure_is_cached_as_safe_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("controlled worker creation failure")

    monkeypatch.setattr(subprocess, "Popen", unavailable)
    sleeps: list[float] = []
    monkeypatch.setattr(links().time, "sleep", sleeps.append)
    with links().EvidenceCache(tmp_path / "cache", offline=False) as cache:
        assert cache.calendar("January 1") == (None, None, "transport_unavailable")
    assert sleeps == [1, 1]
    with links().EvidenceCache(tmp_path / "cache", offline=True) as cache:
        assert cache.calendar("January 1") == (None, None, "transport_unavailable")
    assert sleeps == [1, 1]
    assert_source(links().resolve_event_link(event(), None, {}))
