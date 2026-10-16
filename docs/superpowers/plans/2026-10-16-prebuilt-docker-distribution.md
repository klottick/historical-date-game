# Prebuilt Docker Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users install the released game from downloaded configuration and prebuilt Linux amd64 images using only Docker Compose.

**Architecture:** One non-root application image serves the existing FastAPI API/media and compiled SPA. PostgreSQL remains separate; a one-shot `initialize` service uses the same application image before `app` starts. Read-only testing produces an image archive; a serialized publisher promotes that exact image without rebuilding.

**Tech Stack:** Python 3.15/FastAPI/SQLModel/Alembic, PostgreSQL 18, React/Vite/Node 26 builders, uv/npm lockfiles, Docker Compose, native amd64 GitHub Actions, GHCR.

**Spec:** `docs/superpowers/specs/2026-10-16-prebuilt-docker-distribution-design.md` (approved).

## Global Constraints

- **Support Linux amd64 only**. ARM images, ARM CI, emulation setup and multi-platform manifest assembly are out of scope.
- Users need Docker with Compose, not Git, source code, local builds, Python or Node.js.
- Image namespace: `ghcr.io/klottick/historical-date-game`.
- Preserve guest and account play, authoritative scoring, identity-bound recovery, exact command replay, Daily/Freeplay, protected administration and attribution.
- Do not change immutable catalogue bytes, historical sources or receipts.
- Never operate on existing LAN services, retained databases/volumes, unrelated Docker resources or the pre-existing modified `.env` during packaging verification.
- PostgreSQL remains a separate service; replacing it with SQLite is not an option.
- Reject missing, generated per-start or placeholder application secrets before migration or account creation.
- Application and initialization references resolve to the same exact release digest. PostgreSQL is independently pinned.
- No automatic gameplay reset, catalogue replacement, ownership repair, database-major upgrade or schema rollback.
- Run browser checks with zero retries, retaining first-failure traces rather than accepting flaky success.
- No privileged host emulation installation is permitted. Do not call the reference publisher unchanged.
- Only an explicitly published, non-draft, non-prerelease canonical stable release (`vMAJOR.MINOR.PATCH`, without leading zeroes) can initiate publication.
- Never silently overwrite an existing exact version tag. Refresh eligibility on every publishing-job attempt.
- Attach `compose.yaml`, non-hidden `env.example`, `INSTALL.md`, `image-digest.txt` and a checksum manifest.
- Ask separately before pushing, merging, creating tags/releases or changing package visibility.

## Review Focus

1. Adding canonical `compose.yaml` must not redirect existing implicit development/test commands into persistent release volumes (Task 4).
2. HTTP loopback origin/port changes, HTTPS secure cookies and spoofed forwarding headers must not break guest identity or bypass origin checks (Tasks 1 and 3).
3. Replacing containers or restoring private backups must retain identities, gameplay, catalogue selection and historical media without root permission workarounds (Task 3).
4. An old publishing-job retry, moved tag or ambiguous registry failure must not overwrite a version or move `latest` backwards (Tasks 5 and 6).
5. A missing asset, encoded traversal or failed initialization must not become SPA HTML/healthy status, leak catalogue answers or reset gameplay (Tasks 1–3).

## File and interface map

| Files | Responsibility |
| --- | --- |
| `backend/app/distribution/{__init__,__main__,config,startup,web}.py` | Release-only configuration, command dispatch, initialization/readiness and static serving |
| `Dockerfile`, `.dockerignore`, `docker/python-build-constraints.txt` | Root release image and isolated dependency build inputs |
| `compose.yaml`, `env.example` | Source-free installation contract |
| `scripts/distribution/{__init__,smoke,backup,release,registry,publish,assets,acceptance}.py` | Focused Docker probes, in-container backup/restore, release validation, registry promotion, asset attachment and post-release acceptance |
| `scripts/distribution/tests/test_{runtime,image,smoke,backup,ci,release,registry,publish,assets,acceptance}.py` | Unit/contract tests, separate from destructive backend pytest fixtures |
| `frontend/playwright.distribution.config.ts`, `frontend/distribution/game.spec.ts` | Browser smoke against the built release server, no Vite server |
| `.github/workflows/{test-distribution,release-image}.yml` | Native amd64 image CI and release validation/build/publication/attachment |
| Existing CI, development entry scripts and operator docs | Explicit development Compose selection and preserved application tests |
| `INSTALL.md`, `docs/verification/docker-distribution.md` | Shipped operator guide and actual evidence/limitations |

