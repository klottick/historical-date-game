# Three-life gameplay and responsive board

## Rules and compatibility

Daily and Freeplay both start with three lives. A correct confirmation adds one
point and one to the current streak. A wrong confirmation spends one life, resets
the streak, and does not score. The first two mistakes reveal the attempted and
correct positions and can be continued locally; that Continue action is not a
second server command. The third mistake ends the run as lost and shows the final
wrong card at the attempted position. A run that exhausts its eligible pool with
at least one life wins. The anchor and corrected cards never score. Daily ranking
uses cumulative correct confirmations; streak is shown separately.

Cards have no internal vertical scroll area. Confirmation is local to a valid
dropped preview, does not happen on drop/navigation/focus/key release, has an
accessible name and visible focus, and meets the 44px target. Long prompt text is
available through details without exposing the pending year. Dialogs may scroll.

The current game protocol is version 2. Old/missing-protocol starts and placements
are rejected before mutation; old recovery records are not adopted as new actions.
Users with an old client must refresh and explicitly start a new game. Existing
account credentials and unrelated browser preferences are not part of this reset.

## Reset and retained data

The planned one-time local gameplay reset is limited to `gameoperation`,
`gamerun`, and `dailydefinition`, in dependency order. It discards prior attempts,
progress, scores, seeds, and Daily attempts. It must retain catalog releases,
source/event/media snapshots and files, selected catalog, accounts and passwords,
guest credentials, unrelated account data, secrets, and lifecycle ownership
evidence. It is not a general database wipe, migration side effect, or public API.

The scoped safety proof used only the exact owned
`historical_date_game_lives_migration_test` database. The completed local reset was
limited to `gameoperation` (473 rows), `gamerun` (162), and `dailydefinition` (8),
then migrated schema `20261013_01` to `20261015_01`. All eight retained-table
baselines and 585 source/runtime/sidecar file hashes were preserved. No catalog,
account, password, guest credential, source, media, or unrelated data was reset.
The reset is complete; **do not repeat it**.

The targeted LAN browser proof passed once and retained three disposable guest
contexts/runs. It left `gameoperation=8`, `gamerun=3`, `dailydefinition=1` after
proving Freeplay loss/Continue/replay and a fresh Daily. A subsequent homepage smoke
created five more guest sessions (four unsuccessful selector/assertion attempts and
one successful check); all five remain, have no owned runs, and were not cleaned up.
Current guest/session totals are 23 (18 at relaunch, plus those five). Gameplay is
still exactly 8 operations / 3 runs / 1 Daily definition, and the original retained
rows other than those eight disposable guest/session additions match baseline.
All 585 source/runtime/sidecar hashes still match. There was no cleanup.

The running product source was reviewed, tested, and activated at `00ee58e` (full
source commit `00ee58e95d710e6f5c132fba0d21de6dea470d0b`). Follow-up commit
`6079772` changes tests only; it fixes a test-only OS-boundary leak and does not
change the product code or the already-running service runtime. This documentation
update is separate again and does not alter the tested/activated source. No
production, accessibility-certification, screen-reader, or physical-device claim is
made.

Historical rollout issues were handled without weakening guards: the first CLI
`apply` invocation was a read-only no-op and made no reset; after its reviewed fix,
the single actual reset completed but its post-migration check exposed a pooled
connection issue. A reviewed verification-only recovery recorded the migration
proof without changing the original reset receipt. The initial delivery generation
was stopped after the browser proof; the reviewed relaunch below restored local
availability without another reset or migration. These are resolved historical
phases, not a current service outage.

The guarded relaunch from the immutable original proof is complete. Its parent is
`/tmp/opencode/three-life-local-20261015T150302Z-task7`; the current child is
`/tmp/opencode/three-life-local-relaunch-20261015T164639Z-2460503`. The owned
services are intentionally **left running** at `http://localhost:5174` and
`http://192.168.1.214:5174`; API binds to `127.0.0.1:8010`. The exact API/UI
identities were independently verified against `/proc` (including argv, cwd,
start ticks) and listener ownership: API PID `2460603` / start ticks `22292738`,
UI PID `2460614` / start ticks `22292787`. Both local health endpoints and the LAN
page returned HTTP 200. The targeted LAN browser smoke passed once: homepage and
options endpoint, protocol 2/pinned release, and a rendered 1920x900 page with no
viewport overflow. Its screenshot and private summary are in the child-adjacent
`/tmp/opencode/three-life-local-relaunch-20261015T164639Z-2460503-lan-proof/`.
The earlier full LAN gameplay proof passed once and its five screenshots and
summary remain under the original parent evidence's `step6/` directory.
An earlier managed-browser attempt could not start Chromium because its sandbox was
unavailable; the project Playwright CLI provided the successful proof.

