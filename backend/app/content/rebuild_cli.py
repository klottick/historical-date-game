"""Explicit fresh-build/replay tools; never activate an installation."""

import argparse
import json
import sys
from pathlib import Path

import httpx

from app.content.rebuild import load_lock, reproduce, update_candidate, validate_recipe
from app.content.source_acquisition import acquire_sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fresh = commands.add_parser(
        "fresh", help="Build a new catalogue from public chronology sources"
    )
    fresh.add_argument("--output", type=Path, required=True)
    fresh.add_argument("--release-id", required=True)
    acquire = commands.add_parser("acquire")
    acquire.add_argument("--lock", type=Path, required=True)
    acquire.add_argument("--output", type=Path, required=True)
    acquire.add_argument("--source-dir", type=Path)
    for command in ("reproduce", "update-candidate"):
        sub = commands.add_parser(command)
        sub.add_argument("--lock", type=Path, required=True)
        sub.add_argument("--sources", type=Path, required=True)
        sub.add_argument("--output", type=Path, required=True)
        if command == "reproduce":
            sub.add_argument("--expected", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "fresh":
            from app.content.fresh import build_fresh

            result = build_fresh(args.output, args.release_id)
        elif args.command == "acquire":
            lock = load_lock(args.lock)
            validate_recipe(lock, require_payloads=False)
            root = acquire_sources(lock, args.output, source_dir=args.source_dir)
            result = {"sources": str(root)}
        elif args.command == "reproduce":
            result = reproduce(
                args.lock, args.sources, args.output, expected_catalogue=args.expected
            )
        else:
            result = update_candidate(args.lock, args.sources, args.output)
        sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
        return 0 if result.get("matches", True) else 1
    except (ValueError, OSError, KeyError, TypeError, httpx.HTTPError) as exc:
        sys.stderr.write(
            json.dumps({"error": str(exc), "command": args.command}) + "\n"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
