#!/usr/bin/env bash
set -eu
exec bash "$(dirname -- "$0")/test.sh" "$@"
