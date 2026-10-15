"""Offline/bounded build entrypoint; metadata is never a public artifact."""

import argparse
import json
import sys
from pathlib import Path

from app.content.event_links import build_event_links


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--release", type=Path, required=True)
    build.add_argument("--cache", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    try:
        summary = build_event_links(
            args.release, args.cache, args.output, offline=args.offline
        )
    except ValueError, OSError:
        sys.stderr.write(json.dumps({"error": "event_links_build_failed"}) + "\n")
        return 1
    sys.stdout.write(summary.model_dump_json() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
