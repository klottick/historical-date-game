#! /usr/bin/env bash

set -e
set -x

# Let the DB start
python app/backend_pre_start.py

# Run migrations
alembic upgrade head

# Create initial data in DB
python app/initial_data.py

# Verify packaged bytes and initialize only if no catalogue is selected.
# Never acquire/rebuild content, reset gameplay, or implicitly upgrade selection.
python -m app.game.runtime_catalog initialize
