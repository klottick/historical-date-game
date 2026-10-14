# Isolated local real-catalog proof (F1)

**Historical F1/F2 evidence:** the retained real game now has owner-authorized
local card-board activation; use the [verified current lifecycle](#verified-local-card-board-activation)
below. The F1 ownership comment is historical provenance, **not current permission
to run destructive pytest/cleanup/seed/probe commands on this live database**.

This is a backend service/persistence check, **not production activation, launch,
browser/device/accessibility evidence, human content review, or legal clearance**.
No API/schema/publication policy changed. All content acceptance remains automated.

## Environment and ownership

- Branch: `feature/friends-beta`; starting commit `afc85a5`.
- Inspected running Compose project: `hdg-beta-baseline`, service `db`, container
  `e330937c0417` (`hdg-beta-baseline-db-1`), PostgreSQL host port `5433`.
- Persistent volume: `hdg-beta-baseline_app-db-data-pg18`; no volume operations.
- The approved database `historical_date_game_catalog_test` was **absent** before
  F1. F1 created only that database, owned by `postgres`, and recorded a database
  comment identifying F1, the base commit, and approved disposable-test ownership.
- Existing `historical_date_game_test` was not migrated, seeded, cleaned, or changed.
  Its live backend PID `1643276`, port `8000`, and `u3-browser-test` data directory
  were inspected rather than inferred from historical PIDs; no process was changed.
- Full pytest cleanup was allowed only on the new owned database, without any
  browser or running backend using it. The probe runs **after** suite cleanup.

The probe requires exactly this DB name, a `localhost`/`127.0.0.1` host, and
`ENVIRONMENT=local`, plus the existing `_test` guard, before its first session.
There is no unsafe/fixture bypass flag. Normal Python assertions must be enabled.
The report must be outside the immutable release and public media directories.

## Verified release and public assets

- Active release: `jsonl-trial-2026-10-12-review-r1`, nonfixture, **1,276 accepted,
  sourced, deduplicated events**; 1,271 chronology events and 5 Wikidata births.
- Exact manifest SHA-256:
  `804ec52ccfc3e19cd955913b05cbfd59158f562408e45c1916fa8626d3ac50d3`.
- Actual category membership counts: births 5; deaths 171; battles 544; inventions
  23; literature 65; arts 32; exploration 145; politics 291. Memberships can overlap;
  they are not the event count.
- Source release remains private in `data/game/releases/`. Only the eight
  manifest-listed, hash-verified fallback SVGs were copied, create-only, into
  `data/game/local-catalog-runtime/media/`. Identical existing assets are preserved;
  conflicting files fail rather than being replaced. No raw, source, answer, or
  rights artifacts were copied into public media.
- SVG filenames are `<SHA-256>.svg`, with these actual byte hashes:

```text
078e5f14e7212c61bf25a71803c2d8a26fed96d1100bf98d7f580580f220461c
9b03553b417e77c5deaceaa6db74eb04d88ec0bb8c81fe92d5eb1b9e8adad62c
a0e7eee85fcfc043be4c187965a8f42aeb3b45784da2ad70366212f03cb9cda9
a369677d756f4dd158a6461b48751ba82dacb566df29705d749736a66284d8a5
a94abf99a00eb056bf9cff24b5a7c8a7bbe187b4fe74a2a41f032ad9428b4b53
c655211bf0e7108f4a6bc8b651e20283949c4c9fced1eab5aeb8e365edd1ca53
dd94a8228b0a1e585b99a1c25c8a512951f3849f805d22472f266800426c5146
fddaeb052db9dd830e63f0722d6945b52fb21665fe36140b84ddd94a30e22c7b
```

## Historical F1 reproduction (from `backend/`, not current lifecycle)

The commands below document the former disposable verification. Do not execute
this block on the now-retained live real DB, especially full pytest or catalog
activation. Task 6 has a separate live guard and no cleanup/seed subcommand.

First inspect project/container/database ownership and consumers. **Do not blindly
run full pytest against an existing database**: its fixtures clean the entire DB.
An existing database requires independently established disposable ownership.

```bash
export POSTGRES_DB=historical_date_game_catalog_test
export POSTGRES_SERVER=127.0.0.1 POSTGRES_PORT=5433 ENVIRONMENT=local
export GAME_DATA_DIR=../data/game/local-catalog-runtime
uv run alembic upgrade head
uv run pytest
# After cleanup, with the approved eight SVG assets already hash-verified/copied:
uv run python -m tests.browser.real_catalog_probe \
  --release "$(realpath ../data/game/releases/jsonl-trial-2026-10-12-review-r1)" \
  --media "$(realpath ../data/game/local-catalog-runtime/media)" \
  --report "$(realpath ../.superpowers/sdd/2026-10-12-historical-date-game-beta-followup)/F1-real-proof.json"
uv run pytest tests/safety/test_real_catalog_probe.py -q
uv run bash scripts/lint.sh
uv run mypy app tests/browser/real_catalog_probe.py tests/safety/test_real_catalog_probe.py
uv run ruff check app tests/browser/real_catalog_probe.py tests/safety/test_real_catalog_probe.py
uv run ruff format app tests/browser/real_catalog_probe.py tests/safety/test_real_catalog_probe.py --check
```

The probe first uses `verify_release(..., require_beta=True)`, then the existing
activation service with the same gate. Repeated activation compares identical
manifest bytes and preserves event rows. It uses actual persisted catalog/run/
Daily services and two owned probe accounts; no answer or clock endpoint exists.
It retains private fixture-switch artifacts outside public media and never
deletes/reset Daily definitions. The trusted test day is the first unused day
(and unused successor) from `2300-01-01`, avoiding existing integration-test dates,
not a fabricated claim about today's game.

## Evidence and outcomes

Complete command outputs and sanitized mode-0600 JSON proof are retained privately
under `.superpowers/sdd/2026-10-12-historical-date-game-beta-followup/`; see
`task-F1-report.md` for command/exit-code inventory and the final verification counts.
The initial full suite passed **796 tests, 70 warnings**. A subsequent rerun
reported **798 passed, 1 failed, 70 warnings**: the probe's initial trusted date
`2200-01-01` overlapped an existing API test's deliberately undefined date. The
service correctly preserved the prior frozen definition. The probe now searches
from `2300-01-01`, with a pure regression test, without changing the API test or
resetting a definition. The pre-writer-fix full rerun passed **800 tests, 70 warnings**;
after the writer-only review fix, pure safety passed **20 tests, 4 warnings**, and
full app lint plus mypy/Ruff on both new test modules passed. The complete
content/game/safety pure suite passed **609 tests, 4 warnings**. The previously
failing API test also passed against real seeded state (**1 test, 7 warnings**),
followed by reseeding after its cleanup. That initial post-suite probe and
independent read-only audit exited 0: the real release is
selected, 1,276 event revisions persist, and two Daily definitions are frozen on
the real release for `2300-01-01`/`2300-01-02`. All 19 proof checks passed.

The report writer now serializes into a fresh private mode-0600 inode in the report
parent and atomically replaces the final entry; it never truncates an existing
inode, including an external report hardlinked to a source manifest or SVG.
Success/failure hardlink regressions preserve original bytes/inodes/permissions;
serialization/replace failures clean only the writer's own temporary file.
Symlink rejection and release/media path-containment checks remain in place.
One authorized real probe after this fix passed all 19 checks on
`2300-01-03`/`2300-01-04`, preserving every existing run/definition/account and all
release/media bytes, with a mode-0600 success report. No DB suite/cleanup/reset was
performed for this writer-only fix. Its proof is `F1-fix1-real-proof.json`.

Observed assertions cover real counts/options/categories, inclusive bounds and
category union, pairwise gaps/no duplicate years, zero-streak anchors, correct
placement plus exact retry/one revision, incorrect placement/no streak gain,
invalid/sparse settings allocating no run, ownership denial, won exhaustion and
terminal immutability, pending allowlists/answer-safe text attribution, revealed
source/credit preservation, and readback in a new session after pool disposal.

Both Daily players share the anchor/private frozen sequence and correct prefix,
with exactly one attempt per owner/day. A separately built eight-event fixture
passes the existing verifier for the **temporary switch only**: new Freeplay sees
it; existing real Daily/Freeplay snapshots, reads, and placements stay frozen.
The probe restores the verified real selection in `finally`, checks the next-day
real definition, then independently reads progress in another DB session.

The first real probe exited 1 with `passed=false`: an overly restrictive probe
assertion assumed every real event was chronology-derived. Sanitized diagnostics
identified the five legitimate Wikidata births; only that assertion was corrected.
The corrected probe exited 0. No verifier was weakened and no rows were fabricated.

Warnings are retained, not suppressed: Starlette/httpx test-client deprecation,
three local default-secret warnings, and API-suite PyJWT short-HMAC-key warnings.
These local defaults are not suitable for deployment. UI ports `8010`/`5174`,
browser checks, physical devices, spoken screen readers, owner gameplay and all
production/budget/invitation approvals remain outside F1.

## F2: isolated real browser environment

F2 adds a **separate** real-catalog Playwright configuration, not a replacement for
the eight-event fixture tests. The private runner requires the absolute
`REAL_CATALOG_RELEASE_DIR`, verifies the pinned manifest above and every listed
file hash, refuses fixtures/counts below 1,000, and checks the API's selected
release **before** loading answers. Answers never enter application imports,
`VITE_` variables, browser globals, or a new API endpoint.

Only the F1-owned `historical_date_game_catalog_test` database at
`127.0.0.1:5433` is used. Confirm its ownership comment and selection first.
Do **not** run full backend pytest, cleanup, migration, or activation merely to
start browser testing. The existing `init_db` may initialize the local admin
without resetting existing accounts/runs/definitions. Supply existing local
admin credentials through the environment; setup uses admin APIs to create
restricted dedicated players. Public signup on the real backend is disabled.

### Media provisioning correction

F1 checked/copied eight flat assets but did not exercise HTTP serving. The
existing production projection and media allowlist require
`/media/<release-id>/<digest>.svg`, not a flat `/media/<digest>.svg` alias. F2
hash-checked all eight originals and made **create-only identical copies** into
`data/game/local-catalog-runtime/media/jsonl-trial-2026-10-12-review-r1/`.
Conflicting existing destinations must fail. No release/original asset bytes
changed, no private artifacts were copied, and the media allowlist was not
weakened. All eight actual projected asset URLs return 200 with matching byte
hashes. Private artifacts and directory listings return 404, including paths
under this release directory. The flat digest path remains deliberately 404.

### Historical F2 launch and tests

This archival launch block is superseded by the SMTP-disabled guarded Task 6
launcher below; do not start a second service or use stale PIDs/addresses.

Inspect `ss -ltnp` and process command/cwd before starting. Occupied ports require
established ownership or approval; a responding health check is not ownership.
Do not stop the original fixture backend on port 8000.

```bash
# From backend/, after ownership checks; keep existing .env credentials private.
export POSTGRES_DB=historical_date_game_catalog_test
export POSTGRES_SERVER=127.0.0.1 POSTGRES_PORT=5433 ENVIRONMENT=local
export GAME_DATA_DIR="$(realpath ../data/game/local-catalog-runtime)"
export FRONTEND_HOST=http://localhost:5174 PUBLIC_REGISTRATION_ENABLED=false
uv run python -m app.initial_data
uv run uvicorn app.main:app --host 127.0.0.1 --port 8010

# In a separate shell, from frontend/; verify 5174 is free first.
# Owner authorized all-interface UI binding; backend remains loopback-only.
export PATH=/tmp/opencode/node-v26.11.1-linux-x64/bin:$PATH
npm run dev -- --config vite.real-catalog.config.ts

# Supply FIRST_SUPERUSER / FIRST_SUPERUSER_PASSWORD privately from local .env.
REAL_CATALOG_RELEASE_DIR="$(realpath ../data/game/releases/jsonl-trial-2026-10-12-review-r1)" \
  VITE_API_URL=http://localhost:8010 npx playwright test \
  --config=playwright.real-catalog.config.ts --project=chromium \
  --project=game-mobile --workers=1 --reporter=line
curl --fail http://127.0.0.1:8010/api/v1/utils/health-check/
```

The configuration has no automatic webServer/reuse behavior. Auth files live
only in ignored `frontend/playwright/.auth/` (directory 0700, files 0600).
Use the separate Vite configuration above: ignoring files and Unix permissions
alone do **not** stop a dev server from serving them. A final F2 probe reproduced
HTTP 200 for private auth JSON under the default Vite configuration; the new
real-only Vite configuration preserves default sensitive-file denies and blocks
auth, test-runner, SDD and catalog paths. Actual UI-origin probes now return 403,
including raw-query and `/@fs/` paths. The initial fix left the fixture Vite
configuration unchanged; the reviewed fix below closes that alternate-origin gap.
`real-catalog.json` is the player storage state; `real-catalog-players.json` and
`real-catalog-journey-players.jsonl` retain dedicated local credentials for owner
play, not public enrollment. Do not paste these into logs or reports. Players
and their active runs are preserved; no whole-DB cleanup is performed.

### Verified outcomes and restart

Final evidence, failures/traces, complete command outputs, lifecycle/PIDs and
sanitized state are in the private same-workspace `task-F2-report.md` and
`F2-evidence/` under the followup SDD directory. The real suite exercised ten
journeys (five per project) plus setup. Actual options expose the eight slugs,
9–2025 CE, and this 1,276-event release. The real two-year exhausted pool uses
inclusive **9–14 CE with gap 5**, chosen from the full verified catalog, not a
synthetic release or a shortened engine. Broad Freeplay proves correct scoring,
preview-only drop, exact retry, reload/resume, intentional loss, and a new run.
Two fresh Daily players per project share the anchor/three-card correct prefix,
frozen categories, one attempt despite a new operation ID, and owner-only reads.
Pending DTO allowlists/credits, revealed sources, real assets, failed imagery and
a genuinely committed-but-dropped response are checked through UI and HTTP.

`frontend/tests-real-catalog/restart-probe.ts` is an explicit two-phase Node
runner, outside default discovery. Run `node tests-real-catalog/restart-probe.ts
before` with the private release environment, stop **only the verified owned
8010 PID**, relaunch with identical settings, then run its `after` phase. F2's
actual restart preserved the complete progressed Daily/Freeplay DTOs at revision
1 (catalog, timeline, pending, config, feedback and Daily identity), then the
browser scored the next correct move on each to revision/streak 2. Saved owner
restart auth is in ignored `real-catalog-restart-players.json` /
`real-catalog-restart.json` so a later setup cannot erase those credentials.

The original fixture suite was independently rerun against port 8000 and its
original eight-event DB/catalog, with a separate loopback Vite on 5173: **111
passed**. No fixture answer table, default discovery or generated client changed.
The owned real UI/API remain usable at `http://localhost:5174` /
`http://localhost:8010`. Use the report's current PIDs, verify cmdline/cwd/port
again, then send SIGTERM only to those owned processes when stopping. The private
`F2-evidence/local-environment.py` retains exact launch and guarded backend
restart commands. Never use a broad service kill or DB reset.

Desktop Chromium and Pixel 5 **touch emulation are not physical-device evidence**
or unassisted owner play. Physical-device, spoken screen-reader, owner gameplay,
production security/default-secret replacement, hosting/budget and invitation
gates remain outstanding. No deployment, paid operations, live acquisition,
LAN/tunnel binding, push, merge, or publication was performed during F2.

### Owner-authorized network access

The real UI now binds **`0.0.0.0:5174`**. Open
`http://<server-ip>:5174` from another device; `0.0.0.0` is a bind address,
not the address to enter on that device. The real-only Vite configuration forces
a same-origin API base, overriding stale local `VITE_API_URL` settings, and proxies
`/api/` and `/media/` to `127.0.0.1:8010`. Thus login, game operations and images
do not point at the visitor's own localhost. The backend stays on loopback;
the fixture configuration and database remain unchanged.

Default Vite host validation and the shared private-file deny list remain enabled.
Use an IP address (or explicitly approve a controlled hostname); do not set
`allowedHosts: true`. This is owner-authorized development access, not a hardened
production deployment: it uses HTTP and existing local credentials. Do not expose
it to untrusted networks or add a public tunnel. This authorization does not
approve production deployment, invitations, or genuine-device test results.

### F2 review fix1: protect every shared-root Vite origin

The controller authorized minimal shared private-artifact deny hardening. A newly
owned default Vite on loopback 5173 reproduced HTTP 200 for retained real auth
JSON, query aliases and actual absolute `/@fs/` aliases. This is a new controlled
reproduction, **not** a claim that 5173 was live during the independent review.

The private-file deny list now lives once in `frontend/vite.config.ts`, with
strict filesystem handling and all installed Vite defaults preserved; the real
config inherits it. Fixture discovery, API origin and application behavior remain
separate. Both default and real servers now deny auth/runner/SDD/catalog paths.
Resolved-config unit tests import both actual configurations and compare against
the installed default deny list; they are not mislabeled as HTTP tests. The
explicit HTTP regression checks both origins and ordinary UI/JS availability:

```bash
# Inspect ownership/free port first; this is the default/fixture frontend only.
VITE_API_URL=http://localhost:8000 npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
F2_PRIVACY_DEFAULT_ORIGIN=http://localhost:5173 \
  REAL_CATALOG_RELEASE_DIR="$(realpath ../data/game/releases/jsonl-trial-2026-10-12-review-r1)" \
  node tests-real-catalog/private-artifact-http.ts
```

The real credits case now requires nonempty chronology attribution and its exact
CC BY-SA 4.0 license link before iterating rendered credits. It excludes only the
five public-domain Wikidata births from that credit-specific run to avoid falsely
requiring CC BY-SA on them; broad Freeplay still tests the full eight-category union.
Owner auth/credentials are snapshotted privately and restored byte-identically
after suite setup; newly created suite credentials and the append-only journey
journal are retained. No existing account, password, registration setting,
backend process, database cleanup, firewall or production configuration changed.
Full fix1 RED/GREEN, fresh browser/unit/build verification and lifecycle results
are appended to the private `task-F2-report.md` and `F2-fix1-evidence/` directory.

## Task 6: current local guest-game lifecycle

This section records the **historical guest-play** lifecycle, not current card-board ownership.
Its original Task 6 cold-start ledger below is historical; the controller's later
guest-play generation uses private
`.superpowers/sdd/2026-10-13-historical-date-game-guest-play/final-fix-evidence/local-lifecycle.py`
and `local-activation/`. Establish actual current ownership there before any
signal; do not use a historical PID, address, or stopped Task 6 ledger as authority.
The original runner was freshly verified and stopped during board Phase B below;
its retained ledgers are provenance, not current service ownership.

Owner-authorized local activation on 2026-10-14 used product baseline `50215af`
from `.worktrees/guest-play`, additive schema `20261013_01`, and the unchanged
reviewed 1,276-event release/manifest/media above. The owner explicitly waived the
old backup/restore gate and authorized the existing DB restart. Neither old real
service existed; the helper performed a guarded cold start with no old-PID args.
No backup/restore subsystem, extra database, data reset, catalog reselection,
original-runtime rewrite or DB-server/exposure change was needed or performed.

Current UI: **http://192.168.1.214:5174**, also http://localhost:5174. The real API
is loopback-only `127.0.0.1:8010` with `--no-access-log`; the existing real Vite
config binds `0.0.0.0:5174` and proxies API/media on the visitor's origin. Its
private-file denies were not widened, including original-beta `/@fs/` paths.
The API reads the original hash-verified **public media** via an absolute
`GAME_DATA_DIR`, without asking Vite to serve the private beta runtime.

For inspection from `guest-play/backend/` (read-only, default dry-run):

The PostgreSQL host must be exactly `127.0.0.1`; `localhost` and `::1` are rejected
before connection/migration so inspection and child processes use one endpoint.

```bash
# Inspect current IP, ports and processes anew; do not assume this IP is permanent.
ip -4 route get 1.1.1.1
ss -ltnp
POSTGRES_DB=historical_date_game_catalog_test \
POSTGRES_SERVER=127.0.0.1 POSTGRES_PORT=5433 ENVIRONMENT=local \
  .venv/bin/python -m tests.browser.guest_local_rollout \
  --live-worktree /home/klottick/repos/historical-date-game/.worktrees/beta \
  --implementation-worktree /home/klottick/repos/historical-date-game/.worktrees/guest-play \
  --origin http://localhost:5174 --origin http://192.168.1.214:5174

# Pure safety verification only; never full pytest on the retained real DB.
.venv/bin/pytest --noconftest tests/safety -q
```

The original successful cold start added `--action start --apply` to that
inspection command. It is **not a reusable automatic restart command**: existing
startup outputs/PIDs/ports cause refusal. Do not delete ledgers to bypass it.
The private ignored directory
`.superpowers/sdd/2026-10-13-historical-date-game-guest-play/task-6-evidence/`
retains `startup-env.json`, preflight/migration records, exact service argv/cwd/
PID/start-time ledgers and logs. Directory mode is 0700; private files are 0600.
Never publish the environment ledger or copy it into public media or Git.

An owner-requested stop uses the same explicit target/origin arguments with
`--action stop --apply`. Both current owned service identities and ports are
rechecked before any SIGTERM; unverified processes are never killed or adopted.
Ledgers remain. After migration/new gameplay, failures preserve DB/evidence and
require an owner recovery/restart decision; no reset, downgrade or automatic
rollback/restore exists. Current processes were left running for owner play.

`hdg_guest_real` is independent of verification/fixture cookies. Only the two
exact origins above are authorized. Public registration and all SMTP sending
are disabled, including ambient SMTP restoration from `.env`. The original
fixture DB/port 8000 were not touched (no listener was present on inspection).

Fresh actual-IP Chromium proved automatic no-account guest entry, Daily and
Freeplay scoring and identical reload, visible credits/images, eight actual media
byte hashes, 18 private-artifact denials, cookie boundary and distinct guests.
A read-only, non-gating spot-check also retained every pre-existing row hash.
Full commands/exits, TDD RED/GREEN, final pure safety counts, owned PIDs and proof
state are in the private `task-6-report.md` in the same SDD workspace.

This remains local HTTP development access with existing placeholder secrets,
not production hardening or remote physical-device proof. Physical touch,
spoken screen readers, production HTTPS/Secure cookies, security/backup/hosting,
invitations and final branch review/publication/integration remain separate owner
decisions. No push, merge, tunnel or external integration was performed.

## Verified local card-board activation

On **2026-10-14**, reviewed card-board product HEAD **9d2c75d** was activated from
`.worktrees/board-redesign`. Its current guarded lifecycle, exact commands and
fresh evidence are documented in
[game-board-redesign.md](game-board-redesign.md#verified-local-card-board-lifecycle).
Phase A committed code/pure tests; independent helper and whole-branch reviews,
one fix wave and its scoped re-review closed blockers before Phase B. Four pinned
native teardown warnings were independently accepted for LOCAL delivery only,
with no suppression/upgrade or production certification.

Fresh original-runner inspection proved both guest-play identities585755/585762,
including start ticks/cwd/argv/binds/origins/DB/release/media. Only that original
runner stopped them, from `guest-play/backend/` with exact live env and
`PYTHONPATH=.`; both ports were proven free before the new inspect/start. Neither
served worktree's code was edited, and original ledgers were retained. The new
wrapper did not adopt them. Fresh create-only ownership is at the board plan's
private `local-activation/` (0700/files0600). Preserve all generations.

The board wrapper reuses exact live DB/IPv4, source/media, current-origin and
PID/start-time/cwd/argv/port guards. It requires existing schema `20261013_01` to
match the sole current script head and passes `upgrade_schema=False`; it invokes
no migration. The existing helper's default upgrade behavior is unchanged in
this isolated worktree; served guest-play/beta code is not edited. Missing
enrichment explicitly uses ordinary source fallback. Supplied private metadata
requires path/permissions/digest and release/event/source validation. Current
actual-R metadata contains no matched articles, only 1,276 source fallbacks.

API/UI remain loopback8010/all-interface5174 with the existing same-origin proxy,
private-file denies, real guest cookie, SMTP/public-registration disabled and
no-access-log API. Current UI is **http://192.168.1.214:5174** (also localhost5174).
API PID**1176900**, start ticks**15553453**; UI PID**1176907**, start ticks**15553507**.
Final owned checks passed and services were left running. Recheck actual current
PID/start/cwd/argv/binds/origins before any future stop; never delete ledgers to
bypass create-only start refusal or assume this IP/PID remains current.

Fresh actual-IP Chromium proved four Daily/Freeplay complete flows at1920×900 and
1366×768 CSS pixels/100% zoom, actual-card preview/re-pickup with zero pre-lock
scoring, eleven correct locks then persisted attempted loss, exact replay/reload,
visible controls/new Freeplay, preview-aware overview and ordinary keyboard focus,
full credits and honest source labels. Native insecure-origin crypto/IndexedDB,
cookie boundaries, unauthorized administration/signup/SMTP routes,24 actual
media hashes and28 existing private-file denials passed. The factory policy was
reproduced from the proven running child environment without credential output.

Hash-only read-only audits proved zero startup DB changes; all2,148 original rows
and36 source/runtime file hashes unchanged at final handoff. The only additions
were2 dedicated guest users and sessions,8 UI-created runs and56 correlated
operations (8 starts/48 unique placements;4 exact HTTP replays added no rows).
Selected release/schema/answers and frozen Daily definitions were unchanged.
No migration, cleanup, reseed/reselection, downgrade/reset, backup subsystem,
automatic rollback or integrated pytest was run against the retained live DB.

Private command/exit logs,33 screenshots,two traces, ownership and mutation proofs
are at `integration/task6-phase-b/` under the board plan; the full phase report is
`task-6-report.md` (0700 directories/0600 files). One private probe's reserved email
input produced422 before correction to a valid address proving closed-signup403;
the diagnostic and original log remain. Router/expected unauthenticated401 and
prior native diagnostics remain unsuppressed; no page errors occurred. Actual
article coverage remains0, not universal or real-article certification.

The final commit delta after the reviewed product HEAD is documentation-only.
No push/merge/tunnel/deployment/invitation or worktree/evidence removal was done.
Production, physical devices, spoken screen readers, legal clearance and branch
integration/publication remain separate decisions, not implied by local approval.
