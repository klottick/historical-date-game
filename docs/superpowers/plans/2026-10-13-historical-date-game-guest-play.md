# Historical Date Game Guest Play Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Daily and Freeplay immediately playable without login, while retaining private, resumable, server-scored runs and protected administration.

**Architecture:** Add internal guest owners and digest-backed HttpOnly sessions alongside existing account bearer authentication. Reuse the existing run services and Daily uniqueness constraints; add an explicit identity bootstrap and identity-scoped frontend recovery. Develop in a separate linked worktree so the currently served beta UI does not hot-reload incomplete code; apply the additive local migration only after isolated verification and a tested backup.

**Tech Stack:** Existing FastAPI/SQLModel/Alembic/PostgreSQL, React/TanStack Query and Router, generated Axios client, Node/Playwright and Vite. Use standard-library secrets/hashlib/hmac and native IndexedDB; no new dependency is planned.

**Spec:** `docs/superpowers/specs/2026-10-13-historical-date-game-guest-play-design.md`

**Status:** Approved by the owner with "Yes" on 2026-10-13; subagent-driven execution selected. Scoped isolated implementation and guarded local rollout are authorized; branch publication/integration remains a separate decision.

## Global Constraints

- Opening the game must allow Daily and Freeplay without entering credentials, registering, or clicking a mandatory "continue as guest" gate.
- Administration and account settings remain protected by account authentication.
- This is browser identity, not person-level anti-cheat.
- Guests must never receive ordinary account JWTs or gain access to account APIs by possessing their game cookie.
- Persist only the credential digest; the raw credential exists only in the cookie/creation response headers.
- Use a host-only HttpOnly cookie, SameSite=Lax, scoped to `/api/v1/games`, with a 90-day lifetime refreshed by a successful session bootstrap.
- Use Secure in staging/production; only the existing explicit local HTTP environment may omit Secure.
- Cookie names must be independently configurable for the real and fixture local environments because cookies do not distinguish host ports.
- The migration is additive and preserves every existing account and run.
- An explicitly supplied invalid/inactive account bearer is an authentication error, not permission to fall through to a new guest.
- Explicit bootstrap is the only guest allocation/replacement path and never scores a run.
- Cookie-authorized mutations, including bootstrap, require an exact allowed Origin and a custom game-request header.
- Bootstrap failure/retry cannot dispatch a scored operation until identity is known.
- Signing in/out does not transfer runs or commands between identities.
- Session failures are availability/recovery errors, never historical losses.
- Preserve both current live game databases, catalog bytes, players and processes.
- No automatic guest-to-account transfer, guest customization, cleanup job, content/source expansion, new dependency, public tunnel, deployment, invitation, main-branch merge or history rewrite.
- This plan's local rollout is distinct from production activation. Branch publication/integration remains a separate owner decision after implementation; do not automatically push a new implementation branch.

## Review Focus

1. Simultaneous first visits on HTTP LAN: both tabs obtain one confirmed cookie identity before either scores, without relying on secure-context-only Web Locks (Task 3 and Task 5).
2. Identity changes while a request is pending: cookie/account changes cannot replay an old command under a new owner or display a late response from another identity (Task 2 and Task 4).
3. Cookie rejection or expiry after a lost response: preserve the operation and show recovery, not a login redirect, new owner allocation or historical loss (Task 3–5).
4. Internal guest account endpoints: forged account tokens, password-reset paths and admin edits must not convert a guest into an ordinary/admin account or expose placeholder emails (Task 1–2).
5. Host aliases/ports and runtime ownership: real and fixture cookies stay distinct, origins are explicit, and verification/migration never resets the currently playable catalogs or accounts (Task 5–6).

## File and interface map

| Unit | Files and responsibility |
| --- | --- |
| Private guest persistence | New `backend/app/game/guest_models.py`, `guest_sessions.py`; additive migration; private `User.is_guest`; model registration |
| HTTP game identity | New `backend/app/api/game_identity.py`; `/games/session` routes and `GameSessionPublic`; account-only guard fixes |
| Browser coordination | New `frontend/src/features/game/sessionBootstrap.ts`, `bootstrapLock.ts`; native cross-tab bootstrap, cookie confirmation, non-credential context |
| Public game UX/recovery | New `GameSessionProvider.tsx`, `GameSessionGate.tsx`, `identityState.ts`; existing route, form, board and auth consumers |
| Isolated evidence | New test-only DB/environment helpers and guest browser directory/config; existing fixture/real test URL helpers |
| Local rollout | New guarded test-only rollout CLI and safety tests; `docs/beta/guest-play.md`; no competing production deployment subsystem |

