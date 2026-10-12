# Historical Date Game Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Supply authoritative, resumable Freeplay and fair shared Daily games without exposing unanswered historical dates.

**Architecture:** A pure rules engine consumes frozen event/year inputs. PostgreSQL stores immutable catalog revisions, Daily definitions, run state, and idempotent operation outcomes. Thin authenticated routes return allowlisted public DTOs.

**Tech Stack:** Python 3.15, FastAPI, SQLModel/SQLAlchemy, Alembic, PostgreSQL 18, pytest, generated Hey API client.

**Spec:** `docs/superpowers/specs/2026-10-11-historical-date-game-beta-design.md`, sections 3-6, 8-9. Read the [master plan](2026-10-11-historical-date-game-beta.md) first.

## Global Constraints

All master constraints/contracts apply. Every timeline obeys all-pairs spacing; no same-year event, arbitrary round cap, client-supplied answer/score, or silently expanded Daily pool. Existing auth/account tests remain supported.

## Review Focus

Master focus 3 belongs to B3 (duplicate/stale/competing moves); focus 4 to B4 (rollover and frozen definitions). B2/B5 protect private artifacts/answers and retained media.

---

## Task B1: pure year, ordering, and run rules

**Files:** Create `backend/app/game/{__init__,years,types,rules,ordering}.py`, `backend/tests/game/{__init__,conftest,test_rules,test_invariants}.py`.

**Interfaces:** Define master domain contracts. Produce `filter_pool(events: tuple[EventKey, ...], rules: RunRules, known_categories: frozenset[str]) -> tuple[EventKey, ...]`, `seeded_order(event_ids: tuple[UUID, ...], seed: bytes) -> tuple[UUID, ...]`, `start_run(events: Mapping[UUID, EventKey], rules: RunRules, order: tuple[UUID, ...]) -> RunState`, `eligible_ids(state: RunState, events: Mapping[UUID, EventKey]) -> tuple[UUID, ...]`, `place(state: RunState, events: Mapping[UUID, EventKey], event_id: UUID, slot: int) -> PlacementOutcome`. Invalid settings/commands raise `RuleError(code: str)` in `types.py`.

- [ ] Write `test_civil_years_and_inclusive_union`, `test_all_pairs_gap_and_viable_anchor`, `test_wrong_place_loses_without_increment`, and `test_scan_skips_incompatible_events_until_exhaustion`. Pin these examples:

```python
assert to_year_index(1, "BCE") == 0
assert to_year_index(1, "CE") - to_year_index(2, "BCE") == 2
assert from_year_index(0).value == 1
assert from_year_index(0).era == "BCE"
# Anchor 1800, gap 10: 1810 is eligible; 1805 and another 1800 are not.
# Two selected categories include their union; a multi-tagged event appears once.
# An isolated event cannot be anchor even if first in the seeded order.
assert wrong_outcome.state.streak == before.streak
assert wrong_outcome.state.status == "lost"
```

- [ ] Run `uv run pytest tests/game/test_rules.py -q`; expect missing-engine failure. Add the directory's no-op session `db` fixture so the test does not touch PostgreSQL.
- [ ] Implement year conversion rejecting bool/float/zero magnitude/unknown era; strict range/category/gap validation; all-pairs eligibility; and starts requiring a compatible pair. Generation version 1 ranks canonical UUID bytes by `sha256(seed + uuid.bytes)` with UUID bytes as tie fallback. Generate a fresh 32-byte cryptographic seed server-side; preserve order and generation version. Select first viable anchor, then first unused eligible event in the complete order. Insert correctly only in the computed slot; malformed slots/terminal state raise without mutation.
- [ ] Write seeded invariant loops over small mixed BCE/CE pools, category selections, ranges, gaps, and multiple seeds in `test_invariants.py`. Assert every selected event belongs to its pool, all timeline pairs meet the gap, anchor streak is 0, each correct move adds 1, wrong moves add 0, and victory implies no eligible unused pool event even when eligible global events exist. Assert row-order permutation gives identical `seeded_order` and runs can exceed 100 placements.
- [ ] Run `uv run pytest tests/game/test_rules.py tests/game/test_invariants.py -q` with DB unavailable; expect all pass. Commit scoped engine/tests: `git commit -m "feat: implement chronology and frozen-pool run rules"`.

