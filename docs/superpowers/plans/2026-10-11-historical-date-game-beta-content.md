# Historical Date Game Content and Media Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a reproducible, reviewed catalog of at least 1,000 playable historical events with usable pictures or meaningful fallback artwork.

**Architecture:** Offline, automated source-assisted publication produces private immutable catalog artifacts and retained public media. The game consumes published releases, never live source responses. Versioned machine checks replace all human content/image approval; no CMS or background service.

**Tech Stack:** Python 3.15, Pydantic, httpx, pytest, Pillow 12.3.0, JSON/JSONL, original SVG fallback art.

**Spec:** `docs/superpowers/specs/2026-10-11-historical-date-game-beta-design.md`, sections 2, 8-10. Read the [master plan](2026-10-11-historical-date-game-beta.md) first.

## Global Constraints

All master constraints/contracts apply. In particular: **at least 1,000 accepted events**, category union, immutable revisions/assets, no unresolved circa/range/conflicting years, complete provenance, no answer-bearing pending media, and no fabricated filler.

User amendment 2026-10-12: no manual content/image review. Every reference to
approved/reviewed events or media means machine validation, not human or legal
certification. Do not require manual pilots, reviewers, art approval, or paid
curation. Preserve exact-year, provenance, licensing and meaningful imagery gates.

## Review Focus

Master focus 1 belongs to C2/C3 (uncertain calendars and aliases); focus 2 belongs to C4 (unsafe media and attribution conflicts). C5 checks integrity; C6 checks actual accepted yield rather than fixture volume.

---

## Task C1: evidence-based fact/image source decision

**Files:** Create `docs/research/historical-sources.md`, `docs/research/image-sources.md`, `docs/research/source-audit.csv`, `docs/research/source-selection.json`.

**Interfaces:** Produces master `SourceSelection` JSON plus 100-or-more audited candidate rows with `source_id`, `record_id`, categories/era/region, exact-year confidence, duplicate status, prompt difficulty, image match/rights, decision, and rejection/fallback reason. C2 validates the JSON; C3 implements its selected sources.

- [ ] Compare at least three plausible fact sources/combinations using documented terms and access methods. Evaluate structured knowledge bases, open chronologies, and specialist datasets; record links, retrieval dates, rate limits, calendar semantics, text reuse, attribution, and redistribution rights. No source is assumed suitable merely because it is readable online.
- [ ] Audit at least 100 representative candidate records across all proposed categories and multiple eras/world regions. Record accepted yield, distinct years, rejection/duplicate rates, recognition/difficulty, and coverage gaps. Describe an evidenced acquisition/review route to 1,000 accepted events, including expected review effort; do not extrapolate a single well-covered category to the whole catalog.
- [ ] Compare plausible image providers separately and attempt matches for audited candidates. Report per-category relevant-image yield, rights suitability, sensitive/date-bearing content, adaptation/caching rights, retrieval cost, automated checks, and fallback demand.
- [ ] Write the recommended source combination and versioned snapshot procedure into the reports/selection JSON. Recommend an explicit fixed Daily category allowlist whose resolved union is a proper playable subset; do not rotate categories or default to all eight.
- [x] Owner approved Wikidata/Wikipedia, metadata-validated Commons media plus original fallbacks, and fixed battles/inventions/exploration/politics Daily categories, with no manual review. Uncertain data is quarantined, not routed to human approval; no paid work is authorized. The real 1,000-event gate remains mandatory.
- [ ] Explicitly stage the four approved research files and amended spec/master/content/launch policy documents; commit `git commit -m "docs: select automated historical and image sources"`. This is policy finalization, not acceptance/publication of the research screens.

## Task C2: normalized contracts and publication checks

**Files:** Create `backend/app/content/{__init__,schemas,validation}.py`, `backend/app/content/taxonomy.json`, `backend/tests/content/{__init__,conftest,test_validation}.py`, `backend/tests/fixtures/content/records.jsonl`; modify `.gitignore` for `data/game/` and acquisition caches.

**Interfaces:** Define all master content models with strict fields; add `ValidationIssue(code: str, field: str, message: str)` and `VALIDATION_POLICY_VERSION = "automated-v1"`. Produce `validate_event(event: EventRecord, taxonomy: tuple[CategoryRecord, ...], current_year_index: int) -> tuple[ValidationIssue, ...]`, unchanged `candidate_digest(event: EventRecord) -> str`, `media_catalog_digest(catalog: MediaCatalog) -> str`, and `validate_receipt(event: EventRecord, receipt: ValidationReceipt, source_digests: tuple[str, ...], media_catalog: MediaCatalog) -> tuple[ValidationIssue, ...]`. The fourth argument is required: independently compute the current catalog's canonical JSON digest using the master's serialization contract; bind every MediaRecord/FallbackRecord field, not just event media references. SourceCitation/MediaRecord retain master provenance fields. C3 keeps unresolved raw candidates outside EventRecord; C5 invokes receipt validation with current source digests and MediaCatalog, not receipt-supplied substitutes.

