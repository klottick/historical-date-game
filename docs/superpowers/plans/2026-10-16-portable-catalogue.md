# Portable Catalogue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Commit an offline-playable final catalogue and provide checked source acquisition and deterministic rebuild tooling without committing raw inputs.

**Architecture:** Separate strict runtime verification from full source/audit verification. A verified build exports an immutable runtime bundle; startup initializes only an unselected database. Locked reproduction reuses the existing content pipeline and compares every exported byte without activating a database.

**Tech Stack:** Python 3.15, Pydantic, SQLModel/PostgreSQL, pytest, uv, existing Docker/Vite application.

**Spec:** `docs/superpowers/specs/2026-10-16-portable-catalogue-and-reproducible-builds-design.md`

**Execution status:** Local engineering implemented and independently reviewed.
The default is immutable runtime v2; v1 is retained unchanged. Offline installation
and checked-local-source reproduction are verified. The user subsequently replaced
exact historical recreation as an acceptance requirement with public sources → a
new valid dataset. The original plan below is historical on that point; see
[current operations](../../operations/catalogue.md) for the separate fresh builder.
No source upload, push, merge or deployment was performed.

## Global Constraints

- "Raw downloads, acquisition caches, intermediate artifacts, private reports, credentials and database dumps remain outside Git."
- "No download, source cache lookup, database connection or content rebuild is allowed during runtime verification."
- "The first runtime release gets a **new ID**", selected here as `chronology-1276-runtime-v1`.
- "Installation never deletes gameplay, credentials, accounts, old catalogues or media."
- "No implicit startup catalogue upgrade."
- "The runtime bundle itself has no timestamp exclusion that weakens byte equality."
- "Unavailable redistributable inputs block that claim; they do not justify removing the five events or adding a compulsory manual curation process."
- Preserve the live LAN services and databases, dirty `.env`, all 83 staged paths in the primary checkout, and original source/evidence directories. Never run default inherited DB fixtures against retained databases.
- No push, release-asset upload, deployment, reset or feature-history publication. User waived further design/plan confirmation; execute continuously.

## Review Focus

1. Correctly hashed but semantically invalid catalogue: runtime verification must reject it (Task 1).
2. Missing legacy download route: rebuilding must fail honestly without substituting current API responses (Task 2).
3. Fresh retrieval timestamps and audit hashes differ: exact runtime bytes must still reproduce without falsifying retrieval evidence (Tasks 1–2).
4. Existing selected catalogue or conflicting asset: startup must preserve selection and files (Task 3).
5. Backend-only Docker context and frontend file serving: offline catalogue is included in the backend but answers are never HTTP-static files (Tasks 3–4).

---

## File Map

- `backend/app/content/runtime_models.py`: strict runtime manifest, default pointer and rebuild-lock contracts.
- `backend/app/content/runtime.py`: bounded path/byte checks, semantic runtime verification, validated snapshot, default pointer verification.
- `backend/app/content/runtime_export.py`: full-verifier-gated, deterministic create-only runtime export.
- `backend/app/content/source-selection.json`: backend-packaged copy of approved policy; sync-tested with research selection.
- `backend/app/content/build_context.py`: explicit scoped evaluation date, defaulting to actual current date outside locked builds.
- `backend/app/content/rebuild.py`: lock validation, pipeline orchestration and exact comparison.
- `backend/app/content/source_acquisition.py`: bounded digest-checked download/cache/source-envelope reads; no DB imports.
- `backend/app/content/rebuild_cli.py`: acquire/reproduce/update-candidate CLI.
- `backend/app/game/catalog_repository.py`: shared checked-snapshot transaction installer and existing audit activation.
- `backend/app/game/runtime_catalog.py`: runtime install, external asset provisioning and conservative initialization CLI.
- `backend/app/content/cli.py`: runtime-export/runtime-verify dispatch, preserving existing audit commands.
- `backend/app/core/config.py`, `backend/Dockerfile`, `backend/scripts/prestart.sh`: packaged media defaults and fresh initialization.
- `backend/catalogue/`: allowlisted final catalogue, source lock, notices and media only.
- `backend/tests/content/test_runtime*.py`, `test_rebuild.py`, `test_source_acquisition.py`: pure tests overriding destructive parent DB fixture.
- `backend/tests/api/routes/test_runtime_catalog.py`: guarded disposable PostgreSQL integration.
- `docs/operations/catalogue.md`, `backend/catalogue/README.md`, `README.md`, `deployment.md`, `.gitignore`: operator workflows and boundaries.