### Execution environment

After plan approval, use using-git-worktrees to create `.worktrees/guest-play` on `feature/guest-play` from the reviewed plan commit. Keep `.worktrees/beta` and its served files unchanged. Move the execution session to the new worktree if supported. Install only the existing locked dependencies there. Preserve the original execution ledger; this plan's private ledger/evidence belongs in its own ignored SDD workspace.

New disposable verification targets on the existing owned PostgreSQL at `127.0.0.1:5433`:

- `historical_date_game_guest_test`: full backend tests, then reviewed real-catalog browser activation **after** destructive tests finish.
- `historical_date_game_guest_migration_test`: migration preservation/backup-restore probe.
- `historical_date_game_guest_fixture_test`: independent eight-event fixture browser environment.
- Real verification backend/UI: loopback `8020` / `5184`; fixture verification backend/UI: loopback `8021` / existing fixture test configuration's `5173`.
- Cookie names: `hdg_guest_verification`, `hdg_guest_fixture`, and final live real `hdg_guest_real`.

Create databases only if absent, record ownership comments, and refuse reuse unless ownership is proven. `_test` suffix alone is insufficient evidence. Inspect ports/cwd/commands before starting or stopping any process. The original `8000` fixture backend and `8010`/`5174` real environment are not verification targets. Immutable source release is read-only at the original beta worktree's `data/game/releases/jsonl-trial-2026-10-12-review-r1/`, manifest SHA `804ec52ccfc3e19cd955913b05cbfd59158f562408e45c1916fa8626d3ac50d3`, 1,276 events. Use absolute private paths; copy only verified public assets into the new runtime.

---

## Task 1: Add guest persistence and protect the account boundary

**Files:** Create `backend/app/game/guest_models.py`, `backend/app/game/guest_sessions.py`, `backend/app/alembic/versions/20261013_01_add_guest_sessions.py`, `backend/tests/api/routes/test_guest_sessions.py`, `backend/tests/browser/guest_test_environment.py`, `backend/tests/safety/test_guest_environment.py`. Modify `backend/app/models.py`, `backend/app/core/config.py`, `backend/app/core/db.py`, `backend/app/alembic/env.py`, `backend/app/api/deps.py`, `backend/app/api/routes/login.py`, `backend/app/api/routes/users.py`, `backend/app/crud.py`, and `backend/tests/conftest.py` only as required for registration/cleanup.

**Interfaces:**

- `GuestSession`: digest primary key, unique `owner_id` FK to `user.id` with delete cascade, unique random `public_id: UUID`, timezone-aware `created_at`/`expires_at`; expiry later than creation.
- `GamePlayer` frozen dataclass: `owner_id: UUID`, `kind: Literal['guest','account']`, `context_id: str`.
- `GuestBootstrap` frozen dataclass: `player: GamePlayer`, `credential: str`, `expires_at: datetime` (private; never a response model).
- `bootstrap_guest_session(session: Session, credential: str | None, now: datetime) -> GuestBootstrap`; reuse valid sessions and refresh expiry, otherwise create owner/session atomically. Caller commits; helper must not call `crud.create_user`, which commits separately and can send account-flow side effects.
- `resolve_guest_session(session: Session, credential: str | None, now: datetime) -> GamePlayer`; read-only, never allocates. `account_player(user: User) -> GamePlayer` uses stable keyed HMAC context, not a exposed owner UUID.
- `GAME_GUEST_COOKIE_NAME: str = 'hdg_guest'` configuration validated as a safe cookie name. Guest context is `g:<public_id>`; account context is `a:<HMAC-SHA256 of domain-separated user UUID with SECRET_KEY>`.
- Test-only `require_guest_test_target(database: str, host: str, environment: str) -> None` permits only the three named verification DBs, loopback and local. Environment CLI subcommands initially `prepare-db --database NAME` and `migration-proof`, with exact ownership checks before own sessions or subprocesses.