- [ ] Write `test_year_precision_categories_and_provenance` and `test_prompt_answer_and_future_rejected` using synthetic records. Assert empty/unknown categories, missing provenance, future years, answer-year prompts, and unapproved records yield named issues; valid exact-year records pass. Add `test_uncertain_calendar_requires_explicit_resolution`: a source with an unresolved calendar/date cannot be promoted to an approved event.
- [ ] Add `test_passed_content_receipt_not_publication_ready`, `test_current_media_catalog_digest_rejects_changed_metadata`, and `test_complete_matching_content_media_receipt`. Reject passed C3-only receipts (`stage='content'`, no media digest); change media/fallback rights, creator, credit, alt/fit, source revision, filename or asset SHA while keeping EventRecord/identity/media_asset_id/fallback_key unchanged and reject old final receipts. Accept only a matching passed `content_media` receipt under `automated-v1` with matching event/source digests and independent current media_catalog_digest. Verify canonical digest stability across object-key/record ordering and that every catalog field is bound. C5 owns independent actual-byte integrity tests; a matching metadata digest alone does not test bytes. No human review gate.

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
- [ ] Implement strict models, taxonomy labels, source-selection validation, and event/receipt validation in the named files, including master ValidationReceipt stage/media digest fields and canonical catalog helper. Require positive civil year inputs at acquisition boundaries; preserve resolved year index privately. Answer leaks/uncertain dates are quarantined automatically rather than rewritten or sent to humans. Publication receipt validation requires `content_media`, passed, expected `automated-v1`, event identity/candidate/source matches and the independently computed current media catalog digest; reject missing media digests, content-only/failed/stale/wrong-policy receipts even if the event's status is `approved`. C5 enforces missing-receipt publication rejection and actual asset-byte integrity separately.
- [ ] Rerun the same command with PostgreSQL unavailable; expect all tests passing with no database connection. Check `.gitignore` excludes large/raw content but not synthetic fixtures.
- [ ] Explicitly stage the named files and commit: `git commit -m "feat: define reviewed historical content contracts"`.

## Task C3: resumable selected-source imports and deduplication

**Files:** Create `backend/app/content/adapters/{__init__,base,selected}.py`, `backend/app/content/importer.py`, `backend/tests/content/test_importer.py`, `backend/tests/fixtures/content/source-snapshot.json`, `docs/operations/content-review.md`.

**Interfaces:** `RawCandidate(source_id: str, record_id: str, payload: dict[str, object])`; `ImportReport(imported: int, quarantined: int, duplicates: int)`. `SourceAdapter.fetch(snapshot_dir: Path) -> Iterable[RawCandidate]`; `SourceAdapter.normalize(raw: RawCandidate) -> EventRecord | tuple[ValidationIssue, ...]`; `import_snapshot(adapter: SourceAdapter, snapshot_dir: Path, workspace: Path) -> ImportReport`. File workspace contains candidates, quarantine, private exact-identity aliases, and automated validation decisions/receipts, not human approvals. Define these types in `adapters/base.py`/`importer.py`.

- [ ] Write `test_reimport_and_aliases_are_idempotent`, `test_birth_and_death_remain_distinct`, and `test_date_conflicts_quarantined` against mocked source snapshots. Require `second.imported == 0`, unchanged stable UUIDs, separate birth/death identities, and quarantine of circa/range/non-Gregorian dates without a deterministic documented resolution. Only exact source entity plus milestone identity merges cross-source records and retains citations; similar wording/fuzzy aliases remain quarantined.
- [ ] Run `uv run pytest tests/content/test_importer.py -q`; expect missing-adapter/importer failure.
- [ ] Implement selected adapters from C1, snapshot caching, retry/backoff within documented limits, raw-date preservation, category mappings, and resumable writes. Persist exact source-key-to-event UUID aliases. Generate original template prompts from resolved milestone fields; quarantine conflicting dates, answer leaks and suspected duplicates automatically. Emit passed/failed content-only receipts bound to candidate/source digests and policy version, with `stage='content'` and `media_catalog_sha256=None`; these are never publication-ready even when passed. Changed inputs invalidate those content checks; C4 must revalidate content plus media for final receipts, not carry forward a C3 pass as acceptance.
- [ ] Rerun the test command; expect all tests passing without internet/DB. Run the approved C1 sample through the real adapter and reconcile every candidate/rejection with the report.
- [ ] Document automated validation/quarantine commands and receipt/file layout; commit the importer, tests, synthetic fixture, and workflow: `git commit -m "feat: import and reconcile historical source snapshots"`.