New release/runtime tests use standard-library `unittest` from the repository root;
they must not trigger `backend/tests/conftest.py` or real DB connections. Test
subprocesses receive synthetic explicit environments before importing app settings.
Only the integration smoke owns real disposable resources. YAML contracts may use
PyYAML from backend development dependencies. Add no runtime dependency for testing.

## Task 0: Establish clean public ancestry and baseline

**Files:** Transfer only this plan and its approved spec into a clean feature lineage from public `main`; keep the original worktree/history intact.

**Interfaces:** Produces a workspace on `feature/prebuilt-docker-amd64`, based on verified public `main`, plus an ignored execution ledger `.superpowers/sdd/2026-10-16-prebuilt-docker-distribution/progress.md`.

- [ ] **Step 1:** At execution handoff, resolve the existing-worktree skill constraint: the current worktree is isolated but its branch has private history. Request consent for a separate clean worktree if not already granted; never switch/reset the dirty worktree. Create the clean branch from current fetched public `main`, copy only the spec/plan, and verify `git merge-base HEAD origin/main` equals its base. Do not cherry-pick private ancestry.
- [ ] **Step 2:** Record original worktree tips/status, private `.env` checksum, live process identities and protected resource names in the ignored ledger; record only hashes/identities, never secret values. Do not copy the real `.env` to the clean workspace.
- [ ] **Step 3:** With execution approval, install locked development dependencies and run the existing frontend lint/typecheck/unit/build and backend lint/pure tests. Run the full backend/browser baseline only through fresh owned disposable resources using the proven CI preparation sequence; never run legacy teardown scripts against retained stacks. Record actual commands/results; investigate baseline failures before implementation.
- [ ] **Step 4:** Commit only the transferred spec/plan on the clean branch. The new branch must contain public ancestry plus these reviewed documents, not earlier private feature commits. No push.

## Task 1: Release-only configuration, startup, readiness and static serving

**Files:** Create `backend/app/distribution/{__init__,__main__,config,startup,web}.py`; create `scripts/distribution/__init__.py` and `scripts/distribution/tests/test_runtime.py`. Reuse, do not weaken, `app/backend_pre_start.py`, `app/initial_data.py`, `app/game/runtime_catalog.py`, `app/main.py` and existing Alembic migrations.

**Interfaces:**
- `config.validate_environment(environment: Mapping[str, str]) -> None`: stdlib-only checks before importing settings; raise sanitized `ValueError` identifying fields, not their values.
- `startup.initialize() -> int`: validate, verify inputs/storage, wait for DB, upgrade Alembic, call existing initial-data and initialize-only catalogue functions; return zero only on success.
- `startup.check_ready() -> None`: fail on inaccessible DB, schema not at packaged head, absent/unusable selected catalogue or missing/invalid selected media; never write rows.
- `web.create_app(frontend_dir: Path) -> FastAPI`: release adapter around existing routes/middleware, explicit static boundary and `GET /healthz` (200 or sanitized 503).
- `python -m app.distribution {initialize,serve,healthcheck}`: default `serve`; `serve` validates then execs one Uvicorn worker on `0.0.0.0:8000`, without reload or trusted forwarded headers. `healthcheck` probes local `/healthz`, exiting nonzero on failure.

