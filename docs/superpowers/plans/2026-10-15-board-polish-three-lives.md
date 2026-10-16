# Board Polish and Three Lives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a warm, space-efficient card board and authoritative three-life Daily/Freeplay, replacing old gameplay state at a controlled local switchover.

**Architecture:** Extend the existing pure rules engine and transactional command path, not the drag library or identity system. Keep canonical timelines sorted after non-final mistakes; reconstruct attempted-position review from revision-bound feedback. Use one rules model after an explicitly scoped gameplay reset, with a protocol/storage boundary to reject old commands.

**Tech Stack:** Python/FastAPI, SQLModel/SQLAlchemy, PostgreSQL/Alembic, React/TypeScript, existing dnd-kit 0.5.0, Node 26.11.1+, pytest and Playwright. No dependency upgrade.

**Spec:** `docs/superpowers/specs/2026-10-15-board-polish-three-lives-design.md` (approved 2026-10-15).

## Global Constraints

- All games start with three lives. No Classic mode or legacy-game preservation branch.
- The anchor is still unscored. Corrected cards never earn points later.
- Zero lives takes precedence over pool exhaustion: the final-life mistake loses.
- Score is total correct confirmations, not timeline length and not the final streak.
- Dropping, navigation, focusing or releasing a key never submits.
- No nested scroll area in the card prompt, fallback/image description, year or action footer, including focused/dragging states.
- Keep a minimum 44px touch target, accessible name and visible focus for confirmation.
- At 1920×900 and 1366×768 CSS pixels, 100% zoom: complete desktop loop without page or native timeline scrolling.
- Dialogs may scroll for genuinely long content; the cards themselves may not.
- Preserve ownership, exact UUID/body replay, Daily uniqueness, inclusive BCE/CE and deterministic minimum-gap eligibility.
- Reset gameplay only; retain catalog/media, accounts/passwords, guest credentials, secrets, unrelated data and lifecycle evidence.
- No live source edit, service stop, reset or migration during development. No automatic push/PR/merge or production deployment.
- Preserve the pre-existing tracked `.env` modification; never print, stage, overwrite or revert it.

## Review Focus

1. A double click, lost response or delayed older-tab response must consume at most one life and cannot roll the UI back (Tasks 3–4).
2. A miss on the last eligible event must still show review; Continue shows a win with remaining lives, but the third miss loses (Tasks 1, 4).
3. Font wrapping, image failure and resizing after a preview must not hide confirmation, introduce tile scrolling or change the chosen slot (Task 5).
4. Storage denial, malformed acknowledgements and account switching cannot unblock a wrong identity's review or resurrect a pre-reset command (Tasks 3–4).
5. Wrong database/process evidence, or a failure between reset and migration, must stop delivery without broad cleanup or restarting an incompatible old server (Tasks 2, 7).

## Workspace, file map and verification conventions

Execute in the already isolated, stopped `/home/klottick/repos/historical-date-game/.worktrees/guest-play`, branch `feature/board-polish-three-lives`, based on merged `master` `da37026`. The live `.worktrees/board-redesign` is not the implementation workspace. Before execution, confirm branch/status, inspect applicable instructions, and verify no consumer is using the implementation checkout. Do not create another worktree or copy credentials unnecessarily.

Responsibilities and new boundaries:

| Area | Files | Responsibility |
| --- | --- | --- |
| Engine | `backend/app/game/{types,rules}.py` | Life/correct-count invariants and deterministic transitions. |
| Persistence | `backend/app/game/models.py`; new `backend/app/alembic/versions/20261015_01_add_three_life_counters.py` | Empty-gameplay schema transition and matching constraints. |
| HTTP/service | `backend/app/game/{schemas,run_service,projections,daily_service}.py`; `backend/app/api/routes/games.py`; new `backend/app/game/protocol.py` | Protocol 2, allowlisted life/score fields, atomic outcomes and ranking. |
| Browser protocol | new `frontend/src/features/game/gameProtocol.ts`; existing `api.ts`, `identityState.ts`, `placementState.ts`, `FreeplayForm.tsx`, `DailyPanel.tsx` | Protocol-aware commands and isolated new recovery keys without changing credentials. |
| Review | new `frontend/src/features/game/mistakeReview.ts`; existing `useOwnedRun.ts`, `lossTimeline.ts`, `GameBoard.tsx`, `GameResults.tsx` | Revision-bound local acknowledgement and attempted-position display. |
| Layout | existing `game.css`, `GameCard.tsx`, `EventDetailsDialog.tsx`, `PendingTile.tsx`, `TimelineStage.tsx`, `useTimelineInteraction.ts`, `boardGeometry.ts`, `timelineNavigator.ts` | Warm responsive board, measured geometry, local confirmation and overflow-aware full text. |
| Verification | existing `backend/tests/browser/guest_test_environment.py`; focused backend/frontend tests listed below | New isolated verification profile; keep existing guest/board proof outputs unchanged. |
| Delivery | new `backend/tests/browser/three_lives_local_rollout.py`; new `backend/tests/browser/test_three_lives_local_rollout.py`; new `docs/beta/board-polish-three-lives.md` | Default read-only inspection, exact-target reset and guarded new generation. |

