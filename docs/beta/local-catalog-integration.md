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
resetting a definition. The final full rerun passed **800 tests, 70 warnings**;
pure safety passed **13 tests, 4 warnings**, and full app lint plus mypy/Ruff on both
new test modules passed. The complete content/game/safety pure suite passed
**602 tests, 4 warnings**. The previously failing API test also passed against real
seeded state (**1 test, 7 warnings**), followed by final reseeding after its cleanup.
The final probe and independent read-only audit exited 0: the real release is
selected, 1,276 event revisions persist, and two Daily definitions are frozen on
the real release for `2300-01-01`/`2300-01-02`. All 19 proof checks passed.

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
