# Historical Date Game Beta Continuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the reviewed real catalog locally, measure and improve remaining content/media gaps automatically, and complete the restricted, recoverable friends-beta release gates.

**Architecture:** Continue the existing FastAPI/React/PostgreSQL application and immutable offline catalog pipeline; do not build a new subsystem. Prove real-catalog behavior in a separate local test database and browser suite, preserving the existing fixture environment. Reuse the approved launch plan for production operations, recovery and the friends trial.

**Tech Stack:** Existing Python 3.15/uv, PostgreSQL, SQLModel, React/TypeScript, Node 26.11.1, Playwright, Docker Compose and current content/media tooling; no new dependency is presumed necessary.

**Spec:** `docs/superpowers/specs/2026-10-11-historical-date-game-beta-design.md` (approved, including the automated-only and year-level chronology amendments). Shared contracts remain in `docs/superpowers/plans/2026-10-11-historical-date-game-beta.md`.

**Status:** Owner reviewed and approved this written continuation with “yes” on 2026-10-12; subagent-driven execution is preserved. Local isolated integration and the plan's bounded research/preparation may proceed. Hosting spending, public exposure, production activation, merging, pushing and invitations retain their separate approval gates.

## Global Constraints

- **At least 1,000 game-ready events in the initial catalog.** Count accepted, sourced, deduplicated events, not raw rows, category memberships, or fixtures.
- No manual content/image review or human publication queue. Accepted/approved means versioned automated validation passed; quarantine unresolved dates/duplicates and use fallbacks for unsupported or unsafe media. Do not claim human verification or legal clearance.
- No displayed civil year zero: CE `n -> n`, BCE `n -> 1 - n`. Keep catalog/media releases immutable for existing runs.
- Minimum year gap is an integer of at least 1 and applies between **every pair of events in the run**; year bounds are inclusive.
- Category selections mean the **union**. No duplicate event or year within a run.
- One scored daily attempt per account per UTC day; fixed Daily categories and **one shared random seed per UTC date**.
- A dropped card previews its position; **Lock it in** submits the guess. No arbitrary round cap. Win only when the frozen run-specific pool has no eligible unused event.
- Taxonomy slugs stay `births`, `deaths`, `battles`, `inventions`, `literature`, `arts`, `exploration`, `politics`; Daily stays `battles`, `inventions`, `exploration`, `politics`.
- Prefer a relevant picture for every event. Research feasibility/rights; representative fallback artwork must cover every event when a usable picture is unavailable.
- Preserve mandatory attribution, hide unanswered years/seeds, provide touch/keyboard alternatives, and respect reduced motion. Catalog text licensing is separate from MIT application code and image licensing.
- Existing exact-source date/calendar checks and whole-raw duplicate/conflict checks remain in force. Do not reinterpret the positive-CE-only chronology as a BCE source or broaden its pinned-file acceptance without a reviewed, evidence-backed change.
- No live acquisition in scoring transactions; honor provider-wide throttle state and `Retry-After`. No IP/host rotation, unlimited retries or acceptance weakening to meet a target.
- Existing test fixtures can clean their entire test database. Never run them concurrently with browser/device sessions, or against production or an unapproved shared database.
- Physical-device, spoken screen-reader and owner gameplay checks remain requirements; emulation is not hardware evidence. They are not content/image curation.
- Hosting/provider/budget/domain/backup destination and production activation require their existing approvals. Invitations require release go/no-go. No paid provisioning, external publication, push or merge is authorized by this plan.

## Review Focus

1. A second test environment must not silently connect to or clean the existing fixture database; F1 guards exact DB identity and loopback connection before opening a session.
2. An existing UTC Daily or active run must keep its frozen catalog after activation changes; F1 tests catalog switching and rollover without resetting attempts.
3. Real catalog text credits, download sources and images must not reveal pending answers or expose private files; F1/F2 test DTOs, HTTP paths and emitted production bundles.
4. Fixture-oriented browser tests must not masquerade as real-catalog tests; F2 isolates discovery/configuration and places private test answers only in the Node test runner.
5. Source throttling, uncertain matches and deployment recovery must fail safely rather than fabricate content or lose progress; F3 exercises existing mocked throttle/matching gates, F6 performs the real restore drill.

---

## 1. Baseline and ownership

Planning baseline: `2d1781335bb681cba5967f085a82e951403ccdb2` on `feature/friends-beta`, worktree `.worktrees/beta`.