## Task C4: legally usable media and representative fallbacks

**Files:** Create `backend/app/content/media/{__init__,rights,download,prepare,pipeline}.py`, `backend/app/content/fallbacks/{birth,death,battle,invention,book,art,exploration,politics}.svg`, `backend/tests/content/test_media.py`; modify `backend/pyproject.toml` and `backend/uv.lock`.

**Interfaces:** Define `MediaCandidate` in `media/rights.py` with MediaRecord's review/provenance fields except `sha256`/`filename` (computed after conversion). `MediaDecision(media: MediaRecord | None, fallback_key: str, reason: str | None)` in `pipeline.py`; `prepare_image(source: Path, output_dir: Path, metadata: MediaCandidate) -> MediaRecord`; `assign_media(event: EventRecord, selection: SourceSelection, workspace: Path) -> MediaDecision`; `finalize_media_receipts(workspace: Path) -> tuple[ValidationReceipt, ...]` in `pipeline.py`. `download_image(url: str, destination: Path, allowed_hosts: tuple[str, ...]) -> Path` in `download.py`. Decisions record each event's search/review evidence, not just success. Batch finalization freezes the complete MediaCatalog before combined content/media revalidation; returned final receipts are persisted for C5 and consumed by the C5 `media` CLI workflow, not emitted during individual assignment.

- [ ] Write `test_date_bearing_required_credit_uses_fallback`, `test_unlicensed_or_nonadaptable_media_not_transformed`, `test_unsafe_redirect_and_oversized_decode_rejected`, and `test_original_fallbacks_cover_every_event_type`. Assert credits are never stripped to conceal a year; approved assets use opaque digest filenames, safe alt text, valid rights/acquisition metadata, and `contain` for important artwork. Verify failed downloads produce a reasoned fallback, not a missing image.
- [ ] Add `test_finalize_media_receipts_refreezes_and_revalidates_all_events`, `test_finalize_media_receipts_rejects_altered_asset_bytes`, and a complete matching machine-only batch case. Reject a passed C3 receipt as final proof; change media/fallback metadata with unchanged EventRecord and invalidate old receipts. After any catalog/rights change, refreeze and recompute receipts for **all** events, including those whose own references did not change. Assert finalization rechecks content and media/rights/relevance/safety plus actual image/fallback bytes against current record SHAs; altered bytes cannot earn a passed final receipt. Only the complete matching frozen batch produces valid passed `content_media` receipts without human review.
- [ ] Run `uv run pytest tests/content/test_media.py -q`; expect missing media-pipeline failure.
- [ ] Add stable Pillow and implement automated metadata/rights-gated acquisition/preparation. Restrict HTTPS hosts to C1's allowlist; reject private/link-local targets on every redirect, apply timeouts and byte/pixel limits, and mock network tests. Require supported per-file Commons licenses/credit and repository origin; missing/unknown/territorial-only rights fall back. Promote decode bomb warnings to rejection; strip optional metadata, never required attribution. Use derivatives only when rights permit. Conservatively exclude text-heavy maps/documents/title pages/plaques and uncertain sensitive/date-bearing media unless automated analysis establishes safety. No human review queue.
- [ ] Create the eight original SVG fallbacks with a cohesive palette and frame-compatible shapes; no scripts/external resources or copied stock assets. Machine-check them and copy to immutable digest filenames/FallbackRecord entries; altered art creates new URLs rather than replacing an old run's fallback. Implement per-event relevant-image attempts, automated safety checks, fit choice and explicit fallback reasons. Emit final `content_media` receipts AFTER the complete MediaCatalog batch is frozen: rerun content and media/rights/relevance/safety checks against current source inputs, records and actual asset bytes, binding candidate/source digests, `automated-v1` and `media_catalog_digest` of that entire catalog. C3 pass flags are not proof of completed media checks. Refreeze and recompute receipts for all events after any catalog/rights change; do not partially refresh receipts against a mutated catalog. No human art approval or commissioning is required.
- [ ] Rerun media tests; expect pass, including broken/huge input, unsupported licensing and text-heavy/date-bearing fallback cases. Check representative framing/credits/fallback rendering through automated/browser checks. Commit named media files/dependency locks: `git commit -m "feat: prepare validated event media and fallback artwork"`.

## Task C5: immutable releases and executable publication workflow

**Files:** Create `backend/app/content/{publish,cli}.py`, `backend/tests/content/test_publish.py`; update `docs/operations/content-review.md`.