Commands below run from `backend/` or `frontend/` as labeled. Use the existing private dependency environment; check installed versions without dumping environment variables. Backend commands have explicit `HDG_VERIFICATION_PROFILE=lives POSTGRES_DB=historical_date_game_lives_test POSTGRES_SERVER=127.0.0.1 POSTGRES_PORT=5433 ENVIRONMENT=local`. This must be an absent database created with the helper's ownership comment, or an already proven disposable database with no consumer. Refuse any unowned/nonempty pre-existing target instead of resetting it. Never use the live `historical_date_game_catalog_test` or original `historical_date_game_test` for pytest.

Frontend verification commands also set `HDG_VERIFICATION_PROFILE=lives BOARD_TEST_EVIDENCE_DIR=../.superpowers/board-polish-three-lives/verification`. Task 1 updates the finite frontend runtime mapping and controlled-config output paths before any browser test runs. Never run the real-catalog config with its default localhost:8010/5174 origins: those are the retained live generation. Run `scripts/generate-client.sh` from the repository root in the private Python/Node environment; its outputs include `frontend/openapi.json` as well as `frontend/src/client/`.

Preserve test logs under ignored `.superpowers/board-polish-three-lives/verification/` (directory 0700; private logs 0600). Record real RED/GREEN outputs and commits in the existing `design-progress.md`; do not claim earlier PR results prove this branch. Every task has its own focused test gate and named-file commit; the whole-suite gate is Task 6.

---

### Task 1: Three-life engine and safe test isolation

**Files:** Modify `backend/app/game/types.py`, `backend/app/game/rules.py`, `backend/tests/game/{conftest,test_rules,test_invariants}.py`, `backend/tests/browser/guest_test_environment.py`, `frontend/tests/utils/boardEvidence.ts`, `frontend/tests/board-evidence.test.ts`, and `frontend/playwright.{board,identity,bootstrap}.config.ts`. Test new `backend/tests/game/test_three_lives.py` and new `backend/tests/browser/test_three_lives_profile.py`.

**Interfaces:** Keep `start_run(events, rules, order) -> RunState` and `place(state, events, event_id, slot) -> PlacementOutcome`. Add `INITIAL_LIVES = 3`, `RunState.mistakes: int`, `RunState.correct_count: int`, and read-only `RunState.lives_remaining: int` in `types.py`. Leave `generation_version=1`. Add verification profile `lives` to the existing helper, with databases `historical_date_game_lives_test`, `historical_date_game_lives_fixture_test`, and `historical_date_game_lives_migration_test`; its evidence path is the new private verification directory. Existing profiles retain their paths/guards.

- [ ] **Step 1: Write isolation tests before preparing a database.** In `test_three_lives_profile.py`, use a subprocess/mock boundary, never a live connection, to assert the new profile selects only the three exact names above, creates only an absent owned target, rejects an unowned target, and leaves `guest`/`board` mappings unchanged. Extend `board-evidence.test.ts` to assert the frontend `lives` mapping agrees with Python, and controlled outputs use the new private directory. Run with `uv run python -m unittest tests.browser.test_three_lives_profile -v` and frontend `node --test tests/board-evidence.test.ts`; expect FAIL for the unknown profile.
- [ ] **Step 2: Implement the minimal profile mapping/allowlist.** Extend `verification_profile()`, `evidence_directory()`, ownership and prepare checks without widening them to arbitrary `*_test` names. Update frontend `verificationDatabase`/`verificationRuntime` for the finite `lives` profile and use `boardEvidence` for all controlled-config output directories. Keep IndexedDB bootstrap coordination/identity unchanged. Run Step 1 again; expect PASS. Then, and only then, prepare the dedicated engine/API test DB with `uv run python -m tests.browser.guest_test_environment prepare-db --database historical_date_game_lives_test` under the explicit environment above. Verify the ownership comment and no consumers first; preserve the DB after tests, not a broad drop command.
- [ ] **Step 3: Write engine RED tests.** Add a deterministic fixture with at least seven eligible distinct years, a BCE/CE case, and a final-event exhaustion case. Parameterize `test_three_life_sequences` with the following assertions (the fixture submits correct or deliberately wrong slots, not a mock of `place`):

```python
# C = correct; W = wrong. All rows except WWW have remaining eligible cards.
# sequence, score/correct_count, mistakes, lives, streak, status, timeline length
cases = [("CWC", 2, 1, 2, 1, "active", 4),
         ("WW", 0, 2, 1, 0, "active", 3),
         ("WWW", 0, 3, 0, 0, "lost", 3)]
# Assert revision == len(sequence), sorted unique timeline, and no corrected
# event redrawn. Final wrong card is absent from canonical timeline.
```