Reviewed local release: `data/game/releases/jsonl-trial-2026-10-12-review-r1/`.
Manifest SHA-256: `804ec52ccfc3e19cd955913b05cbfd59158f562408e45c1916fa8626d3ac50d3`.
Do not substitute the older `-final` release: its acceptance fingerprint is stale.
Current code verification remains mandatory; if fingerprints change, refinalize a new immutable release, never reseal an old one to bypass stale checks.

Measured baseline:

| Property | Evidence-backed value |
| --- | --- |
| Accepted real events | 1,276: 1,271 chronology + five existing C6 births |
| Category counts | births 5; deaths 171; battles 544; inventions 23; literature 65; arts 32; exploration 145; politics 291 |
| Years | 569 distinct; 9–2025 CE; no BCE |
| Daily pool | 1,003 events / 492 distinct years; a proper restricted subset |
| Regions | 1,271 chronology records unclassified; do not infer measured world coverage |
| Media | 0 photographs; 1,276 representative fallback assignments, eight original SVG assets |
| Verification at baseline | 589 pure tests, Ruff and mypy passed; actual `verify --require-beta` exit 0 |
| Not yet verified | Real-catalog DB/browser integration, genuine touch/speech/owner play, production deployment/restore |

Completed work is not to be repeated: F0, C1–C5 implementation, B1–B5, U1–U3, U4's automated fixture portion, provider-throttle fix and JSONL adapter/review. C6 still has broad-coverage/media concerns; full U4 and L1–L3 remain open. See the existing master execution ledger and `docs/beta/{catalog-readiness,interaction-review}.md` for historical evidence.

### File/responsibility map

| Files | Responsibility |
| --- | --- |
| New `backend/tests/browser/real_catalog_probe.py` | Explicit opt-in real-catalog activation/proof command, local guard and private probe report; never an application API |
| New `backend/tests/safety/test_real_catalog_probe.py` | Pure safety/orchestration regressions without a database |
| New `frontend/tests-real-catalog/{auth.setup,game-catalog.spec}.ts`, `frontend/playwright.real-catalog.config.ts` | Separate real-catalog browser discovery/auth and journeys |
| New `frontend/tests/real-catalog-config.test.ts` | Configuration separation regression; discovered by existing unit command |
| New `docs/beta/local-catalog-integration.md` | Measured environment, release, tests, HTTP/privacy and restart evidence |
| New `docs/research/catalog-expansion.md`; update `docs/research/image-sources.md` | Reproducible automatic coverage/media feasibility findings and selected next work |
| `backend/app/content/adapters/{onthisday,selected,router}.py`, `corpus.py`, media pipeline, source-selection files and their existing tests | Only targeted, separately specified expansion changes after F3 evidence; no rebuild of completed pipeline |
| `docs/beta/{catalog-readiness,interaction-review}.md` | Append dated evidence without erasing earlier failures or limitations |
| Original L1/L2/L3 file lists | Production overlays/runbook/backup, release checks/restore, trial feedback; owned by the launch plan, not duplicated here |

## 2. Dependencies and checkpoints

`F1 -> F2 -> local integration checkpoint`.

`F3 -> evidence-backed expansion brief/plan -> approved targeted implementation -> new immutable release -> repeat F1/F2 against that release`.

F3 research and F4 hardware scheduling may proceed after local integration; no parallel database-cleanup/browser sessions. F5 hosting comparison may run independently, but provisioning waits on explicit approval. `F6` requires F1/F2, the content/media disposition from F3, completed F4 and F5. `F7` requires F6 and owner go/no-go.

This is a continuation, not permission to dispatch agents or execute anything before written-plan confirmation. Maintain a continuation execution ledger with inherited task/commit pointers, not copied full implementation reports. Each implementation task uses TDD, a scoped commit and the chosen review gate. Research/hardware/ops tasks use actual evidence, not manufactured RED tests for external facts.

## Task F1: isolated real-catalog activation and backend proof

**Files:** Create `backend/tests/browser/real_catalog_probe.py`, `backend/tests/safety/test_real_catalog_probe.py`, `docs/beta/local-catalog-integration.md`. Reuse, do not replace, `tests/db_guard.py`, `app/content/cli.py`, `app/game/{catalog_repository,run_service,daily_service}.py` and existing API/database tests.