The relaunch command is for the exact retained original parent proof, not a generic
child-to-child restart protocol. If this current generation is intentionally
stopped, use its child evidence for the ownership-checked stop below. A later
reviewed relaunch must use a fresh unique child evidence directory and the original
parent path above; do not pass the child as its own parent. The helper does not
reset, migrate, seed, or clean guest/gameplay rows during relaunch.

The Step 6 binding covers the exact retained proof tree: summary, package, Playwright
config/spec, results record, and all five summary-listed screenshots. Every proof
file is checked for owner, private mode, regular-file identity, and single-link
status, SHA-256-bound into the child receipt, and compared again after preflight.
Unexpected/missing entries, aliases, or changes during validation refuse before
child creation. The retained `node_modules` entry is handled separately: only the
exact absolute symlink to this checkout's `frontend/node_modules` is accepted, its
link/target identity metadata is bound, and dependency contents are not recursively
traversed. The protected Step 6 directory and observed `results` mode are validated
without changing either. The original summary contains no screenshot checksums, so
these hashes bind the existing bytes at relaunch preflight; they do not claim
retroactive authentication of screenshot bytes at browser-test creation time.

The services are already running. Do not execute a relaunch while they are up.
For a separately approved future relaunch after the current generation has been
ownership-stopped, use the exact original parent evidence, a fresh unique child
directory, and the reviewed selectors below. From `backend/`, source the original
private settings into this shell only (disable xtrace first); this does not rewrite
either `.env` or print credentials:

```sh
cd /home/klottick/repos/historical-date-game/.worktrees/guest-play/backend

# Load the retained private runtime settings into this shell only. Disable xtrace
# before sourcing; this does not rewrite either checkout's .env or print values.
set +x
set -a
. /home/klottick/repos/historical-date-game/.worktrees/board-redesign/.env
set +a

export POSTGRES_DB=historical_date_game_catalog_test
export POSTGRES_SERVER=127.0.0.1 POSTGRES_PORT=5433 ENVIRONMENT=local
export GAME_GUEST_COOKIE_NAME=hdg_guest_real
export GAME_DATA_DIR=/home/klottick/repos/historical-date-game/.worktrees/beta/data/game/local-catalog-runtime
export GAME_EVENT_LINKS_FILE=/home/klottick/repos/historical-date-game/.worktrees/board-redesign/.superpowers/sdd/2026-10-14-game-board-redesign/integration/task-5/event-links.json
export GAME_EVENT_LINKS_SHA256=53da618a7ca6efc621296b0da429fa4c83caa906f3683b9375cb7c99302f9fcd
export FRONTEND_HOST=http://localhost:5174
export BACKEND_CORS_ORIGINS='["http://localhost:5174","http://192.168.1.214:5174"]'
EVIDENCE_DIR=/tmp/opencode/three-life-local-20261015T150302Z-task7
RELAUNCH_DIR="/tmp/opencode/three-life-local-relaunch-$(date -u +%Y%m%dT%H%M%SZ)-$$"
```

Only after confirming the owned ports are free and obtaining fresh authorization,
run this single relaunch command. It uses no reset/apply/migration operation:

```sh
test ! -e "$RELAUNCH_DIR"
uv run python -m tests.browser.three_lives_local_rollout relaunch \
  --parent-evidence-dir "$EVIDENCE_DIR" \
  --evidence-dir "$RELAUNCH_DIR" \
  --origin http://localhost:5174 \
  --origin http://192.168.1.214:5174
```

The current child is persistent local delivery; leave it running. To intentionally
stop this exact current generation, use its child evidence:

```sh
uv run python -m tests.browser.three_lives_local_rollout stop \
  --evidence-dir /tmp/opencode/three-life-local-relaunch-20261015T164639Z-2460503
```

`resume-migration` is only for a recorded `reset_committed` phase where migration
has not completed; never use it for this already-migrated target. Never use these
commands on another database. The helper requires the pinned sidecar path/hash,
cookie selector, catalog runtime, and exact frontend/CORS settings, plus
exact selected catalog identity on the live target; the sidecar is optional only
for its exact owned disposable test database. Private evidence remains mode 0700,
with proof files mode 0600 and no credentials/startup environment saved. A successful
`start` launches only after exact schema/data/file proof, current LAN origin, stopped
old services, and free intended listeners. It launches the API from this exact
backend checkout at `127.0.0.1:8010` and Vite from this checkout at `0.0.0.0:5174`,
preserving the selected catalog runtime and `hdg_guest_real`. `stop` validates every
confirmed new-generation PID/start tick/cwd/argv and bind before individual SIGTERM;
any mismatch prevents all signals.

For a future failed initial `start`, the helper supports ownership-checked partial
recovery only using that attempt's own evidence directory. Do not pass the original
parent or an unrelated/current child directory. For `start_failed`, stop signals
only the exact component set in the private `started` record whose process ledgers
and listeners all validate. Missing, extra, malformed, or mismatching ledgers refuse
the entire stop before any signal.
`*-unconfirmed-<pid>.json` files remain diagnostics only: they never authorize a
signal or process adoption. An unconfirmed child may therefore remain running;
the helper will not guess at its identity, stop it, or restart anything. Preserve
the evidence and obtain separate operator review if cleanup of an unconfirmed child
is needed.