- [ ] Establish the isolated worktree and disposable DBs above; capture baseline tests/remote/worktree ownership without altering the live environment.
- [ ] Write failing persistence tests: `test_bootstrap_stores_only_digest_and_reuses_owner`, `test_expiry_refresh_is_90_days`, `test_invalid_session_reads_never_allocate`, `test_guest_cannot_use_account_auth_or_recovery`, `test_admin_cannot_convert_or_list_internal_guests`. Pin assertions:
  ```python
  first = bootstrap_guest_session(db, None, datetime(2026, 10, 13, tzinfo=UTC))
  second = bootstrap_guest_session(db, first.credential, datetime(2026, 10, 14, tzinfo=UTC))
  assert second.player == first.player
  assert second.expires_at == datetime(2027, 1, 12, tzinfo=UTC)
  assert first.player.kind == "guest"
  assert db.get(User, first.player.owner_id).full_name == "Guest"
  assert db.get(User, first.player.owner_id).is_superuser is False
  assert stored.token_digest == hashlib.sha256(first.credential.encode()).hexdigest()
  assert first.credential not in serialized_database_rows
  ```
  `stored`/`serialized_database_rows` are test-local reads of the actual new rows, not mocks. Also reject inactive/non-guest/admin owners, naive dates, malformed credentials and fabricated guest bearer tokens. Assert that request-supplied `is_guest` never creates/changes guest status; keeping private fields outside account DTOs need not change unrelated extra-field behavior.
- [ ] Run `uv run pytest tests/api/routes/test_guest_sessions.py tests/safety/test_guest_environment.py -q` in the explicitly owned new DB; observe missing behavior/guard failures before implementation.
- [ ] Implement the interfaces with `secrets.token_urlsafe(32)` and SHA-256; private `User.is_guest` default false, DB check forbidding guest admins, unique internal placeholder `guest-<UUID>@guests.example.com` and an unknown random hashed password. The placeholder must satisfy the existing EmailStr schema but never be sent email. Exclude guests from normal admin list/count and deny direct ordinary account read/update/delete targeting them. Preserve ordinary account errors and behavior.
- [ ] Add migration `20261013_01` after `20261011_01`, registering the new model explicitly. In `migration-proof`, seed an ordinary account and verified synthetic fixture run/operation, capture private row digests, downgrade only the new empty guest schema in its dedicated disposable DB, then upgrade again and assert old rows/daily references unchanged and `is_guest=false`. Test lifecycle cleanup/cascades; no live downgrade. After proof, close its connections and remove only this newly created, comment-verified migration-proof DB so Task 6 can create an empty restore target; preserve the other verification DBs.
- [ ] Run focused tests, `migration-proof`, full owned backend suite, and `uv run bash scripts/lint.sh`; retain inherited warnings. Commit only the named implementation/tests/docs needed for this task: `feat: persist isolated guest game identities`.

## Task 2: Expose game-only guest sessions and preserve authoritative authorization

**Files:** Create `backend/app/api/game_identity.py`, `backend/tests/api/routes/test_guest_game_api.py`. Modify `backend/app/api/routes/games.py`, `backend/app/game/schemas.py`, relevant existing game API assertions, `frontend/openapi.json` and generated `frontend/src/client/` through the existing generator only.

**Interfaces:**

- `GameSessionPublic(PublicModel)`: exactly `kind: Literal['guest','account']`, `context_id: str`.
- Internal `resolve_game_player(request: Request, session: Session, *, require_context: bool) -> GamePlayer`; dependency wrapper `get_current_game_player(request: Request, session: SessionDep) -> GamePlayer` always passes `require_context=True`, alias `CurrentGamePlayer`. Session inspection/bootstrap routes use `require_context=False` because the client has not confirmed a context yet. Never expose that switch as a query/body parameter. Reuse account validation when any Authorization header is supplied; invalid Authorization cannot be treated as absent.
- `read_game_session(...) -> GameSessionPublic` at `GET /games/session`; `bootstrap_game_session(...) -> GameSessionPublic` at POST. POST alone may allocate/refresh; account bootstrap allocates no guest.
- `X-Game-Request: 1` for guest mutations; require exact Origin in `settings.all_cors_origins`. `X-Game-Context` binds guest owned requests to their confirmed context; if supplied by accounts it must also match. Context is never an authorization credential.
- Errors follow existing `detail={code,message}`: missing/expired/invalid guest session `401`; rejected origin/header `403`; changed context `409` with `game_identity_changed`. Existing run-not-found and account validation remain unchanged.
- Generated SDK: `GamesService.readGameSession()` and `bootstrapGameSession()`; existing game body/DTO contracts unchanged.

