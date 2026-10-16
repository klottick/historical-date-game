# syntax=docker/dockerfile:1
FROM node:26.11.1-trixie-slim@sha256:dc959319aa89ba9ab709c3e2d2ef8827e254284df2221856c58d78d32c45a913 AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY frontend/index.html frontend/tsconfig*.json frontend/vite.config.ts ./
COPY frontend/src ./src
COPY frontend/public ./public
ENV VITE_API_URL=""
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.13.0@sha256:22fbda6ef3b6466750a6fb1c7ce1d23a2a63a53be91e03d408b6e4274753998d AS uv

FROM debian:trixie-slim@sha256:918311b7b6c4c6f68b232ba516584925f6c78ad82b6fd534b98979df6438e483 AS python-build
WORKDIR /build/backend
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends ca-certificates build-essential
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/python UV_PYTHON=3.15.0 \
    UV_PYTHON_PREFERENCE=only-managed UV_LINK_MODE=copy
RUN --mount=type=cache,target=/root/.cache/uv uv python install 3.15.0
COPY backend/pyproject.toml backend/uv.lock ./
COPY docker/python-build-constraints.txt /build/python-build-constraints.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file /build/requirements.txt && \
    uv venv --python 3.15.0 /opt/venv && \
    uv pip sync --python /opt/venv/bin/python --require-hashes \
      --build-constraints /build/python-build-constraints.txt /build/requirements.txt && \
    uv pip check --python /opt/venv/bin/python

FROM debian:trixie-slim@sha256:918311b7b6c4c6f68b232ba516584925f6c78ad82b6fd534b98979df6438e483 AS runtime
WORKDIR /app/backend
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends ca-certificates libgcc-s1 libstdc++6 && \
    groupadd --gid 10001 hdg && useradd --uid 10001 --gid 10001 --no-create-home hdg && \
    install -d -o 10001 -g 10001 -m 0750 /data
COPY --from=python-build /opt/python /opt/python
COPY --from=python-build /opt/venv /opt/venv
COPY --link backend/app /app/backend/app
COPY --link backend/alembic.ini /app/backend/alembic.ini
COPY --link backend/catalogue /app/backend/catalogue
COPY --link LICENSE /app/LICENSE
COPY --link scripts/distribution/backup.py /app/backup.py
COPY --from=frontend /build/frontend/dist /app/frontend/dist
ARG VERSION=unreleased
ARG VCS_REF
LABEL org.opencontainers.image.title="Historical Date Game" \
      org.opencontainers.image.source="https://github.com/klottick/historical-date-game" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version=$VERSION \
      org.opencontainers.image.revision=$VCS_REF
ENV PATH="/opt/venv/bin:$PATH" PYTHONPATH=/app/backend \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 GAME_DATA_DIR=/data
USER 10001:10001
# These imports exercise copied interpreter/native-library compatibility.
RUN python -c "import psycopg, pydantic_core, PIL._imaging, mwparserfromhell.parser._tokenizer, uvloop, argon2"
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=6s --start-period=15s --retries=3 \
    CMD ["python", "-m", "app.distribution", "healthcheck"]
ENTRYPOINT ["python", "-m", "app.distribution"]
CMD ["serve"]