**Interfaces:** Define `require_local_probe_target(database: str, host: str, environment: str) -> None`; accept only DB `historical_date_game_catalog_test`, host `localhost` or `127.0.0.1`, environment `local`, additionally invoking the existing `_test` guard. Define `run_probe(release_dir: Path, media_dir: Path, report_path: Path) -> dict[str, object]` and `main(argv: list[str] | None = None) -> int`. CLI: `uv run python -m tests.browser.real_catalog_probe --release <absolute-release-dir> --media <absolute-media-dir> --report <private-report.json>`. No unsafe/fixture bypass flag. The command guards before constructing its own DB session, runs `verify_release(..., require_beta=True)`, activates via `activate_catalog(..., require_beta=True)`, uses existing services with owned probe users, and writes a sanitized private report; no schema/API change.

- [ ] **Write failing pure tests** `test_probe_rejects_nonisolated_target_before_db`, `test_probe_rejects_invalid_release_before_activation`, `test_probe_failure_returns_nonzero`, `test_probe_report_has_no_credentials_or_future_answers`. Parametrize rejected targets: existing `historical_date_game_test`, `production`, a remote host and `environment='production'`. Assert no DB/session/service call for rejected targets; failed verification means zero activation calls; command failures cannot write `passed=true`. Assert the accepted tuple returns normally. Use injected/mocked boundaries, not a pretend 1,000-event fixture as real evidence.
- [ ] **Observe RED:** from `backend/`, run `uv run pytest tests/safety/test_real_catalog_probe.py -q`; expect missing probe module/functions, not an accidental database connection.
- [ ] **Implement the opt-in probe** and re-run those pure tests GREEN. Probe assertions must include: actual nonfixture manifest/count/categories/options; idempotent reactivation with identical manifest bytes; pending allowlist and answer-safe text credits; revealed source/credit preservation; inclusive bounds/category union and all-pairs gap; zero-streak anchor; correct move then same-operation retry with one revision increment; wrong placement without streak gain; invalid/sparse configuration creates no run; terminal immutability and ownership denial; reads in a new DB session preserve progress.
- [ ] **Add real-data Daily/switch assertions to the probe:** create two owned accounts and a trusted service-level day not already used in this isolated DB; both share anchor and correct prefix, with one attempt per owner. Record the frozen definition, switch selection temporarily to a separately built valid small fixture, and prove that existing Daily/Freeplay read/placement remains on the real release while new Freeplay sees the changed selection. Restore real selection, test next-day definition, and never delete/reset a definition to force today's catalog. Private service `now` injection is test-only; do not add a clock/answer endpoint. Use private catalog years only within this server-side probe to select legal correct/wrong slots.
- [ ] **Prepare the isolated DB/environment after execution approval:** inspect the execution-owned PostgreSQL connection and existing services rather than trust old PIDs. Create/migrate `historical_date_game_catalog_test` on the execution-owned PostgreSQL host port `5433`; do not modify the existing browser database. Set `POSTGRES_DB=historical_date_game_catalog_test POSTGRES_SERVER=127.0.0.1 POSTGRES_PORT=5433 ENVIRONMENT=local`. Use `GAME_DATA_DIR=../data/game/local-catalog-runtime`, copying only hash-verified asset files into its `media/` directory with create-only semantics. Keep source releases/raw/rights files outside public media storage. Preserve prior referenced assets.
- [ ] **Run ordinary backend integration before seeding the real browser state:** `POSTGRES_DB=historical_date_game_catalog_test POSTGRES_SERVER=127.0.0.1 POSTGRES_PORT=5433 uv run pytest`. No browser/device session may use that DB concurrently. Its cleanup is expected; after it finishes, run the real probe against the reviewed release. Report actual counts rather than reuse the previous 589 pure result. If verification is stale, stop and issue a new validated release first.
- [ ] **Record real activation evidence** in `docs/beta/local-catalog-integration.md`: command exit codes, actual manifest SHA/count, runtime asset hashes, exact isolated DB/project identity without credentials, frozen-state results, warnings, and release-switch restoration. Preserve original fixture DB/backend and source release bytes. Re-run pure safety tests, covering changed code tests, Ruff/mypy; commit named task files: `test: prove real catalog activation in isolated postgres`.

**Exit:** A current verified real release is active only in the separate local environment; real service/persistence invariants pass. This is not a production activation or launch claim.

## Task F2: real-catalog browser journeys and private local play

