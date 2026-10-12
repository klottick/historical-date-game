"""Non-destructive browser fixture setup; run from backend/, never production.

Shares B4's eight synthetic source events and the full C5 verification gate.
Private answers remain in the backend's test-only GAME_DATA_DIR, not the UI.
"""

import json
import sys
from pathlib import Path
from uuid import uuid4

from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine, init_db
from app.game.catalog_repository import activate_catalog
from tests.api.routes.test_game_daily import release
from tests.db_guard import require_test_database


def main() -> None:
    require_test_database(settings.POSTGRES_DB)
    root = settings.GAME_DATA_DIR.resolve()
    root.mkdir(parents=True, exist_ok=True)
    state = root / "browser-fixture.json"
    with Session(engine) as session:
        init_db(session)
        if state.exists():
            published = Path(json.loads(state.read_text())["release_path"])
            release_id = activate_catalog(
                session, published, published / "media", require_beta=False
            )
            session.commit()
        else:
            build = root / ("browser-build-" + uuid4().hex)
            release_id = release(session, build)
            published = build / "releases" / release_id
            target = root / "releases" / release_id
            target.parent.mkdir(exist_ok=True)
            published.rename(target)
            published = target
            state.write_text(json.dumps({"release_path": str(published)}))
    sys.stdout.write(
        json.dumps({"release_id": release_id, "release_path": str(published)}) + "\n"
    )


if __name__ == "__main__":
    main()
