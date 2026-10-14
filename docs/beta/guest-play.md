# Guest play: verification and owner-authorized local activation

The 2026-10-13/14 isolated verification is **not a release or rollout approval**.
Daily and Freeplay were verified against the actual reviewed catalog without
login, including the controlled insecure HTTP hostname `guest.test`.

An integration-discovered `crypto.randomUUID` secure-context limitation was fixed
with an owner-authorized, cryptographic `getRandomValues` UUID-v4 fallback.
Saved commands keep their original UUID and payload, even if new randomness is
unavailable during retry. No dependency or weak-randomness fallback was added.

## Evidence reached

- The full backend suite passed before final browser seeding: 912 tests.
- The unchanged reviewed 1,276-event release and separate verified eight-event
  fixture were activated only in explicitly owned verification databases.
- Verification backends/UI bound loopback only, on 8020/5184 and 8021/5173.
  The hostname mapping was Chromium-only; no DNS changes or external exposure.
- Desktop Chromium, Pixel 5 emulation and genuine insecure-origin Chromium
  completed all 27 guest cases:
  no-login entry, Daily/Freeplay scoring and reload, exact committed-command retry,
  two guests and account shared Daily prefix and ownership isolation, cold tabs,
  deleted/expired cookies, transport recovery, optional account switching,
  protected routes, credits, media hashes and actual private-artifact denial.
- Actual backend restarts preserved progressed guest Daily and Freeplay public
  DTOs identically, then accepted the next correct move in all three projects.
- The preserved fixture suite passed all 111 cases; the account real-catalog
  suite passed all 11. Separate no-account bootstrap/identity harnesses passed
  22/21 cases. No uncertainty or ownership assertions were removed.
- Frontend units passed 43 cases; types, lint and production build passed. The
  emitted bundles contained no matches for actual private event IDs/markers.
- The actual content verification CLI passed against the immutable original
  release. All manifest/source digests and original private runner bytes matched;
  all 16 projected real/fixture media assets passed filesystem and HTTP hashes.
  Thirty-eight actual private-artifact requests were denied.
- All verification processes were ownership-checked and stopped. Databases were
  retained; no cleanup ran while browsers/backends were using them. A separate
  owned loopback Mailcatcher supported preserved password-reset tests and was
  stopped; the original support container remained untouched.

## Local real-game activation (Task 6, 2026-10-14)

The owner explicitly authorized the existing DB restart and waived the earlier
backup/restore/data-preservation gate ("you don't even have to worry about the
data"). Task 6 therefore performed a guarded **additive migration and cold start**,
not backup orchestration, a restore database, a reset, or production activation.
The old 8010/5174 services were absent on fresh inspection; no historical PID was
adopted or killed. The existing DB server/exposure was not changed.

- Current access: **http://192.168.1.214:5174** or http://localhost:5174.
  The LAN address was detected anew; it is not a permanent address guarantee.
- Implementation: `feature/guest-play`, product baseline `50215af`, plus the
  scoped Task 6 helper/tests/docs commit. Both services run from `.worktrees/guest-play`.
- Exact retained real DB: `historical_date_game_catalog_test`, loopback PostgreSQL
  port 5433, original F1 ownership comment. Schema upgraded `20261011_01` →
  `20261013_01`; no seed, catalog reselection, reset, full pytest, or cleanup ran
  on it. Original beta release/public media remain read-only and hash verified.
- API: `127.0.0.1:8010`, access logging disabled. UI: existing
  `vite.real-catalog.config.ts`, `0.0.0.0:5174`, same-origin API/media proxies.
  No new exposure, public tunnel, hosting or publishing was added.
- Cookie: `hdg_guest_real`, host-only, HttpOnly, SameSite=Lax,
  `/api/v1/games`, refreshed 90-day lifetime. Secure is intentionally false for
  this explicit local HTTP environment, **not** a production configuration.
- Only `http://localhost:5174` and `http://192.168.1.214:5174` are allowed game
  mutation origins. Public registration is disabled. The local API factory forces
  SMTP off, including ambient or `.env` SMTP credentials, before importing routes.
- Fresh Chromium at the actual nonloopback IP automatically established guest
  identity without login/signup/continue-as-guest. Daily and Freeplay each scored
  correctly to revision/streak 1 and reloaded identical public state. Images and
  credits rendered, eight HTTP media hashes matched, 18 actual private paths were
  denied, account API access was 401, and separate contexts had different guests.
  Native insecure-context IndexedDB and cryptographic UUID fallback were used;
  no browser answer globals or crypto polyfills were installed.
- A non-gating read-only spot-check found all pre-existing account/run/operation/
  Daily/catalog row hashes unchanged before migration, after migration and after
  browser proof. New proof guests/runs are retained, including preliminary runs.

The rollout helper defaults to inspection/dry-run. It requires exact worktrees,
DB/environment/host/port/comment, selected release/manifest bytes, original media
paths/hashes, current IP/origins and free cold-start ports. `--apply` is necessary
for migration/start or owned stop; existing processes are never adopted. Private
outputs are create-only fresh mode-0600 inodes inside an ignored mode-0700 evidence
directory, outside public paths. Stop verifies PID start-time, cwd, exact command
and bound port for both services before signalling. Failure preserves evidence
and live state; there is no automatic reset/restore/recovery.

Task 6 focused guards and the full pure safety suite pass via `pytest --noconftest`
(no DB cleanup fixture); focused Ruff/format/mypy also pass. Exact counts,
commands/exits, current owned PIDs, private startup environment and browser proof
are in the ignored Task 6 report/evidence directory. See
[local lifecycle instructions](local-catalog-integration.md#task-6-current-local-guest-game-lifecycle).

## Remaining gates

The preserved hundred-card pointer-drag fixture assertion intermittently failed
when several browser suites were stressed concurrently. The unchanged full
fixture suite passed when run separately. This timing concern is retained for
review; no retries, skips or assertion weakening were used to conceal it.

Physical devices, LAN behavior on actual hardware, HTTPS/Secure-cookie production
configuration, production backup/activation, hosting, invitations and deployment
remain separate owner-controlled gates. Browser identity is not person-level
anti-cheat. Clearing cookies or changing browser/site address loses guest access.
The nonloopback browser run above was on this server, not a remote physical-device
or screen-reader session. Existing local placeholder secrets/HTTP are not hardened
for production or untrusted networks. Final branch review and the owner's
publication/integration choice remain pending; nothing was pushed or merged.
