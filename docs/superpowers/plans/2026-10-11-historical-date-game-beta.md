# Historical Date Game Beta Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a polished friends beta with at least 1,000 sourced events, meaningful imagery, configurable Freeplay, and a fair shared Daily game.

**Architecture:** Keep the existing FastAPI/React/PostgreSQL application. Separate offline content/media publication, pure chronology rules, transactional run/Daily services, and the tactile player interface. Freeze each run's catalog and pool; never expose unanswered years or Daily seeds.

**Tech Stack:** Existing Python 3.15, SQLModel/SQLAlchemy, React 19, TypeScript 7, Vite, Tailwind, pytest, Node test runner, and Playwright. Add stable Pillow 12.3.0 for offline media preparation and `@dnd-kit/react`/`@dnd-kit/dom` 0.5.0 for accessible dragging; CSS handles polish without another animation framework.

**Spec:** `docs/superpowers/specs/2026-10-11-historical-date-game-beta-design.md` (approved).

**Execution approval:** On 2026-10-12 the user chose Subagent-driven execution
and authorized separate modernization/planning commits plus an isolated beta
worktree. On 2026-10-12 the user approved source/image/Daily choices with **no
manual content or image review**. Hosting/cost and launch authorization remain
in force; human curation/pilots/labor budgets are not beta requirements.

## Global Constraints

- **At least 1,000 game-ready events in the initial catalog.** Count accepted, sourced, deduplicated events, not raw rows, category memberships, or fixtures.
- Minimum year gap is an integer of at least 1 and applies between **every pair of events in the run**; year bounds are inclusive.
- Category selections mean the **union**. No duplicate event or year within a run.
- One scored daily attempt per account per UTC day; fixed Daily categories and **one shared random seed per UTC date**.
- A dropped card previews its position; **Lock it in** submits the guess. No arbitrary round cap. Win only when the frozen run-specific pool has no eligible unused event.
- Prefer a relevant picture for every event. Research feasibility/rights; representative fallback artwork must cover every event when a usable picture is unavailable.
- Preserve mandatory attribution, hide unanswered years/seeds, provide touch/keyboard alternatives, and respect reduced motion.
- No manual content/image review or human publication queue. Accepted/approved means versioned automated validation passed; quarantine unresolved dates/duplicates and use fallbacks for unsupported or unsafe media. Do not claim human verification or legal clearance.
- No displayed civil year zero: CE `n -> n`, BCE `n -> 1 - n`. Keep catalog/media releases immutable for existing runs.
- Use current stable tooling, preserve existing modernization work, and follow repository conventions. No implementation, provisioning, merge, push, or task commits before plan/execution approval.
- Sound, chat, real-time multiplayer, friend groups, exact-date difficulty, full CMS, achievements, and monetization are outside beta scope.

## Review Focus

1. Uncertain/non-Gregorian source dates and cross-source aliases must be quarantined or explicitly resolved, never silently converted into confident duplicate facts (C2/C3).
2. Malformed/oversized images, unsafe download targets, or required date-bearing credits must produce a safe fallback without removing rights obligations (C4).
3. A timeout followed by duplicate/reordered responses or two tabs must not score twice or roll the UI back to an older state (B3/U2).
4. UTC rollover and mid-day catalog/configuration changes must preserve an already-started Daily while allowing the next day's independent attempt (B4).
5. Long touch timelines, canceled drags, failed media, and restored deployments must remain playable without losing scored progress (U3/L2).

---

## 1. Linked workstream plans

Read this master and the relevant workstream together. Shared contracts below
are normative; do not invent a second set of field names in a later task.

| Plan | Tasks | Independently verifiable deliverable |
| --- | --- | --- |
| [Content and media](2026-10-11-historical-date-game-beta-content.md) | C1-C6 | Source evidence, repeatable publication tools, reviewed catalog/assets |
| [Game backend](2026-10-11-historical-date-game-beta-backend.md) | B1-B5 | Tested engine, persisted runs, shared Daily, authorized API |
| [Player interface](2026-10-11-historical-date-game-beta-interface.md) | U1-U4 | Tactile accessible gameplay against the API |
| [Launch and trial](2026-10-11-historical-date-game-beta-launch.md) | L1-L3 | Safe deployment, verified release gates, friends feedback |

### Dependency/order map

`F0 -> C1 -> C2`. C1 is a feasibility checkpoint: return to the owner if
licensing, image access, usable yield, or cost cannot support the target.

