# Historical Date Game: Compact, Card-First Board

**Status:** Written spec approved by the owner with "approve" on 2026-10-14.
**Baseline:** `6240352`, `feature/guest-play`.

## Intent and approved decisions

The owner wants a full playable sequence at 100% browser zoom without scrolling
the page or manually scrolling the timeline. Their screen is 1080p. Cards must
remain readable, dragging must feel like moving the actual tile, and loss must
show the mistake in its attempted position rather than as a disconnected result.

The owner selected **A, the miniature event timeline**, over the era ribbon.
Not every event needs to be visible simultaneously: automatic navigation and a
graphic overview replace a visible scrollbar. They approved:

- Actual-card dragging, a subtle grip, animated insertion, and no numbered slots
  or separate pickup button.
- An unlocked dropped preview that can be picked up or returned to the hand;
  explicit **Lock it in** remains the only scoring action.
- Confirmed cards remain fixed.
- Wrong cards stay in the attempted position, reveal their year, and have both a
  contrasting outline and a textual **Wrong** marker. Show the correct location
  without automatically relocating the wrong card.
- A compact loss view with visible replay/navigation controls.
- No repeated copyright or chronology/category heuristics on tiles; required
  attribution remains accessible through **Credits/Sources**.
- **Learn more** for revealed cards, with automatically verified event-specific
  Wikipedia links. Unmatched events use explicitly labeled source-page links;
  never fabricate an article URL or claim that a calendar page is the article.

These approvals permit this spec, not implementation or publication.

## Scope and invariants

Change the game board, card presentation, insertion/navigation behavior, result
presentation, and the public metadata needed to support them. Extend feedback
to retain attempted placement. Automatically resolve supplemental article links
without human curation or changing historical answers.

Preserve guest/account ownership, session boundaries, uncertainty recovery,
operation UUID replay, frozen run configuration/catalog, UTC Daily uniqueness,
shared Daily sequence, unscored anchor, streak rules, and inclusive BCE/CE year
semantics. No scoring on drag, hover, drop, navigation, or animation completion.

Excluded: new game modes, manually curated content/images/links, catalog coverage
expansion, guessed historical explanations, moving already-confirmed cards,
guest/account merging, paid services, deployment, invitations, and branch
push/merge. This is not a production-security or physical-device certification.

## Viewport-sized layout

- Treat 1920×1080 as screen resolution, not guaranteed browser content height.
  Verify the complete game loop at a 1920×900 CSS-pixel viewport and 100% zoom,
  allowing space for ordinary browser chrome. Also verify a compact 1366×768
  viewport; do not require fullscreen or zoom reduction.
- Use a bounded play surface: compact header/streak, readable timeline, one
  pending-card hand area or inserted preview, miniature overview, and persistent
  action/result area. Remove tall repeated guidance, status panels, and details
  from the main play flow rather than hiding essential controls with overflow.
- Start, preview, submission, correct feedback, next card, loss, and a subsequent
  Freeplay run require no page scrolling at those desktop viewports. Optional
  long-form Credits/Sources or Learn more content may scroll inside an accessible
  dialog; closing it returns to the same board without changing placement.
- Cards retain a readable title, image/fallback, and revealed year. Long prompts
  have a bounded presentation with full text available on focus or in details;
  they must not expand the board indefinitely or make events indistinguishable.
- Smaller screens use a responsive window of fewer readable cards. Preserve
  controls and accessibility rather than shrinking all text to force a fit.

## Dragging, placement and navigation

The actual pending card is the draggable surface. Its grip is a visual cue, not
the only pointer target and not a separate pickup control. Interactive links or
detail controls must not accidentally start dragging. Touch activation must
distinguish a tap from a drag without allowing the page to pan while dragging.

Insertion uses card geometry and pointer position, not visible gap buttons.
Every boundary from before the first confirmed event through after the last is
reachable. Neighboring cards make room for an in-timeline preview. Internal
indices may remain zero-based; no numbered slot labels appear in ordinary play.

Near a visible edge, the timeline pans automatically with bounded speed until
the desired area is visible or the sequence end is reached. Navigation stops
when dragging ends/cancels, focus leaves the operation, or the session changes.
Panning must keep the drag target and preview coherent as geometry changes.
Do not require the player to release the card to navigate or manipulate a
scrollbar. Once a move is confirmed, bring the new placement and next-card hand
into a useful view without jumping the page.

The miniature overview represents the whole confirmed sequence using event
marks and a highlighted visible range. It includes an unlocked-preview marker
when appropriate. For long sequences, aggregate marks rather than drawing
unreadably tiny controls. It represents positions, not the hidden pending year.
Accessible optional overview navigation may supplement automatic panning.

Dropping creates an unlocked preview, not an HTTP scoring request. The preview
can be picked up again, repositioned, or returned to the hand. Dropping outside
the board or canceling restores the prior unlocked state without losing the
card. Confirmed events never become movable. **Lock it in** is disabled until a
valid preview exists and while a submitted command remains unresolved.

Use short, restrained neighbor movement, pickup/drop settling, and confirmation
animations. The next card appears only when the authoritative response permits
it. Honor reduced motion; animation completion must not determine game state.

Keyboard users focus the same card, use Space/Enter to pick up, arrow keys to
change the insertion position, Space/Enter to drop, and Escape to cancel. Focus
and relevant position announcements follow automatic navigation. Locking stays
an explicit separate action. Do not add a visible pickup button for keyboard use.

## Submission, recovery and loss

Keep the existing captured-identity API and recovery state machine separate from
visual drag/navigation state. Only Lock it in creates/persists the placement
command and sends it. Once submitted, its UUID, event, revision and slot remain
unchanged through transport failure or retry. Freeze interaction during pending
or uncertain submission; a timeout/session error is not a wrong historical move.

