# Historical Date Game: Board Polish and Three Lives

**Status:** Approved by the owner with “I approve” on 2026-10-15, after the
gameplay-only reset revision at `e2170d6`. Approval covers the presentation,
three-life rules in both modes, reset scope and scoring contract below.
**Baseline:** merged `master` at `da37026618fc848474ba59bb2340c0dc57f04c27`.
**Design branch:** `feature/board-polish-three-lives`, in the stopped guest-play
worktree. The LAN-serving board-redesign checkout remains unchanged.

## Intent

Make the board feel like a readable, usable card game rather than a small strip
inside a blue page. Use the available space, put confirmation where the player
is looking, remove scrolling within cards, and make mistakes educational rather
than ending a new game immediately.

Owner feedback:

- The dominant blue styling is unwanted.
- Too much of the page is unused.
- Confirmation belongs directly beneath the card after dropping it.
- Cards must not contain their own scrolling areas.
- The date and Learn more area has too much whitespace.
- Both Daily and Freeplay should default to three lives.

Approved mistake behavior: a wrong confirmed placement costs one life, resets
the current streak and awards no point. Reveal the answer and correct location;
before continuing, put the card in its correct position. The third mistake ends
the run, preserving the attempted placement for review. Unconfirmed movement is
free. The upgraded game has only the three-life rule; no Classic mode is retained.

## Chosen approach and alternatives

Use the existing actual-card board/navigation and server-owned command path.
Polish their presentation and replace the single-life rule with three lives.
This preserves tested drag, ownership, retry and Daily boundaries.

Do not implement lives only in the browser: refreshes, concurrent tabs and exact
retries would make life consumption unreliable. The owner chose a clean gameplay
reset instead of legacy migration/version coexistence; do not build preservation
or backfill paths for old runs. A replacement multi-row board or new drag library
is unnecessary for this scope.

## 1. Presentation

### Warm, space-efficient board

- Replace the dominant navy/blue play canvas with a warm off-white/stone palette,
  charcoal text, cream cards, and restrained earthy accents. Incorrect/correct
  state must also have text/icons, not depend on red/green alone. Apply this
  consistently to the play shell, navigation, options and results; preserve
  readable controls in either application theme.
- Let the play area use the available viewport width and height. Remove redundant
  instruction/status panels and oversized margins before enlarging cards.
- Use responsive card sizing rather than the existing universal 230px width and
  320px height. On roomy desktop viewports, allocate more space to readable event
  text and artwork, not blank footer padding. Fit the compact desktop target
  without clipping or shrinking text to make a fixed layout fit.
- Keep one chronological horizontal timeline with automatic navigation and its
  miniature overview. Do not require every event to be visible simultaneously.
  A short timeline should form a balanced group rather than a tiny left-aligned
  cluster in an otherwise empty surface; do not stretch two events into giant
  cards just to fill width.
- Size geometry from the actual responsive card dimensions, including the local
  confirmation area. Keep real-tile dragging, subtle grip, animated neighbors,
  fixed confirmed cards and preview re-pickup. No visible numbered slots.

### Confirmation follows the dropped card

- A valid dropped preview gets a clearly visible **✓ Confirm** button immediately
  beneath that actual card, in the same position container. It moves with a
  repositioned preview. Keep a minimum 44px touch target, accessible name and
  visible focus; the check is an action, not a misleading success indicator.
- Use the existing submit action and operation identity. Dropping, navigation,
  focusing or releasing a key never submits. Returning to hand removes the local
  confirmation action. Invalid/outside drops never expose an enabled confirm.
- Remove the distant primary Lock it in button. Keep compact secondary Return to
  hand and recovery actions. Update keyboard instructions consistently. Disable
  confirmation during dragging, submission, reconciliation or mistake review;
  uncertain retries keep the original UUID/body rather than creating a move.
- Reveal/pan the card and its confirm button together. Keyboard users can move
  directly from the dropped tile to its confirm control without a focus trap or
  the viewport hiding the button.

### Cards have no internal scrolling

- No nested scroll area in the card prompt, fallback/image description, year or
  action footer, including focused/dragging states. Remove the current focused
  heading overflow behavior.
- Use a readable bounded excerpt when a prompt cannot fit. Provide an explicit
  full-prompt/details action whenever content is visually truncated; do not use
  a character-count cutoff that misses overflowing shorter text.
