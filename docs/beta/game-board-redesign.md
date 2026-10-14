# Compact game-board verification

The miniature event timeline uses actual-card input and preview-only movement.
Only **Lock it in** scores. Confirmed cards stay fixed; a failed placement is
displayed at its persisted attempted position, separately from the correct marker.

## Isolated verification

This work is confined to `.worktrees/board-redesign`; it does not activate or alter
the LAN-served guest-play/beta worktrees. The finite `board` verification profile
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
the execution plan, but remains held at the independent code-review gate below.

## Draft local lifecycle — Phase A only

The guarded helper is `backend/tests/browser/board_local_rollout.py`. Phase A
delivers code, pure safety tests and this draft; **the card-board game has not been
activated locally**. The live guest-play API/UI at 8010/5174 remain unchanged.
Independent Task 6 and whole-branch review, including residual native teardown
diagnostic triage, must finish before any operational switch. This is review
sequencing, not an additional owner check-in or production approval.

The wrapper loads the existing guarded rollout into a separate module namespace,
pins `.worktrees/board-redesign` and original `.worktrees/beta` source/media, and
uses fresh create-only ownership evidence at
`.superpowers/sdd/2026-10-14-game-board-redesign/local-activation/` (0700/0600).
It neither reads nor adopts old guest-play or stopped verification ledgers.
An occupied port without this generation's proven ownership is refused.

Default inspection, and start/stop without `--apply`, make no helper filesystem,
environment, database or process mutations. Inspection may read the database in
a read-only transaction and query IP/process ownership. Phase A runs only pure
`--noconftest` tests, **not this operational inspection**:

```sh
# From board-redesign/backend/; pure, no destructive DB fixture.
uv run pytest --noconftest tests/safety/test_board_local_rollout.py -q
```

After the review gate, first inspect the actual old guest-play ownership via its
private `final-fix-evidence/local-lifecycle.py` and `local-activation/`, using the
original runner from `guest-play/backend/`. Stop only that proved pair, with the
exact live DB/IPv4 environment; verify both ports released. Never use the new
wrapper to stop or adopt the old pair. Changed provenance requires a halt.

For subsequent **post-review** inspection from `board-redesign/backend/`, substitute
the freshly verified nonloopback IPv4 address, not a historical IP:

```sh
POSTGRES_DB=historical_date_game_catalog_test \
POSTGRES_SERVER=127.0.0.1 POSTGRES_PORT=5433 ENVIRONMENT=local \
  uv run python -m tests.browser.board_local_rollout \
  --origin http://localhost:5174 --origin "http://<current-LAN-IP>:5174"
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
mutation mode. It retains the exact API/UI binds, no-access-log API, real Vite
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

Phase B must still prove fresh actual-IP no-login Daily/Freeplay, tile preview and
re-pickup, explicit scoring, persisted attempted loss/reload/replay, both no-scroll
desktop sizes, overview/credits/source labels, private-file/media security and
unchanged selected release/answers. Only verified owned services are left running.
The final activation commit must be documentation-only; a helper/product change
after whole-branch review requires scoped re-review and affected verification.
No push/merge, public tunnel, production activation, worktree/evidence removal or
integrated pytest against the retained live database is authorized here.