- [ ] Write failing API tests using actual TestClient cookie jars: public options with no row allocation; bootstrap/read allowlists; correct HttpOnly/SameSite/path/Max-Age/Secure/host-only flags; bootstrap refresh reuses owner; Origin missing/null/untrusted and header missing are rejected before writes; arbitrary Host headers cannot authorize an Origin.
- [ ] Add `test_guest_and_account_share_daily_but_not_runs` and `test_changed_cookie_rejects_inflight_context`: two guest jars and one account share Daily anchor/correct prefix, but cross-owner reads/moves are 404. Exact placement retry increments once; new operation IDs cannot create a second Daily. A guest cookie replaced after context confirmation rejects the old-context start/move without allocating an operation. Deleting/expiring a cookie never allocates through a scored endpoint. Test trusted UTC rollover and a run finishing after midnight.
- [ ] Run `uv run pytest tests/api/routes/test_guest_game_api.py -q` in the owned test DB and observe RED before route changes.
- [ ] Implement the interfaces, non-cacheable session responses and cookie headers; guest mutations pass checks before guest persistence/scoring. Valid bearer wins over cookie. Make only options public; remaining game routes use `CurrentGamePlayer.owner_id` with existing services and locks. Keep leaderboard guest names `Guest` and existing rank/tie rules.
- [ ] Verify focused and full backend suites. Run the existing OpenAPI/client generation workflow in the isolated worktree; confirm operation names and generated `GameSessionPublic` fields, and reject unrelated generator/manual-client changes. Type/lint check new code. Commit: `feat: authorize guest sessions for gameplay only`.

## Task 3: Implement browser bootstrap and HTTP-compatible cross-tab coordination

**Files:** Create `frontend/src/features/game/bootstrapLock.ts`, `sessionBootstrap.ts`, `identityState.ts`, `frontend/tests/game-session.test.ts`, `frontend/tests/game-session-bootstrap.spec.ts`. Do not wire existing game UI consumers until Task 4.

**Interfaces:**

- `withBootstrapLock<T>(work: (signal: AbortSignal) => Promise<T>) -> Promise<T>` in `bootstrapLock.ts`.
- `ensureGameSession(mode: 'bootstrap' | 'inspect', signal?: AbortSignal) -> Promise<GameSessionPublic>` in `sessionBootstrap.ts`; per-tab single-flight, generated SDK with cookies, custom bootstrap header, 15-second transport bound. Inspect mode never POSTs or allocates. Bootstrap mode locks, inspects first, POSTs to create/refresh, then GET-confirms cookie acceptance and identical context before returning ready.
- `gameRequestOptions(context: GameSessionPublic): {withCredentials: true; headers: Record<string, string>}` returns both game headers. `sessionFailure(error: unknown): 'missing' | 'expired' | 'invalid' | 'identity_changed' | 'origin' | 'storage' | null` distinguishes session/context/origin/storage failures from ordinary run conflicts and transport failures; client storage errors use code `guest_storage_unavailable`.
- Pure `startStorageKey(contextId: string, mode: 'daily' | 'freeplay')`, `placementStorageKey(contextId: string, runId: string)`, `gameQueryKey(contextId: string, resource: string, id?: string)`; keys include the confirmed context.

- [ ] Write unit assertions for context-specific keys/options and failure classification; malformed/stale identity errors cannot become known historical rejection or clear saved commands. Run `node --test tests/game-session.test.ts` to observe RED.
- [ ] Write browser tests that invoke the actual production bootstrap modules with controlled HTTP responses, not a mocked lock: two fresh tabs on one origin, held bootstrap response, no-cookie acceptance, aborted/failed request, unavailable IndexedDB, tab closure and account bearer changes. Assert one issued guest context, both results equal, zero game mutations before confirmation, no POST in inspect mode, no repeated allocations after a rejected cookie. Name tests `cold_tabs_share_confirmed_identity`, `rejected_cookie_stops_bootstrap`, `inspection_never_allocates`, `closed_tab_releases_coordination`.
- [ ] Implement coordination with an origin-local IndexedDB `readwrite` transaction on a dedicated coordination store, held active across the bounded bootstrap/confirmation callback through queued request keep-alives. Exclusive transactions serialize tabs; commit only after callback settles, abort on error/timeout/closed tab. Store only a constant coordination marker, not credentials or identity metadata. Capture account-auth state when starting; abort/reject if it changes before confirmation, and do not reuse a single-flight result for a different auth state. Do not substitute a localStorage lease that can expire while a live request completes or rely solely on Web Locks. Unsupported storage fails closed with a retryable message. Confirm actual insecure-context behavior in Task 5.
- [ ] Run units and the new bootstrap browser cases via `npx playwright test tests/game-session-bootstrap.spec.ts --project=chromium --workers=1 --reporter=line`; these controlled-HTTP tests must not require migrating or modifying the original backend. Run full frontend units/types/lint/build. Commit: `feat: coordinate automatic guest bootstrap across tabs`.