- Full pending wording opens in a dialog without revealing the year. Revealed
  details retain explanation, event/source links and accessible attribution.
  Dialogs may scroll for genuinely long content; the cards themselves may not.
- Keep the year and Learn more close to the event wording in a compact footer,
  with normal text spacing and usable hit targets. Do not reserve large empty
  rows or push the footer away with filler space.
- Preserve Credits/Sources and honest labeled Wikipedia source fallbacks. No new
  acquisition, manual curation, invented imagery or article-match claims.

## 2. Three-life state machine

All games start with three lives. Event-order generation stays unchanged; changing
the life rule does not require a new shuffle algorithm.
Show hearts plus an accessible numeric label, for example **Lives: 2 of 3**.

| Accepted confirmation | Lives | Score | Current streak | Timeline and next state |
| --- | --- | --- | --- | --- |
| Correct | Unchanged | +1 | +1 | Insert at the attempted/correct slot; choose the next eligible card, or finish won. |
| Wrong with lives remaining | -1 | Unchanged | Reset to 0 | Reveal attempted/correct positions; insert this revealed card at the correct slot; choose the next eligible card, or finish won if none remain. |
| Wrong using the final life | 0 | Unchanged | Reset to 0 | Finish lost; do not insert this last wrong card into the canonical sorted timeline. Display it at the attempted slot with the separate correct-location marker. |

The anchor is still unscored. A corrected wrong card becomes a fixed, revealed
timeline member, so it cannot be drawn again and participates in existing
minimum-year-gap eligibility. Corrected cards never earn points later. BCE/CE,
inclusive ranges, same-year rules and deterministic eligibility remain unchanged.
Zero lives takes precedence over pool exhaustion: the final-life mistake loses.
Exhausting eligible cards with at least one life wins, even if earlier mistakes
mean the score is lower than the number of revealed non-anchor cards.

### Mistake review before continuing

For a non-final mistake, show the attempted position, revealed year and separate
correct location. Show **Incorrect — 2 lives left** and a local **Continue**
action. While reviewing, do not permit another placement. On Continue, move the
card to the server's already-corrected position, then reveal the next pending
card, or show completion if the server has finished the run.

The correction, counters and next-card selection are one server transaction;
Continue only acknowledges a presentation step. It is not another scored command
or a second server-side correction. Reduced motion skips the movement animation,
not the feedback. Store any review acknowledgement locally keyed by player
context, run and revision, never as an authentication credential. A reload before
acknowledgement can reconstruct review from committed feedback; a newer revision
must supersede an older review. Losing the local acknowledgement can repeat the
explanation but cannot consume another life or replay a new command.

## 3. Persistence, projection and exact recovery

The current code equates streak, timeline growth and successful placements. That
invariant does not hold after a corrected miss and will be replaced, not retained
as a legacy branch. Persist mistakes and correct-placement count alongside the
existing streak/revision. Initial lives is the fixed rule value 3; derive remaining
lives as 3 minus mistakes rather than maintaining contradictory life counters.

Revision equals correct placements plus mistakes. Timeline size
equals one anchor plus accepted placements, excluding the final losing card.
Current streak counts only consecutive correct placements since the latest miss.
Database and engine validation reject impossible counters/status/pending
combinations without supporting a parallel single-life state machine.

Expose allowlisted initial/remaining lives and cumulative score
in current run responses, alongside current streak. Persist enough immutable
feedback to reconstruct the attempted versus correct placement for the latest
miss without revealing future cards. Preserve pre-insertion slot coordinates;
review projection removes the corrected card before reconstructing the attempt,
so neither the card nor the correct-location marker is duplicated or shifted.

Keep owner-bound operation locking, expected revisions and one transaction per
accepted confirmation. One UUID/body can charge at most one life. Duplicate
retries return the recorded result, including its original counters and feedback;
different bodies with the same UUID conflict. Rejected/stale/foreign commands
change no lives, score, streak or revision. Identity switches and insecure-origin
IndexedDB recovery retain their existing protections.

Update public schemas and generated clients together. Old operation snapshots are
discarded by the reset; they do not require field-preservation adapters. Exact
operation replay remains mandatory for every command accepted after the reset.

## 4. Clean reset, Daily fairness and scoring

### What is discarded and what is preserved

- At the controlled local switchover, delete old `GameOperation`, `GameRun` and
  `DailyDefinition` state in dependency order. This removes prior attempts,
  leaderboards, scores, seeds and saved progress. No historical-game backfill,
  Classic label or dual rules engine is needed.
