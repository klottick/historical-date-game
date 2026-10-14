# Compact game-board verification

The miniature event timeline uses actual-card input and preview-only movement.
Only **Lock it in** scores. Confirmed cards stay fixed; a failed placement is
displayed at its persisted attempted position, separately from the correct marker.

## Isolated verification

Tasks 1–5 verification was confined to `.worktrees/board-redesign` without changing
the LAN-served guest-play/beta worktrees. The later reviewed local switch is
recorded below; neither original worktree's served code was edited. The finite `board` verification profile
uses only the explicitly owned `historical_date_game_board_test` and
`historical_date_game_board_fixture_test` databases. Retain them after verification.
Do not run cleanup/pytest or reseed while browser/API consumers use them.

Backend environment (B), from `backend/`:

Use the locked Python `>=3.15,<3.16` and Node `26.11.1` toolchain; no upgrades.

```sh
export HDG_VERIFICATION_PROFILE=board POSTGRES_DB=historical_date_game_board_test
export POSTGRES_SERVER=127.0.0.1 POSTGRES_PORT=5433 ENVIRONMENT=local
```

Frontend environment (F), from `frontend/`:

```sh
export HDG_VERIFICATION_PROFILE=board
export PATH=/tmp/opencode/node-v26.11.1-linux-x64/bin:$PATH
export REAL_CATALOG_RELEASE_DIR=/home/klottick/repos/historical-date-game/.worktrees/beta/data/game/releases/jsonl-trial-2026-10-12-review-r1
export REAL_CATALOG_API_ORIGIN=http://localhost:8020 REAL_CATALOG_UI_ORIGIN=http://localhost:5184
export BOARD_TEST_EVIDENCE_DIR=../.superpowers/sdd/2026-10-14-game-board-redesign/integration/task-5
```

Pass local test-admin credentials privately through the environment, not arguments
or documentation. Real verification SMTP is explicitly disabled before app imports;
fixture/reset tests use only an ownership-checked loopback Mailcatcher. Full backend
pytest uses the private `integration/task1-pytest.py` SMTP-before-import entrypoint.

The existing helper owns lifecycle and verifies cwd/command/PID start-time plus DB
comments before stopping. Use B `uv run python -m tests.browser.guest_test_environment`
with `seed-real --release "$REAL_CATALOG_RELEASE_DIR"`, `seed-fixture`,
`launch|stop --target real|fixture --component backend|ui`, and `audit --target ...`.
The real API/UI are `8020/5184`; fixture `8021/5173`; controlled board `5186`.
Never substitute the live `8010/5174` services.

## Test commands

Run backend full suite and lint first, before seeds or consumers:

```sh
uv run python ../.superpowers/sdd/2026-10-14-game-board-redesign/integration/task1-pytest.py -q
uv run bash scripts/lint.sh
```

Browser suites run **serially**, at least 300 seconds allowed per full suite, no
retries/skips. Node-only helpers verify R and choose indices; no hidden years or
answer maps enter page evaluation or the application bundle.

```sh
npx playwright test --config=playwright.guest-catalog.config.ts --workers=1 --retries=0 --reporter=line
VITE_API_URL=http://localhost:8021 npx playwright test --workers=1 --retries=0 --reporter=line
npx playwright test --config=playwright.real-catalog.config.ts --workers=1 --retries=0 --reporter=line
npx playwright test --config=playwright.board.config.ts --workers=1 --retries=0 --reporter=line
npx playwright test --config=playwright.bootstrap.config.ts --workers=1 --retries=0 --reporter=line
npx playwright test --config=playwright.identity.config.ts --workers=1 --retries=0 --reporter=line
npm run test:unit
npm run typecheck
npm run lint
npm run build
```

After real-suite setup, F `node tests-real-catalog/restart-probe.ts before`,
`node tests-real-catalog/restart-probe.ts restart`, then
`node tests-real-catalog/restart-probe.ts after` preserve the original authenticated
Daily/Freeplay active-state comparison and next correct moves. The new guest board
suite independently proves persisted attempted loss and identical operation replay.
The restart phase invokes only the ownership-checked helper with F's board profile.

B final release check (R is `REAL_CATALOG_RELEASE_DIR`):

```sh
uv run python -m app.content.cli verify --release "$REAL_CATALOG_RELEASE_DIR" --media "$REAL_CATALOG_RELEASE_DIR/media" --require-beta
```

## Recorded results

