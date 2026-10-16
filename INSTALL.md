# Prebuilt installation (Linux amd64)

Release installation needs Docker Engine with Docker Compose v2, not Git,
source code, builds, Python or Node.js. This guide is shipped with version-pinned
`compose.yaml`, `env.example`, `image-digest.txt` and `SHA256SUMS` release assets.
No release is claimed available by the source-tree templates alone.

Download all those assets into a new empty directory. Verify `SHA256SUMS`, then:

```sh
umask 077
cp env.example .env
```

Edit `.env`. Keep the released `HDG_IMAGE` version-and-digest reference. Configure
permanent, independently generated random secrets: `SECRET_KEY` (32+ characters),
`POSTGRES_PASSWORD` (20+), `FIRST_SUPERUSER_PASSWORD` (12+), and an administrator
email in `FIRST_SUPERUSER`. Generate tokens using the pinned image without any
configured stack or host language runtime:

```sh
docker run --rm --network none --entrypoint python IMAGE_FROM_ENV_EXAMPLE -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Do not use the literal `IMAGE_FROM_ENV_EXAMPLE`: substitute the supplied complete
image reference. Re-run the generator for each secret; retain `SECRET_KEY` across
upgrades/restores to preserve account contexts and sessions. Never generate it on
every application start.

`FRONTEND_HOST` must match the exact browser origin, including port and without a
trailing slash (default `http://localhost:8000`). `ENVIRONMENT=local` permits plain
HTTP guest cookies; non-local modes require HTTPS and use Secure guest cookies.
Changing `HDG_PORT` requires changing `FRONTEND_HOST`. The default binding is
loopback only; PostgreSQL has no published host port.

```sh
docker compose --env-file .env -f compose.yaml config --quiet
docker compose --env-file .env -f compose.yaml pull
docker compose --env-file .env -f compose.yaml up -d --wait
```

Open the configured origin. Only `app` and `db` run continuously; `initialize`
exits successfully after safe migrations, idempotent admin creation and
initialize-only catalogue provisioning. Initialization failure prevents startup;
it never resets gameplay or silently changes an existing catalogue selection.

## Backup (private data)

Use a private directory with sufficient free space. These commands assume your
installation directory contains exactly the released Compose file and `.env`.
The dump/media archive and `.env` contain private state; do not commit or upload
them. Back up all three together while application writes are stopped. Keep the
release assets and digest as well. No host PostgreSQL/Python tools are needed.

```sh
set -eu
umask 077
mkdir backup
docker compose --env-file .env -f compose.yaml stop app
docker compose --env-file .env -f compose.yaml exec -T db sh -c 'exec pg_dump --format=custom -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > backup/database.dump
docker compose --env-file .env -f compose.yaml run --rm -T --no-deps --entrypoint python initialize /app/backup.py export-media > backup/media.tar
cp .env backup/environment.private
cp compose.yaml image-digest.txt backup/
docker compose --env-file .env -f compose.yaml up -d --wait
```

If a backup command fails, retain its failure and keep the app stopped until you
have assessed the backup; never treat a partial file as a successful backup.

## Restore to fresh storage only

Restore into a **new installation directory and a new Compose project name** with
the same released assets, PostgreSQL major version and private environment.
Restore the original `SECRET_KEY`, database credentials and media archive. Set a
different loopback port/origin if the old installation still exists. Never point
this procedure at retained/populated volumes. Do not delete data to make a
restore destination empty.

In the new directory, place `database.dump`, `media.tar`, the original `.env` and
`compose.yaml`; use a fresh project name throughout (shown as `hdg-recovery-new`).
Do **not** run full `up`/initialization before restoring:

```sh
set -eu
umask 077
docker compose --env-file .env -f compose.yaml -p hdg-recovery-new up -d --wait db
test "$(docker compose --env-file .env -f compose.yaml -p hdg-recovery-new exec -T db sh -c 'psql -XAt -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT (SELECT count(*) FROM pg_class WHERE relnamespace = current_schema()::regnamespace) + (SELECT count(*) FROM pg_proc WHERE pronamespace = current_schema()::regnamespace) + (SELECT count(*) FROM pg_type WHERE typnamespace = current_schema()::regnamespace)"')" = 0
docker compose --env-file .env -f compose.yaml -p hdg-recovery-new exec -T db sh -c 'exec pg_restore --exit-on-error --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < database.dump
docker compose --env-file .env -f compose.yaml -p hdg-recovery-new run --rm -T --no-deps --entrypoint python initialize /app/backup.py restore-media < media.tar
docker compose --env-file .env -f compose.yaml -p hdg-recovery-new up -d --wait
```

Media restore refuses unsafe archive paths, links, corrupted hashed assets and
nonempty destination storage. PostgreSQL restore has no `--clean`, drop, or
automatic rollback. An interrupted restore is not a working installation: retain
it for diagnosis and use another new project/empty volumes. Verify existing
guest sessions, account login, progressed games, exact replay, catalogue selection
and old media before considering recovery successful.

## Safety and operations

Use `docker compose --env-file .env -f compose.yaml logs --no-color` for logs;
`GET /healthz` is read-only readiness (database/schema/catalogue/media), not simply
an HTTP-process check. Ordinary `stop` and `down` without `-v` retain named volumes.
**Never use `down -v`, volume pruning or deletion as an upgrade/recovery step.**

The app and initializer run as UID/GID `10001:10001`. Fresh named game volumes get
that ownership; app media mounts read-only, initializer mounts read-write. Wrong
ownership/missing/corrupt media is a failure to fix explicitly; the image does
not chown retained data, run the app as root or ignore failed initialization.

Before upgrading, stop consumers and take a verified backup. Download the new
release assets; review configuration changes and pin the new digest while keeping
your private environment/secret and volumes. Do not change PostgreSQL major
versions automatically. The three-life migration intentionally refuses populated
legacy gameplay: preserve the original installation and seek a separately
reviewed migration; never reset gameplay to force an upgrade. Schema rollback or
running an old image against a newer schema is not a recovery strategy.

Docker does not add authentication or make public hosting safe. Loopback HTTP is
the default, not a public deployment. LAN/public access requires explicit binding,
an exact origin, access control/TLS/reverse-proxy policy and security review.
Forwarded headers are not trusted by the app. Configure SMTP explicitly if you
need account email/reset; no mail service is included. Public repository visibility
does not guarantee anonymous GHCR pulls. Supported images are **Linux amd64
only**, including amd64 Docker VMs; no ARM or emulation support is promised.