Extend `MoveFeedback` with `attempted_slot: int | None`. New placements record
the submitted slot alongside the existing correct slot/card/outcome in the
same transactional operation snapshot. Owned run reads and operation replays
expose this persisted feedback. The client must not reconstruct attempted
placement from a transient local drag position, the correct slot, or today's
catalog. Existing operation snapshots accept a missing field as `None`; do not
rewrite their original outcomes or pretend their missing attempted slot is known.

For a new loss, compose a display-only timeline that inserts the revealed wrong
card at `attempted_slot` among the confirmed cards. The scored run timeline stays
unchanged. Automatically center the wrong card, mark it with outline/icon/text,
and indicate the correct boundary in the board/overview. Do not silently sort
the mistake into the correct chronology. Show the streak and applicable Freeplay
or Daily navigation in the compact result area, not in a second long page.

If an older lost run lacks attempted position, show its revealed wrong card in a
clearly labeled result area and state that the old placement position is
unavailable; never invent a location. Server replay/reload must preserve the new
loss view, including after backend restart. Identity changes cancel dragging and
discard only transient previews, never unresolved commands belonging to an owner.

## Card details, article links and attribution

The tile itself contains no repeated license paragraphs or technical chronology
and category-heuristic notes. Revealed cards have a concise Learn more control;
pending cards do not expose their year, explanation, article metadata or answer
through details, the miniature overview, drag data, or browser fixtures.

Credits/Sources opens an accessible dialog that preserves required text/image
creator attribution, license links, dataset/Wikipedia lineage and fallback-art
credits. Deduplicate common notices while retaining event/asset associations.
Per-event details distinguish a Wikipedia article from a calendar source page
and from dataset provenance. Technical notes belong under source/provenance
details, not in the primary event summary or ordinary move feedback.

Link resolution is a bounded, automatic content-enrichment step, not a network
request made while dragging or scoring:

1. Reuse a verified event-specific Wikipedia article already present in retained
   sources when available.
2. For calendar-page sources, consider actual linked articles from the
   corresponding event entry. Require an unambiguous match to the retained event
   wording/context and record the source and resolved canonical article.
3. Missing, ambiguous, unrelated, unavailable, or unsafe candidates remain
   unresolved and use the approved source-page fallback. No search-result guess,
   invented slug, manual-review queue, or universal-coverage claim.

Keep cached evidence/link metadata keyed to the selected catalog release and
event, with deterministic validation and measured matched/unmatched counts.
Never overwrite sealed catalog/media bytes or change event IDs, dates, prompts,
category assignments or selection. Store supplemental metadata separately from
the sealed artifacts; absent enrichment must not break existing runs. Only
validated Wikipedia article URLs reach the revealed-card projection; preserve
ordinary source URLs and existing exact recorded operation outcomes.

## Component boundaries

- **Board orchestration:** existing authoritative run/session/recovery state and
  explicit submission; does not own collision geometry or source matching.
- **Insertion/navigation controller:** visible window, pointer/keyboard target,
  edge panning and overview projection; emits only an unlocked insertion index.
- **Card/timeline presentation:** compact cards, in-timeline preview, animation
  and display-only wrong-card insertion. It cannot mutate confirmed run state.
- **Details/credits presentation:** on-demand, accessible attribution and links;
  it does not resize the board or reveal pending metadata.
- **Feedback projection:** persisted attempted/correct positions and revealed
  outcome, maintaining existing owner and revision filtering.
- **Article resolver/projection:** cached automatic evidence validation and safe,
  release/event-bound revealed links; no synchronous dependency in gameplay.

Keep these responsibilities independently testable. Regenerate public SDK types
through the existing workflow when schemas change, rather than hand-editing them.

## Verification and delivery gates

The reported slot-2 drag failure is not yet diagnosed. Reproduce it on the old
interaction using pointer/geometry evidence before attributing its cause. Carry
the reproducer forward as a regression; a redesign alone is not proof of a fix.

Required verification:

- Test every insertion boundary, especially displayed slot 2 in the old UI and
  its equivalent index in the new UI, with actual-card pointer dragging,
  preview pickup/reposition, panning, first/last positions and keyboard movement.
- Verify start → preview → lock → correct → next card → wrong → result → new
  Freeplay sequence without document scrolling at both desktop viewport targets.
  Include long sequences and long prompts; controls remain visible and readable.
- Test no scoring until lock, one submission, unchanged saved UUID/body on lost
  response, session failure and identity switch; retain private-answer guards.
- Test wrong-card attempted placement versus correct placement after owned read,
  exact replay, reload and restart, plus honest legacy missing-slot behavior.
- Test article/source distinction, safe canonical URL validation, ambiguous and
  missing matches, unavailable network/cache behavior, release/event association,
  and no pending-answer/article disclosure. Report resolution coverage honestly.
- Verify full required attribution remains accessible and associated with assets
  after removing inline credits; test image fallback and dialog keyboard focus.
- Verify reduced-motion behavior, cleanup of panning, and real browser pointer
  interaction without broad retries or weakened assertions to hide instability.
- Run backend, frontend unit/type/lint/build and applicable fixture/real-catalog
  browser suites against explicitly owned disposable databases and processes.
  Never use destructive test cleanup against the running real-game database.

Implementation planning must isolate unfinished UI changes from the current
LAN-served guest-play worktree. Activation is a later guarded local step: inspect
process ownership, apply only necessary additive changes, retain the existing
release, then verify fresh no-login LAN play. Keep API loopback/proxy arrangement,
private-file denies, cookie security and administration protection intact. The
owner waived old-data backup/preservation machinery, not these safety boundaries.

Written-spec approval is required before writing the implementation plan; the
plan then requires owner review and an execution-method choice before coding.
