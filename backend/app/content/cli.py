"""Machine-only private content commands; only activation requires a database."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from app.content.adapters.router import AdapterRouter
from app.content.commons_transport import (
    CommonsThrottle,
    ensure_commons_ready,
    retry_commons,
)
from app.content.importer import import_snapshot
from app.content.media.pipeline import (
    assign_chronology_media,
    assign_media,
    finalize_media_receipts,
)
from app.content.publish import (
    _events,
    _files,
    _json,
    _path,
    _pointer,
    _safe_root,
    publish_release,
    verify_release,
)
from app.content.schemas import SourceSelection


def _selection(path: Path) -> SourceSelection:
    selection = SourceSelection.model_validate_json(_safe_root(path).read_bytes())
    approved = SourceSelection.model_validate_json(
        Path(__file__)
        .parents[3]
        .joinpath("docs/research/source-selection.json")
        .read_bytes()
    )
    if selection != approved:
        raise ValueError("unsupported_source_selection")
    return selection


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    importing = commands.add_parser("import")
    importing.add_argument("--selection", type=Path, required=True)
    importing.add_argument("--snapshot", type=Path, required=True)
    importing.add_argument("--workspace", type=Path, required=True)
    media = commands.add_parser("media")
    media.add_argument("--selection", type=Path, required=True)
    media.add_argument("--workspace", type=Path, required=True)
    media.add_argument(
        "--offline",
        action="store_true",
        help="Use cached image evidence only; never request absent metadata or originals",
    )
    media.add_argument(
        "--retry-throttled",
        action="store_true",
        help="Explicitly retry a stopped Commons batch after its retry deadline",
    )
    publishing = commands.add_parser("publish")
    publishing.add_argument("--workspace", type=Path, required=True)
    publishing.add_argument("--output", type=Path, required=True)
    publishing.add_argument("--release-id", required=True)
    publishing.add_argument("--fixture", action="store_true")
    verifying = commands.add_parser("verify")
    verifying.add_argument("--release", type=Path, required=True)
    verifying.add_argument("--media", type=Path, required=True)
    verifying.add_argument("--require-beta", action="store_true")
    activating = commands.add_parser("activate")
    activating.add_argument("--release", type=Path, required=True)
    activating.add_argument("--media", type=Path, required=True)
    activating.add_argument("--require-beta", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "import":
            _selection(args.selection)
            snapshot = _safe_root(args.snapshot)
            workspace = _safe_root(args.workspace)
            _files(snapshot)
            if workspace.exists():
                _files(workspace)
            if (snapshot / "snapshot.json").exists():
                for request in _json(snapshot, "snapshot.json")["requests"]:
                    _path(snapshot, request["file"])
            result = asdict(import_snapshot(AdapterRouter(), snapshot, workspace))
        elif args.command == "media":
            selection = _selection(args.selection)
            workspace = _safe_root(args.workspace)
            _files(workspace)
            if args.retry_throttled:
                retry_commons(workspace)
            ensure_commons_ready(workspace)
            root, _ = _pointer(workspace, "current.json", "generations")
            events = sorted(
                _events(root, "candidates.jsonl"), key=lambda e: str(e.event_id)
            )
            # Finalization runs only after EVERY current candidate is assigned.
            for event in events:
                if not event.identity_key.startswith("onthisday:"):
                    assign_media(event, selection, args.workspace, offline=args.offline)
            if any(event.identity_key.startswith("onthisday:") for event in events):
                assign_chronology_media(selection, args.workspace)
            receipts = finalize_media_receipts(args.workspace)
            result = {
                "events": len(receipts),
                "passed": sum(r.passed for r in receipts),
                "failed": sum(not r.passed for r in receipts),
            }
            sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
            return 1 if result["failed"] else 0
        elif args.command == "publish":
            result = publish_release(
                args.workspace, args.output, args.release_id, fixture=args.fixture
            ).model_dump(mode="json")
        elif args.command == "activate":
            # Keep all acquisition/publication/verification commands DB-independent.
            from sqlmodel import Session

            from app.core.db import engine
            from app.game.catalog_repository import activate_catalog

            with Session(engine) as session:
                release_id = activate_catalog(
                    session, args.release, args.media, require_beta=args.require_beta
                )
                session.commit()
            result = {"release_id": release_id}
        else:
            result = verify_release(
                args.release, args.media, require_beta=args.require_beta
            ).model_dump(mode="json")
        sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
        return 0
    except CommonsThrottle as exc:
        sys.stderr.write(
            json.dumps(
                {
                    "error": "commons_throttled",
                    "incomplete": True,
                    "retry": "Rerun content media with --retry-throttled at or after retry_at; no automatic retry.",
                    **exc.details,
                },
                sort_keys=True,
            )
            + "\n"
        )
        return 1
    except (ValueError, OSError, KeyError, TypeError) as exc:
        sys.stderr.write(f"content {args.command} failed: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
