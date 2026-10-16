"""Release commands: no implicit migrations in the serving process."""

import argparse
import os
import sys
from urllib.request import urlopen

from app.distribution.config import validate_environment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("initialize", "serve", "healthcheck"),
        nargs="?",
        default="serve",
    )
    args = parser.parse_args()
    try:
        validate_environment(os.environ)
    except ValueError as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1
    if args.command == "healthcheck":
        try:
            with urlopen("http://127.0.0.1:8000/healthz", timeout=5) as response:
                return 0 if response.status == 200 else 1
        except OSError:
            return 1
    if args.command == "initialize":
        from app.distribution.startup import initialize

        return initialize()
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.distribution.web:release_app",
            "--factory",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--workers",
            "1",
            "--no-proxy-headers",
            "--no-access-log",
        ],
    )
    return 1  # pragma: no cover (successful exec never returns)


if __name__ == "__main__":
    raise SystemExit(main())