- [ ] **Step 1:** Write `test_missing_or_placeholder_secrets_refuse_before_settings_or_db`, `test_origin_and_mode_are_consistent`, `test_initialize_failure_never_serves_or_resets`, `test_readiness_is_read_only_and_reports_503`, and `test_spa_fallback_never_captures_api_media_or_secrets`. Assert required `SECRET_KEY` ≥32 characters, `POSTGRES_PASSWORD` ≥20, `FIRST_SUPERUSER_PASSWORD` ≥12; reject blank/whitespace and `changethis`. Require project, DB endpoint/user/name, admin email, `FRONTEND_HOST`, and explicit `ENVIRONMENT`. Accept an exact HTTP(S) origin without credentials/path/query/fragment; staging/production require HTTPS. Preserve existing guest origin/header checks.
- [ ] **Step 2:** Run `PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s scripts/distribution/tests -p test_runtime.py -v`; observe named failures for missing modules/behavior without opening a DB.
- [ ] **Step 3:** Implement configuration/startup and CLI interfaces. Use Alembic's Python API and existing init/install functions in the one-shot process, avoiding a subprocess supervisor. Validate the bundled catalogue and writable initializer storage before mutations; preserve migration refusal and initialize-only selection. `app` never migrates, initializes accounts or writes media. Initialization uses a cooperative per-database advisory lock and documented single-installation ownership, not forced termination of consumers.
- [ ] **Step 4:** Implement static serving limited to real built output: immutable caching for fingerprinted assets; no-cache HTML; fallback only for actual SPA routes from `frontend/src/routeTree.gen.ts`. Assert 404 for missing `/assets/*.js`, `/api/missing`, `/media/missing`, `/catalogue/default.json`, `/.env`, `/app/...`, `/@fs/...`, encoded dot/slash/backslash traversal and symlinks. Preserve genuine `/api/v1/*` routes, API 404s and existing no-store middleware. Test local/HTTPS cookie attributes through existing session handler with mocked dependencies; do not weaken cookie rules.
- [ ] **Step 5:** Rerun the Task 1 command; expect all named tests green. Run `uv run bash scripts/lint.sh` from `backend/` and Ruff checks/format on new scripts; verify existing app-only imports do not mount the SPA.
- [ ] **Step 6:** Commit explicit Task 1 paths: `feat: add isolated release runtime and readiness`.

## Task 2: Production image and pull-only Compose

**Files:** Create `Dockerfile`, `.dockerignore`, `docker/python-build-constraints.txt`, `compose.yaml`, `env.example`, `scripts/distribution/tests/test_image.py`. Preserve existing service Dockerfiles.

**Interfaces:** Image layout `/app/backend`, `/app/frontend/dist`, `/opt/python`, `/opt/venv`, data root `/data`; UID/GID `10001:10001`. Runtime `WORKDIR=/app/backend`, `PYTHONPATH=/app/backend`, `GAME_DATA_DIR=/data`. Compose variables `HDG_IMAGE` (complete image reference), `HDG_BIND_ADDRESS=127.0.0.1`, `HDG_PORT=8000`; required app settings from Task 1. Default command uses Task 1 CLI; initializer overrides command to `initialize`.