Also add `test_last_eligible_miss_wins_with_life_remaining`, `test_last_eligible_third_miss_loses`, `test_wrong_correction_participates_in_min_gap`, `test_bce_ce_inclusive_rules_unchanged`, and `test_impossible_life_counters_rejected`. Assert zero-point anchor/correction, unchanged lives on correct/rejected commands, invalid booleans/negative counters, pending/status consistency and same-year/min-gap semantics.
- [ ] **Step 4: Run RED.** `uv run pytest tests/game/test_three_lives.py -q`; expect assertion/contract failures from immediate-loss behavior, not a database setup error.
- [ ] **Step 5: Implement the transitions and invariants.** In `RunState.__post_init__`, require `0 <= mistakes <= 3`, `0 <= streak <= correct_count`, `revision == correct_count + mistakes`, and `len(timeline) == 1 + revision - int(status == "lost")`; lost requires three mistakes and streak=0, other statuses fewer than three; zero mistakes requires streak=correct_count. Preserve pending/order validation. `place` inserts a non-final miss at `correct_slot`, increments mistakes/revision, clears streak, then picks the next eligible card from the existing deterministic order. Correct increments correct_count/streak/revision. Third miss terminates before eligibility exhaustion and is not inserted. Update existing engine fixture constructors/old immediate-loss expectations for the new rule, without weakening rejection tests.
- [ ] **Step 6: Run GREEN.** `uv run pytest tests/game -q` and Step 1's isolation tests must pass. Commit the named Task 1 files with `feat: implement authoritative three-life rules`.

### Task 2: Empty-gameplay schema transition

**Files:** Modify `backend/app/game/models.py`; create `backend/app/alembic/versions/20261015_01_add_three_life_counters.py` and `backend/tests/browser/test_three_lives_migration.py`.

**Interfaces:** `GameRun.mistakes: int`, `GameRun.correct_count: int` mirror Task 1. Revision `20261015_01` follows `20261013_01`; it changes constraints/columns only after verifying `gameoperation`, `gamerun` and `dailydefinition` are all empty. No automatic data deletion, backfill or single-life branch. Fresh installation also passes the emptiness guard.

- [ ] **Step 1: Write RED migration proof.** Use unittest plus the exact owned `historical_date_game_lives_migration_test`, created only if absent with its ownership comment. Upgrade to `20261013_01`, insert representative legacy gameplay and catalog/account/guest/unrelated sentinel rows, then assert:

```python
# test_nonempty_upgrade_refuses_without_mutation
assert upgrade_to_three_lives_failed
assert revision_after == "20261013_01"
assert private_row_digests_after == private_row_digests_before
# test_empty_upgrade_preserves_non_gameplay: remove gameplay in fixture only,
# upgrade, assert retained row digests identical and new counter constraints work.
```

Add invalid SQL inserts/updates for negative score/mistakes, >3 mistakes, revision/timeline mismatch, nonzero streak on third-miss loss, and zero-life active/won state. Add `test_nonempty_downgrade_refuses`: no silent conversion of a three-life run back to a one-life run. Tests must refuse wrong database name/comment before connecting to a mutating path.
- [ ] **Step 2: Run RED.** `uv run python -m unittest tests.browser.test_three_lives_migration -v`; expect missing-revision/constraint failure, not access to a retained database.
- [ ] **Step 3: Implement columns and matching constraints.** Add non-null counters without a legacy backfill. Use named checks matching Task 1, retaining mode/owner/catalog/pending checks; set defaults only for genuinely new runs. Under the migration transaction acquire locks on the three gameplay tables before emptiness validation. Downgrade requires empty gameplay too. Do not edit historical migration scripts.
- [ ] **Step 4: Run GREEN.** Repeat Step 2; expect PASS for successful empty transition and rejected nonempty transitions. Upgrade the owned engine/API test DB with `uv run alembic upgrade head` under its explicit test environment, only after verifying gameplay empty. Commit named files with `feat: constrain three-life persistence on empty gameplay state`.

### Task 3: Transactional API, scoring, protocol and new recovery namespace

**Files:** Modify `backend/app/game/{schemas,run_service,projections,daily_service}.py`, `backend/app/api/routes/games.py`; create `backend/app/game/protocol.py`. Modify `frontend/src/features/game/{api,identityState,placementState}.ts`, `FreeplayForm.tsx`, `DailyPanel.tsx`; create `frontend/src/features/game/gameProtocol.ts`. Regenerate `frontend/src/client/` and `frontend/openapi.json`. Update command/DTO builders in `backend/tests/api/routes/`, `backend/tests/browser/`, `frontend/tests/fixtures/`, existing `frontend/tests/game-*.{test,spec}.ts`, `frontend/tests-guest-catalog/` and `frontend/tests-real-catalog/` where the new required contract is consumed. Test `backend/tests/api/routes/{test_game_runs,test_game_daily,test_game_concurrency,test_game_attempted_slot,test_guest_game_api}.py`; new `frontend/tests/game-protocol.test.ts`.

**Interfaces:** `GAME_PROTOCOL_VERSION = 2` in backend `protocol.py` and frontend `gameProtocol.ts`. Required strict integer `protocol_version: Literal[2]` with **no default** on `FreeplayStart`, `DailyStart`, `PlaceCommand`; advertise `protocol_version=2` in `GameOptions` and `GameSessionPublic`. Add required `initial_lives: Literal[3]`, `lives_remaining: int`, `score: int` to `RunPublic`; `score` is persisted `correct_count`. Add `score` to `LeaderboardEntry`, retaining separate `streak`. Make `MoveFeedback.attempted_slot` required/non-null since old snapshots are discarded. All feedback slots refer to the timeline before this move.