### Task 1: Verified runtime contract and exporter

**Files:** Create `runtime_models.py`, `runtime.py`, `runtime_export.py`, `source-selection.json` and `backend/tests/content/test_runtime.py`; modify `cli.py` and approved-policy lookup in `publish.py`.

**Interfaces:**
- `RuntimeCatalogManifest`: strict `kind="runtime-catalogue"`, version 1, single-component `release_id`, `created_at`, `fixture`, positive `event_count`, `files`, `media`, `origin_release_id`, `origin_manifest_sha256`, `content_sha256`.
- `BuildLock`: strict version 1, `recipe="catalogue-v1"`, `release_id`, `created_at`, `evaluation_date`, `origin_release_id`, `origin_manifest_sha256`, `python`, `dependencies: dict[str,str]`, `code_sha256: dict[str,SHA256]`, `sources: tuple[LockedSource,...]`, `payload_sha256: dict[str,SHA256]`.
- `LockedSource`: `path` (canonical relative), `sha256`, exact `size`, nullable HTTPS `url`, `role` (`chronology` or `supplements`); paths preserve raw snapshots/envelopes rather than accepted events. Original chronology receipt is one locked input; its historical observation is not a new transport receipt.
- `VerifiedRuntime`: immutable manifest/manifest bytes, categories/events/media records, checked file and asset bytes. Consumers must not reopen unchecked payloads.
- `verify_runtime(release_dir: Path, media_dir: Path, *, expected_sha256: str | None = None, require_beta: bool = False) -> VerifiedRuntime`.
- `verify_default(catalogue_root: Path) -> VerifiedRuntime`: strict default pointer with release ID + external manifest SHA, beta required.
- `runtime_payloads(audit_release: Path, media_dir: Path) -> tuple[CatalogManifest, dict[str,bytes], dict[str,bytes]]`: full verification first; deterministic final payloads and media indexed by basename.
- `export_runtime(audit_release: Path, media_dir: Path, catalogue_root: Path, lock: BuildLock) -> RuntimeCatalogManifest`: all lock payload digests must match; no overwrite, no implicit default change.

- [x] Write failing pure tests `test_verified_runtime_round_trip`, `test_semantic_mutation_with_rehashed_manifest_rejected`, `test_runtime_is_not_audit_release`, `test_runtime_rejects_duplicate_json_and_unsafe_paths`, `test_export_requires_full_verification`, `test_export_is_create_only`, `test_origin_reference_and_timestamp_are_locked`. Use actual small synthetic audit fixtures from `tests.content.test_publish.final_batch`, not copied production data. Parametrize missing/extra files, IDs/keys, wrong schema/count/year/source/media/license/fallbacks, symlink/hardlink, corruption, malformed pointer and size limits.
- [x] Run `cd backend` equivalent via workdir and `uv run pytest tests/content/test_runtime.py -q`; establish expected red failures before implementation.
- [x] Implement strict models and offline byte verifier. Reuse existing `validate_event`, taxonomy, fallback checks, rights policy and nonfixture >=1000 gate. Require exact allowlisted release files; validate all source/media/credit URLs and full reference closure. Bound individual and aggregate reads; reject duplicate keys/nonfinite JSON and special/link files before reading. Compare approved selection to the backend-packaged policy (sync test with docs), not an unavailable container path.
- [x] Implement exporter: sorted UUID/canonical newline JSON, fixed locked runtime metadata, new runtime ID, portable attribution, hashes excluding manifest self-hash. Manifest hashes build lock; lock hashes generated payloads/assets but not itself/manifest. Locked historical origin reference remains separate from replay audit digest. Verify fresh audit before producing any bundle. CLI runtime commands remain DB-independent.
- [x] Run the new tests and existing `tests/content/test_publish.py tests/content/test_validation.py`; `uv run ruff check` and `uv run mypy` on touched app files. Commit only task paths as `feat: add verified portable catalogue bundles`.

