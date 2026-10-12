# Historical Date Game: friends beta design

Date: 2026-10-11
Status: written specification and implementation plan approved; subagent-driven execution authorized.
Scope: product and technical specification only, not authorization to implement.

Amendment approved 2026-10-12: the user requires **no manual content or image
review**. Source publication and media selection use automated checks only.
"Approved" content/assets below means machine-validated, not human-curated or
legally certified. Code review, gameplay tests, and deployment authorization
remain separate requirements. The previous human-curation workload is removed.

## 1. Intent and starting point

Build a fun chronological card-placement game for the owner and friends who
have solid general historical knowledge but do not study history. Players chase
their longest streak, compare a shared daily challenge, and experiment in
Freeplay. The experience should feel like a polished, tactile card game rather
than the administration dashboard of the underlying template.

The repository currently supplies FastAPI, React, PostgreSQL, authentication,
user administration, sample item CRUD, generated API clients, automated tests,
and container/deployment scaffolding. It does not yet implement gameplay or a
historical event catalog. Existing uncommitted stack-modernization work must
be preserved and treated as the development baseline.

### User-confirmed requirements

- Daily and Freeplay modes.
- Insert each new historical event into the chronological order of a growing
  timeline. Its year is hidden until the placement is scored.
- One wrong placement ends the run. Each correct placement adds one to the
  streak; the revealed starting event does not count.
- Win when no more events satisfy that run's settings and spacing constraints.
- One scored daily attempt per account per day, with the same sequence and
  settings for everyone and a simple daily leaderboard.
- Unlimited Freeplay runs, with inclusive beginning/end years and a minimum
  year gap between **every pair of events in the run**, plus a selectable subset
  of event categories.
- Daily uses a fixed, hardcoded selection of categories rather than the entire
  event catalog. All players for a given day share the same random seed,
  frozen event pool, anchor, and sequence.
- No two events from the same year in one run.
- Broad world history: inventions, battles, notable births/deaths, important
  art, and other major milestones.
- **At least 1,000 game-ready events in the initial catalog.** Finding a suitable
  data source is an explicit early task; importing 1,000 raw rows is not enough.
- Drag-and-drop placement and a tactile card-game aesthetic: rich colors,
  layered cards, and playful motion. Touch and keyboard alternatives are required.
- A dropped card previews its position; **Lock it in** submits the guess.
- Prefer a relevant picture for every event. Investigate sourcing feasibility;
  where an appropriate usable picture cannot be obtained, use a representative
  category/event-type image rather than a text-only card. Frame varied images
  consistently for a cohesive look without requiring identical art styles.

### Deliberate beta limits

No real-time multiplayer, friend-group management, chat, achievements,
monetization, user-submitted events, exact day/month difficulty, or live source
lookups during gameplay. No microservices or mandatory new background services.
Sound is optional future polish. Image sourcing and representative fallback
artwork are beta requirements, not optional post-launch polish.
The beta is for friends, not an open public launch; existing user administration
can manage enrollment, with public registration disabled in the beta deployment.

## 2. Content sourcing and publication

Use **automated source-assisted publication**, rather than hand-writing a small
launch catalog or accepting an unchecked import. Small fixtures may support
development, but cannot satisfy the initial 1,000-event requirement.

### Source-discovery deliverable

Compare at least three plausible sources or source combinations. Structured
knowledge bases, openly licensed historical chronologies, and specialist
datasets are candidate families, not preselected or verified sources.
The evaluation must cover:

1. Rights to store, transform, redistribute, and display the data and text;
   attribution requirements and any restrictions on eventual public release.
2. Explicit year precision, reliability, provenance, calendar information,
   conflicting dates, and stable source identifiers.
3. Recognisable events and coverage across categories, eras, and world regions.
4. Export/access feasibility, rate limits, reproducibility, and maintenance cost.
5. Usable event yield after normalization, deduplication, and quality filtering.
6. Distribution of distinct years, not just record count. A thousand events
   concentrated into a handful of years would make range/spacing options weak.
7. Access to relevant event/subject pictures and their separate licensing,
   attribution, adaptation, caching, and redistribution requirements. A reusable
   historical fact does not automatically grant rights to its associated image.

