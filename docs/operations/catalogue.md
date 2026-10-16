# Portable historical catalogue

The committed default is `chronology-1276-runtime-v2`: 1,276 events (1,271
chronology events and five birth supplements), eight original CC0 fallback SVGs,
and no photographs. The backend image includes `backend/catalogue/` at
`/app/catalogue`; raw inputs and audit workspaces are not runtime dependencies.

**Required workflows: offline play, and public sources → a new valid dataset.**
Exact recreation of the old catalogue is optional, not a release prerequisite.
The `fresh` command below needs no existing dataset, private cache or original
receipt. Historical receipt/supplement files remain on Mustafar; no archive upload
is required. They are needed only for optional exact historical replay, and must
not be fabricated or silently replaced inside that replay workflow.

The immutable v1 bundle and assets are retained byte-for-byte. Its historical
recipe is tied to its original code version. Both committed recipes are now
historical: v1 matches code at `4b96e38`, v2 at `8b2c862`. New builder changes do
not rewrite either immutable bundle or pretend those code pins still match.
v2 preserves every event/source/media field, and newly seals the shared Daily
playability gate and standalone export's locked-date verification. Existing
selected catalogues are still never implicitly upgraded.

## Run and verify without content-network access

Install Python and dependencies first (dependency/image installation can require
network access). From `backend/`:

```bash
uv sync --frozen
```

Then, with content-network access denied, verify the default pointer, its pinned
manifest, every payload/asset, licences, references and beta eligibility. This
command needs neither `.env`, PostgreSQL nor source inputs:

```bash
.venv/bin/python -c 'from pathlib import Path; from app.content.runtime import verify_default; print(verify_default(Path("catalogue")).manifest.model_dump_json())'
```

The explicit release CLI is also available; supply the reviewed manifest digest
from `catalogue/default.json` (not a digest obtained from an untrusted download):

```bash
MANIFEST_SHA=$(.venv/bin/python -c 'import json; print(json.load(open("catalogue/default.json"))["manifest_sha256"])')
.venv/bin/python -m app.content.cli runtime-verify \
  --release catalogue/releases/chronology-1276-runtime-v2 \
  --media catalogue/media/chronology-1276-runtime-v2 \
  --expected-sha256 "$MANIFEST_SHA" --require-beta
```

For a **new, operator-owned database**, configure the normal application settings
and credentials (see [deployment](../../deployment.md)). With PostgreSQL running,
from `backend/`:

```bash
source .venv/bin/activate
bash scripts/prestart.sh
.venv/bin/fastapi run app/main.py --host 0.0.0.0 --port 8000
```

Activate the environment first (`source .venv/bin/activate`) for the prestart
script's `python` and `alembic` commands. Prestart waits for the DB, migrates,
creates the initial account, then initializes the catalogue. To perform only the
catalogue step against an already migrated database:

```bash
.venv/bin/python -m app.game.runtime_catalog initialize
```

Initialization verifies the bundle and provisions assets before DB insertion. It
selects the default only when no catalogue is selected; otherwise it reports the
actual existing selection. It does **not** silently upgrade a selected catalogue.
Only this explicit command authorizes changing selection:

```bash
.venv/bin/python -m app.game.runtime_catalog install --catalogue catalogue
```

`--catalogue` names a catalogue root containing a reviewed `default.json`, not an
audit release. Conflicting immutable IDs/assets fail closed. Old runs, Dailies,
catalogues, media, accounts and credentials are not deleted. The separate
three-life schema migration still refuses populated gameplay; stop and plan a
separate migration, **do not reset/delete gameplay to bypass the refusal**.

### External media roots: the same storage for both processes

Without an override, `GAME_DATA_DIR` is the internal absolute catalogue root.
When overridden, assets are installed into `$GAME_DATA_DIR/media/<release-id>/`.
Prestart and backend must use the **same root and shared mount**, not merely the
same directory spelling in two isolated container filesystems. Keep old releases'
assets there too if old games reference them. Real files are required; symlink
aliases and conflicting existing bytes are rejected. Request handlers never copy
or download media.

For example, save this as an operator-local `catalogue-volume.yml` at the repo
root (do not commit operator configuration/secrets):

```yaml
services:
  prestart:
    environment:
      GAME_DATA_DIR: /var/lib/historical-date-game
    volumes:
      - catalogue-media:/var/lib/historical-date-game
  backend:
    environment:
      GAME_DATA_DIR: /var/lib/historical-date-game
    volumes:
      - catalogue-media:/var/lib/historical-date-game:ro
volumes:
  catalogue-media:
```