Storage/query prefixes become `game:v2:` / `["game", 2, ...]`. Keep public `context_id`, access tokens, HttpOnly cookies and guest bootstrap coordination unchanged. Prefix only gameplay recovery/acknowledgement keys; do not adopt the legacy unversioned start/placement keys through `adoptAccountPlacement` or other fallback paths.

- [ ] **Step 1: Write API RED tests.** `test_nonfinal_miss_is_atomic_and_reloadable` asserts lives=2, score=0, streak=0, revision=1, corrected card once in sorted timeline, next pending year absent, and identical feedback on GET. `test_mixed_sequence_scores_correct_count` asserts CWC score=2/streak=1. `test_three_misses_end_run` asserts lives=0/lost and final miss absent from canonical timeline. `test_missing_or_old_protocol_cannot_mutate` covers all three commands, both identities, `1`, missing, boolean and string values; assert validation rejection and unchanged operation/run/definition counts. Session/options responses advertise 2 without private data.

```python
# After the first intentionally wrong placement in the existing API fixture:
body = response.json()
assert (body["initial_lives"], body["lives_remaining"], body["score"],
        body["streak"], body["revision"]) == (3, 2, 0, 0, 1)
assert body["status"] == "active"
assert "year" not in body["pending"]
assert sum(c["event_id"] == body["feedback"]["card"]["event_id"]
           for c in body["timeline"]) == 1
assert reloaded.json()["feedback"] == body["feedback"]
```
- [ ] **Step 2: Write concurrency/Daily RED tests.** `test_duplicate_wrong_command_costs_one_life` sends the same UUID/body concurrently and after committed-response loss; assert equal JSON results, one operation and revision=1/mistakes=1. `test_changed_body_same_uuid_conflicts` and `test_foreign_or_stale_command_preserves_lives` assert no new counters. `test_daily_score_not_final_streak` ranks completed score=4/streak=0 ahead of score=3/streak=3; equal scores share a rank without speed/lives tie-breakers. Preserve shared definition, one attempt per owner and UTC-midnight exact retry tests.
- [ ] **Step 3: Run RED.** `uv run pytest tests/api/routes/test_game_runs.py tests/api/routes/test_game_daily.py tests/api/routes/test_game_concurrency.py tests/api/routes/test_game_attempted_slot.py tests/api/routes/test_guest_game_api.py -q`; expect contract/assertion failures, not fixture database errors.
- [ ] **Step 4: Implement the service contract.** Round-trip both persisted counters in start/load/place paths (use named `RunState` arguments). Project derived lives and score explicitly. Save corrected state, next pending and immutable attempted/correct feedback in the same transaction and operation outcome. Preserve operation-before-owner/run lock order, owned reads, digest conflict semantics and revision-bound `latest_placement`. Rank completed Dailies by correct_count, not streak, with shared score ranks. Reject old protocol at validation before gameplay mutations; avoid protocol defaults that would accept old request bodies. Preserve strictness against bool/coercion; add a before-validator if Literal alone accepts `True`/coercible values.
- [ ] **Step 5: Regenerate clients.** Use the repository's existing `scripts/generate-client.sh` against this checkout's OpenAPI, never a live API. Inspect the generated diff for the named fields and no unrelated generator churn; then update current DTO/command factories to send protocol 2 and three-life metadata. Preserve authentication and same-origin request handling.
- [ ] **Step 6: Write frontend protocol RED tests.** `game-protocol.test.ts` asserts new `beginPlacement` bodies include `protocol_version: 2`, exact retries retain UUID/body, new storage keys differ from literal legacy keys, and no account-token key changes. Extend controlled bootstrap/identity tests with old saved start/placement records: assert zero recovery POSTs from those records, intact credentials, and an intentional fresh start sends protocol 2. Unsupported server protocol or missing old run shows **Game updated. Refresh and start a new game.**, never silently creates a run or regenerates a rejected UUID.
- [ ] **Step 7: Run protocol RED, then implement it.** From `frontend/`, `node --test tests/game-protocol.test.ts` must first fail on the missing/new contract. Implement the exact namespace/constants in `gameProtocol.ts` and call sites; check bootstrap/options version before accepting gameplay. Teach validation/recovery errors to distinguish incompatible release from an uncertain committed current move. Update the controlled test harness response factories, not assertions that enforce ownership.
- [ ] **Step 8: Run GREEN.** Repeat Step 3, `npm run test:unit`, `npm run typecheck`, and `npx playwright test --config playwright.bootstrap.config.ts` / `--config playwright.identity.config.ts` on their owned unused ports; expect no old-protocol mutation or credential regression. Commit only named changed files with `feat: expose three-life scoring and isolate protocol recovery`.

### Task 4: Revision-bound mistake review and continuation