- Preserve historical catalog/source/media files and their database snapshots,
  selected catalog, accounts/passwords, guest credentials, unrelated account data,
  application secrets, repository history and private lifecycle ownership records.
  This is a gameplay reset, not a database/server/filesystem wipe.
- Use a one-off, explicitly scoped reset action against the freshly verified
  local target only. Do not put an unconditional delete/reseed into ordinary
  startup or a general migration. Verify gameplay tables are empty before enabling
  the new constrained state model; fail closed on an unexpected nonempty target.
  No permission to wipe any other test/staging/production database is inferred.
- Initialize the first fresh Daily after the reset with three lives immediately,
  even if an old challenge had existed for the same UTC date. The owner waives
  preservation of those old attempts for this one reset. Once recreated, each
  Daily definition remains immutable and each owner gets one scored attempt per
  UTC Daily. Reloads and retries do not reset an attempt.
- Freeplay also always starts with three lives. Do not add a difficulty/lives
  selector in this change. No public reset endpoint or user-controlled clock is
  introduced.

### Old browser state must not create new actions

Discard or ignore old game recovery records and saved-run pointers using a new
game-specific storage namespace. Leave login credentials and unrelated browser
preferences alone. An old command must not silently become a fresh start because
its operation registry was deleted: require an explicit new game protocol version
on start/placement commands, advertise it in public bootstrap/options metadata,
and reject commands from the old protocol before mutation. Keep that protocol
constant separate from seeded event-order generation; it is a release boundary,
not support for multiple gameplay rules. Show a clear refresh/new-game message
instead of retrying a pre-reset command with a newly generated UUID.

### Score and Daily rankings

Score is total correct confirmations, not timeline length and not the final
streak. Rank Daily results by cumulative score only; equal scores share a rank
with no speed/lives tie-breaker. Show current streak separately. All post-reset
games and Daily results follow the same rule. Exact retries across UTC midnight
still return the originally committed post-reset outcome.

## 5. Verification and safe delivery

Use focused RED/GREEN tests before implementation, then the existing isolated
backend/browser verification pipelines. Required coverage:

- Correct and mixed sequences, first/second/third misses, streak reset, unscored
  correction/anchor, no repeated corrected cards, win after a non-final miss,
  final-life loss precedence, BCE/CE and minimum-gap exhaustion.
- Scoped reset with representative old active/lost/won runs and operations:
  gameplay state removed, catalog/accounts/secrets and unrelated data unchanged;
  nonempty/wrong-target refusal; fresh three-life Daily on the same UTC date.
- New state/schema invariants, shared Daily configuration/ranking, uniqueness,
  midnight retries and rejection of old protocol/storage recovery before mutation.
- Exact duplicate/concurrent confirmations, stale revisions, committed-response
  loss/reload and competing tabs: exactly one life/score/revision change per move.
- Pointer, touch and keyboard preview/re-pickup/confirm; a confirm button beneath
  the actual dropped tile; offscreen reveal; return-to-hand and uncertain retry.
- Non-final review/correction/Continue, reload and identity boundaries; third-miss
  attempted-position result; no leaked pending year or duplicate display card.
- At 1920×900 and 1366×768 CSS pixels, 100% zoom: complete desktop loop without
  page or native timeline scrolling; meaningfully larger readable card area,
  compact footer, and no accidental giant gaps. Check narrow mobile and 200% zoom
  for usable reflow without card-internal scrolling; do not apply the desktop
  no-page-scroll promise to accessibility zoom or small mobile heights.
- Long/short/fallback prompts and missing media, all card focus states, readable
  contrast, focus restoration after dialogs, reduced motion and full attribution.

Do not edit, hot-reload or migrate the running LAN generation while developing.
Develop/test using disposable owned databases only. At delivery, stop only the
freshly verified owned old service pair before the authorized gameplay reset and
schema transition; do not let old and new consumers run against half-upgraded
state. The eventual service switch requires a reviewed lifecycle compatible with
the new schema, exact database/table scope, fresh process/bind/origin proof and
preserved old-generation ownership evidence. Do not reuse old create-only
activation outputs or disable the pinned revision guard to force a start. The
catalog is retained, not reacquired or reseeded. No automatic push/PR/merge,
production deployment or paid service follows from this design.

## Review and next gate

This is the approved combined implementation contract. The next gate is owner
review of the implementation plan and choice of execution method. No application
code, dependencies, schema or running service has been changed by this design work.