## Task B2: immutable catalogs, game tables, and migration safety

**Files:** Create `backend/app/game/{models,catalog_repository,run_repository}.py`, `backend/tests/api/routes/test_game_catalog.py`, `backend/app/alembic/versions/20261011_01_add_game_catalog_and_runs.py`; modify `backend/app/models.py`, `backend/app/alembic/env.py`, `backend/tests/conftest.py`, `backend/app/core/config.py`, `backend/app/api/routes/users.py`, `backend/app/content/cli.py`.

**Interfaces:** `activate_catalog(session: Session, release_dir: Path, media_dir: Path, *, require_beta: bool) -> str`; `load_events(session: Session, release_id: str) -> Mapping[UUID, EventRecord]`; `load_options(session: Session) -> CatalogOptions`. Define `CatalogOptions(release_id: str, categories: tuple[CategoryRecord, ...], start_year_index: int, end_year_index: int)` and `CatalogError(code: str)` in `catalog_repository.py`; B5 converts this to GameOptions and maps unavailable catalogs to 503. Repository `lock_run(session: Session, run_id: UUID, owner_id: UUID) -> GameRun`. Activation CLI: `activate --release --media [--require-beta]`.

- [ ] Write `test_activate_is_idempotent_and_immutable`, `test_frozen_revision_survives_activation`, and `test_account_deletion_cascades_owned_game_data`. Assert mutated release reuse is rejected, old answers/categories/media stay unchanged when new release becomes active, and deleting a user removes owned runs/operations without deleting shared catalog/Daily definitions. Use F0's dedicated PostgreSQL database, not a unit fixture override.
- [ ] Run `POSTGRES_DB=historical_date_game_test POSTGRES_PORT=5433 uv run pytest tests/api/routes/test_game_catalog.py -q`; expect missing-table/repository failure.
- [ ] Add tables `CatalogRelease`, `CatalogSelection` (singleton active pointer), `CatalogCategory`, `EventRevision`, `MediaAsset`, `DailyDefinition`, `GameRun`, `GameOperation`. Event/category/media JSON snapshots belong to a release; composite `(release_id,event_id)` is unique. DailyDefinition is unique on UTC date and stores seed, generation version, categories/config, pool/order, anchor, catalog release. GameRun stores owner/mode/daily ID, frozen rules/pool/order/state, revision, timestamps. GameOperation stores owner, operation UUID, scope/run ID, normalized payload digest, and exact public outcome; unique `(owner_id,operation_id)` prevents start/move reuse across scopes. Database unique `(owner_id,daily_definition_id)` enforces daily attempts. Use explicit cascade FKs from User -> GameRun/GameOperation; retain shared definitions/catalogs.
- [ ] Register game tables for Alembic without a circular import or changing existing model names. Add `GAME_DATA_DIR`; activate only C5-verified artifacts in one transaction and never replace published revision bytes. Extend test cleanup in dependency order before deleting User; retain the `_test` guard. User-delete paths must work with ORM-loaded relationships and DB cascades.
- [ ] Run targeted tests and fresh-database `uv run alembic upgrade head` using F0's test environment. On a disposable fixture database verify this revision's downgrade/upgrade; never downgrade a scored beta database. Commit model/migration/repositories and relevant edits: `git commit -m "feat: persist immutable catalogs and game state"`.

## Task B3: owned runs, projections, and exactly-once scoring

**Files:** Create `backend/app/game/{schemas,projections,run_service}.py`, `backend/tests/api/routes/test_game_runs.py`, `backend/tests/api/routes/test_game_concurrency.py`; update `run_repository.py`.