Prestart writes checked assets; backend reads the same volume. The packaged
verification source remains `/app/catalogue`. On an operator-controlled stack,
after reviewing `.env`, ports, database ownership and existing mounts, use the
same Compose file set for every operation:

```bash
docker compose -f docker-compose.yml -f catalogue-volume.yml config
docker compose -f docker-compose.yml -f catalogue-volume.yml up -d --build
```

If explicitly selecting a new bundle on this read-only-backend configuration,
run the installer with the writable **prestart** service and the same volume:

```bash
docker compose -f docker-compose.yml -f catalogue-volume.yml run --rm prestart \
  python -m app.game.runtime_catalog install
```

These are deployment instructions, not authorization to alter an existing live
stack. Do not mount raw sources as static content. Only qualified digest-named
assets are HTTP media; manifests, events/answers, build locks and notices are not
HTTP-static files. Answers are deliberately present in the public Git catalogue;
pending gameplay responses must still hide the selected answer and run ordering.

### Clean-checkout acceptance (disposable resources only)

`tests/api/routes/packaged_runtime_acceptance.py` is a **standalone acceptance test**,
not an ordinary shared-fixture API test. It requires the exact owned lives-profile
database below, loopback port 5433, zero consumers and an entirely empty schema.
It runs the real prestart twice and leaves its rows intact for inspection. Never
point it at an existing installation, run it with the default DB settings, or
combine it with tests that initialize/clean the same schema. Its filename keeps
it out of default pytest discovery without silently skipping an acceptance gate.

To repeat the container proof without touching a Compose stack:

1. Export the reviewed Git commit to a new empty directory using `git archive`.
   Exclude the root `.env` explicitly (it is tracked in the current base); do not
   copy a working directory, `.git`, worktrees, ignored data or source archives.
   Build the **unmodified** `backend/Dockerfile` from that export's `backend/`
   context. Dependency downloads/build caches are allowed only at build time.
2. Give the image and every container unique names and an ownership label. Record
   their full IDs, not just names. In a container with no settings/envfile, mounts
   or DB, run this against that image with `--network none`:

   ```bash
   python -c 'from pathlib import Path; from app.content.runtime import verify_default; s=verify_default(Path("catalogue")); assert s.manifest.event_count == 1276; print(s.manifest.release_id)'
   ```

3. Create a **new** `postgres:18.6` container with `--network none`, no published
   ports and `--tmpfs /var/lib/postgresql` (no retained data mount). Start it with
   `postgres -p 5433`. Generate a strong temporary PostgreSQL password, application
   secret and initial-account password; pass them as environment variables, never
   print them or reuse deployment credentials. Initially use `POSTGRES_DB=postgres`
   for the PostgreSQL container, not the application's disposable DB name.
4. Create backend test containers using only
   `--network container:<recorded-postgres-container-id>`, no port publications or
   filesystem mounts. Set these application variables, plus the generated secrets:

   ```text
   ENVIRONMENT=local
   HDG_VERIFICATION_PROFILE=lives
   POSTGRES_SERVER=127.0.0.1
   POSTGRES_PORT=5433
   POSTGRES_DB=historical_date_game_lives_backend_test
   POSTGRES_USER=<the new PostgreSQL container's user>
   PROJECT_NAME=Packaged catalogue acceptance
   FIRST_SUPERUSER=acceptance@example.com
   ```

   Do not override `GAME_DATA_DIR`: this checks the actual packaged default.
   After PostgreSQL readiness, create/mark the absent DB with the existing helper
   **inside that image**, so the ownership marker matches its worktree identity:

   ```bash
   python -c 'from app.core.config import settings; from tests.browser.guest_test_environment import prepare_database, require_owned_guest_database; assert prepare_database(settings.POSTGRES_DB); require_owned_guest_database()'
   ```

5. In a new backend container with that same environment/network namespace, run:

   ```bash
   python -m pytest tests/api/routes/packaged_runtime_acceptance.py -q
   ```

   This exercises actual migrations/account/catalogue initialization, public
    options without identity/session row allocation, guest identity, Daily/Freeplay moves, owner-bound reads/retries,
   answer-free pending cards, source/CC0 credits, exact qualified media bytes,
   backend static/traversal denial and complete row preservation on repeat prestart.
   The shared network namespace has only loopback: DB access works, but no
   external source-content network is available. No Uvicorn/live API is needed.
