# FastAPI Project - Development

## Docker Compose

`compose.yaml` is the **pull-only release installer**, not the development stack.
In every development terminal (including ones used for logs/tests), select the
legacy development files explicitly before using the commands below:

```bash
ROOT=$(git rev-parse --show-toplevel)
export COMPOSE_FILE="$ROOT/docker-compose.yml:$ROOT/docker-compose.override.yml"
```

Do not use installer volumes for development or verification. Existing data and
running LAN services must remain untouched; never use volume pruning/reset as
test setup. See [INSTALL.md](INSTALL.md) for source-free releases.

### Owned test entry points

`scripts/test.sh` / `scripts/test-local.sh` no longer delete volumes or run host
`sudo` cleanup. They consume an **already prepared disposable** backend fixture
stack only. They require `HDG_CI_DISPOSABLE=true`, a unique project named
`hdg-devtest-` plus 32 lowercase UUID hex characters, and every container labelled
`hdg.devtest.owner` equal to that complete project name. Missing/foreign labels
refuse execution before backend tests. Preparation must use the existing exact
database-profile/ownership guards; never label a retained stack just to bypass a
refusal. These wrappers do not provision fixtures, build, stop or delete anything.
Use the explicit owned-fixture sequence in `.github/workflows/test-backend.yml`
as the reference for isolated verification, not an implicit local reset script.

Generated clients are checked, never pushed by PR CI; run
`uv run bash scripts/generate-client.sh` and commit generated changes yourself.

* Start the local stack with Docker Compose:

```bash
docker compose watch
```

* Now you can open your browser and interact with these URLs:

Frontend, built with Docker, with routes handled based on the path: <http://localhost:5173>

Backend, JSON based web API based on OpenAPI: <http://localhost:8000>

Automatic interactive documentation with Swagger UI (from the OpenAPI backend): <http://localhost:8000/docs>

Adminer, database web administration: <http://localhost:8087>

PostgreSQL is exposed on `localhost:5433` (containers use `db:5432`).
The stack uses PostgreSQL 18 with a new `app-db-data-pg18` volume, leaving
the old PostgreSQL 17 volume untouched. Development data is intentionally
not migrated. PostgreSQL 18 mounts its versioned data directory under
`/var/lib/postgresql`.

Traefik UI, to see how the routes are being handled by the proxy: <http://localhost:8091>

**Note**: The first time you start your stack, it might take a minute for it to be ready. While the backend waits for the database to be ready and configures everything. You can check the logs to monitor it.

To check the logs, run (in another terminal):

```bash
docker compose logs
```

To check the logs of a specific service, add the name of the service, e.g.:

```bash
docker compose logs backend
```

## Mailcatcher

Mailcatcher is a simple SMTP server that catches all emails sent by the backend during local development. Instead of sending real emails, they are captured and displayed in a web interface.

This is useful for:

* Testing email functionality during development
* Verifying email content and formatting
* Debugging email-related functionality without sending real emails

The backend is automatically configured to use Mailcatcher when running with Docker Compose locally (SMTP on port 1025). All captured emails can be viewed at <http://localhost:1080>.

## Local Development

The Docker Compose files are configured so that each of the services is available in a different port in `localhost`.

For the backend and frontend, they use the same port that would be used by their local development server, so, the backend is at `http://localhost:8000` and the frontend at `http://localhost:5173`.

This way, you could turn off a Docker Compose service and start its local development service, and everything would keep working, because it all uses the same ports.

For example, you can stop that `frontend` service in the Docker Compose, in another terminal, run:

```bash
docker compose stop frontend
```

And then start the local frontend development server:

```bash
cd frontend
npm run dev
```

Or you could stop the `backend` Docker Compose service:

```bash
docker compose stop backend
```

And then you can run the local development server for the backend:

```bash
cd backend
fastapi dev app/main.py
```

## Docker Compose in `localhost.tiangolo.com`

When you start the Docker Compose stack, it uses `localhost` by default, with different ports for each service (backend, frontend, adminer, etc).

When you deploy it to production (or staging), it will deploy each service in a different subdomain, like `api.example.com` for the backend and `dashboard.example.com` for the frontend.

In the guide about [deployment](deployment.md) you can read about Traefik, the configured proxy. That's the component in charge of transmitting traffic to each service based on the subdomain.

If you want to test that it's all working locally, you can edit the local `.env` file, and change:

```dotenv
DOMAIN=localhost.tiangolo.com
```

That will be used by the Docker Compose files to configure the base domain for the services.

Traefik will use this to transmit traffic at `api.localhost.tiangolo.com` to the backend, and traffic at `dashboard.localhost.tiangolo.com` to the frontend.

The domain `localhost.tiangolo.com` is a special domain that is configured (with all its subdomains) to point to `127.0.0.1`. This way you can use that for your local development.

After you update it, run again:

```bash
docker compose watch
```

When deploying, for example in production, the main Traefik is configured outside of the Docker Compose files. For local development, there's an included Traefik in `docker-compose.override.yml`, just to let you test that the domains work as expected, for example with `api.localhost.tiangolo.com` and `dashboard.localhost.tiangolo.com`.