After C2: C3-C5 build offline publication; B1 can build rules using fixtures.
B2 requires C5's artifact contract, then B3 -> B4 -> B5. U1 follows B5's generated
API contract, then U2 -> U3 -> U4. C6 assembles real content alongside backend/UI
work, but must finish before L2 launch verification. L1 can prepare operations
after B5/C5; L2 requires C6, B5, U4, and L1. L3 follows the release gate.

This ordering permits independent work; it is not permission to dispatch agents
or run destructive tests before the user chooses an execution method.

## 2. File/responsibility map

| Files | Responsibility |
| --- | --- |
| `backend/app/content/{schemas,validation}.py`, `taxonomy.json` | Private catalog/source/media contracts and checks |
| `backend/app/content/adapters/{base,selected}.py`, `importer.py` | Selected-source acquisition, normalization, resumable imports |
| `backend/app/content/media/{rights,download,prepare,pipeline}.py`, `fallbacks/` | Media selection, safe preparation, credits, representative art |
| `backend/app/content/{publish,cli}.py` | Manifest generation and command-line workflow |
| `backend/app/game/{years,types,rules,ordering}.py` | Pure year math, eligibility, seeded ordering, run transitions |
| `backend/app/game/{models,catalog_repository,run_repository}.py` | SQLModel persistence and transactional reads/writes |
| `backend/app/game/{schemas,projections,run_service,daily_service,daily_config}.py` | Public DTOs, authorization, idempotency, daily definitions/ranks |
| `backend/app/api/routes/games.py` | Thin HTTP mapping for game services |
| `backend/app/api/main.py`, `app/main.py`, `app/core/config.py` | Router, public media mount, deployment settings |
| `backend/app/models.py`, `app/alembic/env.py`, new migrations | Register new model metadata without replacing User/Item |
| `frontend/src/features/game/{api,config,placementState}.ts` | Typed API wrapper, form/year conversion, preview/reconciliation state |
| `frontend/src/features/game/{GameCard,EventImage,Timeline,InsertionSlot,GameBoard,GameResults,FreeplayForm,DailyPanel,ContentIssueDialog}.tsx`, `game.css` | Player UI, framed imagery, accessible placement, feedback and polish |
| `frontend/src/routes/_layout/{index,freeplay,daily}.tsx`, `frontend/src/routes/_layout/play/$runId.tsx` | Player navigation, configuration, resume, and game pages |
| `frontend/src/components/Sidebar/{AppSidebar,Main}.tsx` | Game-first navigation while preserving settings/admin |
| `backend/tests/{content,game}/`, `tests/api/routes/test_game_*.py`, `frontend/tests/game-*.{test,spec}.ts` | Unit, PostgreSQL concurrency, and browser verification |
| `docs/research/`, `docs/operations/`, `docs/beta/`, `scripts/{verify-beta,backup-beta,restore-beta}.sh` | Evidence, operations, release checks, trial notes |
| `docker-compose.beta.yml`, `docker-compose.traefik.beta.yml` | Production-safe overlays, retained catalog/media storage |

Create package `__init__.py` files with their owning task. No broad refactor or
deletion of sample CRUD is required. Generated `frontend/src/client/` and
`src/routeTree.gen.ts` are regenerated, never manually edited.

## 3. Shared contracts

### Content artifacts (C2 defines; C5 publishes; B2 consumes)

- Taxonomy slugs: `births`, `deaths`, `battles`, `inventions`, `literature`,
  `arts`, `exploration`, `politics`. Labels may be refined; changing slugs requires
  updating the contract before consumers are implemented.
- `SourceCitation(source_id: str, record_id: str, url: str, rights_basis: str,
  raw_date: str, calendar: str, acquired_at: datetime, snapshot_id: str,
  date_resolution: str)`; resolution states why the canonical year is justified.
  The adopted machine token is `source-resolved:<calendar>:year_index=<integer>`;
  `<calendar>` is `gregorian` or `proleptic-gregorian`. C3 emits it only from
  resolved exact sources, retaining raw dates/calendars unchanged. The token is
  not proof: C2 independently checks raw source/calendar/year consistency using
  positive civil magnitude `n`, with CE `n -> n` and BCE `n -> 1 - n` (1 BCE is 0).
  Preserved signed provider BCE encodings denote a positive civil magnitude.
  Unsupported/unresolved strings stay quarantined, with no manual queue. This
  acquisition-boundary check precedes B1, which later owns gameplay conversion.
