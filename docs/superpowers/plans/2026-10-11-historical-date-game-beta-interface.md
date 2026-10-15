# Historical Date Game Player Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make both modes feel like a polished, tactile card game with accessible placement, meaningful imagery, and reliable resume.

**Architecture:** Generated public DTOs remain the source of truth. Local state holds only tentative placement and an in-flight command; the server confirms results. Focused game components use the existing router/query/auth setup.

**Tech Stack:** React 19, TypeScript 7, TanStack Router/Query, existing Tailwind/Radix UI, stable dnd-kit React/DOM 0.5.0, CSS transitions, Node tests, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-11-historical-date-game-beta-design.md`, sections 3-8. Read the [master plan](2026-10-11-historical-date-game-beta.md) first.

## Global Constraints

All master constraints/contracts apply. Only the pending card moves; **Lock it in** scores. Keyboard/tap alternatives and reduced motion are mandatory. No answer years, future sequence, seeds, or private catalog artifacts in frontend source/bundles.

## Review Focus

Master focus 3 belongs to U2 (timeout, stale responses/tabs); focus 5 belongs to U3/U4 (long touch layouts, cancellation, image failures). Confirm accessibility on actual layouts, not only reducer tests.

---

## Task U1: game-first navigation and mode configuration

**Files:** Create `frontend/src/features/game/{api,config}.ts`, `frontend/src/features/game/{FreeplayForm,DailyPanel}.tsx`, `frontend/src/routes/_layout/{freeplay,daily}.tsx`, `frontend/src/routes/_layout/play/$runId.tsx`, `frontend/tests/game-config.test.ts`, `frontend/tests/game-modes.spec.ts`; modify `frontend/src/routes/_layout/index.tsx`, `frontend/src/components/Sidebar/{AppSidebar,Main}.tsx`, `frontend/src/components/Common/{Footer,Logo}.tsx`, `frontend/src/routes/{login,signup}.tsx`, `frontend/src/utils.ts`, `frontend/tests/api-errors.test.ts`; regenerate `frontend/src/routeTree.gen.ts`.

**Interfaces:** API wrapper exports `getGameOptions(): Promise<GameOptions>`, `getDaily(): Promise<DailyOverview>`, `startFreeplay(input: FreeplayStart): Promise<RunPublic>`, `startDaily(input: DailyStart): Promise<RunPublic>`, `getRun(runId: string): Promise<RunPublic>`, `getActiveRuns(): Promise<RunPublic[]>`, `placeCard(runId: string, input: PlaceCommand): Promise<RunPublic>`, `getLeaderboard(day: string): Promise<LeaderboardPublic>` using B5's generated DTOs. `validateConfig(config: GameConfig, options: GameOptions): string[]` in `config.ts`; export `formatYear(year: YearInput): string`. Existing error helper handles structured `detail.message` plus string/array errors.

- [ ] Write `config_rejects_empty_unknown_and_zero_year` and `era_bounds_and_gap_match_backend` Node tests. Assert magnitude 0/negative, bool/noninteger, reversed BCE/CE bounds, gap < 1, and unknown/empty categories are rejected; gap 10 and inclusive 1 BCE-to-1 CE are represented without civil zero. Defaults use all published categories/full bounds/gap 1. Add browser `daily_preview_does_not_start` and `signup_hidden_when_enrollment_closed`; a direct signup URL explains restricted enrollment, not just a hidden link.
- [ ] Run from `frontend/`: `npm run test:unit` and `npx playwright test tests/game-modes.spec.ts --project=chromium`; expect missing exports/routes/config failure against B5's test backend.
- [ ] Implement typed wrappers using existing client configuration/auth, error extraction, era-aware Freeplay validation, category checkboxes, and disabled/loading submits. Add an api-errors regression asserting structured `detail.message` is displayed. Generate one start operation UUID per action and reuse it on timeout retry. Explain sparse configurations using the server's error; no attempt/run is allocated until valid start. Create `/play/$runId` with an authorized `getRun` loader and read-only initial anchor/pending summary so start/resume navigation works independently; U2 replaces its summary with the playable board.
- [ ] Replace template home emphasis/branding with Historical Date Game, Daily, Freeplay, and resume-owned-run links; remove upstream promotional/social links from the player footer while preserving required notices. Keep settings/admin authorization and sample-item routes working; remove their navigation emphasis, not their data/code. Daily shows UTC reset/countdown, fixed categories, Start or Resume/View Result, and completed leaderboard with tied ranks; past-day results remain accessible via the run's day. Login/signup read B5's small public enrollment config; backend remains the enforcement boundary.
- [ ] Run Node tests, mode browser tests, typecheck/lint/build; expect pass. Regenerate the route tree through the existing router tooling. Commit named files: `git commit -m "feat: add game modes and category-based freeplay setup"`.

## Task U2: authoritative board state and retry/resume

**Files:** Create `frontend/src/features/game/placementState.ts`, `frontend/src/features/game/{GameBoard,GameResults,ContentIssueDialog}.tsx`, `frontend/tests/game-state.test.ts`, `frontend/tests/game-recovery.spec.ts`; modify `frontend/src/routes/_layout/play/$runId.tsx` and `api.ts`.

**Interfaces:** `PlacementState = {run: RunPublic, selectedSlot: number | null, command: PlaceCommand | null, phase: 'idle' | 'sending' | 'uncertain' | 'reconcile'}`. Pure exports `selectSlot(state: PlacementState, slot: number | null): PlacementState`, `beginPlacement(state: PlacementState, operationId: string): PlacementState`, `acceptRun(state: PlacementState, run: RunPublic): PlacementState`, `markUncertain(state: PlacementState): PlacementState` in `placementState.ts`. Components `GameBoard({runId}: {runId: string})` and `GameResults({run}: {run: RunPublic})` return `React.JSX.Element`.

- [ ] Write `preview_never_scores`, `timeout_retains_operation_and_preview`, and `older_response_cannot_roll_back`. Selecting/repositioning/canceling changes no streak/revision or network state; duplicate submit while sending is blocked. A retry preserves operation UUID/event/revision/slot exactly. An older RunPublic is ignored; a newer authoritative revision clears invalid pending-card preview/command; an equal-revision failed/retry response preserves recoverable preview.

```typescript
assert.equal(selectSlot(initial, 1).run.streak, initial.run.streak)
assert.deepEqual(markUncertain(sending).command, sending.command)
assert.equal(acceptRun(newer, older.run).run.revision, newer.run.revision)
```

- [ ] Run `npm run test:unit`; expect missing-placement-state failure.
- [ ] Implement state transitions and board/query wiring with initial labeled slot buttons and Lock it in so this task is playable before U3 adds dragging/art. Do not optimistically score or use hidden years. Ordinary pre-commit failure preserves card/preview; uncertain timeout offers retry with the same command or authoritative refetch before accepting a new guess. A 409 triggers reconcile/refetch; invalid/auth/service failures are distinct from historical loss. On tab focus/reconnect/reload read authoritative state; after login renewal return to the run route, preserving server progress. Associate every response/query with run ID and monotonic revision so delayed responses cannot roll back another round.
- [ ] Write browser tests `committed_move_response_lost_then_retry`, `two_tabs_one_authoritative_move`, and `reload_and_login_renewal_preserve_progress` against the real test backend. Simulate a committed response being dropped, not just a request that never reaches the server; assert one increment, same operation ID on retry, unchanged pending card until reconciliation, and no accidental loss. Use route interception plus recorded backend revision to prove the committed timeout case.
- [ ] Implement results: mistake reveals answer/correct slot/explanation and unchanged final streak; victory is distinct and describes the exhausted configuration/catalog release. New Freeplay leaves active runs resumable; Daily cannot restart or replay. Add ContentIssueDialog with copyable event/run IDs and a mailto report link to configurable `VITE_FEEDBACK_EMAIL` (L1 owner supplies beta address); no tokens/player email in the report. Add a browser assertion that feedback instructions are accessible from active cards/results. Run unit/recovery tests; expect pass.
- [ ] Commit state/board/results/route/tests: `git commit -m "feat: resume authoritative games and recover uncertain moves"`.

## Task U3: framed cards, accessible insertion, and tactile dragging

**Files:** Create `frontend/src/features/game/{GameCard,EventImage,Timeline,InsertionSlot}.tsx`, `frontend/src/features/game/game.css`, `frontend/tests/game-interaction.spec.ts`; modify `GameBoard.tsx`, `frontend/src/routes/_layout.tsx`, `frontend/package.json`, `frontend/package-lock.json`, `frontend/playwright.config.ts`.

**Interfaces:** `GameCard({card, revealed}: {card: PendingCard | RevealedCard, revealed: boolean})`; `EventImage({media}: {media: MediaPublic})`; `Timeline({cards, selectedSlot, onSelectSlot}: {cards: RevealedCard[], selectedSlot: number | null, onSelectSlot: (slot: number | null) => void})`; `InsertionSlot({index, selected, onSelect}: {index: number, selected: boolean, onSelect: () => void})`. Each returns `React.JSX.Element`. Timeline renders exactly `cards.length + 1` equally styled slots with index labels, not chronology hints.

- [ ] Write browser `drop_previews_reposition_and_lock`, `outside_drop_and_escape_do_not_submit`, `touch_and_keyboard_can_place_every_slot`, `image_failure_does_not_change_state`, and `reduced_motion_preserves_feedback`. Assert no placement POST on drop/tap/cancel, exactly one POST on confirmation, only pending card draggable, focus/labeled slots/live result announcements available, 44px-or-larger touch targets, and failed primary media shows meaningful fallback/credits without scoring.
- [ ] Run `npx playwright test tests/game-interaction.spec.ts --project=chromium`; expect missing components/interaction failure.
- [ ] Add current-compatible stable `@dnd-kit/react`/`@dnd-kit/dom` and implement pending draggable plus slot droppables with `DragDropProvider`, pointer/touch and keyboard sensors. Keep library calls current via Context7; don't mix legacy `DndContext` APIs with the new provider. Drag/drop calls `onSelectSlot`, never `placeCard`. Provide independent tap slot buttons, keyboard previous/next/first/last controls, Escape cancel, and explicit Lock it in. Outside drops reset safely. Disable submission while sending/uncertain until resolved.
- [ ] Implement shared image window (`aspect-ratio: 4/3`), media-specified contain/cover, opaque retained URLs, readable compliant credits, fallback-on-error once (no recursion), and an accessible fallback placeholder if both assets fail. Slow/failed imagery cannot move slot targets or obscure text. Already-revealed cards include year; pending content uses only the public DTO. Nonidentical art styles share borders/spacing/elevation.
- [ ] Implement rich palette (navy `#17243b`, cream `#f7f0df`, teal `#087f8c`, coral `#d65a42`), high-contrast labels, category accents plus text/icons, lifted drag overlay, and modest neighbor shifts. Only server-confirmed success triggers snap/year reveal/streak flourish; failure shows correct position, victory its own nonblocking celebration. Reduced motion disables decorative transforms/confetti, not result information.
- [ ] Implement horizontal desktop timeline and vertical narrow-screen layout below 768px with pending card/controls accessible, edge auto-scroll, and first/last-slot shortcuts. Give play routes a full-width card-table surface and compact navigation instead of the default dashboard max-width/sidebar footprint; retain existing admin/settings layout. Add explicit mobile-touch Playwright project `game-mobile` matching `game-*.spec.ts` with setup/auth dependencies; tests on the same account must not race a Daily, so use fresh accounts per test. Run Chromium/mobile interaction tests; expect pass. Commit: `git commit -m "feat: add tactile accessible card placement and imagery"`.