**Files:** Create `frontend/src/features/game/mistakeReview.ts`, `frontend/tests/mistake-review.test.ts`; modify `useOwnedRun.ts`, `placementState.ts`, `lossTimeline.ts`, `GameBoard.tsx`, `GameResults.tsx`, `frontend/tests/{loss-timeline,game-state}.test.ts`, `frontend/tests/{game-board-ux,game-identity-recovery,game-recovery}.spec.ts`.

**Interfaces:** `mistakeReviewKey(contextId: string, runId: string, revision: number): string`, `needsMistakeReview(run: RunPublic, acknowledged: boolean): boolean` in `mistakeReview.ts`. It returns true for a latest non-final miss (`feedback.correct === false && lives_remaining > 0`), including `status === "won"` from pool exhaustion. `useOwnedRun` produces `reviewingMistake: boolean` and `continueAfterMistake(): void`. Extend `lossTimeline(run: RunPublic, reviewingMistake = false)` to reuse the existing attempted/correct display API; legacy display fallback is unnecessary with required attempted_slot. Rendering is a projection; never mutate canonical `run.timeline`.

- [ ] **Step 1: Write review RED unit tests.** `test_nonfinal_review_removes_corrected_card_before_attempt_projection` asserts one feedback card in attempted position, input timeline unchanged, and the correct-location marker uses pre-insertion coordinates in both move directions and first/last slots. Assert `needsMistakeReview` for active and won non-final misses, false for final loss/correct/acknowledged feedback. Acknowledge keys differ by context/run/revision; malformed values are not treated as acknowledgement. Older revisions cannot replace newer accepted run state.

```typescript
// With the new-schema non-final-miss fixture, also parameterized as won:
assert.equal(needsMistakeReview(run, false), true)
assert.equal(needsMistakeReview(run, true), false)
const before = structuredClone(run.timeline)
const display = lossTimeline(run, true)
assert.equal(display.items.filter((item) => item.wrong).length, 1)
assert.deepEqual(run.timeline, before)
assert.notEqual(mistakeReviewKey("a", run.run_id, 1),
                mistakeReviewKey("b", run.run_id, 1))
```
- [ ] **Step 2: Run RED.** `node --test tests/mistake-review.test.ts tests/loss-timeline.test.ts tests/game-state.test.ts`; expect absent helper/wrong display assertions.
- [ ] **Step 3: Implement review and acknowledgement.** Read/write a literal acknowledgement value under its versioned context/run/revision key, catching storage failures. On denial use in-memory acknowledgement for this mounted run; losing it may repeat explanation, never a command. Check current identity and revision before acknowledging. Lock preview/submit while reviewing, hide the next pending tile, and show **Incorrect — 2 lives left** (with correct singular/plural) plus **Continue** near the wrong card. Continue changes only local presentation and reveals sorted canonical state; no HTTP call. For a terminal win defer completion until Continue. Final loss retains attempted-position review and separate correct marker without Continue. Render **Lives: 2 of 3**, cumulative score and separate streak accessibly; focus feedback/Continue then the next pending card or result as appropriate. Reduced motion uses the same states without movement animation.
- [ ] **Step 4: Write browser tests, then run their RED/GREEN cycle.** In `game-board-ux.spec.ts`, confirm a non-final miss, assert no next pending tile and disabled placement, reload before Continue to reconstruct review, Continue and assert **zero additional placement POSTs**, sorted correction once and next prompt visible without its year. Repeat for final eligible non-final miss (review then won) and third miss (lost). In `game-identity-recovery.spec.ts`, switch accounts mid-review and inject malformed/denied storage; assert no cross-context acknowledgement or submission. Add delayed older-revision/response-loss cases to `game-recovery.spec.ts`; assert one life charged, no revision rollback. Run `npx playwright test --config playwright.board.config.ts` and `--config playwright.identity.config.ts`; for real `game-recovery.spec.ts` use Task 6's fixture runner, not the live backend.
- [ ] **Step 5: Run GREEN unit checks** from Step 2 plus `npm run typecheck`; then commit named files with `feat: review mistakes before continuing three-life runs`.

### Task 5: Warm responsive board, inline confirmation and non-scrolling cards

**Files:** Modify `frontend/src/features/game/{game.css,GameCard.tsx,EventDetailsDialog.tsx,PendingTile.tsx,TimelineStage.tsx,GameBoard.tsx,useTimelineInteraction.ts,boardGeometry.ts,timelineNavigator.ts}`; update `DailyPanel.tsx`, `FreeplayForm.tsx`, `GameResults.tsx` only for consistent play-shell presentation. Tests: `frontend/tests/board-geometry.test.ts`, `frontend/tests/{game-board-ux,board-projection-focus,board-navigation}.spec.ts` and their existing harnesses under `frontend/tests/fixtures/`; update confirm helpers/old first-miss-loss expectations in `frontend/tests-guest-catalog/` and `frontend/tests-real-catalog/` to actually exercise three-miss loss, not weaken terminal assertions.

