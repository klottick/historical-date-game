# Historical Date Game Content and Media Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a reproducible, reviewed catalog of at least 1,000 playable historical events with usable pictures or meaningful fallback artwork.

**Architecture:** Offline, source-assisted curation produces private immutable catalog artifacts and retained public media. The game consumes published releases, never live source responses. File-based review is sufficient; no CMS or background service.

**Tech Stack:** Python 3.15, Pydantic, httpx, pytest, Pillow 12.3.0, JSON/JSONL, original SVG fallback art.

**Spec:** `docs/superpowers/specs/2026-10-11-historical-date-game-beta-design.md`, sections 2, 8-10. Read the [master plan](2026-10-11-historical-date-game-beta.md) first.

## Global Constraints

All master constraints/contracts apply. In particular: **at least 1,000 accepted events**, category union, immutable revisions/assets, no unresolved circa/range/conflicting years, complete provenance, no answer-bearing pending media, and no fabricated filler.

## Review Focus

Master focus 1 belongs to C2/C3 (uncertain calendars and aliases); focus 2 belongs to C4 (unsafe media and attribution conflicts). C5 checks integrity; C6 checks actual accepted yield rather than fixture volume.

---

## Task C1: evidence-based fact/image source decision

**Files:** Create `docs/research/historical-sources.md`, `docs/research/image-sources.md`, `docs/research/source-audit.csv`, `docs/research/source-selection.json`.

**Interfaces:** Produces master `SourceSelection` JSON plus 100-or-more audited candidate rows with `source_id`, `record_id`, categories/era/region, exact-year confidence, duplicate status, prompt difficulty, image match/rights, decision, and rejection/fallback reason. C2 validates the JSON; C3 implements its selected sources.

- [ ] Compare at least three plausible fact sources/combinations using documented terms and access methods. Evaluate structured knowledge bases, open chronologies, and specialist datasets; record links, retrieval dates, rate limits, calendar semantics, text reuse, attribution, and redistribution rights. No source is assumed suitable merely because it is readable online.
- [ ] Audit at least 100 representative candidate records across all proposed categories and multiple eras/world regions. Record accepted yield, distinct years, rejection/duplicate rates, recognition/difficulty, and coverage gaps. Describe an evidenced acquisition/review route to 1,000 accepted events, including expected review effort; do not extrapolate a single well-covered category to the whole catalog.
- [ ] Compare plausible image providers separately and attempt matches for the audited candidates. Report per-category relevant-image yield, rights suitability, sensitive/date-bearing content, adaptation/caching rights, retrieval cost, manual work, and fallback demand.
- [ ] Write the recommended source combination and versioned snapshot procedure into the reports/selection JSON. Recommend an explicit fixed Daily category allowlist whose resolved union is a proper playable subset; do not rotate categories or default to all eight.
- [ ] Obtain owner approval of source/media feasibility, effort/cost, and initial Daily categories. If evidence fails the target, stop and evaluate a combination or return for a scope decision, rather than writing the importer anyway.
- [ ] Commit only the approved research files: `git commit -m "docs: select evidenced historical and image sources"` after explicitly staging them.

## Task C2: normalized contracts and publication checks

**Files:** Create `backend/app/content/{__init__,schemas,validation}.py`, `backend/app/content/taxonomy.json`, `backend/tests/content/{__init__,conftest,test_validation}.py`, `backend/tests/fixtures/content/records.jsonl`; modify `.gitignore` for `data/game/` and acquisition caches.

**Interfaces:** Define all master content models with strict fields; add `ValidationIssue(code: str, field: str, message: str)`. Produce `validate_event(event: EventRecord, taxonomy: tuple[CategoryRecord, ...], current_year_index: int) -> tuple[ValidationIssue, ...]`. SourceCitation/MediaRecord retain the master provenance fields. C3 keeps unresolved raw candidates outside EventRecord.

- [ ] Write `test_year_precision_categories_and_provenance` and `test_prompt_answer_and_future_rejected` using synthetic records. Assert empty/unknown categories, missing provenance, future years, answer-year prompts, and unapproved records yield named issues; valid exact-year records pass. Add `test_uncertain_calendar_requires_explicit_resolution`: a source with an unresolved calendar/date cannot be promoted to an approved event.

```python
assert (
    approved_bce_event.year_index == 0
)  # Fixture represents 1 BCE; B1 owns conversion.
assert {i.code for i in validate_event(unknown_category, taxonomy, 2026)} >= {
    "unknown_category"
}
assert validate_event(approved_exact_year, taxonomy, 2026) == ()
```