Audit at least 100 representative candidate records across the proposed
categories/eras/regions. Record rejection reasons, dating ambiguity, duplicate
rates, prompt suitability, and difficulty. Produce a source-selection report,
sample normalized records, coverage report, and an evidenced route to at least
1,000 accepted events. If no single source meets the criteria, evaluate a
combination before committing to an importer. Do not fabricate events to fill
a count shortfall.

Include image matching in the representative audit. Report event-specific or
subject-specific image coverage by category, quality, rights suitability,
automated-processing effort, acquisition cost, and the remaining fallback need. The
image source can differ from the historical fact source. Make the feasibility
finding explicit rather than silently substituting icons for all events.

### Event contract

Every published event revision contains a stable event identity, a concise
original or properly licensed prompt, a canonical chronological year, category
and region tags, a short reveal explanation, source references/identifiers,
date precision/provenance, publication/review status, and a reviewed media
reference or representative fallback mapping. Preserve source licensing and
acquisition metadata with the catalog release.

Prefer precise milestones over ambiguous claims: for example, specify a
documented public demonstration instead of an undefined invention date.
Exclude unresolved circa dates, ranges, uncertain years, conflicting claims,
and prospective future milestones from gameplay. Prompts must not state their
answer year or be made misleading by stripping it from a historical name.

Distinct events may share a year in the catalog, but never within a run.
Deduplicate the same historical milestone across sources; birth and death of
the same person remain separate events. Records cannot count toward the
1,000-event launch gate until they are accepted for publication.

### Categories

Use a versioned taxonomy with stable identifiers and player-friendly labels.
Initial groups cover births, deaths, battles/conflict, inventions/discoveries,
literature, visual/performing arts, exploration, and politics/society. Refine
labels and mapping during source review without dropping the user-requested
content types. Distinguish event types when needed for fallback art, such as
birth versus death or a novel versus a painting.

Every published event has at least one category. Events may have multiple
categories, but each historical event is still one event for catalog counts
and run selection. Categories, event revisions, and fallback mappings are
frozen with a catalog release.

### Image sourcing and fallback policy

Attempt to find a relevant, legally usable image for each accepted event.
Prefer the actual work, person, invention, location, or documented event;
a representative picture of the subject need not depict the exact historical
moment. Do not present illustrative imagery as documentary proof.

Use a small, cohesive set of reusable fallback assets when event-specific
imagery is absent, unsuitable, or infeasible to obtain. Examples include a baby
silhouette for a birth and a book for a novel's creation/publication. Maintain
enough category/event-type coverage that every playable event has a meaningful
visual representation. No unlicensed download or invented historical image is
required merely to claim complete picture coverage.

For each image, retain its origin, creator, license/rights basis, required
attribution, adaptation permission, and acquisition/version metadata. Review
relevance, sensitive/graphic content, and answer-revealing dates before use.
Alt text, visible credits, captions, asset URLs, and embedded metadata must not
directly reveal the unanswered year. Required attribution cannot be hidden or
removed to make an image usable: choose another asset or a fallback if the
obligations conflict with that presentation. External historical research is
still outside the friends beta's anti-cheating scope.

Use a shared image window/frame, consistent sizing, borders, spacing, and card
treatment. Source art styles may vary. Preserve important artwork and text
with containment where appropriate; crop/transform only when suitable and
permitted. Supply optimized, versioned assets with answer-safe opaque filenames,
not fragile live hotlinks. Serve retained assets from the existing deployment;
an additional image service is not required for beta. A failed image load must
automatically show the representative fallback without changing game state.

### Reproducible pipeline

Acquisition -> normalized/categorized candidates -> deduplication -> automated
fact/prompt/provenance and media/rights checks -> machine-validated publication
-> versioned published catalog and associated assets. No human approval queue.

Keep rejected/quarantined records and reasons separate from playable content.
Validate every published record and retain traceable source metadata. Conflicting
or uncertain dates and suspected fuzzy duplicates remain quarantined; do not
invent a resolution or require a person to clear the queue. Accept deterministic
source identity/milestone matches only. Generate concise original prompts from
source-backed templates or retain licensed text with its obligations. Automated
audits report source coverage and quality heuristics, not human verification of
truth or recognisability. Reimporting a snapshot must not create duplicates.