**Interfaces:** Add `contentOrigin(layout: BoardLayout): number` in `boardGeometry.ts` for short-strip centering; use the same origin in render positions, hit testing, visible ranges and reveal. Geometry continues using CSS pixels and logical slots. `TimelineStage` receives `onConfirm: () => void`, `canConfirm: boolean`; the preview position container owns the **✓ Confirm** button, outside the draggable handle. `GameBoard` still calls the existing guarded `submit`. Measure actual responsive card width/gap with the existing observer path, not a second hardcoded geometry system.

- [ ] **Step 1: Write geometry RED tests.** For a short strip, assert a positive centered origin and `insertionIndex(contentOrigin(layout) + cardWidth / 2, layout)` maps to the intended boundary without offset drift. For long strips, origin=0. Cover preview expansion, all endpoint slots, resized widths, stationary pointer stability, navigation reveal and visible-confirmed marks. Run `node --test tests/board-geometry.test.ts`; expect the new origin contract to fail.
- [ ] **Step 2: Write layout/interaction RED tests in the existing controlled board suite.** At both desktop sizes, assert document height/width within viewport, full card plus confirmation visible after drop, confirmation center under that tile, button >=44px high, and no placement POST until a click/keyboard activation. Re-pickup/reposition moves the same preview/confirmation; return-to-hand removes it. Assert pending preview width increases at 1920×900 relative to the existing fixed 230px baseline without forcing a tiny-font 1366×768 layout. Compare computed canvas colors with the agreed warm palette, not old navy. Assert warm styling in light/dark app themes and readable control contrast.

```typescript
// After a valid drop in the harness, before any explicit confirmation:
const confirm = page.getByRole("button", { name: "Confirm", exact: true })
const buttonBox = (await confirm.boundingBox())!
const cardBox = (await page.getByTestId("pending-card").boundingBox())!
expect(buttonBox.y).toBeGreaterThanOrEqual(cardBox.y + cardBox.height)
expect(buttonBox.height).toBeGreaterThanOrEqual(44)
expect(Math.abs(buttonBox.x + buttonBox.width / 2 -
                cardBox.x - cardBox.width / 2)).toBeLessThan(2)
expect(placementRequests).toHaveLength(0)
```
- [ ] **Step 3: Add overflow/accessibility RED cases.** Supply long unbroken text, many short wrapped words, a medium-length overflowing title, missing/broken imagery and a short prompt. Assert no card descendant uses vertical `auto`/`scroll`, no clipped content lacks a full-text action, date and Learn more share a compact footer, pending full-text dialog omits the year, and attribution survives. Resize after dropping and after font/image load; selected slot stays stable and confirmation stays reachable. Check keyboard focus/modal return, touch drag, reduced motion, narrow 390×844 reflow and 200% zoom-equivalent layout without requiring desktop page-fit at zoom.
- [ ] **Step 4: Run browser RED.** `npx playwright test --config playwright.board.config.ts`; expect focused geometry/layout/action assertions to fail on the current UI, not browser launch/configuration errors. Do not call a sandbox failure a test failure or a pass.
- [ ] **Step 5: Implement geometry and local actions.** Center short strips using Task 5's origin throughout logical math and rendering; long strips retain pan/navigation. Share measured responsive dimensions, including reserved card-local action height, with CSS. Render **✓ Confirm** immediately below valid dropped previews only, with the check decorative (`aria-hidden`) and accessible name **Confirm**; disable while dragging/sending/reconciling/reviewing and prevent pointer activation from starting a drag. Remove the distant primary Lock it in action, update keyboard instructions and retain compact Return to hand/recovery actions. Reveal the card/action pair, including after resize and at end slots.
- [ ] **Step 6: Implement warm, denser card layout.** Replace the hardcoded navy play canvas with scoped warm stone/cream/charcoal tokens and earthy accents, with text/icons for correctness. Use responsive card width/height and real available play-shell space; remove redundant panels/margins before growing text/art. Keep a single timeline/overview. Replace tile-internal overflow with a bounded readable excerpt; detect actual text overflow using measured content on resize/font/layout changes rather than a character cutoff. Offer explicit full wording/details for truncation. Keep year/Learn more tightly grouped with usable targets, existing event links, Credits/Sources and dialog-based long explanations; no content acquisition or invented photographs.
- [ ] **Step 7: Run GREEN and capture screenshots.** Repeat Steps 1/4, `npm run typecheck`, `npm run lint`, `npm run build`; inspect actual screenshots at 1920×900, 1366×768 and narrow mobile for whitespace/readability and footer density rather than relying only on DOM sizes. Keep private before/after evidence and note limitations. Commit named files with `feat: use a warm responsive board with card-local confirmation`.

### Task 6: Whole-branch verification and review gate

**Files:** Update affected test expectations in `backend/tests/`, `frontend/tests/`, `frontend/playwright*.config.ts` only as needed; create `docs/beta/board-polish-three-lives.md`. Evidence/checklist remains private under `.superpowers/board-polish-three-lives/`. Existing earlier evidence is never overwritten.

**Interfaces:** The `lives` profile uses the existing `prepare-db`, `seed-real`, `seed-fixture`, `launch`, `stop`, `audit` helper commands with ownership checks. Reuse existing Playwright fixture/real/controlled configurations and same-origin browser vs isolated Node provisioning origins. No live consumer or retained catalog mutation is part of verification.