**Files:** Create `frontend/playwright.real-catalog.config.ts`, `frontend/tests-real-catalog/auth.setup.ts`, `frontend/tests-real-catalog/game-catalog.spec.ts`, `frontend/tests/real-catalog-config.test.ts`; update `docs/beta/local-catalog-integration.md`. Add narrow game UI/API fixes only with reproduced regressions; do not alter the fixture journey answer table.

**Interfaces:** Consume F1's real selection, private release path and runtime media. Browser suite uses backend `http://localhost:8010`, UI `http://localhost:5174`, auth state `playwright/.auth/real-catalog.json`, and separate `testDir='./tests-real-catalog'`; projects `setup`, `chromium`, `game-mobile`. Backend binds loopback, with `FRONTEND_HOST=http://localhost:5174`, restricted local enrollment and no answer endpoint. Test runner reads `REAL_CATALOG_RELEASE_DIR` (no `VITE_` prefix) and validates the nonfixture manifest/count before loading its private answer map; never import that map into `frontend/src` or a page/browser evaluation.

- [ ] **Write the configuration regression:** `test_real_catalog_suite_does_not_discover_fixture_journeys` asserts separate test directory, backend/frontend URLs, auth filename, setup dependency and project selection. Missing `REAL_CATALOG_RELEASE_DIR` must fail real-suite setup, not silently use the fixture. Run `npm run test:unit`, observe the missing configuration failure.
- [ ] **Implement separate configuration/auth** following existing Playwright project patterns. New setup authenticates using environment-supplied local admin credentials, then creates dedicated player accounts via admin APIs with public registration disabled. Never commit auth files or credentials. Configure `npm run dev -- --host 127.0.0.1 --port 5174 --strictPort` with `VITE_API_URL=http://localhost:8010`; do not reuse an unrelated process just because its port responds. Leave standard `playwright.config.ts` discovery unchanged.
- [ ] **Write real journey assertions:** options show the actual real release/all eight slugs/9–2025 CE at this baseline; broad Freeplay can make a correct placement, preview without a POST, reload/resume, lose intentionally and start anew. Configure a real small range/gap by selecting two compatible years from the private test-runner map so pool exhaustion can be tested cheaply without falsifying events or limiting the production engine. Assert the UI's reported victory/settings match authoritative exhaustion. For two fresh Daily players assert shared anchor and several correct-prefix cards, one attempt and frozen Daily categories; backend F1 owns full service outcome/rollover checks. Browser reads only public DTOs; Node computes slots using private answers without placing years, source snapshots or sequence into browser globals.
- [ ] **Check real text/media boundaries:** pending keys are exactly `event_id`, `prompt`, `category_ids`, `media`; no answer/source fields or answer-bearing historical URLs; required text/image credits still render. On reveal show the year/explanation/source links. Verify `/media/<digest>.svg` is served while direct `manifest.json`, `events.jsonl`, `raw.jsonl`, snapshot/receipt paths and directory listing are inaccessible. Simulate failed imagery and uncertain placement response: fallback and same-operation recovery preserve authoritative progress, not a loss. Verify desktop and touch-emulated controls, labeling emulation honestly.
- [ ] **Run the real suite:** with a healthy owned backend on `8010`, from `frontend/`, `REAL_CATALOG_RELEASE_DIR=<absolute-current-release> VITE_API_URL=http://localhost:8010 npx playwright test --config=playwright.real-catalog.config.ts --project=chromium --project=game-mobile --workers=1 --reporter=line`. Record actual cases, failures and traces. Run standard fixture browser tests separately against their original backend; do not point `game-journeys.spec.ts` at the real catalog. Re-run units, typecheck, lint, build and scan emitted bundles for actual test-only answers/maps/private artifact paths (not generic number patterns).
- [ ] **Restart only the owned real backend** while an active real Daily and Freeplay exist; rehydrate through HTTP and verify identical run revision, timeline, pending card and Daily identity, then make another scored move. Record local health/launch/stop instructions and sanitized results. Leave the separate real environment usable for owner testing, or record precisely why it was stopped. Commit named files: `test: exercise real catalog browser journeys`.

**Exit:** The real catalog plays through the actual UI/API and restart without privacy/credit/progress regressions; fixture regressions stay separate and green. No hardware or unassisted-player claim yet.

## Task F3: automatic coverage and picture feasibility, then scoped expansion