## Task 4: Make gameplay public and scope all recovery to identity

**Files:** Create `frontend/src/features/game/GameSessionProvider.tsx`, `GameSessionGate.tsx`, `frontend/tests/game-identity-recovery.spec.ts`. Modify `frontend/src/features/game/api.ts`, `GameBoard.tsx`, `DailyPanel.tsx`, `FreeplayForm.tsx`, `frontend/src/main.tsx`, `frontend/src/hooks/useAuth.ts`, `frontend/src/routes/_layout.tsx`, `_layout/index.tsx`, `_layout/daily.tsx`, `_layout/freeplay.tsx`, `_layout/admin.tsx`, `_layout/items.tsx`, `_layout/settings.tsx`, `frontend/src/components/Sidebar/AppSidebar.tsx`; add targeted unit assertions in `game-session.test.ts`.

**Interfaces:**

- `GameSessionProvider` with `useGameSession()` returning confirmed context or loading/error, `retrySession()` for inspection and explicit `continueAsGuest()` for an unrecoverable/account-expired session. No automatic owner replacement during a run.
- `GameSessionGate` wraps gameplay readiness; run URLs use inspect-only mode. Public mode entry may bootstrap; newly opened mode links never show login/signup by default.
- In `api.ts`, `getDaily(context)`, `getActiveRuns(context)`, `getRun(runId, context)`, `startDaily(input, context)`, `startFreeplay(input, context)`, `placeCard(runId, input, context)` and `getLeaderboard(day, context)` take captured `context: GameSessionPublic` and retain their existing return types plus Task 3 request options. No mutable global context is substituted during an operation. Public options/config stay context-free.
- Existing board/form/Daily props become `context: GameSessionPublic`; keys and query caches use Task 3 functions. Identity changes unmount/cancel old observers and ignore late responses; client context header protects the server side too.

- [ ] Write failing `guest_home_has_no_login_gate`, `guest_does_not_request_user_me`, `guest_settings_and_admin_stay_protected`, `identity_switch_does_not_replay_uncertain_move`, `expired_guest_does_not_bootstrap_during_move`, `expired_account_can_explicitly_continue_as_guest`, and `existing_account_recovery_key_survives_transition`. Include sign-out/sign-in, another tab changing the account bearer, delayed GETs/responses and equal-revision uncertainty.
- [ ] Run focused browser/unit cases and observe RED. Controlled DTOs remain explicit fixtures; real integration follows in Task 5.
- [ ] Remove only the unconditional game-route account guard; enforce account/admin/item guards individually. Add the provider/gate and optional sign-in navigation, guest welcome copy, context-based resume/Freeplay/Daily/board readiness and no guest account-profile query. Preserve all drag/keyboard/credit behavior and pending DTO privacy.
- [ ] Scope starts, placements and owned query keys to the confirmed identity. Keep unresolved UUID/payloads until authoritative original-context recovery. Session/context errors retain commands, offer retry, and never call the old forced-login path for guests. Changing identity cannot clear another context's data or consume its start. For legacy account placement keys, migrate only after `/users/me` identifies the same valid account and a fresh owned run read confirms it. Legacy start keys have no run ID yet: adopt their unchanged UUID/body only after that same account-profile confirmation and let the existing operation registry resolve replay. Refuse conflicting destination commands rather than overwriting. Never migrate guest keys into accounts.
- [ ] Update global auth-error handling so public game failures do not force `/login`; account-only guards keep their behavior. Explicit guest continuation clears the stale account bearer and switches context, without replay/transfer. Signing out preserves guest cookies and returns Home. Cancel/ignore old-context query and mutation callbacks before they write caches/storage.
- [ ] Run focused cases plus frontend units/types/lint/build. Commit: `feat: open game routes with identity-safe guest recovery`.

