"""Fresh local card-board generation. Default inspection is strictly read-only.

Apply only after controller Task 6 and whole-branch review gates. Never adopt the
old guest-play generation; use its verified original runner to stop it separately.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID

from app.content.adapters.onthisday import _json
from app.content.event_links import EventLinksFile
from app.content.schemas import EventRecord
from app.core.config import settings
from tests.browser import guest_local_rollout as guest
from tests.browser.guest_test_environment import MANIFEST_SHA

WORKTREE = Path("/home/klottick/repos/historical-date-game/.worktrees/board-redesign")
LIVE = WORKTREE.parent / "beta"
PRIVATE = WORKTREE / ".superpowers/sdd/2026-10-14-game-board-redesign"
INTEGRATION = PRIVATE / "integration"
EVIDENCE = PRIVATE / "local-activation"


def guarded_rollout() -> ModuleType:
    # Separate module globals, not monkeypatches of the legacy generation. All
    # original guards/launch/stop functions keep their own coherent configuration.
    if Path(__file__).resolve().parents[3] != WORKTREE:
        raise RuntimeError("Exact board implementation worktree required")
    spec = importlib.util.spec_from_file_location(
        "_board_guarded_guest", guest.__file__
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Guarded rollout unavailable")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    runner.__dict__["EVIDENCE"] = EVIDENCE
    original_command = runner.command

    def command(component: str) -> list[str]:
        argv: list[str] = original_command(component)
        if component == "backend":
            argv[3] = "tests.browser.board_local_rollout:local_app"
        return argv

    runner.__dict__["command"] = command
    return runner


def release_sources(release: Path) -> dict[UUID, set[str]]:
    return {
        event.event_id: {source.url for source in event.sources}
        for event in (
            EventRecord.model_validate_json(line)
            for line in (release / "events.jsonl").read_bytes().splitlines()
        )
    }


def require_sidecar(file: Path | None, sha256: str | None, release: Path) -> None:
    if file is None and sha256 is None:
        return  # Explicit original-source fallback, never ambient enrichment.
    if file is None or sha256 is None:
        raise RuntimeError("Sidecar file and SHA256 must be supplied together")
    if (
        not file.is_absolute()
        or file.resolve(strict=True) != file
        or not file.is_relative_to(INTEGRATION)
        or not file.is_file()
        or file.stat().st_mode & 0o777 != 0o600
        or file.stat().st_nlink != 1
        or file.stat().st_size > 32 * 1024 * 1024
    ):
        raise RuntimeError("Sidecar must be a private nonaliased integration file")
    for parent in (file.parent, *file.parent.parents):
        if parent == INTEGRATION.parent:
            break
        if (
            parent.resolve(strict=True) != parent
            or parent.stat().st_mode & 0o777 != 0o700
        ):
            raise RuntimeError("Sidecar directories must remain private and nonaliased")
    body = file.read_bytes()
    if hashlib.sha256(body).hexdigest() != sha256:
        raise RuntimeError("Sidecar SHA256 mismatch")
    links = EventLinksFile.model_validate_json(json.dumps(_json(body)))
    sources = release_sources(release)
    if (
        links.release_id != guest.RELEASE_ID
        or links.manifest_sha256 != MANIFEST_SHA
        or set(links.records) != set(sources)
        or any(
            record.source_url not in sources[key]
            for key, record in links.records.items()
        )
    ):
        raise RuntimeError("Sidecar must bind the exact release, events and sources")


@contextmanager
def sidecar_environment(file: Path | None, sha256: str | None) -> Iterator[None]:
    values = {
        "GAME_EVENT_LINKS_FILE": str(file) if file else "",
        "GAME_EVENT_LINKS_SHA256": sha256 or "",
    }
    before = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def local_app() -> Any:
    # Override settings explicitly before app/runtime-loader import: .env may
    # restore ambient values even when the child environment contains empty text.
    file = os.environ.get("GAME_EVENT_LINKS_FILE")
    settings.GAME_EVENT_LINKS_FILE = Path(file) if file else None
    settings.GAME_EVENT_LINKS_SHA256 = os.environ.get("GAME_EVENT_LINKS_SHA256") or None
    return guest.local_app()  # Original SMTP-off/public-registration-off factory.


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action", choices=["inspect", "start", "stop"], default="inspect"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--live-worktree", type=Path, default=LIVE)
    parser.add_argument("--implementation-worktree", type=Path, default=WORKTREE)
    parser.add_argument("--origin", action="append", required=True)
    parser.add_argument("--event-links-file", type=Path)
    parser.add_argument("--event-links-sha256")
    args = parser.parse_args(argv)
    try:
        runner = guarded_rollout()
        original_inspect = runner.inspect
        original_start = runner.start

        def inspect(
            live: Path, implementation: Path, origins: list[str], cold: bool
        ) -> dict[str, Any]:
            runner.require_target()
            runner.require_paths(live, implementation)
            release = live / "data/game/releases" / guest.RELEASE_ID
            if args.event_links_file is not None or args.event_links_sha256 is not None:
                runner.verify_real_source(release)
            require_sidecar(args.event_links_file, args.event_links_sha256, release)
            proof: dict[str, Any] = original_inspect(
                live, implementation, origins, cold
            )
            runner.require_current_schema(proof["database"])
            proof["event_links"] = {
                "file": str(args.event_links_file) if args.event_links_file else None,
                "sha256": args.event_links_sha256,
                "fallback": args.event_links_file is None,
            }
            return proof

        def start(proof: dict[str, Any]) -> None:
            with sidecar_environment(args.event_links_file, args.event_links_sha256):
                original_start(proof, upgrade_schema=False)

        runner.__dict__.update(inspect=inspect, start=start)
        delegated = [
            "--action",
            args.action,
            "--live-worktree",
            str(args.live_worktree),
            "--implementation-worktree",
            str(args.implementation_worktree),
        ]
        for origin in args.origin:
            delegated.extend(["--origin", origin])
        if args.apply:
            delegated.append("--apply")
        return int(runner.main(delegated))
    except Exception as error:
        sys.stderr.write(
            f"Board rollout stopped ({type(error).__name__}); preserve private evidence/state\n"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