- [ ] Run from `backend/`: `uv run pytest tests/content/test_validation.py -q`; expect failure on missing content contracts. The directory's no-op session `db` fixture must bypass the inherited database fixture.
- [ ] Implement strict models, taxonomy labels, source-selection validation, and `validate_event` in the named files. Require positive civil year inputs at acquisition boundaries; preserve resolved year index privately. Numeric pattern checks flag answer leaks for human review rather than rewriting historical names. Distinguish quarantine reasons from approved publication metadata.
- [ ] Rerun the same command with PostgreSQL unavailable; expect all tests passing with no database connection. Check `.gitignore` excludes large/raw content but not synthetic fixtures.
- [ ] Explicitly stage the named files and commit: `git commit -m "feat: define reviewed historical content contracts"`.

## Task C3: resumable selected-source imports and deduplication

**Files:** Create `backend/app/content/adapters/{__init__,base,selected}.py`, `backend/app/content/importer.py`, `backend/tests/content/test_importer.py`, `backend/tests/fixtures/content/source-snapshot.json`, `docs/operations/content-review.md`.

**Interfaces:** `RawCandidate(source_id: str, record_id: str, payload: dict[str, object])`; `ImportReport(imported: int, quarantined: int, duplicates: int)`. `SourceAdapter.fetch(snapshot_dir: Path) -> Iterable[RawCandidate]`; `SourceAdapter.normalize(raw: RawCandidate) -> EventRecord | tuple[ValidationIssue, ...]`; `import_snapshot(adapter: SourceAdapter, snapshot_dir: Path, workspace: Path) -> ImportReport`. File workspace contains candidates, quarantine, private identity aliases, and review decisions. Define these types in `adapters/base.py`/`importer.py`.

- [ ] Write `test_reimport_and_aliases_are_idempotent`, `test_birth_and_death_remain_distinct`, and `test_date_conflicts_quarantined` against mocked source snapshots. Require `second.imported == 0`, unchanged stable UUIDs, separate birth/death identities, and quarantine of circa/range/non-Gregorian dates without documented resolution. A reviewer-approved cross-source alias merges the same milestone and retains both citations; mere similar wording never auto-merges.
- [ ] Run `uv run pytest tests/content/test_importer.py -q`; expect missing-adapter/importer failure.
- [ ] Implement the selected adapters from C1, snapshot caching, retry/backoff within documented limits, raw-date preservation, category mappings, and resumable writes. Persist source-key-to-event UUID aliases; flag conflicting dates and suspected duplicates for review. File review decisions bind to candidate/source digests so a changed snapshot cannot inherit stale approval.
- [ ] Rerun the test command; expect all tests passing without internet/DB. Run the approved C1 sample through the real adapter and reconcile every candidate/rejection with the report.
- [ ] Document review commands/file layout and commit the importer, tests, synthetic fixture, and workflow: `git commit -m "feat: import and reconcile historical source snapshots"`.

## Task C4: legally usable media and representative fallbacks

**Files:** Create `backend/app/content/media/{__init__,rights,download,prepare,pipeline}.py`, `backend/app/content/fallbacks/{birth,death,battle,invention,book,art,exploration,politics}.svg`, `backend/tests/content/test_media.py`; modify `backend/pyproject.toml` and `backend/uv.lock`.

**Interfaces:** Define `MediaCandidate` in `media/rights.py` with MediaRecord's review/provenance fields except `sha256`/`filename` (computed after conversion). `MediaDecision(media: MediaRecord | None, fallback_key: str, reason: str | None)` in `pipeline.py`; `prepare_image(source: Path, output_dir: Path, metadata: MediaCandidate) -> MediaRecord`; `assign_media(event: EventRecord, selection: SourceSelection, workspace: Path) -> MediaDecision`. `download_image(url: str, destination: Path, allowed_hosts: tuple[str, ...]) -> Path` in `download.py`. Decisions record each event's search/review evidence, not just success.

