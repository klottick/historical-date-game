#!/usr/bin/env bash
# Consume only an explicitly prepared, ownership-labelled disposable stack.
# No implicit build/start, volume deletion or host filesystem cleanup.
set -eu
export COMPOSE_FILE=docker-compose.yml:docker-compose.override.yml
if [[ ${HDG_CI_DISPOSABLE:-} != true || ! ${COMPOSE_PROJECT_NAME:-} =~ ^hdg-devtest-[a-f0-9]{32}$ ]]; then
  echo "Refusing an unowned test stack. See development.md: owned test entry points." >&2
  exit 2
fi
ROOT=$(cd -- "$(dirname -- "$0")/.." && pwd)
exec "$ROOT/backend/.venv/bin/python" "$ROOT/scripts/test_owned_compose.py" "$@"