## Task U4: complete-mode journeys and real-layout polish

**Files:** Create `frontend/tests/game-journeys.spec.ts`, `frontend/tests/fixtures/game-public.ts`, `docs/beta/interaction-review.md`; update existing game components/CSS based on evidence.

**Interfaces:** Public fixtures contain synthetic prompts/years and public DTOs only; no production catalog/answer map is bundled. Browser tests use a small backend fixture release for real scoring; long-layout visual tests may intercept public DTOs without claiming engine coverage.

- [ ] Write end-to-end `freeplay_category_bounds_gap_win_and_loss`, `daily_shared_game_one_attempt_and_leaderboard`, and `hundred_card_timeline_every_slot_accessible`. Assert mode configs/results/catalog labels, same Daily current cards for two accounts, resume after leaving, no retry after completion, both terminal outcomes, and no hidden years/source URLs before scoring. Verify sparse errors and unavailable catalog never show loss.
- [ ] Run `npx playwright test tests/game-journeys.spec.ts --project=chromium --project=game-mobile`; expect failures for any uncovered journey/layout gap, not invented regressions. Fix only the failures with their owning components/services.
- [ ] Manually inspect desktop and a real touch device with a 100-card timeline, first/last/middle insertion, edge scrolling, keyboard-only focus, slow/failed images, attribution, reduced motion, and BCE/CE settings. Record screenshots/device/browser and concrete results in interaction-review. Check text/control contrast and that all insertion slots are reachable with sticky controls present.
- [ ] Ask the owner to complete representative Daily/Freeplay runs without developer assistance. Record wording, motion, framing, and controls feedback; resolve scoring/accessibility/progress-loss blockers before launch rather than adding scope.
- [ ] Run all frontend unit/browser tests, lint/typecheck/build and existing authentication/account/table tests. Expected all pass with no production answers/private artifact URLs in built bundles. Commit UI fixes/tests/evidence: `git commit -m "test: verify complete accessible game journeys"`.