- [ ] Write `test_date_bearing_required_credit_uses_fallback`, `test_unlicensed_or_nonadaptable_media_not_transformed`, `test_unsafe_redirect_and_oversized_decode_rejected`, and `test_original_fallbacks_cover_every_event_type`. Assert credits are never stripped to conceal a year; approved assets use opaque digest filenames, safe alt text, valid rights/acquisition metadata, and `contain` for important artwork. Verify failed downloads produce a reasoned fallback, not a missing image.
- [ ] Run `uv run pytest tests/content/test_media.py -q`; expect missing media-pipeline failure.
- [ ] Add stable Pillow and implement review-gated acquisition/preparation. Restrict HTTPS hosts to C1's allowlist; reject private/link-local targets on every redirect, apply timeouts and byte/pixel limits, and mock network tests. Promote decode bomb warnings to rejection; strip optional metadata, never required visible attribution. Use compatible WebP derivatives only when rights permit; otherwise select another image/fallback. Keep original source/rights records private.
- [ ] Draw/approve the eight original SVG fallbacks with a cohesive palette and frame-compatible shapes; no scripts/external resources. Copy them to immutable digest filenames and record `FallbackRecord` entries in `MediaCatalog`; altered art creates new bytes/URLs rather than replacing an old run's fallback. Implement per-event relevant-image attempts, sensitive-content checks, fit choice, and documented fallback reason. Shared assets may serve several events but must suit each subject/event type.
- [ ] Rerun media tests; expect pass, including broken/huge input. Manually inspect representative portrait, painting, book, and fallback renderings and obtain owner review of fallback art/coverage. Commit named media files/dependency locks: `git commit -m "feat: prepare reviewed event media and fallback artwork"`.

## Task C5: immutable releases and executable publication workflow

**Files:** Create `backend/app/content/{publish,cli}.py`, `backend/tests/content/test_publish.py`; update `docs/operations/content-review.md`.

**Interfaces:** `publish_release(workspace: Path, output_root: Path, release_id: str, *, fixture: bool = False) -> CatalogManifest`; `verify_release(release_dir: Path, media_dir: Path, *, require_beta: bool = False) -> CatalogManifest`. CLI entry: `uv run python -m app.content.cli <command>` supporting `import --selection --snapshot --workspace`, `media --selection --workspace`, `publish --workspace --output --release-id [--fixture]`, and `verify --release --media [--require-beta]`. C3/C4 reports are consumed unchanged.

- [ ] Write `test_release_is_complete_and_immutable`, `test_tampered_asset_or_path_escape_rejected`, and `test_beta_gate_counts_approved_distinct_events`. Assert reusing a release ID with changed bytes fails; unapproved/quarantined records and duplicate identities cannot inflate the count; `fixture=True` and 999 approved records both fail `require_beta=True`; missing rights/fallback assets fail publication.
- [ ] Run `uv run pytest tests/content/test_publish.py -q`; expect failure on missing publisher.
- [ ] Implement canonical artifact serialization, per-file and per-asset SHA-256 verification, atomic release-directory publication, and refusal to overwrite immutable releases. Include review/era/region/category/distinct-year/image coverage reports, selection/taxonomy, and fallback digests. Manifest identity is verified separately from file digest entries; forbid symlinks/path traversal. CLI runs approved adapters and reports quarantine counts without publishing them.
- [ ] Rerun tests; expect pass. Publish/reverify a small `--fixture` release twice and compare event/media identity and digests. `created_at` may differ for distinct release IDs; imports/record serialization must not vary with filesystem iteration order.
- [ ] Document exact file-review/approval and CLI usage; commit publisher/tests/workflow: `git commit -m "feat: publish integrity-checked historical catalogs"`.

## Task C6: assemble the actual beta catalog

**Files:** Create `docs/beta/catalog-readiness.md`; populate ignored `data/game/releases/<release-id>/` and `data/game/media/` via C3-C5. Store restricted source snapshots separately according to C1's terms.

**Interfaces:** Produces a non-fixture `CatalogManifest` with `event_count >= 1000`, approved selection/taxonomy, complete reviewed media/fallback references, and coverage evidence. B2 activates it; L2 verifies it.

- [ ] Acquire selected snapshots, normalize/deduplicate them, and process the review queue until at least 1,000 distinct events are approved. Review prompt recognisability/difficulty, dates/citations, answers not appearing in prompts, and each image's relevance/rights; do not automatically approve an entire raw batch.
- [ ] Review era/region/category/distinct-year imbalances against broad world history and audit at least 100 accepted records across the final distribution. Fix misleading wording/ambiguous claims and record remaining intentional gaps and image fallback reasons.
- [ ] Publish the release with C5's CLI and run `uv run python -m app.content.cli verify --release ../data/game/releases/<release-id> --media ../data/game/media --require-beta` from `backend/`. Expected: exit 0, fixture false, at least 1,000 accepted identities, all integrity/rights/media checks pass.
- [ ] Record source licenses, approved event count, coverage, image/fallback percentages, manual review evidence, and selected Daily categories in catalog-readiness. Have the owner approve suitability for friends; a numeric count alone is not approval.
- [ ] Commit only the readiness evidence/report, not bulk assets or private snapshots: `git commit -m "docs: certify reviewed beta catalog and imagery"`.