**Files:** Create `docs/research/catalog-expansion.md`; append to `docs/research/image-sources.md` and `docs/beta/catalog-readiness.md`. Retain private probe scripts/raw responses under ignored `data/game/acquisition/followup-probe/`. Any later production changes have their own evidence-backed brief, exact file/signature/test list and review before implementation.

**Interfaces:** A probe report contains source URL/version/hash/license, raw/accepted/quarantined identity counts and reasons, category/era/known-region/distinct-year distributions, match confidence basis, picture/fallback yields and provider retry evidence. It identifies whether each candidate fits the unchanged `SelectedSourceAdapter`, existing chronology rules, or needs a new reviewed adapter/policy. No precomputed accepted flag is an input to publication.

- [ ] **Reconcile baseline first:** independently read the reviewed release and raw dispositions. Record all eight category counts, BCE/era/year distribution, unclassified regions, Daily playable capacity, picture/fallback counts, and existing first-100/all-event automatic audit. A positive-CE-only input cannot acquire BCE through classification changes. Region inference or new minimum quotas are not silently substituted for the original specification.
- [ ] **Evaluate three bounded automatic routes in this order:** reuse genuine approved C1/C6 cached birth/art/invention/BCE leads through unchanged selected-source checks; inspect rejected chronology rows for additional explicit milestone grammars using source-backed positive and negative examples; inspect official Wikipedia selected-page exports/downloadable chronologies for missing births/BCE and stable linked subjects. Reuse existing cached bytes before requesting new data. Selected-page exports are candidates to evaluate, not already supported input; no full 35 GiB snapshot or replacement provider is assumed. External source choices beyond the approved Wikimedia family require a documented choice and owner approval before production integration.
- [ ] **Measure picture matching separately:** select 100 distinct accepted identities by deterministic category round-robin over sorted event IDs (thin categories contribute only their genuine available records). Use only source-proven exact article/subject associations; prose search/fuzzy title matches cannot automatically become image provenance. Test cached Commons evidence first; make bounded permitted metadata/image attempts only when provider state allows. Preserve hashes, license/credit/relevance/safety decisions, failure bodies and retry headers. Use existing C4 downloader/rights/safety checks; missing, unsafe, ambiguous or throttled candidates remain explicit fallbacks. Zero usable pictures is an honest result, not success disguised as 100 matches.
- [ ] **Run existing safety regressions** `uv run pytest tests/content/test_onthisday.py tests/content/test_importer.py tests/content/test_media.py tests/content/test_publish.py -q`; confirm uncertainty, whole-raw conflicts, answer leakage, source mismatch, credits and provider-wide throttling remain covered. Documentary source research does not require a contrived unit-test RED. Report measured probes, costs/storage/runtime and unavailable evidence; do not promise a yield or access window.
- [ ] **Produce the selected expansion brief/plan:** prescribe exact acquired source format, stable identity/year/calendar conventions (including `1 BCE -> 0` without civil zero), automatic category/region evidence, subject-image association, license attribution, immutable snapshot retention and independent C4/C5 verification. Include synthetic positive/negative regression cases plus genuinely retained source-backed examples, dedup across the existing catalog, cache/fingerprint changes and a bounded acquisition command. Do not implement a speculative adapter before these choices exist. Seek review of material new source/contract decisions, then execute only the approved targeted extension; do not replay C1–C5 completed work wholesale.
- [ ] **Publish any improved result as a new immutable release:** reimport the combined genuine sources, re-run full-corpus constraints, assign media, refreeze **all** final receipts, `publish`, then `verify --require-beta`. Measure count/category/era/region/year/image changes versus baseline and audit at least 100 accepted identities automatically. Preserve IDs for unchanged milestones and all assets/release bytes referenced by old runs. Repeat F1/F2 before promoting this release beyond isolated testing. Commit only scoped code/tests/small policy/docs after review, not raw data/assets.
- [ ] **Close the content/media disposition:** document actual improvements and residual limitations. If acquisition or deterministic matching is blocked, mark that work blocked with retry/research actions; continue independent local/device/hosting research, but do not silently waive broad-history or picture-feasibility requirements. Owner release go/no-go may assess disclosed limitations; a scope waiver is an explicit spec amendment, not a fabricated coverage report.

**Exit:** Evidence establishes the supported automatic expansion route and actual picture feasibility; any promoted release is independently verified and locally tested. No guaranteed BCE, regional labels, category balance or photograph percentage is asserted in advance.

