# Prebuilt Docker distribution — Linux amd64

## Status and intent

The user approved the proposed application/PostgreSQL architecture and phased
scope, with one explicit reduction: **support Linux amd64 only**. ARM images,
ARM CI, emulation setup and multi-platform manifest assembly are out of scope.
The user approved this written specification after the amd64-only correction.
Detailed planning is authorized; implementation and publication retain their
separate approval gates.

Users download attached release configuration into an empty directory, copy
`env.example` to `.env`, configure credentials and run Docker Compose. They need
Docker with Compose, not Git, source code, local builds, Python or Node.js.

### Workflow checklist

- [x] Inspect this repository and the immutable reference project.
- [x] Present architecture options and phased scope; receive conversational approval.
- [x] Incorporate the user's amd64-only correction.
- [x] Write and self-review this specification.
- [x] Receive approval of this written specification.
- [ ] Write the detailed implementation plan and agree its execution method.
- [ ] Implement and verify locally; request permission before external publication.
- [ ] Verify hosted CI and the real release only after their separate approvals.

## Existing system and preservation boundaries

The backend uses Python 3.15, FastAPI, SQLModel, Alembic and PostgreSQL-specific
JSONB, locks and constraints. PostgreSQL remains a separate service; replacing it
with SQLite is not an option. React/Vite produces static frontend files. There
is no required Redis instance, task worker or frontend runtime server.

Startup currently waits for PostgreSQL, applies migrations, creates the initial
administrator only when absent, and installs the verified bundled catalogue only
when no catalogue is selected. Preserve those behaviors and existing migration
refusals. In particular, populated pre-three-life gameplay must stop the migration;
packaging must never erase gameplay to get past that boundary.

Preserve guest and account play, authoritative scoring, identity-bound recovery,
exact command replay, Daily/Freeplay, protected administration and attribution.
Do not change immutable catalogue bytes, historical sources or receipts. Never
operate on existing LAN services, retained databases/volumes, unrelated Docker
resources or the pre-existing modified `.env` during packaging verification.

The current isolated source branch contains private unpublished history, although
its committed tree matches public `main`. Before implementation, arrange a clean
feature lineage from public `main`; transfer only reviewed new documentation/code,
not private feature history. Keep the current worktree and its user state intact.

## Architecture

Provide a single application image at
`ghcr.io/klottick/historical-date-game` and a pull-only root `compose.yaml`:

| Service | Responsibility | Persistent storage / exposure |
| --- | --- | --- |
| `db` | Pinned PostgreSQL 18 patch/image digest with readiness check | Named PostgreSQL volume; no host port |
| `initialize` | One-shot validation, migration, initial administrator and conservative catalogue/media initialization | Same app image; writable named media volume; no port |
| `app` | Existing API/media plus compiled SPA, one application server process | Same media volume read-only; loopback HTTP port by default |

The frontend consists of static files, so serving it from the application process
does not require combining independent daemons or introducing a supervisor.
Keep the release serving adapter separate from the development application entry
point. No Nginx, Traefik, Adminer, Mailcatcher or language build tools are required
in a released installation. External SMTP is optional configuration, not a bundled
dependency. One installation owns its database/media volumes; automatic scaling or
concurrent migrations from multiple installations are unsupported.

The alternative is separate web/API/database services and two application images.
It preserves the existing Nginx split but adds image coordination and proxy setup
without a required frontend runtime; it was not selected.

### Dockerfile and build context

Add a root multi-stage Dockerfile and restrictive `.dockerignore`. Build frontend
assets with `npm ci`; build target-architecture Python dependencies using the
committed `uv.lock` with frozen, production-only installation. Pin the exact Python
3.15 runtime and build-tool versions and pin base-image digests. Keep compiler
toolchains in builder stages. Copy the managed interpreter at a consistent path
along with its environment rather than leaving references into builder caches.

Native Python dependencies include `mwparserfromhell`, psycopg-binary, Pillow,
Argon2/bcrypt, pydantic-core and Uvicorn extensions. `mwparserfromhell` currently
requires compilation on Python 3.15; verify the resulting extension and shared
libraries in the runtime. npm's native build tooling must be installed inside the
builder, never copied from the developer's `node_modules`. Only Linux amd64 needs
to build and execute successfully.

The runtime uses a fixed non-root UID/GID, contains application code, migrations,
compiled frontend, verified catalogue and attribution, but no Node/npm, compiler,
test suite, development dependencies, secrets, preinitialized database, source
inputs or developer caches. Include all required licence/notices despite general
documentation exclusions. Label the source repository, version and full commit.

Exclude credentials at every depth, `.env` variants, `.npmrc`, VCS/worktree data,
private evidence, local environments, dependency trees and generated test outputs.
Use explicit runtime copies as well as ignore rules. Reproducible dependency
selection is required; bit-for-bit rebuild identity across different dates is not
claimed. Publication identity comes from promoting the tested image without rebuild.

### Compose, configuration and initialization