The helper has no old-generation restart path. The LAN origin is an exact
precondition: if this machine no longer uses `192.168.1.214`, stop and request a
reviewed plan/documentation update rather than substituting an origin.

## Verification results (2026-10-15)

Task-suite logs and browser artifacts are retained privately under
`.superpowers/board-polish-three-lives/verification/`; live-delivery evidence is
private under `/tmp/opencode/`. The sealed real source was
verified at the pinned absolute path with manifest SHA-256
`804ec52ccfc3e19cd955913b05cbfd59158f562408e45c1916fa8626d3ac50d3` and 1,276
events. Its source/media and private event-link sidecar were not edited. Owned
fixture and real targets were audited for database/process ownership and public
media hashes; owned test processes were stopped. Test databases and artifacts
were retained.

| Gate | Result |
| --- | --- |
| Task 7 helper focused unittest | **46 passed** on `00ee58e` after Step 6 artifact binding. After the test-only isolation fix `6079772`, the focused recovery/relaunch group passed **16 tests** while the local API/UI remained running. |
| Task 7 app/helper gates | `mypy app` (62 files), `ruff check app tests`, focused helper Ruff/mypy, and helper format checks passed. |
| Lives profile/ownership preflight | 43 passed. |
| Full backend `uv run pytest tests -q` | The first controller run at `00ee58e` was **RED: 1,299 passed, 17 failed, 42 subtests** because recovery/relaunch unit tests consulted real listeners while the intended API/UI were running. Commit `6079772` changed only test isolation seams and added an occupied-listener refusal regression. The exact full backend command below then passed: **1,306 passed, 53 subtests passed, 165 warnings, 158.84s**, on the owned `historical_date_game_lives_backend_test` at `20261015_01`, with zero rows in the audited tables and zero other active sessions afterward. The earlier **1,303 + 50** result remains historical, not the final result. |
| Three-life migration unittest | 1 passed on the owned migration target; preservation/refusal checks ran. |
| Backend lint | Passed after `6079772`: `mypy app` (62 files), `ruff check app tests`, focused helper Ruff/mypy, helper format check, and `git diff --check`. |
| Client generation | Pass; generated `frontend/openapi.json` and `frontend/src/client/` had no diff. |
| Frontend unit/typecheck/lint/build | 86 unit tests passed; typecheck, lint, and build passed. |
| Controlled browser configs | Board 63 passed; bootstrap 23 passed; identity 34 passed after correcting one stale confirmation expectation. |
| Owned fixture browser config | **113 passed** across Chromium and mobile projects, including authentication/reset-password and three-miss recovery journeys. |
| Owned guest-catalog config | **48 passed** across Chromium, mobile, and insecure Chromium projects against the pinned real catalog, including cookie, ownership, privacy, restart, retry, and three-life journeys. |
| Owned real-catalog config | 11 passed across configured projects using explicit isolated origins and private test credentials. |
| Fixture/real audit | Both passed; owned browser API/UI processes were stopped after testing. The uniquely owned loopback Mailcatcher was also stopped. |

These gates verify the tested code and isolated fixtures only; they are not a
delivery certificate. No production-ready, accessibility-certified, or
physically-device-tested claim follows. The reviewed real catalog has no BCE
content or photographs; inclusive BCE/CE correctness is covered by fixtures.
Screen-reader and physical-device testing remain outstanding. The catalog source
was not curated or augmented.

Exact final backend command (run after the test-only change, on the owned backend
test database):

```sh
HDG_VERIFICATION_PROFILE=lives POSTGRES_DB=historical_date_game_lives_backend_test \
POSTGRES_SERVER=127.0.0.1 POSTGRES_PORT=5433 ENVIRONMENT=local \
uv run pytest tests -q
```

The initial failed-run log is retained as
`.superpowers/board-polish-three-lives/verification/final-delivery-00ee58e-backend.log`;
it is the RED run, not the final result. The repaired GREEN command and result are
recorded in the latest section of the private Task 7 report. The API/UI process
identities remained unchanged throughout; no live-target DB connection or service
action was part of the test-only repair.

## Current local delivery

Delivery and persistent relaunch remain complete at product source `00ee58e`. The
test-only repair is `6079772`; the documentation-only handoff is separate. The current
owned API/UI pair is intentionally running on localhost and LAN as recorded above;
no routine reset, migration, or seeding command is part of startup. Current counts
and preservation audits are recorded in the delivery summary. The final full
backend GREEN is **1,306 passed + 53 subtests** after `6079772`; this change only
adjusted tests and did not reload or otherwise alter the active runtime. Keep Node
provisioning on isolated backend origins; do not use real-catalog defaults
(`localhost:8010`/`5174`).