## Task F4: finish genuine device, accessibility and owner-play checks

**Files:** Update `docs/beta/interaction-review.md` with dated real evidence; targeted UI fixes and named regression tests only if an actual issue is reproduced. Reuse completed U4's automated tests and private 100-card public-DTO harness.

**Interfaces:** Evidence names actual device/OS/browser/orientation, input method, screen reader and spoken observations, release ID, scenario/outcome and unresolved blockers. No credentials or unnecessary personal data. Hardware results are supplied by an actual operator, not generated by the agent.

- [ ] **Arrange owner access privately** to the separate real environment after F2. Do not publicly expose local test/private routes to reach a phone; agree a safe physical-device access arrangement before changing binding/firewall/tunneling. If hardware/speech/operator access is unavailable, retain this gate as blocked, not emulated PASS.
- [ ] **Check physical touch and 100-card navigation:** use a clearly labeled test-only public DTO layout harness for all 101 slots if a genuine long run is unavailable. Check first/middle/last, drag/hold/edge scroll/outside-drop/cancel/tap, return to Lock controls, large text/zoom, orientations, reduced motion and failed images. Layout fixtures cannot prove historical scoring or real-catalog capacity.
- [ ] **Listen to real assistive speech** for focus, preview, slot navigation, correct/mistake/victory results and recovery; also complete keyboard-only control checks. Record exact obstruction/announcement problems and screenshots without answer assistance. Fix scoring, accessibility or progress-loss blockers using reproduced RED/GREEN regressions and repeat the affected real check.
- [ ] **Have the owner play representative real Daily and Freeplay unassisted**, including selection, preview/Lock, mistake, a small achievable victory and resume. Record actual observations without inventing feedback; completed Daily cannot restart as a new attempt, Freeplay can. Do not ask the owner to curate event facts or image rights.
- [ ] **Append dated outcomes and commit evidence:** `docs: record genuine beta device and owner checks`. Complete full U4 only after its real checks pass.

## Task F5: approved restricted hosting and operations (original L1)

**Files/Interfaces:** Reuse **Task L1 verbatim** from `docs/superpowers/plans/2026-10-11-historical-date-game-beta-launch.md`, including its precise production overlay/test/script/runbook file list and backup/restore command contracts. Do not create competing scripts/configurations here.

- [ ] **Compare at least two current hosting options** including persistent storage, off-host encrypted backups, traffic/domain and monthly cost; size using actual release/media/database measurements. Record findings in `docs/research/beta-hosting.md`. Get owner approval of provider, budget, domain, backup destination and feedback contact before provisioning or paid work.
- [ ] **Execute original L1's RED/GREEN deployment tests and overlays/runbook work**: remove exposed DB/Adminer/proxy management/Mailcatcher/test routes; production registration disabled; HTTPS, nondefault secrets/origins and retained read-only assets. Its tests inspect rendered Compose, not only source YAML.
- [ ] **Implement original L1 backup/restore protection**: explicit projects, checksums/version inventory, encryption/transfer verification, failure alert, at least seven daily restore points and every run-referenced catalog/media/rights artifact. Never restore over production or prune an in-use release.
- [ ] **Record approvals, rendered checks and scoped L1 commit** using its exact verification commands. Hosting planning/preparation is not launch permission.

## Task F6: complete release gate and restart/restore drill (original L2)

**Files/Interfaces:** Reuse **Task L2 verbatim** from the launch plan: `scripts/verify-beta.sh <release-dir> <media-dir>`, `backend/tests/game/test_release_check.py`, release checklist, restore drill, CI/runbook updates. Substitute the current verified real continuation release for historical references to C6's old partial workspace. No fixture or stale release can satisfy the real gate.