Publication requires a versioned validation receipt bound to the candidate and
source digests. Unknown/missing image rights, incompatible adaptation or credits,
unsafe/ambiguous date-bearing imagery, or failed downloads use representative
fallbacks. Automatically check image metadata and conservatively exclude maps,
documents, title pages, plaques, and other text-heavy media unless automated
analysis establishes answer-safe presentation. Do not label the resulting
catalog human-reviewed or legally cleared. Report actual automated acceptance
and picture/fallback yield; no manual pilot or labor budget is a release gate.

Publish immutable catalog releases with a manifest and integrity digest,
including category membership, media references, credits, and fallback mappings.
Corrections create new revisions/releases; they must not change an active run
or already-frozen daily challenge. Keep operational fallback behavior for
unavailable images. The importer and review workflow may be
file/command based for beta; a full content-management UI is not required.

## 3. Year semantics and Freeplay configuration

The UI accepts year magnitudes with an explicit BCE/CE era. There is no
displayed or accepted civil year zero. Internally use a continuous integer
year index: CE year `n` maps to `n`; BCE year `n` maps to `1 - n`.
Thus 1 BCE and 1 CE are one year apart, while 2 BCE and 1 CE are two years apart.
Chronological ordering and gap checks use this index consistently.

Freeplay settings are:

- One or more selected categories. Multiple selections mean the **union**:
  include an event belonging to any selected category, not only events belonging
  to all of them. Deduplicate events matching more than one category.
- Beginning year and end year, inclusive.
- Minimum year gap, an integer of at least 1. Two events are compatible when
  the absolute difference between their year indices is at least this gap.

For example, a gap of 10 permits 1800 and 1810, but not 1800 and 1805.
The check applies against every timeline event, including the starting anchor,
not just the most recently drawn event. Settings cannot change during a run.

Defaults are all published categories, the full catalog's year span, and a
one-year gap. Reject an empty category selection or unknown category identifiers.
Apply category and year-range filtering before choosing an anchor or testing
spacing. Validate ordering, input types/eras, and gap before starting. The
filtered pool must admit at least two compatible published events so that the
player receives a real placement round. Otherwise explain that categories can
be broadened, the range widened, or the gap reduced; do not consume a daily
attempt or award an empty victory.

## 4. Run lifecycle and selection

1. Create a run using a frozen catalog release, settings, an explicit event
   pool, and server-held random seed/ordering. Freeplay's pool is the selected
   category union within its year range. Daily's pool is the union of its fixed
   category allowlist within its fixed settings. Daily uses its frozen shared
   seed/ordering; Freeplay uses a fresh seed/ordering per run.
2. Choose an anchor that has at least one compatible event remaining. Reveal
   the anchor's year and start the streak at zero.
3. Select the first unused eligible event in the ordering and return only its
   unanswered-card fields. Selecting an event is not selecting its position.
4. The player previews an insertion slot by dragging, tapping, or using a
   keyboard, then submits the selected slot with Lock it in.
5. The server computes the correct slot from the frozen answer year. A wrong
   slot marks the run lost and reveals the year and correct position, without
   incrementing the streak.
6. A correct slot inserts the event, reveals its year, and increments the streak.
    Scan the complete remaining **run-specific pool** for another eligible event.
    If one exists, continue; otherwise mark the run won for its configuration.

Skipping one incompatible candidate must not end a run while another eligible
event exists. Previously incompatible events cannot become eligible as the
timeline grows, because range/settings are fixed and gap constraints only grow.
No repeated event or year is permitted. There is no arbitrary round cap.

Exhaustion is relative to the frozen run-specific pool and actual timeline,
not a claim that the player has arranged every historical event or reached an
optimal maximum-length packing for the settings. Different Freeplay draws can produce
different attainable streaks. Freeplay results include the configuration and
catalog version and are not placed into one supposedly fair global leaderboard.

Statuses are active, lost, and won. A network error, invalid request, canceled
drag, or stale browser tab is not a historical mistake and cannot end a run.
Active Freeplay runs may be resumed or left behind when starting another run.

## 5. Daily mode and scores

Use a shared UTC calendar date, displaying the reset timezone/countdown clearly.
Daily uses a fixed category allowlist in code or versioned configuration;
players cannot customize it. The allowlist stays the same across days unless
the author deliberately changes configuration for future games. It is not a
hand-picked list of individual events or a randomly rotating set of categories.
Resolve its category union against the published catalog, deduplicating events
with multiple matching categories, then apply the Daily year/gap settings.
The resulting pool must be a proper subset of the catalog, not an implicit
all-categories/full-catalog default.