- `CategoryRecord(id: str, label: str)`.
- `MediaRecord(asset_id: UUID, sha256: str, filename: str, source_url: str,
  creator: str, rights_basis: str, attribution: str, license_url: str | None,
  adaptation_allowed: bool, alt_text: str, fit: Literal['contain','cover'],
  acquired_at: datetime, source_revision: str)`.
- `FallbackRecord(key: str, filename: str, sha256: str, alt_text: str,
  creator: str, rights_basis: str)`; `MediaCatalog(records: tuple[MediaRecord, ...],
  fallbacks: dict[str, FallbackRecord])` is the `media.json` contract. All public
  asset filenames are immutable content digests, including fallbacks.
- `EventRecord(event_id: UUID, identity_key: str, prompt: str, year_index: int,
  category_ids: tuple[str, ...], region_ids: tuple[str, ...], explanation: str,
  sources: tuple[SourceCitation, ...], date_precision: Literal['year','month','day'],
  review_status: Literal['pending','quarantined','approved'], media_asset_id:
  UUID | None, fallback_key: str)`. Identities are opaque UUIDs; corrections keep
  event identity and create a new release revision. `identity_key` is private.
- Retain the field name `review_status` for contract stability; `approved` now
  means machine-validated only. `ValidationReceipt(event_id: UUID,
  candidate_sha256: str, source_sha256: tuple[str, ...], policy_version: str,
  stage: Literal['content','content_media'], media_catalog_sha256: str | None,
  passed: bool, checked_at: datetime, issue_codes: tuple[str, ...])` is defined
  by C2. C3 emits `stage='content'`, `media_catalog_sha256=None`; even a passed
  content receipt is never publication-ready. C4 revalidates content plus media
  and emits final `stage='content_media'` receipts only after the complete
  MediaCatalog batch is frozen. Any catalog/rights change requires C4 to refreeze
  the batch and recompute receipts for all events, not reuse C3 pass flags.
- C2 defines `media_catalog_digest(catalog: MediaCatalog) -> str` as SHA-256 of
  canonical JSON (UTF-8, sorted object keys, compact separators, deterministic
  typed serialization and records ordered by asset ID). It binds **all MediaRecord/FallbackRecord fields**:
  rights, creator, credits/attribution, license/adaptation, alt text, fit,
  source revision/URL/acquisition metadata, keys/IDs, digest filenames and asset SHA
  fields. `candidate_digest(event: EventRecord) -> str` is unchanged and does not
  absorb media metadata. C2 defines
  `validate_receipt(event: EventRecord, receipt: ValidationReceipt, source_digests: tuple[str, ...], media_catalog: MediaCatalog) -> tuple[ValidationIssue, ...]`;
  publication requires `content_media`, passed, expected `automated-v1`, matching
  event identity/candidate/source digests and an independently recomputed current
  media catalog digest, never a digest copied from the receipt.
- C5 also independently checks actual asset bytes against every referenced
  current MediaRecord/FallbackRecord SHA at publication and release verification;
  the receipt digest is **not asset integrity**. Changed media/fallback metadata
  invalidates final receipts even with unchanged event identity/media_asset_id/
  fallback_key. Changed asset bytes fail verification even if those references
  and metadata are unchanged; updating the catalog SHA to match new bytes requires
  fresh C4 batch receipts. Receipt files remain private in releases. No human review gate.
- `SourceSelection(source_ids: tuple[str, ...], allowed_media_hosts: tuple[str, ...],
  decision_report: str, daily_category_ids: tuple[str, ...])` is the machine-readable
  result of C1; adapters validate their source-specific configuration themselves.
- `CatalogManifest(schema_version: int = 1, release_id: str, created_at: datetime,
  event_count: int, fixture: bool, files: dict[str, str])`; `files` maps relative
  artifact paths to SHA-256 digests. Paths cannot escape the release directory.
- Release layout: `manifest.json`, `taxonomy.json`, `events.jsonl`, `media.json`,
  `validation.json`, `source-selection.json`, and validation/coverage reports. Image bytes live separately
  at `media/<sha256>.webp`; generic fallbacks live at `media/<sha256>.svg`.
- Runtime root: `GAME_DATA_DIR` (default `../data/game` when running in backend;
  containers set `/app/data/game`). Releases/rights reports remain private;
  **only** its `media/` subdirectory is publicly served. Bulk data/media and raw
  downloads are ignored by Git. Commit small, explicitly synthetic test fixtures.

### Domain contracts (B1 defines)

- `YearInput(value: int, era: Literal['BCE','CE'])`; positive values only.
  `to_year_index(value: int, era: str) -> int`; `from_year_index(index: int) -> YearInput`.
