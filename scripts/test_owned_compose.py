"""Run tests only on a caller-prepared, exactly labelled disposable dev stack."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = os.environ.get("COMPOSE_PROJECT_NAME", "")
if os.environ.get("HDG_CI_DISPOSABLE") != "true" or not re.fullmatch(
    r"hdg-devtest-[a-f0-9]{32}", project
):
    raise SystemExit("Refusing an unowned disposable test project")
compose = [
    "docker",
    "compose",
    "-f",
    str(root / "docker-compose.yml"),
    "-f",
    str(root / "docker-compose.override.yml"),
    "-p",
    project,
]
ids = subprocess.run(
    [*compose, "ps", "-aq"], check=True, capture_output=True, text=True
).stdout.split()
if not ids:
    raise SystemExit(
        "Prepare a fresh owned fixture stack first; this script never provisions or deletes data"
    )
for identity in ids:
    info = json.loads(
        subprocess.run(
            ["docker", "container", "inspect", identity],
            check=True,
            capture_output=True,
        ).stdout
    )[0]
    labels = info["Config"]["Labels"] or {}
    if (
        labels.get("com.docker.compose.project") != project
        or labels.get("hdg.devtest.owner") != project
    ):
        raise SystemExit("Refusing an unlabelled or foreign test container")
raise SystemExit(
    subprocess.run(
        [
            *compose,
            "exec",
            "-T",
            "backend",
            "bash",
            "scripts/tests-start.sh",
            *sys.argv[1:],
        ],
        check=False,
    ).returncode
)