## Task 5: Prove guest play against isolated real and fixture catalogs

**Files:** Extend `backend/tests/browser/guest_test_environment.py`. Create `frontend/playwright.guest-catalog.config.ts`, `frontend/vite.guest-catalog.config.ts`, `frontend/tests-guest-catalog/game-guest.spec.ts`, `frontend/tests/utils/apiOrigin.ts`. Modify `frontend/vite.config.ts`, `frontend/playwright.real-catalog.config.ts`, `frontend/tests-real-catalog/auth.setup.ts`, `game-catalog.spec.ts`, `restart-probe.ts`, `frontend/tests/real-catalog-config.test.ts`, and fixture `game-journeys.spec.ts`, `game-modes.spec.ts`, `game-recovery.spec.ts`, `game-interaction.spec.ts` only for explicit test origins/changed public-entry assertions.

**Interfaces:**

- Environment CLI adds `seed-real`, `seed-fixture`, `audit`, and owned-process launch/stop commands. Every destructive/full-pytest phase precedes seeding/browser use; never clean either browser DB during tests.
- `vite.guest-catalog.config.ts`: loopback 5184, same-origin `/api/` and `/media/` proxies to 8020; inherits all existing private denies plus `**/tests-guest-catalog/**`. Explicitly allow only the controlled additional test hostname `guest.test`, never `allowedHosts: true`.
- Guest Playwright config: separate directory, one worker, Chromium and mobile projects plus an insecure-context Chromium project, no account setup/storageState, no arbitrary server reuse. The insecure project maps `guest.test` to `127.0.0.1` through Chromium's `--host-resolver-rules`, base URL `http://guest.test:5184`; configure that exact Origin on the owned 8020 backend. This hostname mapping does not change system DNS or expose a listener.
- `fixtureAPIOrigin`/`fixtureAPI` from test-only `VITE_API_URL`, defaulting to existing localhost:8000. Replace hardcoded origins in the named fixture tests, including image expectations; no changes to synthetic answer tables.
- Existing real config gets optional `REAL_CATALOG_API_ORIGIN` and `REAL_CATALOG_UI_ORIGIN`, defaults still 8010/5174. Export `realCatalogUIOrigin` for setup/restart; no environment values or private answers enter product code.

- [ ] Add origin/config RED tests and guest browser cases: fresh unauthenticated Home, Freeplay score/loss/reload, Daily score/reload/one attempt, two isolated guests plus account sharing Daily, uncertain committed retry, cookie deletion/expiry and no auto-reallocation, simultaneous cold tabs, account context switching and protected routes. Real answers come only from existing Node-only `loadCatalog` after verifying selected release and all manifest files; never inject them into browser globals.
- [ ] In the owned real-verification DB, run full backend pytest first. Re-initialize admin without cleanup, verify/activate the unchanged 1,276-event release, and mount only its hash-verified release-scoped public assets. Seed the separate fixture DB through the existing verified eight-event builder. Start only the separate owned 8020/5184 and 8021/5173 processes with explicit cookie names/origins; original live processes remain untouched.
- [ ] Run `npx playwright test --config=playwright.guest-catalog.config.ts --workers=1 --reporter=line`; real `POST /games/session` responses must set HttpOnly cookies, guest state must persist across a restart of owned 8020, and native IndexedDB cold-tab coordination must work with `window.isSecureContext === false` at `guest.test`. A Host header alone is not proof of an insecure browser origin. Let browser-side fetch/UI handle that hostname; Node APIRequestContext does not inherit Chromium's resolver rule. No private answer map may enter browser evaluation.
- [ ] Run the entire existing fixture suite with `VITE_API_URL=http://localhost:8021` using a 300-second-or-longer harness timeout. Run the existing real suite against 8020/5184 using the new optional test origins; do not claim old-beta tests prove the new UI. Keep credentials/traces private. Run units/types/lint/build and scan emitted bundles with actual private event IDs/markers. Verify actual auth/runner/catalog/env HTTP denial and all projected media hashes.
- [ ] Run the actual content CLI `verify --release ABSOLUTE_ORIGINAL_RELEASE --media ABSOLUTE_ORIGINAL_RELEASE/media --require-beta`; record unchanged manifest/source digests, all test counts, failures corrected and retained warnings. Add `docs/beta/guest-play.md` with honest isolated evidence and remaining rollout/device gates. Commit: `test: verify no-login real catalog journeys and isolation`.