- `EventKey(event_id: UUID, year_index: int, category_ids: frozenset[str])`.
- `RunRules(category_ids: frozenset[str], start_year_index: int,
  end_year_index: int, min_gap: int)`.
- `RunState(rules: RunRules, order: tuple[UUID, ...], timeline: tuple[UUID, ...],
  pending_event_id: UUID | None, streak: int, status: Literal['active','lost','won'],
  revision: int)`; order contains the already category/range-filtered pool.
- `PlacementOutcome(state: RunState, correct: bool, revealed_event_id: UUID,
  correct_slot: int)`. Incorrect slots within legal bounds lose; malformed/stale
  commands raise typed errors, not a losing outcome.

### Public/API contracts (B3 defines; U1-U4 consume)

- `GameConfig(category_ids: list[str], start: YearInput, end: YearInput, min_gap: int)`.
- `FreeplayStart(operation_id: UUID, catalog_release_id: str, config: GameConfig)`.
- `PlaceCommand(operation_id: UUID, expected_revision: int, event_id: UUID, slot: int)`.
- `MediaPublic(url: str, fallback_url: str, alt_text: str, fit: str,
  credits: list[CreditPublic])`; `CreditPublic(label: str, url: str | None)`.
- `PendingCard(event_id: UUID, prompt: str, category_ids: list[str], media: MediaPublic)`.
- `RevealedCard` adds `year: YearInput`, `explanation: str`, and `sources: list[SourcePublic]`;
  `SourcePublic(label: str, url: str)`. Never derive PendingCard by dumping a private EventRecord.
- `MoveFeedback(correct: bool, card: RevealedCard, correct_slot: int)`.
- `RunPublic(run_id: UUID, mode: Literal['daily','freeplay'], daily_date: date | None,
  catalog_release_id: str, config: GameConfig, categories: list[CategoryRecord],
  status: Literal['active','lost','won'], streak: int, revision: int, timeline: list[RevealedCard],
  pending: PendingCard | None, feedback: MoveFeedback | None)`.
- `GameOptions(catalog_release_id: str, categories: list[CategoryRecord],
  start: YearInput, end: YearInput, registration_open: bool)`.
- `DailyOverview(day: date, reset_at: datetime, category_ids: list[str],
  attempt_run_id: UUID | None)`; Daily start accepts only `operation_id`, not a seed/config/day.
- `LeaderboardEntry(display_name: str, streak: int, status: Literal['lost','won'], rank: int)`;
  `LeaderboardPublic(day: date, entries: list[LeaderboardEntry])`.
- Public response models forbid unknown fields. Game errors use existing FastAPI
  `detail` with stable `code`/`message` fields; teach `frontend/src/utils.ts` to
  extract structured details without regressing existing string/validation errors.

| Endpoint under `/api/v1/games` | Response |
| --- | --- |
| `GET /options` | GameOptions |
| `POST /freeplay` | RunPublic |
| `GET /active-runs` | list[RunPublic] owned by caller |
| `GET /runs/{run_id}` | RunPublic owned by caller |
| `POST /runs/{run_id}/placements` | RunPublic; idempotent recorded response |
| `GET /daily` | DailyOverview; does not allocate an attempt |
| `POST /daily` | RunPublic; current server UTC day only |
| `GET /daily/{day}/leaderboard` | LeaderboardPublic; authenticated |

## 4. Task F0: preserve baseline and make tests safe

**Files:** Create `backend/tests/db_guard.py`, `backend/tests/safety/{__init__,conftest,test_db_guard}.py`; modify `backend/tests/conftest.py`, `.github/workflows/test-backend.yml`, `.github/workflows/playwright.yml`, and `development.md` at execution. Preserve all existing edits. Pure-test overrides are owned by C2/B1.

**Interfaces:** `require_test_database(name: str) -> None` in `tests/db_guard.py` raises RuntimeError unless the name ends in `_test`. Backend integration commands use a dedicated PostgreSQL database with that suffix; no production database is touched.