### Task 2: Pinned source acquisition and deterministic pipeline replay

**Files:** Create `build_context.py`, `source_acquisition.py`, `rebuild.py`, `rebuild_cli.py`, `backend/tests/content/test_source_acquisition.py`, `test_rebuild.py`; modify date evaluation only in `importer.py`, `adapters/onthisday.py`, `media/pipeline.py`, `publish.py` and rule-fingerprint inputs in `adapters/router.py`/`media/pipeline.py`; add ignored `/data/catalogue-build/`.

**Interfaces:** Consumes Task 1 `BuildLock`, `LockedSource`, `runtime_payloads`, `export_runtime`.
- `evaluation_date() -> date`; `locked_evaluation(day: date)` scoped context manager, resetting even after exceptions. Fresh acquisition receipts keep actual current time.
- `acquire_sources(lock: BuildLock, destination: Path, *, source_dir: Path | None = None) -> Path`: create-only input root; checked cache and explicit local source files accepted only against exact lock; HTTPS allowlist, no redirects, bounded timeout/bytes, descriptive missing source exception. Supports source-only supplement envelopes as JSONL inputs, not accepted-event fixtures.
- `reproduce(lock_path: Path, source_dir: Path, output: Path, *, expected_catalogue: Path | None) -> dict[str,object]`: validates toolchain/code/input digests, uses empty workspaces and whole input sets, runs existing importer/router/media/full publisher/full verifier, exports runtime, and compares every bundle byte. Returns differing files and added/changed/removed event IDs; CLI exits nonzero on mismatch.
- CLI: `python -m app.content.rebuild_cli acquire --lock ... --output ... [--source-dir ...]`; `reproduce --lock ... --sources ... --output ... --expected ...`; `update-candidate` runs a newly edited lock to a new output with no DB activation/default change.

- [x] Write failing tests `test_acquisition_checks_download_and_cache_hashes`, `test_missing_legacy_route_is_explicit`, `test_rejects_redirect_unsafe_host_and_oversize`, `test_locked_context_resets`, `test_whole_input_pipeline_reproduces_twice`, `test_retrieval_time_is_not_historical_observation`, `test_compare_reports_record_and_file_differences`, `test_replay_rejects_changed_code_or_context`. HTTP tests use `httpx.MockTransport`; synthetic fixtures monkeypatch only upstream pins as existing chronology tests do, never the transform or full verifier.
- [x] Run new test files to confirm expected red failures.
- [x] Implement bounded acquisition and strict lock checks. Prefer direct immutable upstream objects; nullable legacy URL requires explicit checked local source directory until a source-only release asset is hosted. Do not invent public URLs. Supplement envelopes must include the complete retained nonchronology raw candidate set and evidence, with no decisions/accepted records.
- [x] Add scoped eligibility context to existing normalization and late checks; leave audit receipt/generation times as current time. Include the context module in rule fingerprints. Rebuild original chronology receipt exactly from locked bytes; log current acquisition separately. Run content and media stages through existing APIs; never modify old fingerprints or receipts. Toolchain/code mismatch fails before fetching/building. Lock files never fingerprint generated runtime outputs.
- [x] Run acquisition/rebuild plus all content tests, lint and typecheck touched files. Commit as `feat: add pinned catalogue acquisition and replay`.

### Task 3: Safe database installation and packaged startup

**Files:** Modify `catalog_repository.py`, `config.py`, `Dockerfile`, `scripts/prestart.sh`; create `runtime_catalog.py`, pure startup tests and `backend/tests/api/routes/test_runtime_catalog.py`.

