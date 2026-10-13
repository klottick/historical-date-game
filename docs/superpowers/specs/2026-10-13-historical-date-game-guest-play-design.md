# Historical Date Game: No-Login Guest Play

**Status:** Written spec approved by the owner with "I approve" on 2026-10-13.
**Baseline:** `4b224ad`, `feature/friends-beta`, verified equal to the remote before
writing this document. No product implementation or live migration has begun.

## Intent and scope

Opening the game must allow Daily and Freeplay without entering credentials,
registering, or clicking a mandatory "continue as guest" gate. The server still
owns answers, scoring, run ownership, retry handling and persisted progress.
Administration and account settings remain protected by account authentication.

The owner approved one guest Daily attempt per browser per UTC day, including
the limitation that clearing browser data or using another device/browser can
create another identity. This is browser identity, not person-level anti-cheat.
Browser profiles and different site hostnames can also have separate cookies;
players should consistently use the same site address to retain progress.

This specification supersedes the [original beta design](2026-10-11-historical-date-game-beta-design.md)'s mandatory account
requirement for ordinary gameplay and extends Daily uniqueness to guest owners.
All other game, catalog, attribution, publication and launch rules remain intact.

Excluded: automatic guest-to-account transfers, account creation prompts, guest
email/password collection, guest naming/customization, catalog/source expansion,
hosting, public deployment, invitations and unrelated authentication redesign.

## Chosen approach

Use an opaque server-issued guest cookie and an internal guest owner, reusing
existing run services and the `(owner, daily definition)` database constraint.
Keep ordinary account bearer authentication available for signed-in players.

Alternatives considered: a JavaScript-stored guest bearer token is simpler to
wire up but exposes the persistent credential to scripts; a separate player
ownership model requires larger migrations of existing runs and operations.
Neither is needed for this change. Guests must never receive ordinary account
JWTs or gain access to account APIs by possessing their game cookie.

## Identity and persistence

- Add a private `is_guest` marker to `User`, defaulting to false for every existing
  account. Guests are active, non-admin internal owners with display name `Guest`.
  They have no usable account login. Any inherited email/password columns contain
  internal placeholders only; guest records cannot receive recovery/notification
  email, log in, reset passwords, or be converted through ordinary account APIs.
- Add a guest-session table referencing that owner, with a unique SHA-256 digest
  of a cryptographically random credential of at least 256 bits, expiry and a
  separate opaque public context identifier. Persist only the credential digest;
  the raw credential exists only in the cookie/creation response headers.
- Validate that each resolved session belongs to an active, non-admin guest.
  Guest status is never accepted from account creation/update request fields.
  Account dependencies also reject guest owners, including any account bearer
  token claiming their ID. Normal admin account lists exclude internal guests;
  existing legitimate account management remains available.
- Use a host-only HttpOnly cookie, SameSite=Lax, scoped to `/api/v1/games`, with
  a 90-day lifetime refreshed by a successful session bootstrap. Use Secure in
  staging/production; only the existing explicit local HTTP environment may omit
  Secure. Cookie names must be independently configurable for the real and
  fixture local environments because cookies do not distinguish host ports.
- Guest sessions and progress survive backend restart. No new automatic deletion
  or destructive cleanup job is included. Expired/lost cookies cannot recover old
  guest runs; that limitation must be explained rather than presented as a loss.

Existing run, operation and Daily-definition tables retain their owner relations,
unique constraints, seeds, frozen catalog references and transaction semantics.
The migration is additive and preserves every existing account and run.

## API boundary and security

1. `GET /games/options` becomes public; it exposes only the existing public
   catalog/config projection. It must not allocate a guest or scored attempt.
2. Add explicit `POST /games/session` bootstrap and `GET /games/session` inspection.
   A valid account bearer selects the existing account; otherwise bootstrap reuses
   a valid guest cookie or creates a guest/session atomically. The response exposes
   only identity kind and an opaque, non-authorizing context identifier. Its JSON body never
   exposes cookie credentials, internal email, owner IDs, seeds or private answers.
3. An explicitly supplied invalid/inactive account bearer is an authentication
   error, not permission to fall through to a new guest. A valid account bearer
   takes precedence over a guest cookie. No guest identity is merged into it.
4. All other game endpoints use a dedicated game-player dependency accepting a
   valid account or guest session. It provides the existing owner ID to unchanged
   scoring services. Missing, malformed, expired or revoked guest credentials fail
   with a structured session error; those endpoints never create a replacement
   owner. Inspection does not allocate one either. Explicit bootstrap is the only
   guest allocation/replacement path and never scores a run.
5. Cookie-authorized mutations, including bootstrap, require an exact allowed
   Origin and a custom game-request header. Missing/untrusted origins, including
   Origin `null`, fail before allocation or scoring. Use the existing explicit
   frontend/CORS origin list, not arbitrary Host/forwarded-header trust or wildcard
   credentialed origins. SameSite is additional protection, not the sole CSRF check.
   Account bearer calls retain their existing authentication behavior.