## Docker Compose files and env vars

There is a main `docker-compose.yml` file with all the configurations that apply to the whole stack, it is used automatically by `docker compose`.

And there's also a `docker-compose.override.yml` with overrides for development, for example to mount the source code as a volume. It is used automatically by `docker compose` to apply overrides on top of `docker-compose.yml`.

These Docker Compose files use the `.env` file containing configurations to be injected as environment variables in the containers.

They also use some additional configurations taken from environment variables set in the scripts before calling the `docker compose` command.

After changing variables, make sure you restart the stack:

```bash
docker compose watch
```

## The .env file

The `.env` file is the one that contains all your configurations, generated keys and passwords, etc.

Depending on your workflow, you could want to exclude it from Git, for example if your project is public. In that case, you would have to make sure to set up a way for your CI tools to obtain it while building or deploying your project.

One way to do it could be to add each environment variable to your CI/CD system, and updating the `docker-compose.yml` file to read that specific env var instead of reading the `.env` file.

## Isolated test environment

Backend integration tests initialize the superuser and delete users/items at
session teardown. Never run them against development, staging, or production
data. The session fixture refuses database names that do not end in `_test`.
Backend and browser CI both use `historical_date_game_test` at job level so
Compose, migrations, and tests agree on the database.

Use a dedicated, execution-owned Compose project for local verification. For
the beta execution this project is `hdg-beta-baseline`; reuse its existing DB
and Mailcatcher rather than starting competing containers on the same ports.
On a fresh environment (with ports available), start only its test services:

```bash
POSTGRES_DB=historical_date_game_test docker compose -p hdg-beta-baseline up -d db mailcatcher
```

An existing PostgreSQL volume is not reinitialized by changing `POSTGRES_DB`.
Ensure the dedicated database exists in the execution-owned project before
migrating. Do not modify unrelated databases or delete volumes to create it.
Host commands use port `5433`; backend/prestart containers use `db:5432`.
Use the approved Python 3.15/uv toolchain and Node 26.11.1 for frontend checks.

```bash
cd backend
uv sync --frozen
# Safety tests override the destructive DB fixture; no PostgreSQL is needed.
uv run pytest tests/safety/test_db_guard.py -q
POSTGRES_DB=historical_date_game_test POSTGRES_PORT=5433 uv run bash scripts/prestart.sh
POSTGRES_DB=historical_date_game_test POSTGRES_PORT=5433 uv run bash scripts/test.sh
```

Run browser tests only after the backend test session has finished cleanup.
Seed the superuser again, then start a host backend against the same isolated
database with localhost Mailcatcher settings:

```bash
# From backend/, after backend tests have exited:
POSTGRES_DB=historical_date_game_test POSTGRES_PORT=5433 uv run python app/initial_data.py
POSTGRES_DB=historical_date_game_test POSTGRES_PORT=5433 \
  SMTP_HOST=localhost SMTP_PORT=1025 SMTP_TLS=false SMTP_SSL=false \
  EMAILS_FROM_EMAIL=noreply@example.com \
  uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal, use the frontend's matching Playwright Chromium binary
(`npx playwright install chromium` if needed), and run:

```bash
cd frontend
npm ci
npm run lint
npm run typecheck
npm run test:unit
npm run build
VITE_API_URL=http://localhost:8000 MAILCATCHER_HOST=http://localhost:1080 \
  npx playwright test --fail-on-flaky-tests