## Task 6: Back up, migrate and switch the owned local real game

**Files:** Create `backend/tests/browser/guest_local_rollout.py`, `backend/tests/safety/test_guest_local_rollout.py`; update `docs/beta/guest-play.md` and `docs/beta/local-catalog-integration.md`. Private backups/reports stay in ignored runtime/evidence directories with restrictive permissions.

**Interfaces:**

- CLI defaults to inspection/dry-run. Explicit `--apply`, `--live-worktree`, `--implementation-worktree`, `--old-backend-pid`, `--old-ui-pid`, `--backup-dir` and allowed frontend origins are required for changes.
- Target only `historical_date_game_catalog_test`, local/loopback PostgreSQL:5433, verified F1 ownership comment and reviewed real release/manifest. Create the restore-target `historical_date_game_guest_migration_test` only if absent, record ownership, and never restore into a pre-existing DB. Test/full-pytest DB guard and live-rollout guard are distinct; there is no live cleanup/full-test subcommand.
- Read-only baseline digest records existing accounts/runs/operations/Daily/catalog/media, excluding the new guest column for comparisons; never print credentials/private answers. Stop only verified-owned real backend/UI, create mode-0600 `pg_dump` backup via the owned Compose DB container, hash it, restore into the dedicated empty migration-test DB and verify preserved baseline before applying live migration.

- [ ] Write RED safety tests for wrong DB/environment/host/comment/release, unowned ports/PIDs/cwd, unavailable/incomplete backup, failed restore, private output hard-link/symlink aliases, and missing `--apply`. Assert no live migration/process stop occurs before its applicable guard; backup/restore failures cannot proceed to migration.
- [ ] Implement the guarded CLI. Refuse overwriting existing files/inodes: create-only private backup/report outputs, no `O_TRUNC` hard-link corruption. Confirm old schema version and process ownership, quiesce only the real services, back up, restore into the new empty test DB and upgrade that restored copy first. Compare baseline row digests before and after its migration; only then `alembic upgrade head` against the exact live DB. Verify every pre-existing owner/run/operation/Daily/catalog hash/reference survives and ordinary accounts are non-guest. No catalog activation/reseal or runtime media rewriting is needed.
- [ ] Launch real services from the implementation worktree with original live DB/runtime, API loopback8010, UI0.0.0.0:5174, cookie `hdg_guest_real`, and exact allowed origins `http://localhost:5174` plus the owner-approved current server-IP:5174. Inspect IP/PIDs anew; do not assume earlier values still exist. The original fixture8000 process/database remain untouched.
- [ ] Fresh browser on server-IP confirms no-login Daily/Freeplay, score and reload, media/credits and private-path denial; inspect guest cookie security/path and unique context. Read-only audit confirms old account runs unchanged. Physical touch/screen-reader/owner-play remain separate genuine checks, not implied by this browser run.
- [ ] On migration/launch/proof failure, stop and report the exact stage. Never reset/restore over a live database or delete guest/account rows automatically. Restore old service only when the migration did not apply and compatibility is known; after migration/new writes, preserve evidence/state and ask for a recovery decision.
- [ ] Record final verification and reviewed scoped commits in the ledger, commit the rollout helper/tests/evidence documentation, and retain working local services and both worktrees. Hand off implementation branch publication/integration for the owner's choice; no automatic main/beta merge, force push, deployment or invitations.

## Self-review and handoff

The spec's identity, cookie, account-boundary, public-route, uncertainty, leaderboard, cross-tab and rollout requirements each have an owning task above. The five Review Focus cases are assigned concrete tests. Backend/player/context/SDK names match frontend consumers; private helpers are not product endpoints. Native IndexedDB coordination is a focused browser algorithm whose real insecure-context proof is mandatory, not a passing Node mock.

Planning does not waive the implementation gates: each task requires observed RED, minimal GREEN, fresh verification, a scoped commit and independent task review under the preserved subagent method. Stop for an unworkable coordination primitive, unexplained data preservation failure, unexpected process/database ownership or required source/design policy change rather than silently widening scope.

**Owner handoff:** Review this plan before execution. Subagent-driven execution is retained unless the owner requests a different method. Approval permits the scoped isolated implementation and guarded local rollout described here; production/hosting/invitation and final branch publication/integration decisions remain separate.