Assign **one shared random seed per UTC date**, not one seed per player. A new
date gets a fresh shared seed; players on that date all use the same one.
Freeplay seeds are independent. Freeze the seed, catalog release, category
allowlist, resolved pool, fixed year range/minimum gap, anchor, and candidate
ordering in the daily definition before the first attempt. The initial range
spans the selected Daily pool with a one-year gap; later edits to the categories,
catalog, assets, or settings apply only to future definitions.

A shared seed alone is not sufficient if query ordering or content changes.
Generate from a canonical stable event-identity order, record the generation
version, and persist the resolved order/anchor as well as the seed. Every daily
run references this same definition rather than independently reshuffling its
own database result. The selection rules yield the same next event for every
correct-play prefix, regardless of account, start time, or server restart.
Create the definition atomically if absent; the date has one definition even
under concurrent requests. Keep seeds and future ordering server-side.

Validate that the Daily pool is an actual restricted pool with a playable pair
before allocating attempts. Missing, invalid, or too-small configuration is a
service error; never silently expand it to the full catalog. Daily victory
means exhausting eligible events in this frozen Daily pool, even if eligible
events remain elsewhere in the global catalog. The exact subset selection
policy is the fixed category allowlist described above. Choose and record its
initial category identifiers during source/coverage review, before implementing
Daily; do not infer them from Freeplay's all-category defaults.

The database enforces one daily run per `(account, daily definition)`.
Previewing the daily page does not consume it; confirming Start Daily creates
the resumable attempt. Loss, victory, or leaving the page cannot create a retry.
Concurrent starts return the same attempt rather than allocating another.

Runs belong to the day they started. A started run can finish after UTC midnight
and still belongs to that original leaderboard; a new day allows its own new
attempt. Catalog edits and application restarts cannot change old definitions
or run answers. There is no attempt-reset or daily replay feature in beta.

Daily leaderboards show completed attempts, display names, streak, and win/loss,
not email addresses or unrevealed event lists. Higher streak ranks first;
equal streaks share rank, with no time-based tiebreaker. Rankings update when a
run completes. Freeplay shows the completed run's result and settings; it does
not affect daily rank or require a separate statistics/history dashboard.

## 6. Architecture, persistence, and API boundaries

Keep the existing FastAPI/React/PostgreSQL application and generated API-client
workflow. Add focused gameplay modules rather than reusing generic sample
items as historical events or rewriting authentication. The player-facing
navigation is game-first; retain account settings and authorized user admin.

| Unit | Responsibility | Dependencies |
| --- | --- | --- |
| Content pipeline | Source acquisition, categorization, normalization, review, release manifests | Chosen sources and event contract |
| Media pipeline | Match images, verify rights, optimize/version assets, assign fallbacks | Content identities, image sources, retained asset storage |
| Catalog repository | Store/query immutable playable event revisions | PostgreSQL |
| Rule engine | Run-pool membership, eligibility, year gaps, ordering, streaks, and exhaustion | Plain event/year inputs; no HTTP or UI |
| Run service | Own state, random ordering, moves, transactions, resume | Rules, catalog, authenticated account |
| Daily service | Resolve fixed categories, freeze shared seeded definitions, enforce attempts, rank results | Catalog, run service, UTC date, database |
| Game API | Authorized start/read/place/result operations | Run/daily services |
| Card-game UI | Presentation, insertion preview, accessible controls, feedback | Public run DTOs and generated API client |

Conceptual stored entities: catalog release, category, historical event
revision, reviewed media asset, daily definition, game run, and accepted
placement/move. Runs record their owner, mode, settings (including selected
categories), frozen pool membership, catalog/daily identity, status, streak,
state revision, pending event, server-held seed/order, generation version,
timestamps, and move history. Public DTOs are separate from answer-bearing
persistence models.

The API supports discovering modes/categories/catalog bounds, starting runs,
resuming an owned run, submitting a placement, reading results, and reading a
daily leaderboard. Placement submits a run identifier, expected state revision,
pending event identifier, insertion slot, and client-generated operation ID.
It does not submit a year or trusted score.