Released Compose contains `image:` references only: no build contexts, source
mounts, external Traefik network or Docker socket. Application and initialization
references resolve to the same exact release digest. PostgreSQL is independently
pinned. Do not set an overriding user that breaks the official PostgreSQL image's
documented first-run permission initialization.

Require private persistent application/database/admin credentials, project name,
public frontend origin and documented deployment mode. Reject missing, generated
per-start or placeholder application secrets before migration or account creation.
Do not rely on `ENVIRONMENT=local` permitting the existing `changethis` defaults.
Do not bake credentials or user configuration into image layers or install assets.
Document generating secrets using the prebuilt image so a host language runtime
is unnecessary. Unix install directories and `.env` should be private.

Same-origin relative API/media URLs allow one frontend build for any installation
origin. Keep existing origin checks and cookie behavior: loopback HTTP uses local
mode; HTTPS hosting uses secure guest cookies and the correct exact frontend
origin. Do not trust arbitrary forwarded headers. Public hosting requires separate
TLS/proxy/access-control decisions; packaging is not their replacement.

`initialize` waits for a healthy DB, validates configuration and storage, then runs
the existing guarded migration/account/catalogue sequence. It writes only checked
assets to the shared media volume, never replaces existing immutable bytes or
silently changes catalogue selection. Initialize a fresh named volume with correct
non-root ownership; never recursively relabel existing user storage to hide errors.

`app` depends on successful initialization and healthy PostgreSQL, checks its
runtime inputs and executes Uvicorn without reload or a shell supervisor. Its
readiness must check database access and usable selected catalogue/media state,
not just return the existing unconditional health boolean. Do not expose private
data or exception details through readiness. Configure explicit termination grace
periods and verify clean SIGTERM handling. Initialization failure prevents serving.

### Static serving boundary

Serve built HTML and fingerprinted JS/CSS with correct content types and suitable
cache policies; HTML must not retain stale deployment references. Support SPA
navigation without converting missing JS, unknown API/media paths, documentation
routes or traversal attempts into successful HTML responses. Never expose the
catalogue's answer-bearing payloads, manifests, environment files or application
source through the SPA mount. Preserve API private-response cache headers.

## Existing development and CI compatibility

Keep existing development Dockerfiles/Compose behavior available. Adding canonical
`compose.yaml` changes Compose's implicit file discovery: update affected CI,
scripts and development documentation to explicitly select the legacy development
files and their overrides, including generated disposable-fixture overrides.
Do not accidentally run source tests against the release Compose stack.

Preserve existing application tests. Explicitly use read-only PR permissions,
non-persisted checkout credentials and no publishing secrets. Ensure relevant
workflow path filters include new distribution files. Run browser checks with
zero retries, retaining first-failure traces rather than accepting flaky success.

Add one native Linux amd64 image build/smoke job, not an architecture matrix.
Use an amd64 GitHub-hosted runner and verify/log actual architecture. Preserve
build output, smoke/container logs and failure diagnostics with always-run artifact
steps before scoped cleanup. No `pull_request_target` execution of PR code with
write credentials, privileged containers or emulation registration is needed.

## Reference publisher assessment

Inspected the reference at immutable commit
`f454814674b008a7101e932e0cc07219186abcdc`, including Dockerfile, ignore rules,
Compose, CI/release/reusable publisher, smoke script and install/recovery docs.
Its reusable workflow is callable at that full SHA; its publisher blob also matches
the earlier documented `41af090209bf25666410809a976e3d8bcb2baa41` pin.

Do not call it unchanged: it unconditionally installs arm64 QEMU using privileged
containers, even if its platform input selects amd64 alone. Keep publication local
and adopt its useful separation of caller validation, real smoke commands,
retry-time release checks, fail-closed registry probing and tested-image promotion.
No reference Django, SQLite, family configuration or Gunicorn dependency is copied.

## Stable release and image publication

Only an explicitly published, non-draft, non-prerelease canonical stable release
(`vMAJOR.MINOR.PATCH`, without leading zeroes) can initiate publication. Make the
existing production deployment workflow manual-only before any packaging release;
an image release must never deploy a service. Preserve manual staging as well.

Serialize releases for this repository. Validate the event's release identity,
current live release metadata, exact immutable event commit, tag resolution and
that the source is on public `main`. Compare semantic versions against complete
paginated published stable-release history; reject older/equal releases. Missing,
malformed or unavailable metadata is an error, not permission to publish.

Use three responsibilities: validation/application tests; read-only native amd64
build/smoke and image archive; then minimally privileged publication. Save the
successfully tested image with its image ID and archive checksum. The publisher
loads and verifies that same-run artifact and source/version labels. It never
builds. Failed smokes do not produce an eligible publication artifact.

On **every publishing-job attempt**, including failed-job retries with reused
earlier outputs, refresh current release history, tag/source and eligibility before
registry writes. Check for an existing exact version tag and conflicting SHA tag.
Only an authenticated, explicit registry manifest-not-found result establishes
absence; authentication, network, rate-limit, server and malformed-response errors
fail closed. Never silently overwrite an existing exact version tag.