6. Clean up only the exact task-created IDs after rechecking their ownership labels
   and names. Stop the task DB, remove its containers, then remove only the unique
   task image after checking its ID/label. Do not use Compose teardown, broad prune,
   forced DB drops or retained-volume cleanup.

The existing pure `tests/content tests/game tests/safety` suites run separately
from the exported repository (some compare packaged policy with tracked research
docs). Before those tests, run `git init --quiet` in the exported root to provide
fresh empty Git metadata for ignore-policy checks; otherwise Git can inherit an
enclosing checkout's ignore rules. Do not copy the original `.git` metadata.
Runtime verification and the image acceptance need no Git metadata.
Existing synthetic API tests also need those tracked docs; the standalone
image acceptance above does not. Guarded catalogue/API verification excludes the
unrelated `test_migration_round_trip_on_owned_fixture_database`, which creates a
separate random database. That exclusion is not a full backend/public-CI pass.

Frontend development-server verification is separate: check real catalogue files
through `/@fs/` and encoded traversal, in normal and alternate configurations,
without changing/restarting an existing server. Expected direct-file denials are
403; some malformed encoded paths instead return the SPA HTML homepage (200),
which is not disclosure. Check the response bytes/content type, not status alone.
No frontend gameplay mutation is required for this filesystem-boundary check.

## Build a new dataset from public sources

From `backend/`, after `uv sync --frozen`:

```bash
BUILD=../data/catalogue-build
OUT="$BUILD/fresh-2026-10-16-a"
.venv/bin/python -m app.content.rebuild_cli fresh \
  --output "$OUT" --release-id chronology-fresh-2026-10-16-a
```

Choose a new, nonexistent output directory and unique release ID each time. No
lock template, old catalogue, local source files, `.env`, database or source cache
is required. The command fetches the three checksum-pinned public chronology
objects directly over HTTPS, records a **new truthful download receipt**, and
runs the existing whole-input importer, quarantine/conflict checks, media,
full-source publisher/verifier and runtime/Daily playability checks. HTTP errors,
redirects, oversized/corrupt responses or validation failures stop the build;
retry explicitly into a new output. Source pins are an integrity policy, not a
promise to recreate an old game release or follow upstream's latest branch.

The current chronology normally yields about **1,271 events**, with eight CC0
fallback illustrations and no photographs. It omits the five old birth
supplements, so **Births has no events**. Category/year coverage is reported in
`build-report.json`; this does not promise balanced coverage or usable Freeplay
in every selected interval. At least 1,000 accepted events and a playable proper
Daily subset are still required. Counts/content may change with evaluation date
or reviewed code/source updates; no equality with the 1,276-event default is
required. The default itself is not changed.

Output:

```text
inputs/                   # newly downloaded public sources and receipt
workspace/                # whole raw corpus, quarantines and media evidence
audit/<release-id>-audit/ # independently verified full-source release
catalogue/                # standalone runtime root, assets, notices and default.json
build-report.json         # actual counts, coverage, hashes and limitations
```

Only `catalogue/` is a distributable runtime bundle. Keep inputs/workspace/audit/
reports ignored, outside Git and the backend Docker context. Every record retains
source attribution; adapted text remains CC BY-SA 4.0 and artwork CC0. Verify the
new output without content-network access or a DB:

```bash
.venv/bin/python -c 'import sys; from pathlib import Path; from app.content.runtime import verify_default; print(verify_default(Path(sys.argv[1])).manifest.model_dump_json())' "$OUT/catalogue"
```

`fresh` creates a default pointer **only inside its new output**. It never writes
the committed default, activates a DB, resets games or changes a running service.
After separately reviewing the result, an operator may use the existing explicit
`runtime_catalog install --catalogue "$OUT/catalogue"` command with the intended
database/settings and shared-media storage. Preserve old games and assets.

Fresh-generation verification on 2026-10-16 used a clean code directory without
a catalogue, source cache, `.env` or Git metadata and fetched the actual three
public objects. It produced 1,271 accepted events from 19,860 raw rows and eight
assets. Offline runtime verification and the shared game rules started active
Daily (1,003 eligible events) and Freeplay (1,271). This is build/runtime/rules
evidence, not a database installation, deployment or complete CI claim.