**Interfaces:** Consumes Task 1 checked snapshots. Shared `install_snapshot(session: Session, snapshot: ..., *, initialize_only: bool = False) -> str` uses existing transaction/advisory lock; audit activation still fully verifies first. `install_runtime(session: Session, catalogue_root: Path, *, initialize_only: bool, media_root: Path) -> str` verifies default, create-only provisions external assets then installs. `python -m app.game.runtime_catalog initialize|install` uses packaged default; `install` is explicit selection change.

- [x] Write red tests for fresh initialize, idempotence, different selected release preserved, conflicting manifest rollback, corruption before DB access, external media conflict and old run/Daily/credentials unchanged. Pure tests assert Docker COPY, startup ordering and no raw/build step. DB tests must use an owned disposable lives-profile database, never retained catalog/test databases.
- [x] Confirm red. Extract shared transaction insertion from existing audit activation without weakening audit verification. Serialize singleton selection before checking initialize-only; concurrent starts must not race into replacing another selection. Verify bytes once; do not reopen unchecked event payloads. Asset provisioning is create-only; failures never switch selection and do not remove old files.
- [x] Default `GAME_DATA_DIR` to absolute packaged catalogue path; preserve explicit settings. COPY only runtime catalogue into backend image. Run initialization after migrations/account creation in prestart; migration refusal remains unchanged. Existing different selection is reported, not silently replaced.
- [x] Run new guarded integration tests, existing catalogue activation tests, media/API projection tests, and touched lint/typecheck. Commit as `feat: initialize fresh games from packaged catalogue`.

### Task 4: Package the real catalogue and document independent workflows

**Files:** Add final `backend/catalogue/` tree, `docs/operations/catalogue.md`; update `README.md`, `deployment.md`; add `backend/tests/content/test_packaged_catalogue.py`.

**Interfaces:** Consume Tasks 1–3; use retained original audit/raw data read-only. All generated intermediate directories go in ignored task-owned workspace. Source-only archive creation is local; no upload/public release.

- [x] Write red tests `test_committed_default_is_offline_beta`, `test_real_release_parity`, `test_distribution_allowlist_and_licences`, `test_default_recipe_has_no_private_paths`. Parity test uses recorded committed content digest; separate local verification compares every event/media field with original release without making private paths a CI dependency.
- [x] Confirm missing-bundle red. Construct a source-only input directory from all original raw inputs: pinned chronology files/receipt, and the complete nonchronology raw envelopes/evidence from the retained audit release. Preserve originals. Inspect for secrets/local paths and retain source licences. Record digests in public lock; legacy URL stays null with documented limitation until separately approved hosting.
- [x] Rebuild a new full audit generation under the current code/date context and prove exact 1,276-event parity before runtime export. Build public lock from code/dependency digests and generated final payload digests, then export create-only `chronology-1276-runtime-v1`; write reviewed `default.json`. Generate twice in isolated ignored outputs and compare runtime bytes. Do not pretend local reconstruction proves public reacquisition of missing legacy inputs.
- [x] Document exact run/verify/initialize/acquire/reproduce/update commands, external media volume requirement, source archive licensing/availability, offline versus rebuild requirements, migration refusal and no default auto-upgrade. Document pending external archive publication prominently. No private operational artifact is a runtime dependency.
- [x] Run committed-bundle tests without network, inspect exact Git file allowlist and privacy/token scan, compare event/media parity with retained source, and commit only intended final files as `content: ship portable historical event catalogue`.

### Task 5: Clean-checkout verification and final review

**Files:** Add targeted clean-checkout verification regression under `backend/tests/content/` as needed; update this plan's checkbox/progress evidence and operator docs with actual limitations.

**Interfaces:** All earlier task outputs; no new product architecture.