- [ ] **Step 1:** Write `test_release_compose_is_pull_only_and_internal_db_is_unpublished`, `test_application_and_initializer_use_identical_reference`, `test_context_excludes_nested_credentials_and_private_worktrees`, and `test_runtime_contains_only_expected_artifacts`. Include hostile nested `.npmrc`/`.env` and sentinel raw-data files in a task-owned copied build context and assert they are absent from built layers/runtime. Require all licence/catalogue notices, no build tools/dev dependencies/tests, numeric non-root user, exec-form command and native extension imports.
- [ ] **Step 2:** Run image contract tests with the Task 1 unittest pattern changed to `test_image.py`; observe missing-artifact failures. Resolve and record actual registry digests for Debian trixie-slim, Node `26.11.1`, uv `0.13.0` and PostgreSQL `18.6`; do not invent digest placeholders. Pin managed CPython `3.15.0` and record exact isolated build dependencies needed by locked source distributions in the build-constraints file.
- [ ] **Step 3:** Implement stages: Node frontend with `npm ci`/empty `VITE_API_URL`; Debian Python builder with fixed uv-managed install directory, `uv sync --frozen --no-dev --no-editable`, pinned isolated build constraints and compiler; compatible slim runtime copying interpreter/environment and explicit app/migration/catalogue/static/licence files. Exclude all private context first. Run dependency consistency/native-import checks in the runtime, not just the builder. Build-time credentials, if ever needed, use secrets, not ARG/ENV/COPY.
- [ ] **Step 4:** Implement three Compose services and two named volumes (`postgres-data`, `game-data`). Initialize the empty `/data` image directory as UID 10001 for volume copy-up; initializer mounts RW, app RO. DB mounts `/var/lib/postgresql`; it has no published port. Set readiness dependencies, 30-second stop grace and `restart: unless-stopped` for app/DB, not initializer. Expose only `${HDG_BIND_ADDRESS}:${HDG_PORT}:8000`. Use explicit environment allowlists and required interpolation; blank template secrets and `HDG_IMAGE` deliberately prevent accidental unconfigured startup.
- [ ] **Step 5:** Build `docker build --platform linux/amd64 --build-arg VERSION=unreleased --build-arg VCS_REF=$(git rev-parse HEAD) -t hdg-distribution-local:check .`, capturing full build log. With synthetic private env in an empty directory, run `docker compose --env-file <fixture> -f compose.yaml config --quiet`. Expect valid configured render, invalid missing-secret render, native imports and image checks passing. This is not publication or a real-release claim.
- [ ] **Step 6:** Commit explicit Task 2 paths: `build: package non-root amd64 release image and compose stack`.

## Task 3: Real smoke, persistence, backup/restore and browser checks

**Files:** Create `scripts/distribution/{smoke,backup}.py`, `scripts/distribution/tests/test_{smoke,backup}.py`, `frontend/playwright.distribution.config.ts`, `frontend/distribution/game.spec.ts`, and initial `INSTALL.md` backup/restore instructions. Include only `backup.py` as `/app/backup.py` in the runtime image.

**Interfaces:**
- `python scripts/distribution/smoke.py --image REF --platform linux/amd64 --evidence-dir PATH [--install-dir PATH]`: consume an already-built image and staged/downloaded installation files, never build; nonzero on failure; ownership-check all resource removal; write sanitized logs and `result.json`.
- `python /app/backup.py {export-media,restore-media} --root /data`: binary archive through stdout/stdin, no host Python dependency. Restore rejects symlinks, absolute/traversal members, unexpected paths and nonempty destination; uses non-root ownership and private modes. Streams backups, never prints credentials.
- `frontend` browser probe consumes `DISTRIBUTION_BASE_URL`; no `webServer`, Vite, seeded synthetic browser DB or retry.