**Interfaces:** `publish_release(workspace: Path, output_root: Path, release_id: str, *, fixture: bool = False) -> CatalogManifest`; `verify_release(release_dir: Path, media_dir: Path, *, require_beta: bool = False) -> CatalogManifest`. CLI entry: `uv run python -m app.content.cli <command>` supporting `import --selection --snapshot --workspace`, `media --selection --workspace`, `publish --workspace --output --release-id [--fixture]`, and `verify --release --media [--require-beta]`. The `media` command assigns/prepares the complete batch then invokes C4's batch finalization function; C5 consumes its persisted final receipts and current frozen MediaCatalog. C3 content receipts are diagnostic inputs only, never publication proof. C5 calls the four-argument C2 validator using independently obtained current event/source/catalog inputs, and independently checks actual assets; it does not trust report pass flags.

- [ ] Write `test_release_is_complete_and_immutable`, `test_tampered_asset_or_path_escape_rejected`, and `test_beta_gate_counts_approved_distinct_events`. Assert reusing a release ID with changed bytes fails; pending/quarantined records, duplicates and missing/stale/failed validation receipts cannot inflate the count; fixture releases and 999 accepted records fail `require_beta=True`; missing rights/fallback assets fail publication.
- [ ] Add `test_publish_rejects_passed_content_only_receipt`, `test_changed_media_or_fallback_metadata_rejected_with_unchanged_event`, `test_altered_media_or_fallback_bytes_rejected`, and `test_complete_matching_machine_only_batch`. In both publication and release verification, reject C3-only passes; mutate rights/creator/credits/alt/fit/source revision/filenames/SHAs without changing EventRecord references and reject stale final receipts even with refreshed artifact manifests. Independently alter image and fallback bytes while keeping metadata/receipts unchanged and reject actual-byte mismatches. Accept a complete matching machine-only batch with valid final receipts/current catalog and assets; no human review gate.
- [ ] Run `uv run pytest tests/content/test_publish.py -q`; expect failure on missing publisher.
- [ ] Implement canonical artifact serialization, per-file and per-asset SHA-256 verification, atomic release-directory publication, and refusal to overwrite immutable releases. In both publication and release verification, require passed `content_media` receipts under expected `automated-v1`, matching current event/candidate/source digests and an independently recomputed current `media_catalog_digest`; independently hash actual asset bytes against every referenced current MediaRecord/FallbackRecord SHA, including fallback assets for events with no image. A receipt/catalog digest alone is not asset integrity. Metadata changes invalidate final receipts; byte changes fail verification even with unchanged identity/media_asset_id/fallback_key. A revised record SHA requires C4 to refreeze/revalidate the entire batch. Include review/era/region/category/distinct-year/image coverage reports, selection/taxonomy, and fallback digests. Manifest identity is verified separately from file digest entries; forbid symlinks/path traversal. CLI runs approved adapters and reports quarantine counts without publishing them.
- [ ] Rerun tests; expect pass. Publish/reverify a small `--fixture` release twice and compare event/media identity and digests. `created_at` may differ for distinct release IDs; imports/record serialization must not vary with filesystem iteration order.
- [ ] Document automated acceptance/quarantine/receipt policy and CLI usage; commit publisher/tests/workflow: `git commit -m "feat: publish integrity-checked historical catalogs"`.

## Task C6: assemble the actual beta catalog

**Files:** Create `docs/beta/catalog-readiness.md`; populate ignored `data/game/releases/<release-id>/` and `data/game/media/` via C3-C5. Store restricted source snapshots separately according to C1's terms.

**Interfaces:** Produces a non-fixture `CatalogManifest` with `event_count >= 1000`, approved selection/taxonomy, complete reviewed media/fallback references, and coverage evidence. B2 activates it; L2 verifies it.

- [ ] Acquire selected snapshots and normalize/deduplicate them until at least 1,000 distinct events pass versioned automated validation with matching receipts. Enforce exact-date/provenance/prompt/rights checks per record; accepting a raw batch or changing status labels without running checks does not satisfy the gate.
- [ ] Produce era/region/category/distinct-year coverage reports and automate a >=100-record accepted-sample audit. Quarantine ambiguous claims, report wording/recognisability heuristics and coverage gaps honestly, and preserve all eight categories. Do not introduce a human acceptance queue or recognition pilot.
- [ ] Publish the release with C5's CLI and run `uv run python -m app.content.cli verify --release ../data/game/releases/<release-id> --media ../data/game/media --require-beta` from `backend/`. Expected: exit 0, fixture false, at least 1,000 accepted identities, all integrity/rights/media checks pass.
- [ ] Record source licenses, machine-accepted event count, coverage, picture/fallback percentages, validation policy/digests and Daily categories in catalog-readiness. State that the catalog is not human-reviewed or legally certified. No per-event/per-image owner approval is required; automated integrity and quality gates still apply.
- [ ] Commit only the readiness evidence/report, not bulk assets or private snapshots: `git commit -m "docs: certify reviewed beta catalog and imagery"`.