**Interfaces:** Define all master public/API contracts, plus `DailyStart(operation_id: UUID)` and `GameServiceError(code: str, status_code: int, message: str)`. `start_freeplay(session: Session, owner_id: UUID, command: FreeplayStart) -> RunPublic`; `read_run(session: Session, owner_id: UUID, run_id: UUID) -> RunPublic`; `list_active_runs(session: Session, owner_id: UUID) -> list[RunPublic]`; `submit_placement(session: Session, owner_id: UUID, run_id: UUID, command: PlaceCommand) -> RunPublic`; `project_run(run: GameRun, events: Mapping[UUID, EventRecord], categories: tuple[CategoryRecord, ...], media_base_url: str) -> RunPublic`.

- [ ] Write `test_owner_and_pending_answer_boundaries`, `test_invalid_settings_and_terminal_commands_do_not_lose`, `test_timeout_retry_returns_recorded_outcome`, `test_reused_operation_payload_conflicts`, and `test_two_tabs_score_only_once`. Assert another owner gets 404; unanswered card has exactly event/prompt/categories/media fields and no year/explanation/source; invalid slot/type/stale revision does not change state; identical retries return exact recorded outcome; changed payload/scope yields 409.

```python
assert retry.model_dump() == first.model_dump()
assert persisted.revision == before.revision + 1
assert persisted.streak == before.streak + 1
assert "seed" not in response_json and "order" not in response_json
assert set(response.pending.model_dump()) == {
    "event_id",
    "prompt",
    "category_ids",
    "media",
}
```

- [ ] Run the two named test files with F0's PostgreSQL environment; expect service/projection failure.
- [ ] Implement allowlisted projection of frozen revisions, including compliant image credits but never pending answer-bearing citations. On loss feedback contains the mistaken card/correct slot; timeline remains the correctly scored cards. Latest feedback persists for resume; completion never returns the unused pool. Frozen category labels/asset URLs come from the run's release.
- [ ] Implement transactions on the request Session: ownership lookup and row lock, operation replay/payload comparison **before** revision checks, strict pending-ID/slot/revision validation, pure transition, persisted state/move/outcome, and one commit. Roll back on any error. Account for dependency-triggered Session autobegin rather than blindly nesting `session.begin()`. Serialize Freeplay start operation creation with an owner-row lock; invalid configuration creates neither run nor operation. Generate fresh seed per new Freeplay; identical start retries return the same run.
- [ ] Add real two-session concurrency tests with synchronization before the request transaction: duplicate operation commits once; different operations with the same revision produce one success/one conflict; operation reuse on different owned runs yields conflict rather than 500 or partial scoring; injected failure before commit leaves no move/partial state. Recover/map uniqueness violations with rollback or savepoints. Test reconnect/read after successful commit with lost response. Run both files; expect all assertions passing on PostgreSQL.
- [ ] Commit service/projection/contracts/tests: `git commit -m "feat: validate owned idempotent game placements"`.

## Task B4: one shared Daily definition and attempt

**Files:** Create `backend/app/game/{daily_config,daily_service}.py`, `backend/tests/api/routes/test_game_daily.py`; update `run_repository.py`.

**Interfaces:** `DailyConfig(category_ids: tuple[str, ...], min_gap: int = 1)` reads the C1-approved fixed allowlist; year span derives from that release's selected category union. `read_daily(session: Session, owner_id: UUID, now: datetime) -> DailyOverview`; `start_daily(session: Session, owner_id: UUID, command: DailyStart, now: datetime) -> RunPublic`; `read_leaderboard(session: Session, day: date) -> LeaderboardPublic`. `now` is timezone-aware server input and injectable in tests, never caller-supplied API data.