- [ ] **Step 1:** Write unit tests `test_smoke_preserves_failure_logs_before_owned_cleanup`, `test_cleanup_refuses_foreign_labels`, `test_smoke_never_builds_or_reuses_services`, `test_restore_refuses_nonempty_or_unsafe_archives`, and `test_backup_streams_preserve_private_permissions`. Simulate failed image start, interrupted probe, cleanup error and missing evidence root; the original failure remains visible and cleanup cannot turn failure into success.
- [ ] **Step 2:** Run the Task 1 unittest command for `test_smoke.py` and `test_backup.py`; confirm expected red behavior, then implement resource lifecycle and stream interfaces. New projects get UUID names and exact tracked labels/IDs, fresh secrets, dynamically selected loopback ports and their own volumes. No broad prune, default-project teardown, retained paths or privileged containers.
- [ ] **Step 3:** Implement actual Compose/HTTP smoke against the bundled 1,276-event catalogue. Use `/api/v1/games/session` with `Origin`, `X-Game-Request: 1`, cookie jar and returned `X-Game-Context`; start Daily/Freeplay with protocol 2 and UUID operations, check correct and incorrect moves, third-mistake loss, unchanged score on mistakes, streak zero and exact replay. Read answers only through a private container-side verifier, never an added public endpoint. Verify other-owner 404s, login/admin authorization, answer-free pending payloads, attribution and real media bytes.
- [ ] **Step 4:** Add config/storage/catalogue/migration failure cases and local HTTP exact-origin tests, HTTPS secure-cookie behavior, foreign origins and spoofed forwarded headers. Test the existing populated legacy migration refusal in a separate new cluster/schema prepared at `20261013_01`; never invoke reset helpers. Snapshot state before refusal and prove it unchanged. Test readiness drops when its owned DB/media is unavailable and recovers without data loss.
- [ ] **Step 5:** Exercise same-secret replacement of both app and DB containers, initializer rerun and preservation of every persisted row plus selected/old media hashes. Freeze app writes; run documented `pg_dump --format=custom` using the DB container and media export using the app image; preserve `.env` privately. Restore to a second owned fresh project before initializer startup, reject nonempty DB/media destinations, then prove original sessions, account credentials, operation replay, Dailies and media survive. Test PostgreSQL restore as well as media restore; never pretend deleting a populated destination is restore preparation.
- [ ] **Step 6:** Implement zero-retry Chromium desktop/mobile-viewport smoke on the actual compiled UI: guest start/move/reload, login/admin boundary, credits/assets, no JS errors or overflow. Run `DISTRIBUTION_BASE_URL=<owned-origin> npx playwright test --config=playwright.distribution.config.ts --retries=0` from `frontend/`. Check native runtime `uname`, graceful app/DB stops within 30 seconds with expected clean exit codes and no OOM/SIGKILL.
- [ ] **Step 7:** Rebuild after including the backup helper; run `python3 scripts/distribution/smoke.py --image hdg-distribution-local:check --platform linux/amd64 --evidence-dir <new-private-path>` and the browser command, then repeat from a directory containing installation files only. Deny runtime content-network access while retaining private DB/loopback access; passing source acquisition is not required or allowed at startup. Record actual results/limitations before cleaning exact owned resources.
- [ ] **Step 8:** Commit explicit Task 3 paths: `test: verify release gameplay persistence and recoverable backups`.

## Task 4: Preserve development CI and add read-only amd64 distribution CI

**Files:** Create `.github/workflows/test-distribution.yml`, `scripts/distribution/tests/test_ci.py`; modify `.github/workflows/{test-backend,lint-backend,playwright,test-docker-compose,deploy-production}.yml`, `frontend/playwright.config.ts`, `scripts/{test,test-local}.sh`, `scripts/test_workflow_contracts.py`, relevant CI-contract tests and `development.md`, `backend/README.md`, `frontend/README.md`.

**Interfaces:** Development CI explicitly selects `docker-compose.yml:docker-compose.override.yml` via `COMPOSE_FILE`; generated fixture overrides append their third file. Release CI explicitly uses the new `compose.yaml`. `test-distribution.yml` supports `workflow_call`, PR and `main` push; read-only permissions, `persist-credentials: false`, native `ubuntu-24.04`, no publishing. Optional reusable input `release-version: string = unreleased`; successful release builds upload `tested-image` with `image.tar`, `image.json` (image ID/revision/version/platform), and checksum.