- [ ] **Step 1: Run full backend gate.** With the explicit isolated test environment, `uv run pytest tests -q` must pass, along with Task 2 migration proof. If the rollout unittest module does not exist until Task 7, run it there. Run `uv run bash scripts/lint.sh`; fix only feature-related regressions and rerun the affected checks. Capture actual totals; do not assume the previous 1,233-test count still applies.
- [ ] **Step 2: Run frontend/client gate.** Regenerate client once more and require no new generated diff; run `npm run test:unit`, `npm run typecheck`, `npm run lint`, `npm run build`. Run controlled board/bootstrap/identity configs separately on verified unoccupied ports with retries=0; all must pass. Preserve unsuppressed known drag-library diagnostics and report any new ones.
- [ ] **Step 3: Provision isolated fixture/real browser targets.** Under `HDG_VERIFICATION_PROFILE=lives`, prepare each target DB with its exact ownership comment and absent/idle checks. Use `seed-fixture`; for `seed-real --release <absolute-sealed-release>`, freshly verify the existing manifest hash `804ec52ccfc3e19cd955913b05cbfd59158f562408e45c1916fa8626d3ac50d3` and 1,276-event catalog first. Copy verified media into new test runtime only; preserve the original sealed release and private event-link sidecar. Launch using the existing owned helper, never ad-hoc processes or an adopted occupied port.
- [ ] **Step 4: Run real journeys.** Run `npx playwright test --config playwright.config.ts` against the owned fixture profile with `VITE_API_URL=http://localhost:8021 PLAYWRIGHT_API_PROXY=http://localhost:8021`; then `npx playwright test --config playwright.guest-catalog.config.ts` against owned real UI localhost:5184/API localhost:8020. For `npx playwright test --config playwright.real-catalog.config.ts`, explicitly set `REAL_CATALOG_API_ORIGIN=http://localhost:8020 REAL_CATALOG_UI_ORIGIN=http://localhost:5184 REAL_CATALOG_RELEASE_DIR=<verified-absolute-sealed-release>` and supply private test credentials without printing them. Keep provisioning requests on the isolated backend, never route Node provisioning through the UI or use the live-origin defaults. Execute all configured shards/projects, not one convenient browser slice. Assert no-login Daily and Freeplay start at three lives, two mistakes can continue, third loses, cumulative score survives reload/response loss, and account/admin protection remains intact. Run helper `audit --target fixture` and `audit --target real`. Stop only owned test processes after proof; preserve artifacts/databases unless a test explicitly owns a create/remove cycle.
- [ ] **Step 5: Document delivery/readiness.** `docs/beta/board-polish-three-lives.md` records rules, reset table scope, old-client refresh behavior, local operator commands from Task 7 and exact verification results. Keep secrets/raw ownership records private. State existing catalog limitations honestly (no BCE content/photographs in the reviewed real catalog; BCE correctness tested with fixtures), screen-reader/physical-device gaps and local-only certification. No production-ready claim follows from automated tests.
- [ ] **Step 6: Obtain the required independent whole-branch review** using the execution method chosen by the owner. Review the approved spec and cumulative diff for mutation/ownership/privacy, protocol recovery, scoring and layout; fix findings with RED/GREEN evidence, rerun impacted gates and get blocking findings resolved. Commit only named feature/test/docs changes with `test: verify three-life gameplay and responsive board`. No publish or merge implied.

### Task 7: Guarded gameplay reset and local generation switch

**Files:** Create `backend/tests/browser/three_lives_local_rollout.py`, `backend/tests/browser/test_three_lives_local_rollout.py`; update `docs/beta/board-polish-three-lives.md` with proven commands. Do not rewrite `board_local_rollout.py`, old lifecycle records, retained `.env` or catalog artifacts.

**Interfaces:** `inspect_target() -> dict[str, object]`, `reset_gameplay(connection: sqlalchemy.Connection) -> dict[str, int]`, `main(argv: list[str] | None = None) -> int` in the new helper. CLI `inspect` is read-only/default; `apply --confirm-database historical_date_game_catalog_test --evidence-dir <fresh-private-path>` is the only live-reset route and is local-only. `reset_gameplay` is internal and callable by the guarded path/tests, not an HTTP endpoint or ordinary startup/migration. New-generation `stop --evidence-dir ...` verifies its own recorded PID/start-time/cwd/argv before signaling. Build this helper/test it before any live action; Task 6's substantive code/test/review gates must be green before applying it.