Commit validation, move record, next event, streak, and status together.
Serialize updates to a run and enforce daily uniqueness in the database.
Repeated identical operation IDs return the recorded outcome without scoring
twice; reuse with different input is rejected. Stale/new competing operations
return a state conflict and allow the UI to refetch authoritative state.

Only run owners can submit/read private run state. Do not send pending or future
answer years, random seeds, future sequence/pool membership, historical answer-source links,
or reveal explanations in active unanswered-card responses or frontend bundles.
Unanswered cards may include the current event's approved image/fallback,
answer-safe alt text, and legally required media attribution. Keep image rights
obligations distinct from answer-bearing historical citations. Reveal the
just-scored event's details after scoring; do not return the unused answer pool
on completion.
Looking up history elsewhere or operating multiple accounts is outside the
anti-cheating scope of a friends beta.

## 7. Tactile interaction and visual personality

Use rich colors, high-contrast text, layered cards, soft elevation, and clear
category accents. Gameplay should not inherit the template's CRUD-table feel.
Only the pending event card is movable; already-scored cards remain ordered.
All cards use a consistent framed image area with event/subject imagery when
available and representative fallback art otherwise. Images complement the
readable event description; neither drag feedback nor card layout should depend
on successful image loading. Provide unobtrusive but compliant media credits.

During a drag, lift the card, highlight available insertion slots without
hinting which is correct, and smoothly preview neighboring-card movement.
Dropping selects a tentative slot. Players can reposition or cancel it until
they press Lock it in. Disable submission while awaiting the server.

On confirmed success, snap the card into the timeline, reveal its year, and
celebrate the streak with short, nonblocking animation. On a mistake, reveal
the correct slot and explain the event; on exhaustion, show a distinct victory
celebration and the winning configuration. Never play success effects solely
because a local preview looked plausible.

Desktop uses a scrollable horizontal timeline; narrow screens use a vertical
layout with generous touch targets. Keep the pending card and confirmation
controls readily accessible. Support edge auto-scroll during dragging and
efficient first/last-slot navigation so long runs remain playable.

Provide an equivalent tap/select-slot flow and keyboard navigation/confirmation.
Maintain visible focus, announce placement/results to assistive technology,
and never rely on color or dragging alone. Reduced-motion preferences remove
decorative motion while preserving all information and controls. Outside drops
cancel safely; canceled or accidental drops never consume a guess.

## 8. Error handling and operations

- Preserve the current card and selected preview after ordinary network errors.
  A timeout may hide a committed move: retry using the same operation ID or
  refetch before allowing another submission.
- Resume authoritative server state after reload, reconnect, or login renewal.
  Local previews need not survive a full reload; scored progress must survive.
- Explain invalid/sparse category/range/gap configurations before allocating
  a run. An unavailable catalog or invalid daily definition is a service error,
  never a player loss.
- Keep unsupported/unpublished content out of selection. Report suspected
  content issues through a feedback link/form carrying event/run identifiers.
- Retain media with its source/rights metadata; invalid or unavailable images
  fall back safely. Image fetching is not part of the scoring transaction.
- Deploy a single small production host with the existing container/proxy
  arrangement and persistent PostgreSQL. Host/provider/domain selection is an
  implementation-planning task; provision nothing during specification work.
- Require HTTPS, nondefault production secrets, correct origin settings,
  authorization boundaries, restricted registration, and local-only private
  test endpoints. Do not publicly expose database/admin/proxy-management tools.
- Schedule daily database backups with at least seven retained restore points;
  retain catalog release artifacts and associated media assets/rights metadata,
  and verify a restore before launch.
- Capture sanitized errors and service health, with no passwords/tokens or
  unnecessary personal data in logs. Document deploy, migration, restore, and
  rollback procedures; verify persisted runs survive a deploy/restart.

## 9. Verification and beta release gates

### Automated checks

- Rule tests: category-union filtering, multi-category deduplication, empty/unknown
  category rejection, restricted Daily pool membership, inclusive range bounds,
  minimum-gap equality, all-pairs spacing,
  same-year exclusion, BCE/CE transitions, anchor viability, correct/incorrect
  slots, streak counting, and exhaustive eligibility scanning.
- Invariant tests: every generated run respects pool/category/range/gap/uniqueness;
  wrong moves never increment a streak; victory implies no eligible unused event
  in the run's pool, regardless of eligible events elsewhere in the catalog.