Push the tested image once, then promote its exact digest to `MAJOR.MINOR.PATCH`,
`sha-<full-commit-sha>` and `latest`. Verify all three resolve to the same digest.
No multi-platform index is needed. The labels and attached digest must identify
the exact tested source/version. Do not silently overwrite a conflicting SHA tag.

Tag updates are not atomic. Preserve run-specific image/archive/digest evidence and
document inspecting all tags after partial failure. Never blindly rerun publication
or delete/rewrite a version tag. An asset-only failure retries only attachment,
verifying the existing published digest/source before attaching. Any actual registry
repair outside that path requires an explicit reviewed operator action.

## Release assets and operator documentation

Attach `compose.yaml`, non-hidden `env.example`, `INSTALL.md`, `image-digest.txt`
and a checksum manifest. All assets come from the release source and reference its
exact version/digest; templates contain empty secrets. Existing assets must either
match the expected bytes or cause refusal rather than silent clobbering.

Document download/copy/configure/pull/up, readiness/log inspection, supported Linux
amd64 containers, configurable loopback port, exact-origin HTTP/HTTPS differences,
non-root permissions and optional SMTP. ARM, 32-bit Linux and native Windows
containers are unsupported. macOS/Windows require an appropriate Linux-container
VM; any amd64 emulation there is not claimed as native verified support.

Document stop/start/down versus destructive volume removal, backup before updates,
and downloading the new pinned bundle before `pull`/`up`. Existing selected
catalogues/media remain intact. No automatic database-major upgrades or schema
rollback: returning to an older image can require its matching pre-upgrade backup.

Backup must cover a consistent PostgreSQL dump, the media volume including old
releases, and private `.env`/configuration, using commands in shipped containers.
Stop application writes while capturing the combined snapshot. Restore first into
a new isolated installation with fresh volumes; refuse nonempty destination state.
Use host stdin/streams where appropriate so private host backups need not be made
world-readable to container UIDs. Preserve secrets so credentials/sessions remain
usable. Test the documented commands, not a separate undocumented restore path.

Security documentation must distinguish the existing account/admin authentication
from guest identity. Docker adds neither authentication nor TLS. Loopback binding
reduces default exposure but does not secure untrusted public hosting. Database
credentials, application tokens and environment are accessible to the Docker host
administrator. Do not claim new rate limiting, brute-force protection, secure proxy
deployment or independent security certification.

## Verification and acceptance

Use uniquely named/labelled task-owned resources, fresh credentials and dynamically
allocated loopback ports; never reuse retained services or broad prune commands.
Collect diagnostics before stopping/removing exact task-owned containers. Preserve
unrelated builders, contexts, networks, images and volumes. No privileged host
emulation installation is permitted.

Local/native and CI/native amd64 smokes must exercise:

- Non-root runtime, required compiled imports/shared libraries, no baked secrets,
  no host runtimes, actual built frontend/assets and safe SPA/404 boundaries.
- Fresh migrations/admin/catalogue startup and real readiness; offline catalogue
  use after image/dependency acquisition, with no source download during startup.
- Guest Daily/Freeplay moves, scoring/lives, owner-bound reads/replay, account login,
  protected administration and source/media/credits responses.
- Invalid/missing configuration, unusable storage, failed migration and conflicting
  immutable media/catalogue state stop serving without resetting user data.
- Existing populated legacy migration refusal, without destructive workaround.
- App and database container replacement retaining credentials, guest/account
  identity, gameplay, selected catalogue and media in named volumes.
- Documented backup/restore into fresh volumes, including preserved identities and
  gameplay, and refusal to restore over nonempty state.
- Graceful shutdown with expected exits, no forced termination hidden as success.
- Release guard regressions: malformed/out-of-order versions, moved tags, stale
  publishing retries, existing versions, ambiguous registry errors and partial
  publication; actual workflow failure propagation and no publication after red smoke.

After separate push/merge/tag/release approvals, complete actual remote acceptance:

1. Verify real PR CI and real release workflow logs, not just YAML contracts.
2. Pull anonymously using an empty private `DOCKER_CONFIG` with no credential
   helper inheritance. Confirm version/SHA/latest digest equality and amd64 platform.
3. Download attached installation assets into an empty directory with no source
   checkout. Check checksums; use the documented configuration and Compose commands.
4. Exercise real browser gameplay/account behavior, container replacement, clean
   shutdown and the documented backup/restore with the downloaded image/bundle.
5. Report exact commit/version/digest and evidence, and explicitly list any unmet
   gate. Public Git repository visibility alone does not establish anonymous GHCR
   accessibility; request approval before any package visibility change.

## Approval and scope boundaries

This is a packaging/distribution change, not a deployment or gameplay redesign.
No ARM jobs, QEMU, Kubernetes, new cache/worker, automatic reset, dataset rebuild,
unrelated refactor, live migration, new public hosting or release version selection.
The initial implementation phase remains local. Ask separately before pushing,
merging, creating tags/releases or changing package visibility. Approval of this
specification permits detailed planning, not those external operations.
