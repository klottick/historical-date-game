# Beta gameplay interaction review

**2026-10-12 — automated portion verified; full U4 remains open.** Physical touch-device/browser checks, screen-reader speech, and owner unassisted play were unavailable to this agent. No genuine-player feedback or hardware verification is claimed. Removing manual content/image curation did **not** remove these gameplay checks.

## Verified scope

- **Real authenticated backend scoring:** selected-category Freeplay union, inclusive 1800–1880 CE bounds, gaps 10 and 70, actual pool-exhaustion wins, deliberate loss, leave/resume/reload, and new runs. A 1 BCE–1880 CE configuration also wins on the synthetic backend; civil year zero and reversed BCE bounds are rejected by the UI.
- **Real Daily:** two fresh isolated accounts receive the same anchor and every pending card through a correct prefix and server-confirmed exhaustion. Both complete with streak 5 and equal leaderboard rank. UTC date/reset labels, display names, completed-only results, owned-run privacy, same-attempt restart, and rejection of further scoring after completion are checked.
- **Errors:** real sparse-selection 422 creates no run/loss. An intercepted public catalog-options 503 disables starting and never becomes a loss. Existing uncertain-command/exact-retry/fresh-hydration tests remain green.
- **Layout only:** `frontend/tests/fixtures/game-public.ts` supplies 100 synthetic revealed public cards, spanning 50 BCE through 50 CE without year zero, plus an unanswered card with no year/citations. No long-run engine or production catalog coverage is inferred from this fixture. Real scoring uses the retained eight-event C5-verified synthetic fixture, not the layout DTO.

## Browser and visual evidence

Linux Playwright 1.64.0 / Chromium **156.0.8078.4**:

| Project | CSS viewport | Boundary | 101 insertion slots |
| --- | --- | --- | --- |
| `chromium` | 1280×720 | Automated desktop browser | Minimum 72×439.33 px |
| `game-mobile` | 393×727 | Pixel 5 touch emulation, DPR 2.75; **not a physical phone** | Minimum 319×44 px |

Every slot was individually scrolled into view, focused and selected with Enter; mobile slots were also tapped. All 101 centers passed viewport hit-testing. Native keyboard drag visited every ordinal gap after allowing the delayed scroll update to settle; dropping only previewed. Desktop pointer edge scrolling and mobile CDP touch hold/edge scrolling worked, including a pointer/touch placement **after** keyboard drag. No layout-fixture placement POST occurred. All placement controls remained reachable and at least 44 px high; no body horizontal overflow.

The current pending panel and gameplay navigation are **nonsticky**. Controls remain in document flow and may require scrolling, especially on mobile; no sticky-control design or simultaneous visibility of far-away gaps and controls is claimed. Slot hit-testing checks actual overlays present in this layout.

Slow primary images were held, then both image URLs failed. Placeholder, credits, target geometry and revision remained intact. Reduced-motion styling and civil BCE/CE labels remained available. Pending credit captions did not overlap their title/drag controls.

Private screenshots and measurements are retained under `.superpowers/sdd/2026-10-11-historical-date-game-beta/artifacts/`:

- `U4-100-{1,51,101}-{chromium,game-mobile}.png`: first/middle/last insertion views; desktop images 1280×720, mobile 1081×1999 image pixels.
- `U4-100-full-chromium.png`: 1280×1217 desktop overview.
- `U4-focus-{light,dark}-{chromium,game-mobile}.png`: keyboard focus with real mounted artwork.
- `U4-100-layout-*.json`, `U4-contrast-*.json`, `U4-settings-contrast-*.json`, `U4-evidence-summary.json`: per-slot hit tests, browser version and computed measurements.

The agent opened desktop overview/middle/last, mobile first/middle/last, and desktop/mobile focus screenshots. Titles, attribution, year labels and focus bands wrap coherently. Development devtools badges remain visible and can obscure a small lower-right credit corner in these screenshots; they were not hidden to manufacture clean evidence. Clean production presentation and other browser engines are not certified here.

## Evidence-driven fixes and contrast

1. Amber focus against cream measured **1.298:1**. A 3 px navy outline plus outer cream band now provides **13.673:1** against cream controls and dark table surfaces. Keyboard-visible focus is asserted in light/dark themes.
2. Victory incorrectly listed all catalog categories. It now lists only the frozen configuration's selected categories.
3. The long mobile keyboard journey exposed dnd-kit 0.5.0's delayed scroll collision pass clearing the ordinal target. The keyboard sensor now suspends geometric collision selection for that ordinal operation and restores it on cleanup; pointer/touch behavior is regression-tested afterward.

Actual computed sRGB text contrast: card headings/categories/credits and enabled Lock text **13.673:1**; hidden/revealed year text **6.863:1**; coupled year/era/gap labels and readonly Daily category labels **19.798:1 light / 17.176:1 dark**. Form hints, reset labels and shortcut text also pass 4.5:1 assertions. Disabled controls are not counted as enabled-control contrast evidence.

## Verification

From `frontend`, with Node 26.11.1 available on PATH and the existing synthetic backend on port 8000:

```sh
npx playwright test tests/game-journeys.spec.ts --project=chromium --project=game-mobile --workers=2 --reporter=line
npm test -- --workers=2 --reporter=line
npm run test:unit
npm run typecheck
npm run lint
npm run build
npm audit --audit-level=low
```

- Final journey run: **13 passed** (12 journey/project cases plus auth setup).
- Final full browser suite, including unchanged signup/reset/account/table tests: **111 passed / 0 failed**, repeated after restoring open local enrollment.
- Separate sequential real closed-enrollment run: **3 passed**; unauthenticated signup API returned 403. Checked-in production policy was unchanged.
- Units **19 passed**; typecheck, lint (94 files), build and audit passed; **0 vulnerabilities**. Emitted-bundle pattern scan found no synthetic test answers/layout fixtures or private catalog artifact URLs/answer fields.
- Inherited Vite SWC recommendation and router export/code-splitting warnings remain recorded, not suppressed.

## Outstanding manual gates — controller/owner follow-up

- [ ] **Real touch hardware:** record device/model, OS, browser/version and orientation. On a private test-only 100-card public DTO harness (or a genuine sufficiently long run), exercise first/middle/last placement, hold/drag, outside-drop, edge scrolling, taps, return to Lock controls, cancellation and explicit commit. Do not activate arbitrary catalogs or bundle fixture answers to arrange this check.
- [ ] **Physical browser/accessibility:** repeat with reduced motion, slow/failed imagery and credits, zoom/large text, keyboard-only navigation and a screen reader. Listen to spoken slot/preview/result announcements; browser accessibility trees/CDP touch are not substitutes for speech or hardware. Check controls/credits for obstruction in the actual production presentation.
- [ ] **Owner unassisted play:** controller arranges representative Daily and Freeplay runs, then observes without giving placement or control instructions. Record the owner's actual wording about rules, framing, motion, gaps, Lock, mistakes, victory and resuming. Record difficulty/confusion, unexpected scoring or lost progress; do not invent feedback. Verify completed Daily cannot replay and Freeplay can start anew.
- [ ] Resolve any scoring, accessibility or progress-loss blocker found above before launch. Attach real-device screenshots/results and genuine owner feedback here; only then can full U4 close.

No owner invitation or new approval question was issued by this subagent; the controller owns that follow-up.