- [ ] **Step 1: Write safety RED tests using mocked process boundaries and an owned disposable migration database.** Assert default inspection executes no mutation; wrong hostname/port/database/environment/revision, stale PID/start ticks, argv/cwd/bind mismatch, active foreign DB sessions, reused evidence path and absent confirmation all reject before deletion/signaling. Verify no arbitrary PID adoption and no broad `pkill`, process-group kill, Compose teardown or DROP/TRUNCATE CASCADE path.
- [ ] **Step 2: Write scoped-reset RED proof.** On an owned DB at old revision `20261013_01`, seed old active/lost/won games, operations/Daily plus catalog/accounts/guest/unrelated sentinels. Assert reset deletes exactly `gameoperation`, `gamerun`, `dailydefinition` in dependency order; compare private row digests for every retained table before/after. Assert old source/media file hashes unchanged. Simulate failure during deletion for full transaction rollback and failure after committed reset/before migration: keep services stopped, record actual phase, never auto-restart the old generation. Migration rerun may resume only from a freshly inspected expected phase. After migration, fresh Daily for the same UTC date starts with three lives and one-attempt uniqueness is restored.

```python
# Capture retained digests privately before calling the guarded reset path:
assert set(deleted_counts) == {"gameoperation", "gamerun", "dailydefinition"}
assert all(count == 0 for count in remaining_gameplay_counts.values())
assert retained_row_digests_after == retained_row_digests_before
assert source_media_hashes_after == source_media_hashes_before
assert new_daily["initial_lives"] == new_daily["lives_remaining"] == 3
```
- [ ] **Step 3: Run RED, implement helper, run GREEN.** `uv run python -m unittest tests.browser.test_three_lives_local_rollout -v` must fail for the unimplemented helper, then pass. Reset uses explicit DELETEs in one transaction with table locks, not filesystem cleanup or catalog reseeding. Apply verifies exact local DB `127.0.0.1:5433/historical_date_game_catalog_test`, settings `local`, original process ledger and expected revision; obtains fresh stopped-service/no-other-consumer proof before mutation. Count/digest evidence is private, not credentials printed to logs. Allow the internal test path only for the exact owned `historical_date_game_lives_migration_test`. Re-run full backend tests and lint including the new helper; review its cumulative diff and safety tests independently before proceeding. Commit named files with `ops: guard local three-life gameplay reset and rollout`.
- [ ] **Step 4: Perform read-only preflight and record the result.** Re-read this plan/spec authorization, check exact tested feature commit and clean product tree (only retained `.env` may differ), catalog/media/links hashes, IP/origin, DB revision, process PIDs/start ticks/cwd/argv and listener binds. Use the old generation's original pinned runner from the live board checkout to inspect/stop it; do not disable its revision guard or change that checkout. A mismatch is a blocker, not permission to kill or repair an unrelated service. Confirm new lifecycle path/ports/origins and preserve the old records.
- [ ] **Step 5: Execute the authorized local reset/switch once.** Stop only the proven old API/UI pair through its original ownership-checked lifecycle. Recheck no consumers; use the new helper's explicit `apply` with the exact confirmation above, reset only gameplay, migrate to `20261015_01`, verify retained-data digests and launch the new API/UI from the tested isolated checkout on API `127.0.0.1:8010`, UI `0.0.0.0:5174` with LAN origin `http://192.168.1.214:5174`. Preserve guest cookie configuration, private secrets and honest public catalog selection. Create fresh ownership records. On failure keep the actual stopped/reset/migrated state visible; do not recreate old gameplay or start old code against incompatible schema.
- [ ] **Step 6: Verify actual LAN delivery.** Check fresh process identity/binds, API health, public options/protocol, admin protection and no-login cookie round trip. Use an actual browser through the LAN origin for a fresh three-life run: first/second mistakes review/continue, exact-retry proof without extra life loss, final loss in attempted position, local confirm placement and responsive screenshots. Also verify new Daily budget/one attempt with an owned disposable guest, without resetting it again. Re-audit retained catalog/account/media state. If browser launch remains blocked by sandboxing, report the blocker; HTTP-only smoke is not equivalent to a browser proof. Do not rerun unrelated completed suites merely for a process restart.
- [ ] **Step 7: Record outcome and hand off.** Update private progress and public delivery notes with tested/activated commits, verification commands/counts, actual URL, reset scope, unresolved limitations and operator stop/resume instructions. Run `git diff --check`, verify only named intended files staged and commit documentation. Report LOCAL availability only; no push/PR/merge/staging/production action is authorized here.

## Self-review and execution gate

Coverage: spec presentation → Task 5; state machine → Task 1; persistence/replay/protocol → Tasks 2–3; review/Continue/reload → Task 4; reset/Daily ranking → Tasks 3/7; verification/safe delivery → Tasks 6–7. Five review-focus conditions each have explicit owning tests above. The only live data deletion is Task 7, after tested implementation and ownership review; no prior task carries out the reset. Post-reset command replay remains exact, while pre-reset state is deliberately abandoned.

Type/copy check: `correct_count` is internal/persisted; `score` is the public field; `streak` is separate everywhere. `protocol_version=2` is a request/release boundary; `generation_version=1` remains event shuffling. `initial_lives=3`, derived `lives_remaining`, required pre-insertion `attempted_slot`, `reviewingMistake` and `continueAfterMistake()` have one meaning across tasks. No extra persistence table/endpoint for Continue or configurable lives is introduced.

Execution starts only after owner review of this plan and choice of method (subagent-driven or native). Approval of the design is not yet approval of this plan or a request to start deleting data now.