- [x] Verify from an exported clean Git tree without `.env`, raw caches, `/tmp/opencode` dependency or private worktrees: runtime verify (no database) and independently owned fresh PostgreSQL initialize plus options/Daily/Freeplay/media/credits. Deny content-network requests during runtime checks. Preserve all existing test ownership guards and never reuse live service ports.
- [x] Test backend and frontend static-boundary attacks against the packaged data; pending card DTOs must remain answer-free. Build backend image if Docker is available; otherwise report an unverified container build rather than claim it passes. Confirm image context includes bundle but no source archives.
- [x] Run complete pure content/game/safety suites, guarded API/catalogue tests, lint/typecheck, and reproducibility comparison. Existing unrelated public-CI rollout blockers are reported separately, never hidden with skips.
- [x] Request independent whole-change review; fix material findings and reverify affected tests. Check only intended task commits/paths, primary staged tree, dirty `.env`, and live service identities. Commit test/docs corrections. Leave branch local; no merge, push, upload, reset or service restart.

Task 5 engineering evidence: unmodified backend Dockerfile built from an
environment-free Git export; runtime verification passed with `--network none`.
A new PostgreSQL 18.6 container (tmpfs, no host ports, no external network) and
backend containers sharing only its loopback namespace passed standalone real
prestart/gameplay/preservation acceptance and 90 guarded catalogue/API tests.
One unrelated random-extra-DB migration test was explicitly deselected. All 1,043
pure content/game/safety tests passed; touched-test Ruff/format/mypy passed.
All 17 runtime files (2,179,005 bytes) still match both full local reproductions
and the sealed update candidate, with no exclusions. Public-only reacquisition
remains blocked by unavailable legacy routes and unsupported release archives.
Frontend boundary evidence covers 20 read-only live probes plus 60 isolated
normal/alternate-config probes; no frontend product edits or restart. The new
`packaged_runtime_acceptance.py` is invoked explicitly, outside ordinary pytest
discovery, because it requires an entirely new owned schema. Independent review
and final acceptance remain coordinator gates, not an author self-review claim.

## Execution tracking

### Final-review follow-up: immutable v2

The first v1 export above remains historical and byte-for-byte retained, including
its assets and old-code recipe. Final review identified missing runtime Daily
pool semantics and standalone export's locked-date scope. The follow-up uses a
new immutable `chronology-1276-runtime-v2`, switches only the default pointer,
and seals the current shared Daily acceptance dependencies through a genuine
full pipeline rebuild. Only v2 claims current-code reproduction. No existing
database selection is implicitly upgraded; public exact reacquisition remains
blocked by the same unavailable legacy routes/unsupported archive transport.

Fresh v2 follow-up evidence: all 1,057 pure content/game/safety tests pass both
locally and in an environment-free Git export; two full reproductions match all
17 v2 files (2,179,373 bytes), without exclusions. A freshly built actual backend
image passes offline verification, real prestart/playable guest Daily/Freeplay,
options identity/session nonallocation, idempotence/preservation, and 140 guarded
Daily/API/catalogue tests (one unrelated extra-DB migration test deselected).
Only newly owned ephemeral containers were used and cleaned up. This establishes
local engineering verification, not independent public reacquisition or final
review acceptance.

Independent final rereview closed Daily-pool compatibility, standalone export's
locked-date scope and options identity-allocation coverage, with no new material
findings. Closing coordinator verification reran all 1,057 pure tests, checked
Ruff across `app`, and typechecked all 70 application source files successfully.
Offline default verification and current recipe pins also passed without importing
settings. The tested backend tree is unchanged by this completion record.

- Retired external gate by user request: exact public historical recreation is
  optional, not an acceptance prerequisite. Keep original receipt/supplements on
  Mustafar. The required replacement is a tested public-only fresh-dataset build,
  retaining full validation, provenance/attribution and immutable releases.

Each task uses red/green tests and a scoped independent review before dependent work. Task progress, decisions and evidence live in the plan-owned ignored SDD ledger; no private reports are committed. This plan is self-reviewed against all thirteen spec sections; external source availability remains an explicit acceptance limitation, not an implicit exception.