- [ ] **Step 1:** Write `test_new_compose_never_changes_development_file_selection`, `test_release_event_never_deploys`, `test_pr_container_jobs_are_read_only_native_amd64`, `test_browser_failures_are_not_retried`, `test_failed_smoke_cannot_upload_eligible_image`, and `test_failure_diagnostics_precede_cleanup`. Update the old workflow test that currently requires release-triggered production deployment; it must now require manual-only staging and production.
- [ ] **Step 2:** Run `backend/.venv/bin/python -m unittest discover -s scripts/distribution/tests -p test_ci.py -v` plus `backend/.venv/bin/python scripts/test_workflow_contracts.py`; observe the expected missing workflow/old trigger failures. Render legacy Compose with synthetic settings after the new canonical file exists; assert services/ports/mounts correspond to the legacy stack, not `app`/`initialize`.
- [ ] **Step 3:** Implement explicit development selection and manual production trigger. Keep CI-owned project uniqueness/DB ownership guards. Set zero retries both in browser config and invoking jobs; upload first-failure traces, build/smoke logs and backend failure logs using always-run steps. Set read-only permissions on application test workflows, with only job-specific action-required read permissions; no blanket write grant or `pull_request_target` code execution.
- [ ] **Step 4:** Adapt local development test entry scripts so they explicitly select legacy files and cannot run inherited broad volume deletion or recursive host cleanup against retained projects. Require a clearly disposable test project and verified ownership for any destructive cleanup; stop/refuse when safety cannot be proved. Do not execute their historical unsafe bodies as a baseline.
- [ ] **Step 5:** Implement native build/smoke/browser job using Tasks 2–3. Upload tested archive only after all smokes succeed and only for release workflow calls; PR diagnostic artifacts are separate and never publishable. Run all contract tests, frontend unit checks, legacy-render checks and actionlint against every edited/new workflow; execute a fake failing smoke through the actual workflow shell block and prove its nonzero exit propagates.
- [ ] **Step 6:** Commit explicit Task 4 paths: `ci: validate amd64 distribution without deployment or write credentials`.

## Task 5: Fail-closed release metadata, registry checks and immutable assets

**Files:** Create `scripts/distribution/{release,registry,assets}.py`, `scripts/distribution/tests/test_{release,registry,assets}.py`.

**Interfaces:**
- `release.validate_release(current: dict, history: list[dict], expected_id: int, expected_sha: str, tag_sha: str, on_main: bool) -> str`: canonical version without `v`; malformed/ineligible/stale source raises `ValueError`.
- `release.refresh_release(repository: str, release_id: int, expected_sha: str) -> str`: fresh complete GitHub release history and tag/main resolution every invocation; propagate HTTP/parse/pagination failures. CLI `python -m scripts.distribution.release check --repository REPO --release-id ID --expected-sha SHA` emits machine-readable eligible version only.
- `registry.manifest(image: str, reference: str, token: str) -> tuple[str, bytes, str] | None`: return digest/raw bytes/media type; `None` only on explicit authenticated `MANIFEST_UNKNOWN`; validate digest/body agreement; all other errors fail. Token acquisition uses ephemeral workflow credentials, no logged secrets.
- `registry.require_absent_version(image: str, version: str, revision: str, token: str) -> None`: refuse existing stable version or conflicting pre-existing SHA tag; registry uncertainty is refusal.
- `assets.write_bundle(source: Path, destination: Path, version: str, revision: str, digest: str) -> dict[str, str]`: generate exact install filenames and SHA256s with complete image reference `ghcr.io/klottick/historical-date-game:VERSION@sha256:...`; blank secrets; fail on conflicting output.
- `assets.attach_bundle(repository: str, release_id: int, directory: Path) -> None`: identical existing assets are no-op; mismatches fail, never `--clobber`.