- API/database tests: ownership, hidden answers, terminal-run immutability,
  resume, atomic moves, concurrent/idempotent starts and placements, invalid
  configurations, frozen catalogs, UTC rollover, and tied ranks.
- Daily reproducibility tests: different accounts share the same seed, anchor,
  and event sequence for a given date; a new date gets a fresh seed. Database
  row-order variation, a catalog/configuration update during the day, and a
  server restart must not change the existing day's definition. Assert that
  every Daily event belongs to the fixed allowed categories, and seeds/future
  ordering never appear in player-facing responses.
- Content tests: repeatable imports, deduplication, quarantine behavior,
  provenance completeness, category validity, publication checks, and release
  integrity/count. Media tests cover rights metadata, image/fallback coverage,
  safe filenames/alt text, asset failure fallback, and frozen media references.
- Browser tests: Daily and Freeplay, drag/preview/reposition/confirm, outside-drop
  cancellation, touch alternative, keyboard-only play, reduced motion,
  mistake/victory reveals, long-timeline navigation, and recovery after reload
  or a simulated connection failure. Include category selection, consistent
  image framing, representative imagery, failed/slow image loading, and media
  attribution without a visible answer-year leak.
- Preserve the existing authentication/account tests, full type checking, lint,
  builds, generated-client reproducibility, and container checks.

### Required before inviting beta players

1. A documented source decision and **at least 1,000 accepted, sourced,
   deduplicated, game-ready events** in a published release. Produce era,
   region, category, and distinct-year coverage reports and review imbalances.
   Include an image-source feasibility/coverage report and reviewed, reusable
   fallback assets: every playable event must render meaningful imagery, with
   event-specific pictures preferred and documented reasons for fallback use.
2. All required automated checks pass with no known scoring/fairness or answer
   exposure defect. Both modes can win and lose through the specified rules.
3. Desktop and touch-device play are checked manually; a 100-card timeline
   remains navigable and allows placement at every slot without layout failure.
   Verify category-based Freeplay and restricted-pool Daily, coherent image
   framing, compliant credits, and image-load fallback on real layouts.
4. HTTPS deployment works with real beta accounts; backups restore successfully,
   errors can be diagnosed, and reload/restart preserves active runs.
5. The owner can play complete representative runs without developer assistance,
   and feedback instructions are accessible from gameplay/results.

### Friends trial and learning criteria

Run a one-week friends-only trial before considering a broader release. Seek
feedback from at least three players on recognisability, ambiguous wording,
range/gap usefulness, tactile controls, and whether they voluntarily replay
Freeplay or return for another daily challenge. This is a usability/difficulty
learning target, not a promised retention rate or a calendar delivery estimate.
Resolve reported scoring/progress-loss defects before widening access; review
content and interaction friction rather than immediately adding new modes.

## 10. Milestone outline and decision ownership

This is the design's release sequence, not the task-by-task execution plan.

| Milestone | Exit evidence |
| --- | --- |
| Source feasibility and contracts | Fact/image-source comparison, sample audit, taxonomy/event/media contracts, evidenced route to 1,000 accepted events |
| Content pipeline and core rules | Reproducible catalog/media releases, fallback assets, and tested category/pool/chronology/eligibility/run rules |
| Playable tactile Freeplay | Category/range/gap controls, framed imagery, drag/confirm, accessible alternatives, both outcomes, and resume |
| Shared Daily and scoring | Fixed-category restricted pools, shared per-day seeds/frozen sequences, one-attempt enforcement, leaderboard, and concurrency tests |
| Beta preparation | Published 1,000-event catalog, image/fallback coverage, polished UI, verified deployment/backup, release checklist |
| Friends trial | Collected feedback and prioritized fixes before any wider launch |

Source discovery is an early feasibility gate, not a last-minute seed-data task.
Once the event contract is agreed, engine/UI development can use fixtures while
the full catalog is assembled. No beta milestone may redefine 1,000 candidates
or a small fixture as the required initial playable catalog.

Fact/image source selection, importer/media-pipeline details, stable drag-and-drop
tooling, hosting selection/cost, exact visual tokens, and concrete file/API task
breakdowns are explicit implementation-planning deliverables. They are not
silently decided by this document. Use current stable tooling where compatible, follow existing
repository conventions, and do not implement, provision, merge, or push until
the user reviews the written specification and subsequent execution plan.