- [ ] Write `test_daily_seed_pool_and_sequence_shared`, `test_concurrent_daily_starts_share_definition_and_attempt`, `test_midnight_and_midday_updates`, and `test_rank_ties_and_display_name_privacy`. Different accounts share seed/anchor/order and every correct-play next event; query row-order changes do not change generation. Same-account starts, including new operation IDs, return the existing active/completed attempt. `GET /daily` creates no scored run. Invalid/missing/full-catalog/sparse allowlist returns service error without consuming an attempt.
- [ ] Run `POSTGRES_DB=historical_date_game_test POSTGRES_PORT=5433 uv run pytest tests/api/routes/test_game_daily.py -q`; expect missing Daily service failure.
- [ ] Atomically insert-or-read one UTC-date definition using unique date and PostgreSQL conflict handling; persist the winning shared seed, generation version, anchor/order and release/categories/config. No per-account recomputation or secret disclosure. Validate restricted proper-subset pool/playable pair first. Uniqueness/conflict handling must recover through a savepoint or `ON CONFLICT`, not continue an aborted transaction. Lock owner to serialize attempt starts and reuse B3 operation machinery; validate operation scope/payload before returning an existing attempt.
- [ ] Test two separate sessions/accounts at one date, simulated process restart, and activating another catalog/config at midday. Assert today's definition and overview category labels unchanged, next UTC date has a new seed/definition, original run finishes after midnight on the old leaderboard, and owner may also start the new day. Verify unexpected service failures roll back the attempt.
- [ ] Implement completed-attempt ranking with SQL rank semantics (`1,1,3` for two top ties), no time tiebreaker. Display `full_name` when supplied, otherwise a generic player label; never email or private IDs. Freeplay/active attempts are excluded. Run Daily and concurrency tests; expect pass. Commit: `git commit -m "feat: freeze shared seeded daily games and rankings"`.

## Task B5: HTTP routes, media boundary, registration gate, and client

**Files:** Create `backend/app/api/routes/games.py`, `backend/tests/api/routes/test_game_api.py`; modify `backend/app/api/main.py`, `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/api/routes/{users,utils}.py`, `backend/tests/api/routes/test_users.py`, `development.md`; regenerate `frontend/src/client/` and `frontend/openapi.json`.

**Interfaces:** Master endpoint table, response models and error envelope. `PUBLIC_REGISTRATION_ENABLED: bool` defaults true for existing local/test behavior; beta explicitly false. A small unauthenticated `GET /api/v1/utils/public-config` returns `PublicConfig(registration_open: bool)` (define in `game/schemas.py`) so login/signup can hide enrollment without exposing game options; add it in existing `utils.py` route file. `GameOptions.registration_open` mirrors the same flag.

- [ ] Write `test_http_commands_reject_answers_and_score`, `test_media_mount_cannot_expose_catalog`, `test_signup_gate_preserves_admin_enrollment`, and `test_error_status_and_resume`. Assert 401 unauthenticated games, 404 another owner's run, 422 malformed input/unknown fields, 409 stale/reused operations, 503 unavailable catalog/Daily definition. Disabled signup gets 403; admin can still create accounts. Public config contains no secrets. `/media/` serves only assets, not manifests/answers or traversed paths.
- [ ] Run API and registration test files; expect missing-routes/gate failure.
- [ ] Implement thin routes using CurrentUser/SessionDep, server UTC clock, stable service-error mapping, and strict DTOs. Mount only `GAME_DATA_DIR/media` at `/media` (not the data root); allow missing local directory at startup without exposing parent files, and report unavailable catalog as service error on use. All scored operations remain authorized. Serve retained opaque asset paths/credits from public origin; do not log seed/answer bodies.
- [ ] Regenerate the client via `scripts/generate-client.sh`, then repeat generation and verify identical bytes. Inspect OpenAPI and built client for seed/order/pool/private source models; only public DTOs should be referenced.
- [ ] Run full backend tests, backend lint/type checks, frontend build/type checks, existing auth/account tests, and client reproducibility using master verification conventions. Commit only task edits/generated artifacts: `git commit -m "feat: expose secure game API and beta enrollment controls"`.