6. The game client includes cookies and the mutation header. The real UI continues
   to use its same-origin API/media proxy; explicit fixture origins use compatible
   credentialed CORS. Local LAN origin authorization must be configured explicitly
   while keeping the backend on loopback and preserving private-file denies.
7. Session responses are non-cacheable. Cookies, authorization headers and raw
   guest credentials must be excluded from logs, public evidence, bundles and Git.
   A context identifier is not a credential and cannot authorize any endpoint.

Bootstrap is coordinated within a tab and across tabs of the same origin, with
cookie acceptance confirmed before enabling owned game operations. Concurrent
first visits must not create two usable guest identities racing to score Daily.
Coordination must work at the approved HTTP LAN address, where secure-context-only
Web Locks cannot be the sole solution. Browser storage/cookie unavailability
produces a retryable explanation, not a login requirement or repeated allocations.
Bootstrap failure/retry cannot dispatch a scored operation until identity is known.

Guest access does not open account, item, admin or password APIs. Cross-owner reads
and placements keep their current denial behavior for guests and accounts alike.

## Player flow and identity changes

- Home, Daily, Freeplay and run routes are public routes with automatic session
  readiness, not children of an unconditional account-login guard. Normal loading
  and retry states are allowed; a login form is not the default entry experience.
- Account/admin/item routes retain appropriate account guards. Guests see game
  navigation and an optional sign-in link, not misleading account settings,
  admin links or a fake logged-in user. No guest `/users/me` request is needed.
- Signed-in players use existing account progress and account Daily limits.
  Signing out returns to guest play, without destroying the guest cookie. Signing
  in/out does not transfer runs or commands between identities.
- Persisted start/placement recovery state and query caches are scoped to the
  current identity context. Switching identity must never replay an old operation
  under a new owner or display stale private run state from another identity.
- Preserve uncertain-operation UUIDs and payloads within their original context.
  Session failures are availability/recovery errors, never historical losses.
  Missing guest cookies during a move do not silently bootstrap and score again.
  Offer session retry and an explicit return-to-new-play action if the old session
  cannot be recovered; explain that its run is no longer accessible.
- Expired account authentication on game pages offers optional account re-login
  or explicit guest continuation, rather than forcing login to play. Guest
  continuation never retries the account's unresolved operation. Account-only
  pages may retain their existing login redirects.

## Daily, Freeplay and rankings

Each guest owner gets one scored Daily attempt per UTC day, using the same frozen
definition, seed, categories, anchor and sequence as accounts and other guests.
Reloads, retries, tabs and new operation IDs cannot allocate another attempt for
that owner. Preview remains unscored; an attempt spanning midnight stays attached
to its original definition; the next day permits its own new attempt.

Freeplay remains unlimited with existing configuration validation, gap rules and
terminal behavior. Public projections and pending-answer privacy are unchanged.

Completed guest attempts appear on the existing Daily leaderboard as `Guest`.
Multiple such entries are acceptable; ties/ranks follow existing streak rules.
Never show their internal placeholder email, owner ID or credential/context ID in
leaderboard entries. Existing account display names remain unchanged. The browser
identity limitation must not be described as a person-level competitive guarantee.

## Verification and rollout requirements

- Add migration/identity tests preserving existing account/run data, cookie
  security flags/digest storage/expiry, bootstrap reuse, rejected credentials,
  explicit origin/header enforcement and denial of account APIs to guests.
- Exercise two guest identities and an account: private reads/moves are isolated,
  exact command replay is idempotent, and all three share the same Daily prefix.
  Verify one attempt through concurrent starts/tabs and UTC rollover.
- Exercise a fresh browser opening the actual real-catalog UI: no login/signup
  interaction, Daily/Freeplay start, score, reload and resume, readable credits,
  working images and retained private-artifact denial.
- Cover simultaneous cold-start tabs, session/bootstrap failures, lost committed
  responses, cookie rejection/expiry, account expiry, sign-in/out context changes
  and prevention of cross-identity command replay. Keep the existing account and
  recovery tests; adapt only assertions intentionally changed by public gameplay.
- Repeat full backend and fixture/real browser suites, units, types, lint, build
  and the immutable-catalog verification. Test HTTP LAN behavior separately from
  secure-cookie production configuration; emulation is not physical-device proof.
- Use a newly owned disposable database for destructive integration verification.
  Preserve both current live game databases, catalog bytes, players and processes.
  Before applying the additive migration to the live local real game, perform a
  guarded, private backup and show preservation of existing owners/runs afterward.
  Restart only verified-owned processes and retain loopback API/all-interface UI.

This design approval does not waive any original launch, device, content/media,
HTTPS, production backup, hosting or invitation gates. The remote was synchronized
before this design work. This specification's commit and publication on the same
feature branch are documentation only, not implementation, deployment or merging.