| Gate | Result | Exit |
| --- | --- | --- |
| Full backend, before seed/consumers | 1,082 passed; 110 inherited warnings | 0 |
| Backend lint | Passed | 0 |
| Full guest (three projects, including native insecure origin) | 48 passed | 0 |
| Full fixture (original journeys/recovery/modes) | 111 passed | 0 |
| Full real catalog | 11 passed | 0 |
| Controlled board / bootstrap / identity | 41 / 22 / 30 passed | 0 |
| Frontend units (including both runtime profiles) | 59 passed | 0 |
| Frontend types / lint / build; sealed release verification | Passed | 0 |
| Disabled and mismatched metadata API generations | Daily/Freeplay correct, loss, exact replay; two UI smokes | 0 |
| Authenticated before / owned restart / after probes | Identical DTOs, next correct moves in both modes | 0 |

All browser suites were serial, workers1/retries0, without skips. The two final
profile units fix a test-only runtime-path selector: the tested board path stays
unchanged, while the legacy guest/CI path is preserved without targeting its DB.
Intermediate failures and exact commands/exits/durations are retained in the private
Task5 report and create-only `integration/task-5/commands.jsonl`; none were hidden
by retries or removed assertions.

Final no-scroll screenshots are under private
`integration/task-5/guest-full-green/`: `*-daily-{start,preview,correct,loss}.png`
and `*-freeplay-{start,preview,correct,loss}.png`. Chromium IDs ending
`ba80aced5cb52b0ee392` and `c580b56a3454d8c907f8` are 1366×768 and 1920×900.
Document dimensions, scale1, scroll offsets0 and essential-control rectangles are
asserted without a scrolling/zoom helper. Long-run, retry/restart, image-fallback
and native identity-teardown evidence is retained alongside them.

HTTP proof verified all eight release-scoped hashes through API8020 and UI5184,
plus16 denials of **existing** private files through both owned UIs. A37-file build
contained0 tested private markers. Matching/disabled/mismatched sidecars used
distinct ownership-checked API generations; the metadata canary never appeared
in revealed DTOs. All owned consumers and the exact verified Mailcatcher container
were stopped; both owned board databases and private evidence were retained.

## Evidence and honest limits

Private command/exit/count logs, screenshots, DTO comparisons and release/sidecar
hash proofs remain under the plan's ignored `integration/` directory (0700;
files0600), not public assets. Required desktop surfaces are **1920×900** and
**1366×768 CSS pixels**, 100% zoom; no fullscreen, scroll helpers or zoom reduction.

Reviewed R contains 1,276 events; pinned manifest SHA-256:
`804ec52ccfc3e19cd955913b05cbfd59158f562408e45c1916fa8626d3ac50d3`.
Retained source `source-snapshots/onthisday/events.jsonl` SHA-256:
`0fd539accf6ee5f31ddbf374ce24398381f5ac51def4309ce4c93e46daed30db`;
normalized `events.jsonl` SHA-256:
`fe31289687a8ae1b1c34bd1ce034ca53f907c5e2d0d334214220578af74db13a`.
All 27 manifest files, including eight media files, are reverified unchanged.
Enrichment is supplemental, private and process-cached. Build into a new cache/output
with `uv run python -m app.content.event_links_cli build --release R --cache PRIVATE_CACHE --output PRIVATE_FILE`.
Relaunch only the owned real API with `GAME_EVENT_LINKS_FILE` and its verified
`GAME_EVENT_LINKS_SHA256`; never mutate a running loader cache or catalog/media.
Remote refusal produces original source-page fallbacks, not a gameplay dependency.
Actual-R build: exit0; **0 matched articles,1,276 source fallbacks,0 failed
requests** (781 canonical-unavailable,475 subject-unresolved,20 entry-unresolved).
All408 cached responses succeeded; canonical queries had incomplete continuation
evidence. Policy was not relaxed. Sidecar SHA-256:
`53da618a7ca6efc621296b0da429fa4c83caa906f3683b9375cb7c99302f9fcd`.
Automated real link coverage is source-page/provenance/attribution and pending
privacy coverage; article branches are covered by controlled DTOs, not real-R
article coverage.

The original displayed-slot-2 issue was not reproduced in Task3's old-UI trials.
New actual-card index1 regressions are verification, **not a proven diagnosis/fix
of that original report**. Native owner teardown still emits pinned React/dnd-kit
insertion-effect diagnostics. A minimal parent-layout cancellation attempt did not
eliminate the dependency-internal warning and was removed; no suppression/upgrade.
Scoring and exact uncertain-command retention are separately tested.