### Optional exact replay of your new build

The generated `chronology-fresh-v1` lock records current code/dependencies, actual
source bytes and evaluation date. With the same code/toolchain you can replay
**this generation**, retaining its four input files and new receipt:

```bash
FRESH_LOCK="$OUT/catalogue/releases/chronology-fresh-2026-10-16-a/build.lock.json"
.venv/bin/python -m app.content.rebuild_cli reproduce \
  --lock "$FRESH_LOCK" --sources "$OUT/inputs" \
  --output "$BUILD/optional-replay-a" --expected "$OUT/catalogue"
```

No legacy supplements are required. Replay keeps strict byte comparison and code
pins; do not edit fingerprints to conceal a changed recipe. Losing the receipt
does not prevent a **new** fresh build; it only prevents exact replay of that
particular generation. Replay does not activate a database or write a default.

## Optional historical acquisition/replay (matching old code required)

The instructions below describe exact replay of the old 1,276-event catalogue,
not the zero-dataset workflow above. Use an isolated checkout of the original
recipe implementation (`8b2c862` for v2, `4b96e38` for v1) and its locked
toolchain. The current builder deliberately rejects those historical code pins.
This limitation is not a fresh-build blocker; no archive publication is planned.

All commands below run from `backend/`, using the checked-out recipe code and
the exact Python/dependency versions in `build.lock.json`. Code/config fingerprints
include `app/content`, the pure shared Daily configuration/rules/types/policy,
`pyproject.toml` and `uv.lock`, but exclude generated data.
A mismatch fails before fetching/building; reproduction never repairs a stale lock.
Keep **all** raw data, caches, archives, workspaces and reports under the ignored
repository-root `data/catalogue-build/`, outside Git and the backend Docker context.

```bash
LOCK=catalogue/releases/chronology-1276-runtime-v2/build.lock.json
BUILD=../data/catalogue-build
mkdir -p "$BUILD"
.venv/bin/python -m app.content.rebuild_cli acquire \
  --lock "$LOCK" --output "$BUILD/acquired-public"
```

**That public-only command cannot currently acquire the complete source set.** It
fails preflight on a source with `url: null`, even if a cache exists; an explicit
checked local source directory is required for this recipe.
Acquisition supports only individual HTTPS files on `raw.githubusercontent.com`,
without redirects. It does **not** download/extract archives and does **not**
support GitHub release-asset URLs (or their redirects). Publishing an archive
later would not alone add a supported automatic download route: that requires a
separately reviewed acquisition change/recipe. No archive availability is promised.

If you possess the exact retained source inputs, prepare a **flat directory**
containing exactly these five real files, with no additional notice/metadata file
or chronology subdirectory:

```text
events.jsonl             # all 19,860 chronology rows, not accepted events
README.md               # original chronology README
NOTICE.md               # original chronology NOTICE
download-receipt.json    # original historical observation, unmodified
supplements.jsonl        # all five original raw envelopes and source evidence
```

Every byte size/SHA-256 must match the lock. Do not edit the receipt to describe
today's retrieval. Fresh acquisition evidence is written beside the output as
`<output>.acquisition.json`, not inside it; checked cache objects live in its
parent's `source-cache/`. Explicit checked local acquisition:

```bash
.venv/bin/python -m app.content.rebuild_cli acquire \
  --lock "$LOCK" --source-dir "$BUILD/local-inputs" \
  --output "$BUILD/acquired-local"
```

The complete scope is 19,865 raw inputs, not just the 1,276 passing records. The
supplement envelope schema is `source_id`, `record_id`, `payload`; payload retains
entity, page, milestone and original evidence, **not** acceptance decisions or
copied approved event rows. A source-only archive, if separately approved, must
retain chronology README/NOTICE and supplement source/licence notices alongside
the five-file input directory. Inspect any externally supplied archive safely
before preparing local files; the CLI performs no archive extraction. Current
availability remains local-only, without publication or a public legal-clearance
claim.

### Historical reproduction: no database, no default change

Given complete checked local inputs, reproduce twice into different nonexistent
output directories:

```bash
.venv/bin/python -m app.content.rebuild_cli reproduce \
  --lock "$LOCK" --sources "$BUILD/acquired-local" \
  --output "$BUILD/reproduce-1" --expected catalogue
.venv/bin/python -m app.content.rebuild_cli reproduce \
  --lock "$LOCK" --sources "$BUILD/acquired-local" \
  --output "$BUILD/reproduce-2" --expected catalogue
```