- [ ] **Step 1:** Write table-driven metadata tests for canonical versions, `v01.0.0`, prereleases/drafts, malformed history, paginated newer releases, wrong release ID, moved/deleted tag, wrong source/main ancestry and an old failed publisher retry after a newer stable release. Stub fresh API responses, not cached validation outputs. Registry tests cover existing tags, 401/403/404-with-wrong-code/429/500, timeouts, invalid JSON, missing token and digest mismatch. Every uncertainty must forbid publication.
- [ ] **Step 2:** Run the three named unittest files and observe red. Write bundle tests asserting precisely `compose.yaml`, `env.example`, `INSTALL.md`, `image-digest.txt`, `SHA256SUMS`, same app/initializer digest, no leading-dot assets/secrets, and identical-versus-conflicting asset retry behavior.
- [ ] **Step 3:** Implement interfaces using stdlib HTTP/JSON/hash utilities and complete paginated GitHub responses. Check stable ordering numerically, not lexically; ignore clearly identified noncanonical historical tags but never malformed metadata. Validate canonical current tag, current live release ID, exact tag SHA and reachability from freshly resolved `main`; annotated tags must be peeled to commits. Reject source reuse with conflicting immutable image identity.
- [ ] **Step 4:** Implement deterministic asset rendering from exact source templates; `HDG_IMAGE` is pinned in the generated `env.example` and the shared Compose reference. Never ship build previews as release bundles. Verify idempotent uploads by byte hash, refusing mismatch and unexpected filenames.
- [ ] **Step 5:** Run all Task 5 tests green, including the actual validator CLI against a local HTTP fixture server with failing later pagination and moved-tag responses. No real release creation/registry writes. Commit explicit paths: `feat: guard stable releases and render immutable install assets`.

## Task 6: Publish the tested image and verify real release installations

**Files:** Create `.github/workflows/release-image.yml`, `scripts/distribution/{publish,acceptance}.py`, `scripts/distribution/tests/test_{publish,acceptance}.py`. Reuse Task 4 workflow and Task 5 interfaces.

**Interfaces:**
- `python -m scripts.distribution.publish --archive PATH --metadata PATH --repository REPO --release-id ID --expected-sha SHA`: verify archive checksum, source/platform/version labels and loaded image ID; refresh eligibility and registry absence; push tested image, record exact digest and tag results in `publication.json`. No build operation is permitted.
- `python -m scripts.distribution.acceptance --repository REPO --release-tag TAG --expected-sha SHA --evidence-dir PATH`: anonymous registry/download probes and Task 3 installation smoke; never builds, deploys to retained stacks, creates releases or changes visibility.

- [ ] **Step 1:** Write `test_publisher_loads_only_this_runs_successful_image`, `test_no_registry_write_after_stale_retry_or_failed_smoke`, `test_archive_and_loaded_image_identity_must_match`, `test_promotion_uses_identical_manifest_bytes`, `test_partial_publication_is_not_blindly_retried`, and `test_asset_only_retry_does_not_republish`. Exercise actual shell/control flow with fake Docker/API boundaries, including nonzero smoke and registry failures; assert no `build`, no untested archive and no overwrite path.
- [ ] **Step 2:** Run Task 6 unit tests red. Implement a serialized `release: published` workflow: `validate` runs fresh eligibility/application checks; `image` calls the read-only tested-image workflow; `publish` downloads that successful same-run artifact with `packages: write`; `attach` alone has `contents: write`. All checkouts use the immutable event SHA and non-persisted credentials. Pin action commits; never consume PR artifacts or `workflow_run` artifacts as trusted images.
- [ ] **Step 3:** Implement publication. Login with token on stdin; verify loaded image ID against metadata, labels and native `linux/amd64`. Refresh eligibility/absence before registry writes. Push a unique run-specific staging reference once; fetch its manifest and confirm config digest equals tested image ID. Recheck eligibility immediately before stable aliases, then PUT exactly the same manifest bytes/media type to version, full-SHA and latest references. Check every resulting digest equals the staging digest; do not create an index or rebuild. Log partial tag outcomes without credentials and retain `publication.json` on failure.
- [ ] **Step 4:** Implement attachment using verified version/source/digest evidence, not publishing again. On attachment retry re-query release/tag/image identity; if newer releases exist, do not change latest or republish the older version. Already-attached identical bytes pass; conflicting bytes stop. Document operator inspection/explicit repair for staging-only or partly promoted failures; no automatic deletion or rollback.
- [ ] **Step 5:** Implement acceptance using a newly created mode-0700 empty `DOCKER_CONFIG`, no inherited auth config/helper and anonymous HTTP. Download assets/checksums, compare version/SHA/latest and platform/config identity, pull exact digest and install from that empty directory. Pass installed files to Task 3 smoke for replacement and documented backup/restore; keep synthetic credentials out of artifacts. Registry access denied is an unmet acceptance gate, not an instruction to change visibility.
- [ ] **Step 6:** Run publish/acceptance tests and actionlint green; use a task-owned local mock registry/API to prove failure behavior and identical manifest promotion without writing GHCR. Commit explicit Task 6 paths: `ci: publish exact tested release images with guarded retries`.