- [ ] Record `git status --short` and obtain the owner's decision on the uncommitted modernization baseline before task commits. Do not use `git add .`, discard changes, or silently bundle the upgrade with game work.
- [ ] Write `test_rejects_non_test_database` asserting RuntimeError for `app`, empty names, and `production`, and `test_accepts_explicit_test_database` accepting `historical_date_game_test`. The safety directory overrides the inherited `db` fixture with a session no-op. Run `uv run pytest tests/safety/test_db_guard.py -q` from backend; expect missing-guard failure.
- [ ] Implement the guard and invoke it before `init_db` in the root session fixture; rerun the safety tests and expect pass without PostgreSQL. Set backend/browser CI's job-level `POSTGRES_DB=historical_date_game_test` so migrations, containers, and tests use the same isolated DB; retain existing workflow modernization. Document the test environment.
- [ ] Create an execution-only Compose project and database `historical_date_game_test`, use migrations, and set `POSTGRES_DB=historical_date_game_test POSTGRES_PORT=5433` for host integration commands. The existing session fixture deletes users/items; this isolation is mandatory.
- [ ] Record green baseline backend/frontend checks using the approved toolchain. No broad `compose down -v`; stop only the execution-owned project when finished.
- [ ] Commit the guard separately only after the baseline and execution choices are approved.

## 5. Verification conventions and checkpoints

- Backend unit directories C2/B1 override the root autouse `db` fixture with a
  session-scoped no-op; prove they pass with PostgreSQL stopped. Do not change
  API/database tests to SQLite: row locks and unique insert races require PostgreSQL.
- From `backend/`: `uv run pytest <named-test-file> -q`; full integration:
  `POSTGRES_DB=historical_date_game_test POSTGRES_PORT=5433 uv run pytest`.
- From `frontend/`: `npm run test:unit`, `npm run lint`, `npm run typecheck`,
  `npm run build`; browser commands use `VITE_API_URL` and `MAILCATCHER_HOST` as
  in existing tests. Set the backend's database to the isolated test DB and seed
  its superuser before browser tests; do not run cleanup concurrently with them.
- Regenerate API clients using `scripts/generate-client.sh` with backend `.venv`
  and the selected Node runtime on PATH. Confirm repeat generation is byte-identical.
- Each code task has a red/green test cycle and a scoped commit checkpoint after
  approval. Research/content/operations tasks use documentary/runtime evidence,
  not fabricated failing unit tests for external facts.
- Source/rights decisions and the fixed Daily categories were approved at C1
  with automated-only publication. Fixture development cannot satisfy the real
  catalog gate. No additional human content/media approval is required.
- New dependencies were checked against registry/documentation during planning:
  dnd-kit 0.5.0 supports React 19; Pillow 12.3.0 is stable. Recheck compatible
  stable versions at execution; preserve TypeScript 6's generator-only pin.

## 6. Done means beta-ready, not merely feature-complete

Require all C/B/U/L evidence, a non-fixture published catalog with at least 1,000
accepted events and complete image/fallback coverage, working Daily fairness,
tested reload/timeout recovery, accessible polished controls, HTTPS, restricted
enrollment, and a successful restore including retained media. Then run a
one-week friends trial seeking feedback from at least three players.

Content yield/review and image rights are the primary schedule risks. Do not
promise a calendar launch date until C1 measures them. Stop for a scope decision
if evidence shows the 1,000-event requirement cannot be met; never reduce it
unilaterally. Review the plan and choose Native or Subagent-driven execution
before any implementation task starts.

## 7. Planning self-review and requirement traceability

| Approved specification section | Owning tasks |
| --- | --- |
| 1: audience, scope, enrollment and 1,000-event goal | C1/C6, U1/U4, B5/L1 |
| 2: sources, taxonomy, provenance, pictures and publication | C1-C6, B2 |
| 3: civil years and Freeplay settings | C2/B1, B3/U1 |
| 4: anchor, placement, streak, loss and pool exhaustion | B1/B3, U2-U4 |
| 5: fixed-category shared Daily, attempts, rollover and ties | C1/B4, U1/U4 |
| 6: persistence, auth/API boundaries and atomic idempotency | B2-B5, U2 |
| 7: tactile framing/drag/confirm, touch/keyboard and motion | C4/U3/U4 |
| 8: failures, feedback, deployment, secrets and recovery | B3/B5, U2, L1/L2 |
| 9: automated/manual gates and one-week learning trial | C6/B5/U4, L2/L3 |
| 10: sequencing and decision ownership | Master dependency map, C1/L1/L2 approvals |

Self-review checked all ten sections, producer/consumer type names, task
dependencies, the five Review Focus tests, explicit commit boundaries, and
proportion. Shared schemas have one owner; fixtures cannot satisfy launch.
Source providers and initial Daily categories are selected; hosting/domain/budget
and real automated content/media validation are evidence-based execution checkpoints,
not unresolved placeholders an implementer may silently decide.
