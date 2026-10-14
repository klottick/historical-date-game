# Guest-play isolated verification

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

## Remaining gates

The preserved hundred-card pointer-drag fixture assertion intermittently failed
when several browser suites were stressed concurrently. The unchanged full
fixture suite passed when run separately. This timing concern is retained for
review; no retries, skips or assertion weakening were used to conceal it.

Physical devices, LAN behavior on actual hardware, HTTPS/Secure-cookie production
configuration, production backup/activation, hosting, invitations and deployment
remain separate owner-controlled gates. Browser identity is not person-level
anti-cheat. Clearing cookies or changing browser/site address loses guest access.