```

Do not run destructive backend pytest fixtures while the browser suite is
active. Shut down the host backend when finished and stop only owned services
with `docker compose -p hdg-beta-baseline stop db mailcatcher`. Never use broad
`docker compose down -v` cleanup or touch unrelated stacks/volumes.

## Game API, beta enrollment, and immutable media

`GET /api/v1/games/options` is public. Supported game operations accept either
account bearer authentication or the game-only guest cookie; account/settings
and administrator routes still require an account bearer. See
[guest-play operations](docs/beta/guest-play.md) for cookie/bootstrap boundaries. Commands
accept only the public DTO fields; answers, scores, seeds, pools, and ordering
remain server-side. Daily always uses the server's timezone-aware UTC date;
client day/seed/config inputs cannot select a scored attempt. Game service errors
use `detail: {code, message}` with 404 for missing/foreign runs, 409 for conflicting
operations or stale revisions, 422 for invalid commands, and 503 for unavailable
catalog/Daily policy. Missing credentials return 401.

`PUBLIC_REGISTRATION_ENABLED` defaults to `true` for local development and existing
tests. **Explicitly set `PUBLIC_REGISTRATION_ENABLED=false` for the friends beta.**
This disables only public `/users/signup` (403); administrator enrollment, login,
account management, and password recovery remain unchanged. Unauthenticated
`GET /api/v1/utils/public-config` contains only `registration_open`; public
game options mirror that same flag and do not expose private catalog fields.

Playwright CI provisions a new ownership-commented synthetic fixture database in
each disposable hosted Compose job before browser consumers start. The existing
C3/C4/C5 fixture builder verifies and activates eight synthetic events; only the
matching release-scoped opaque-hash public media is mounted read-only into the
backend. Private catalog/build files stay outside frontend and container build
contexts. `tests.browser.ci_fixture` is CI-only and refuses existing runtime/DB
state; it is not a local/live catalog tool or part of production startup. Docker
browser tests use a same-origin Vite API/media proxy so the actual Lax guest
cookie works after logout. Board/bootstrap/identity controlled harnesses run
separately, serially with zero retries, without account, DB, or SMTP fixtures.

`GAME_DATA_DIR/media/<release_id>/<sha256>.svg` and `.webp` are the only served
paths under `/media`. Provision each release's retained public assets into this
tree as real files, not symlinks, and mount the tree read-only. Keep catalogs,
manifests, release metadata, answers, and importer workspaces outside it. No
directory listings, index files, named-year assets, or symlinks (including in-tree
aliases and mount-root symlinks) are served. A missing local media directory is
allowed at startup and returns 404. A missing active catalog returns 503 on use.
Public card credits and original source/license URLs must be preserved by clients.

### Packaged Daily policy and client generation

`docs/research/source-selection.json` is the versioned machine-approved source
policy. Daily's runtime copy is `backend/app/game/source-selection.json`, included
by the existing backend-only Docker context and Python package. When the source
policy intentionally changes, produce the runtime copy from the policy, never
edit the copy independently:

```bash
cp docs/research/source-selection.json backend/app/game/source-selection.json
cd backend
POSTGRES_DB=historical_date_game_test POSTGRES_PORT=5433 \
  uv run pytest tests/api/routes/test_game_api.py -q
```

The equality regression compares exact bytes, executes the copied backend package
without root `docs`, and verifies missing/unknown policy fails closed. The Daily
integration regression checks the four approved categories yield the proper
selected pool rather than all events. There is no mutable public policy override;
existing date definitions remain frozen. The Docker build installs build tools
because `mwparserfromhell` currently compiles its tokenizer for Python 3.15.

From the repository root, with Node 26.11.1 and `backend/.venv/bin` on `PATH`, run
`bash scripts/generate-client.sh` twice and compare checksums of
`frontend/openapi.json` and every `frontend/src/client/` file. Never manually edit
generated API files. Only public DTOs belong in OpenAPI/client schemas; private
event/source records, seed, pool/order, and account identity must not appear in
game responses. Run backend tests/lint/types and frontend units/lint/types/build
after regeneration; no game UI is included in B5.

## Pre-commits and code linting

we are using a tool called [pre-commit](https://pre-commit.com/) for code linting and formatting.

When you install it, it runs right before making a commit in git. This way it ensures that the code is consistent and formatted even before it is committed.

You can find a file `.pre-commit-config.yaml` with configurations at the root of the project.

#### Install pre-commit to run automatically

`pre-commit` is already part of the dependencies of the project, but you could also install it globally if you prefer to, following [the official pre-commit docs](https://pre-commit.com/).

After having the `pre-commit` tool installed and available, you need to "install" it in the local repository, so that it runs automatically before each commit.

Using `uv`, you could do it with:

```bash
❯ uv run pre-commit install
pre-commit installed at .git/hooks/pre-commit
```

Now whenever you try to commit, e.g. with:

```bash
git commit
```

...pre-commit will run and check and format the code you are about to commit, and will ask you to add that code (stage it) with git again before committing.

Then you can `git add` the modified/fixed files again and now you can commit.

#### Running pre-commit hooks manually

you can also run `pre-commit` manually on all the files, you can do it using `uv` with:

```bash
❯ uv run pre-commit run --all-files
check for added large files..............................................Passed
check toml...............................................................Passed
check yaml...............................................................Passed
ruff.....................................................................Passed
ruff-format..............................................................Passed
eslint...................................................................Passed
prettier.................................................................Passed
```

## URLs

The production or staging URLs would use these same paths, but with your own domain.

### Development URLs

Development URLs, for local development.

Frontend: <http://localhost:5173>

Backend: <http://localhost:8000>

Automatic Interactive Docs (Swagger UI): <http://localhost:8000/docs>

Automatic Alternative Docs (ReDoc): <http://localhost:8000/redoc>

Adminer: <http://localhost:8087>

Traefik UI: <http://localhost:8091>

MailCatcher: <http://localhost:1080>

### Development URLs with `localhost.tiangolo.com` Configured

Development URLs, for local development.

Frontend: <http://dashboard.localhost.tiangolo.com>

Backend: <http://api.localhost.tiangolo.com>

Automatic Interactive Docs (Swagger UI): <http://api.localhost.tiangolo.com/docs>

Automatic Alternative Docs (ReDoc): <http://api.localhost.tiangolo.com/redoc>

Adminer: <http://localhost.tiangolo.com:8087>

Traefik UI: <http://localhost.tiangolo.com:1>

MailCatcher: <http://localhost.tiangolo.com:1080>