- [ ] **Implement original L2's failing release-check tests** for fixture, 999 accepted events, tampered artifacts and propagation of failed verification commands; then orchestration GREEN. Also pin that incomplete actual device/restore/go-no-go evidence cannot be reported as fully release-approved merely because automated commands passed.
- [ ] **Run the full automated release matrix in separate test phases:** backend integration/concurrency, standard fixture browser suite, current real-catalog F1/F2 suite, unit/lint/type/build/client regeneration twice, pre-commit and rendered/container checks. DB cleanup finishes before browser state is seeded. Check auth/account/admin behavior remains preserved; no scoring/fairness/answer-exposure/progress-loss blocker may remain.
- [ ] **With owner-approved hosting/deployment authorization**, deploy production-safe tagged images and activate the current qualifying immutable release using `activate --require-beta`; verify HTTPS, restricted real accounts, private-file isolation, credits/assets and sanitized health/errors. Do not open public registration to simplify testing.
- [ ] **Run original L2's actual recovery exercise:** score Daily/Freeplay, back up, restart/redeploy, compare exact revision/timeline/pending/frozen Daily/media credits; restore to a separate isolated project, compare again, and finish restored gameplay. Record time/digests, retained release inventory and operational rollback compatibility. Do not count an untested backup script as a successful restore.
- [ ] **Complete the checklist and obtain owner go/no-go** using actual content/media distributions, all required device/owner evidence, production security and restore results. Fix known blockers first. Commit sanitized release/recovery evidence as prescribed by L2; no automatic push/merge/invitations.

## Task F7: one-week friends-only trial (original L3)

**Files/Interfaces:** Reuse **Task L3 verbatim** from the launch plan: `docs/beta/{friends-trial,feedback-triage}.md`, anonymized reports with event/run identifiers and dispositions.

- [ ] Invite only owner-approved friends after F6 passes; explain UTC Daily/one attempt, Freeplay, preview/Lock, resume and feedback.
- [ ] Run one week and seek feedback from at least three actual players. Report real recognition/ambiguity/controls/picture usefulness and voluntary return/replay observations, not invented retention statistics.
- [ ] Reproduce and regression-test scoring/fairness/security/progress-loss reports. Content corrections use new immutable releases; never change old Daily answers or reset attempts. Prioritize before widening access.
- [ ] Review the trial with the owner; remain friends-only, iterate or separately plan a broader launch. Commit sanitized findings; no wider launch presumed.

## 3. Verification commands and execution handoff

From `backend/` unless otherwise noted:

```sh
uv run python -m app.content.cli verify --release ../data/game/releases/jsonl-trial-2026-10-12-review-r1 --media ../data/game/releases/jsonl-trial-2026-10-12-review-r1/media --require-beta
uv run pytest tests/content tests/game tests/safety -q
uv run ruff check app tests
uv run mypy app
```

Integration uses explicit isolated DB settings from F1. New browser/probe commands are deliverables, not commands currently available. Node 26 must be on PATH for frontend checks; existing runtime is `/tmp/opencode/node-v26.11.1-linux-x64/bin`. At execution verify actual tool/process versions and availability instead of assuming this machine state persists.

From `frontend/`: `npm run test:unit`, `npm run typecheck`, `npm run lint`, `npm run build`; F2 specifies the separate real browser command. Original L1/L2 define Compose/render/restore and full release commands. Never run `scripts/deploy.sh` or build/push scripts merely as a local verification shortcut.

Review this continuation before implementation. The previously selected **subagent-driven** method is preserved: scoped implementer and task reviewer gates, followed by the final whole-branch review at beta completion. Planning does not authorize spending, exposing services, deploying or inviting anyone.

## 4. Planning self-review and traceability

| Spec section / remaining obligation | Owning task |
| --- | --- |
| 1–2: audience, genuine 1,000, broad coverage, pictures/rights, automated-only publication | F3, F6; current accepted count is baseline evidence, not a waiver |
| 3–4: bounds/category union/gaps/anchor/scoring/outcomes/resume | F1/F2, existing engine regressions in F6 |
| 5: shared UTC Daily, one attempt, immutable day/prefix/rollover/ranks | F1/F2 plus existing Daily/concurrency matrix in F6 |
| 6: persistence/API ownership/idempotency/answer boundary/text attribution | F1/F2/F6 |
| 7: tactile preview/Lock, long layouts, touch/keyboard/reduced motion | F2/F4 |
| 8: provider failures/media fallback, enrollment/secrets/HTTPS/health/retention/restore | F3/F5/F6 |
| 9: automated matrix, genuine hardware/owner checks, release gates | F1/F2/F4/F6 |
| 9–10: one-week learning and approval ownership | F5/F6/F7 |

Self-review: reused original contracts/launch tasks without duplicating their implementations; separated fixture and real browser discovery/answer handling; guarded database identity before session creation; retained truthful coverage and hardware blockers. The five Review Focus conditions each have an owning test/proof step. Unknown expansion source formats are explicit evidence/approval checkpoints, not undefined adapter interfaces an implementer may guess. No new numeric category/region/picture quotas or forced launch date were introduced.