The integration-only mobile correction follows a keyboard-dropped card's actual
rectangle vertically after it moves from the dock into the stage, rounding fractional
CSS edges outwards. It does not scroll the horizontal stage, alter scoring/commands,
or add a desktop scrolling workaround. Actual mobile Daily supplied the failing
integration evidence; 1920×900 and 1366×768 remain no-scroll surfaces.

Physical devices, production deployment, and invitations remain unreached gates
requiring separate owner decisions. The controlled local switch is authorized by
the execution plan and completed after the independent code-review gates below.

## Verified local card-board lifecycle

The guarded helper is `backend/tests/browser/board_local_rollout.py`. On
**2026-10-14**, Phase B activated reviewed product HEAD **9d2c75d** for controlled
local play after Phase A/helper review, whole-branch review, one final fix wave and
its independent scoped re-review closed both blocking findings. The four pinned
native teardown diagnostics were independently accepted as nonblocking for LOCAL
delivery only; they were not suppressed or upgraded. This is not production approval.

Current UI: **http://192.168.1.214:5174**, also http://localhost:5174. API remains
`127.0.0.1:8010`; UI binds `0.0.0.0:5174`. Fresh owned records identify API PID
**1176900**, start ticks **15553453**, and UI PID **1176907**, start ticks
**15553507**, both with exact board-redesign cwd/argv/bind proof. They were left
running. These recorded PIDs are not future permission to signal without rechecking.

The wrapper loads the existing guarded rollout into a separate module namespace,
pins `.worktrees/board-redesign` and original `.worktrees/beta` source/media, and
uses fresh create-only ownership evidence at
`.superpowers/sdd/2026-10-14-game-board-redesign/local-activation/` (0700/0600).
It neither reads nor adopts old guest-play or stopped verification ledgers.
An occupied port without this generation's proven ownership is refused.

Default inspection, and start/stop without `--apply`, make no helper filesystem,
environment, database or process mutations. Inspection may read the database in
a read-only transaction and query IP/process ownership. Phase A used only pure
`--noconftest` tests; they remain safe independently of the retained live DB:

```sh
# From board-redesign/backend/; pure, no destructive DB fixture.
uv run pytest --noconftest tests/safety/test_board_local_rollout.py -q
```

For this switch, the original guest-play runner at private
`final-fix-evidence/local-lifecycle.py` freshly inspected and stopped only its
proved pair **585755/585762**, from `guest-play/backend/`, with exact live DB/IPv4
environment and `PYTHONPATH=.`. Both ports were then proven released before the
new wrapper's inspection/start. Original ledgers were retained, not adopted or
deleted; no old served code changed. Changed provenance always requires a halt.

For current read-only inspection from `board-redesign/backend/`, first recheck
the nonloopback IPv4 address; the example uses the address proved at activation:

```sh
POSTGRES_DB=historical_date_game_catalog_test \
POSTGRES_SERVER=127.0.0.1 POSTGRES_PORT=5433 ENVIRONMENT=local \
  .venv/bin/python -m tests.browser.board_local_rollout \
  --origin http://localhost:5174 --origin http://192.168.1.214:5174 \
  --event-links-file /home/klottick/repos/historical-date-game/.worktrees/board-redesign/.superpowers/sdd/2026-10-14-game-board-redesign/integration/task-5/event-links.json \
  --event-links-sha256 53da618a7ca6efc621296b0da429fa4c83caa906f3683b9375cb7c99302f9fcd
```

Both worktree flags remain available for explicit documentation, but only the
pinned beta/board paths pass. The DB name, owner/comment, selected manifest bytes,
release/count and endpoint guards are unchanged. Hostnames/IPv6 are refused.
The board requires existing revision **20261013_01** and that exact sole script
head, including a fresh check before the first start write. Its call to
`guest_local_rollout.start(..., upgrade_schema=False)` never invokes Alembic.
The legacy default remains `upgrade_schema=True`. A future schema change fails
closed; it needs isolated proof and review, not an automatic live migration.

After successful cold-start inspection, `--action start --apply` is the explicit
mutation mode used for this activation. **It is not a reusable restart command**:
this generation now owns existing outputs/processes, so another cold start must
refuse. It retains the exact API/UI binds, no-access-log API, real Vite
private-file denies/proxy, `hdg_guest_real`, exact current origins, disabled SMTP
and disabled public registration. With no sidecar arguments, enrichment is
explicitly disabled even if ambient settings contain it; ordinary source fallback
still works. To supply the Task 5 sidecar, append both:

```sh
--event-links-file /home/klottick/repos/historical-date-game/.worktrees/board-redesign/.superpowers/sdd/2026-10-14-game-board-redesign/integration/task-5/event-links.json \
--event-links-sha256 53da618a7ca6efc621296b0da429fa4c83caa906f3683b9375cb7c99302f9fcd
```

Supplied metadata must be a nonaliased mode-0600 file in this plan's private
mode-0700 integration tree; public paths, hardlinks/symlinks, digest mismatch,
duplicate JSON keys, unsafe links and wrong release/manifest/event/source binding
are refused. It is rechecked in the final cold-start preflight. Real-R coverage
remains **0 articles / 1,276 source fallbacks**, not verified article coverage.

The same explicit arguments with `--action stop --apply` stop only this new
generation: both PID/start-time/cwd/argv/port identities must pass before either
SIGTERM. Outputs are never overwritten or deleted to force a restart. Failed or
partial starts retain state/evidence and need a reviewed recovery decision; no
automatic reset/rollback/cleanup exists.

### Fresh Phase B results

Private one-shot proofs ran serially on the actual nonloopback origin, not test
ports, with locked Node26.11.1/Python3.15. Exact commands/exits are retained in
`integration/task6-phase-b/commands.jsonl` and the private `task-6-report.md`.

| Fresh local gate | Result | Exit |
| --- | --- | --- |
| Original inspect / owned stop / port release | Exact original provenance; both ports released | 0 |
| Board inspect / explicit start / final inspect | Verified private sidecar; existing current schema; **no migration** | 0 |
| Actual-IP Daily + Freeplay at 1920×900 and 1366×768 | Four complete desktop flows, 100% zoom, no page/native-stage scroll | 0 |
| Preview/re-pickup, scoring, loss/reload/replay/new Freeplay | Zero preview/navigation POSTs; 48 unique locks, four identical replays; correct streak11 then loss revision12 | 0 |
| Expanded overview and ordinary Tab/Shift+Tab focus | Painted-card marks agree; clipped inserted preview becomes fully visible, no scoring | 0 |
| Native insecure context | Native getRandomValues/IndexedDB; no randomUUID; two distinct no-login guests | 0 |
| Credits/source labels | Every displayed asset association; explicit source-page labels; follow-up13-card full source/39 media notice/26 lineage check | 0 |
| Media/privacy/security | 24 HTTP media hashes,28 **existing-file** denials; three-origin admin/signup/SMTP authorization checks | 0 |
| Read-only mutation/catalog audit | All2,148 existing rows unchanged; only2 guest owners/sessions,8 runs,56 expected operations added; zero unexpected changes | 0 |
| Final owned-pair proof | Exact new PID/start/cwd/argv/binds and current origins retained | 0 |

There are33 private screenshots (32 state/fit surfaces plus the full-credits
dialog), two private traces, public DTO/replay/command comparisons and hash-only
read-only DB proofs at mode0600 under mode0700 `integration/task6-phase-b/`.
Screenshot names are `<width>-<mode>-{start,preview,correct,overview-focus,credits-closed,loss,reload,new-freeplay}.png`.
Cookie checks require `hdg_guest_real`, HttpOnly, SameSite=Lax, games-only path,
non-Secure only for this local HTTP environment, and no administrator access.
No access-log HTTP lines were present after the probes. A private reader reproduced
the exact owned factory/environment and confirmed SMTP off, registration off and
loaded sidecar coverage **0 articles / 1,276 source fallbacks**.

One initial private HTTP probe used a reserved `.invalid` signup email and correctly
received422 validation before the disabled-registration handler. A diagnostic
confirmed the input issue; a valid example.com address then proved403 at all three
origins. No product change or assertion weakening was needed. All intermediate
logs were preserved. Sixteen browser diagnostics (router notices and expected
initial unauthenticated401s) remain recorded; there were zero page errors. Prior
native teardown diagnostics remain disclosed and unsuppressed, not claimed fixed.

All27 sealed manifest files plus the manifest itself and eight original public
runtime assets remained byte-identical; DB selection, schema, frozen Daily
definitions and existing answers were unchanged. No reseed/reselection/reset,
Alembic, destructive/integrated pytest or automatic rollback was run. The final
delta after reviewed HEAD9d2c75d is documentation-only; later helper/product changes
require scoped re-review and affected verification. Server-side LAN Chromium is
not a physical remote-device, spoken screen-reader, legal or production-security
certification. The old displayed-slot-2 issue remains undiagnosed, not a claimed fix.
No push/merge, public tunnel, production activation, worktree/evidence removal or
integrated pytest against the retained live database is authorized here.
