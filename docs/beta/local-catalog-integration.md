# Isolated local real-catalog proof (F1)

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

## Reproduction (from `backend/`)

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

### Launch and tests (loopback only)

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
export PATH=/tmp/opencode/node-v26.11.1-linux-x64/bin:$PATH
VITE_API_URL=http://localhost:8010 npm run dev -- --config vite.real-catalog.config.ts --host 127.0.0.1 --port 5174 --strictPort

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
LAN/tunnel binding, push, merge, or publication was performed.

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