## Task 7: Operator guide, whole-change verification and gated publication handoff

**Files:** Complete `INSTALL.md`; update `README.md`, `deployment.md`, `SECURITY.md`, `docs/operations/catalogue.md`; create `docs/verification/docker-distribution.md`. Adjust relevant source-doc instructions, not historical evidence/specs unrelated to this feature.

**Interfaces:** Shipped instructions match Tasks 2–3 CLI and asset names. Verification report distinguishes local native amd64, actual hosted amd64 and real released-image acceptance; unexecuted gates are explicitly unverified.

- [ ] **Step 1:** Add doc contracts to `test_assets.py`/`test_backup.py` asserting install uses downloaded attachments, `env.example` copied to `.env`, only Docker/Compose required, exact digest pin, loopback defaults, no DB port and destructive-volume warnings. Extract the documented backup/restore command blocks in tests and execute them on owned smoke installations; reject diverging undocumented procedures.
- [ ] **Step 2:** Complete installation, secret generation via image, origin/HTTP/HTTPS/SMTP configuration, UID permissions, logs/readiness, stop/start, updates and old migration refusal guidance. Document PostgreSQL dump + old media + `.env` backup, restore into fresh isolated volumes, no schema rollback/PG major auto-upgrade, and partial-publication recovery. State Linux amd64-only and actual authentication/TLS/rate-limit/proxy limitations. Public source repo does not imply public GHCR.
- [ ] **Step 3:** Run `PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s scripts/distribution/tests -v`, workflow contracts, app mypy/Ruff/format, frontend lint/typecheck/unit/build, full isolated backend and zero-retry browser suites. Rebuild the final source once locally and run full image/browser/source-free/persistence/restore/shutdown smoke. Run actionlint, `git diff --check`, context/layer privacy audit and compare immutable catalogue hashes against the recorded public base. Record every result and any unverified gate.
- [ ] **Step 4:** Request one fresh read-only whole-change review after execution, focusing on this plan's five Review Focus cases, actual release shell failure propagation, absence of private ancestry/secrets and preservation evidence. Fix material findings with observed regression failures and rerun affected/full gates. No independent agents are dispatched during this planning phase.
- [ ] **Step 5:** Commit reviewed implementation/docs locally. Stop and ask before pushing/opening the chosen remote review flow. After an approved push, inspect actual read-only hosted CI rather than infer success. Ask separately before merging and before creating the selected tag/stable release; do not choose/publish a version implicitly.
- [ ] **Step 6:** Only after approved release creation, inspect the actual release workflow and run Task 6 anonymous downloaded-asset acceptance. Ask separately if public package visibility must change. Report published version/full SHA/digest, real hosted results, backup/restore and persistence evidence, security limits, deferred findings and every incomplete verification. Never deploy the app as part of image publication.

## Execution recommendation and self-review

Recommend **Native execution**: the tasks share runtime, Compose, smoke and release
interfaces closely; implementing inline avoids repeated context transfer. One fresh
whole-branch review remains mandatory. Subagent-driven execution is also available
if the user prefers independent review after each task.

Self-review: spec sections map to Tasks 0–7; every Review Focus case has named
tests; all cross-task commands/interfaces above are defined; amd64-only applies
throughout. No source/application code is changed by this plan. Exact image digests
are resolved and recorded during Task 2 rather than guessed in documentation.
Remote CI, release execution, anonymous GHCR pulls and downloaded release assets
cannot be claimed verified before their separately approved external operations.