Each uses a fresh importer generation, the entire raw input set, media validation,
the full nonfixture publisher and beta verifier under evaluation date
`2026-10-12`, then create-only runtime export and offline verification. Runtime
metadata uses the locked release timestamp, not today's acquisition time. The
original audit ID/digest is historical provenance; each fresh audit digest/time is
recorded separately in ignored `replay-report.json`.

Standalone `app.content.cli runtime-export --release <verified-audit> --media
<audit-media> --output <new-catalogue-root> --lock "$LOCK"` also establishes the
lock's evaluation date for full audit verification, then restores the caller's
context on success or failure. New acquisitions and unlocked audit verification
continue to use the actual current date; old fingerprints are never exempted.

Comparison includes **every runtime byte**, including the lock, manifest,
timestamps, attribution and asset bytes; there are no exclusions. A mismatch
reports differing filenames and added/removed/changed event UUIDs, exits nonzero,
and refuses export when payload pins disagree. No database is activated and no
committed file/default pointer is modified. Outputs are create-only: use a fresh
path for retries. A local two-build match does not prove independent public fetch.

### Historical update candidate: separate review, never an automatic upgrade

Copy the lock outside Git. Explicitly choose a new immutable release ID and
release metadata, reviewed source pins/policy, evaluation context and current
toolchain/code fingerprints. Empty `payload_sha256` is permitted **only** for
candidate sealing; `reproduce` requires the complete map. Helpers for recording
current recipe fingerprints are `app.content.rebuild.code_fingerprints()`,
`dependency_versions()` and `python_version()`. Do not disguise changed code as
the old recipe or alter retained original evidence.

```bash
cp "$LOCK" "$BUILD/candidate.lock.json"
# Edit candidate.lock.json deliberately as described above; never edit the default.
.venv/bin/python -m app.content.rebuild_cli update-candidate \
  --lock "$BUILD/candidate.lock.json" --sources "$BUILD/new-local-inputs" \
  --output "$BUILD/new-candidate"
```

The output bundle contains the **complete sealed lock**, not the empty input
template. Review changed/missing/added events, source/asset rights, complete
acceptance evidence and privacy, then reproduce using that sealed lock. Copy only
reviewed final release/media files into the distribution. Changing `default.json`
and its manifest digest is a separate intentional Git review; installation with
`install` is a separate operator action. Never reuse an ID or remove assets still
referenced by retained games. No release upload, push or deployment is implied.

## Attribution and trust boundary

Catalogue text adapted from Wikipedia contributors via
[mneedham/wikipedia-onthisday](https://github.com/mneedham/wikipedia-onthisday)
retains **CC BY-SA 4.0**, source links/contributor histories and modification
notices. Structured Wikidata content is CC0; supplements retain their per-record
Wikipedia/Wikidata source credits. Original geometric fallback artwork is CC0
1.0, with per-asset metadata in `media.json`. Application code is separately MIT.
See each release's `LICENSE.catalog.txt`, `NOTICE.catalog.md` and
`attribution.json`; preserve these and per-record source/asset credits when
redistributing. The pinned dataset is not a promise of pinned Wikipedia article
revisions. No author/Wikimedia endorsement or blanket legal clearance is claimed.

Runtime verification checks integrity and supported semantics anchored in the
reviewed Git/default digest; it does not independently establish historical truth
or upstream copyright ownership. Full raw-source validation is a distinct build
gate. Raw source archives need their own privacy/licence review before any
separately authorized publication. Existing CI/publication prerequisites are not
resolved merely by packaging this catalogue.
# Prebuilt distribution boundary

The root `compose.yaml` is the pull-only release installer; source/development
commands in this guide must explicitly select the legacy Compose files, never
rely on automatic discovery. See [INSTALL.md](../../INSTALL.md) for the released
image layout (`/app/backend/catalogue`), UID `10001`, shared `/data` volume,
read-only serving and the tested PostgreSQL/media/private-environment backup.
Its initializer verifies the packaged catalogue offline and preserves any existing
selection; it never rebuilds data, upgrades the selected catalogue or resets
gameplay. Keep historical media releases for old runs and receipts. A populated
legacy three-life migration refusal requires a separately reviewed migration or
recovery of its matching backup, not deletion of retained state.
