"""Verify an already-built image on uniquely owned, isolated installations."""

import argparse
import hashlib
import http.cookiejar
import json
import os
import re
import secrets
import select
import shutil
import signal
import socket
import socketserver
import subprocess
import tempfile
import threading
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
EMPTY_SCHEMA_SQL = "SELECT (SELECT count(*) FROM pg_class WHERE relnamespace = current_schema()::regnamespace) + (SELECT count(*) FROM pg_proc WHERE pronamespace = current_schema()::regnamespace) + (SELECT count(*) FROM pg_type WHERE typnamespace = current_schema()::regnamespace)"


def require_owned(labels: dict, project: str, owner: str) -> None:
    if (
        labels.get("com.docker.compose.project") != project
        or labels.get("hdg.distribution.owner") != owner
    ):
        raise ValueError("Refusing foreign or unlabelled resource")


def private_temp() -> str | None:
    path = os.environ.get("RUNNER_TEMP", "/tmp/opencode")
    return path if Path(path).is_dir() else None


def install_signal_handlers() -> None:
    def interrupted(_signum, _frame):
        raise InterruptedError("Smoke interrupted by termination request")

    signal.signal(signal.SIGTERM, interrupted)


class Relay:
    """Test-only loopback TCP relay into an internal Docker bridge.

    Docker deliberately suppresses published ports on internal networks. This
    host-side relay lets the browser reach the owned app without granting the
    application internet egress. It is never part of an installed application.
    """

    def __init__(self, address: tuple, target: tuple):
        self.target = target
        relay = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                with socket.create_connection(relay.target, timeout=12) as upstream:
                    sockets = [self.request, upstream]
                    while True:
                        readable, _, _ = select.select(sockets, [], [], 15)
                        if not readable:
                            return
                        for source in readable:
                            data = source.recv(65536)
                            if not data:
                                return
                            (
                                upstream if source is self.request else self.request
                            ).sendall(data)

        self.server = socketserver.ThreadingTCPServer(address, Handler)
        self.server.daemon_threads = True
        self.server_address = self.server.server_address
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Installation:
    def __init__(
        self,
        image: str,
        assets: Path,
        directory: Path,
        settings: dict | None = None,
        *,
        offline=False,
    ):
        self.owner = uuid4().hex
        self.project = "hdg-dist-" + self.owner
        self.directory = directory
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.image = image
        self.offline = offline
        self.relay = None
        self.checks: list[str] = []
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.origin = f"http://127.0.0.1:{port}"
        self.settings = {
            "HDG_IMAGE": image,
            "HDG_BIND_ADDRESS": "127.0.0.1",
            "HDG_PORT": str(port),
            "PROJECT_NAME": "Distribution smoke",
            "ENVIRONMENT": "local",
            "FRONTEND_HOST": self.origin,
            "POSTGRES_SERVER": "db",
            "POSTGRES_PORT": "5432",
            "POSTGRES_USER": "hdg",
            "POSTGRES_DB": "hdg",
            "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
            "SECRET_KEY": secrets.token_urlsafe(48),
            "FIRST_SUPERUSER": "smoke@example.com",
            "FIRST_SUPERUSER_PASSWORD": secrets.token_urlsafe(24),
        }
        if settings:
            for field in (
                "SECRET_KEY",
                "POSTGRES_PASSWORD",
                "FIRST_SUPERUSER",
                "FIRST_SUPERUSER_PASSWORD",
            ):
                self.settings[field] = settings[field]
        for name in ("compose.yaml", "env.example"):
            shutil.copyfile(assets / name, directory / name)
        if (assets / "INSTALL.md").is_file():
            shutil.copyfile(assets / "INSTALL.md", directory / "INSTALL.md")
        with (directory / ".env").open("x") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(
                "".join(f"{key}={value}\n" for key, value in self.settings.items())
            )
        labels = f"{{hdg.distribution.owner: {self.owner}}}"
        (directory / "owned.yaml").write_text(
            "services:\n"
            + "".join(
                f"  {name}:\n    labels: {labels}\n"
                for name in ("app", "initialize", "db")
            )
            + "volumes:\n"
            + "".join(
                f"  {name}:\n    labels: {labels}\n"
                for name in ("game-data", "postgres-data")
            )
            + f"networks:\n  default:\n    internal: {str(offline).lower()}\n    labels: {labels}\n"
        )
        self.env = {
            k: v
            for k, v in os.environ.items()
            if k in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG", "XDG_RUNTIME_DIR")
        }

    def child(self, directory: Path, *, settings=None, offline=None):
        child = Installation(
            self.image,
            self.directory,
            directory,
            self.settings if settings is None else settings,
            offline=self.offline if offline is None else offline,
        )
        child.env = dict(self.env)
        return child

    def compose_command(self, *args: str) -> list[str]:
        command = [
            "docker",
            "compose",
            "--env-file",
            str(self.directory / ".env"),
            "--project-directory",
            str(self.directory),
            "-p",
            self.project,
            "-f",
            str(self.directory / "compose.yaml"),
            "-f",
            str(self.directory / "owned.yaml"),
            *args,
        ]
        if args and args[0] == "up":
            command.append("--no-build")
        return command

    def docker(self, *args: str, check=True, **kwargs):
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
        return subprocess.run(
            ["docker", *args], env=self.env, check=check, timeout=120, **kwargs
        )

    def compose(self, *args: str, check=True, **kwargs):
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
        return subprocess.run(
            self.compose_command(*args),
            env=self.env,
            check=check,
            timeout=180,
            **kwargs,
        )

    def resources(self) -> list[tuple[str, str]]:
        resources = []
        for kind, args in (
            ("container", ("ps", "-aq")),
            ("volume", ("volume", "ls", "-q")),
            ("network", ("network", "ls", "-q")),
        ):
            ids = (
                self.docker(
                    *args,
                    "--filter",
                    "label=com.docker.compose.project=" + self.project,
                )
                .stdout.decode()
                .split()
            )
            for identity in ids:
                info = json.loads(self.docker(kind, "inspect", identity).stdout)[0]
                labels = (
                    info["Config"]["Labels"] if kind == "container" else info["Labels"]
                )
                require_owned(labels or {}, self.project, self.owner)
                resources.append((kind, identity))
        return resources

    def start(self) -> None:
        image = json.loads(self.docker("image", "inspect", self.image).stdout)[0]
        if (image["Os"], image["Architecture"]) != ("linux", "amd64"):
            raise ValueError("Only already-loaded Linux amd64 images are eligible")
        if self.resources():
            raise ValueError("Refusing to reuse an existing project")
        self.compose("config", "--quiet")
        self.compose("up", "-d", "--wait", "--wait-timeout", "90")
        self.refresh_endpoint()

    def refresh_endpoint(self):
        if self.offline:
            identity = self.compose("ps", "-q", "app").stdout.decode().strip()
            info = json.loads(self.docker("container", "inspect", identity).stdout)[0]
            require_owned(info["Config"]["Labels"], self.project, self.owner)
            network = info["NetworkSettings"]["Networks"][self.project + "_default"]
            target = (network["IPAddress"], 8000)
            if self.relay:
                self.relay.target = target
            else:
                self.relay = Relay(
                    ("127.0.0.1", int(self.settings["HDG_PORT"])), target
                )

    def redact(self, data: bytes) -> str:
        text = data.decode(errors="replace")
        for field in ("SECRET_KEY", "POSTGRES_PASSWORD", "FIRST_SUPERUSER_PASSWORD"):
            text = text.replace(self.settings[field], "[REDACTED]")
        return text

    def diagnostics(self, destination: Path) -> None:
        try:
            logs = self.compose("logs", "--no-color").stdout
        except subprocess.CalledProcessError as exc:
            logs = exc.stdout + exc.stderr
        (destination / (self.project + ".log")).write_text(self.redact(logs))

    def cleanup(self) -> None:
        # Validate the ENTIRE set before any deletion. Reinspect each exact ID
        # immediately before action; never down -v, prune or remove by prefix.
        if self.relay:
            self.relay.close()
            self.relay = None
        resources = self.resources()
        for kind, identity in resources:
            info = json.loads(self.docker(kind, "inspect", identity).stdout)[0]
            labels = info["Config"]["Labels"] if kind == "container" else info["Labels"]
            require_owned(labels or {}, self.project, self.owner)
            if kind == "container":
                self.docker("stop", "--time", "30", identity)
                self.docker("rm", identity)
            else:
                self.docker(kind, "rm", identity)

    def python(self, source: str, *, initializer=False, check=True):
        try:
            if initializer:
                return self.compose(
                    "run",
                    "--rm",
                    "--no-deps",
                    "--entrypoint",
                    "python",
                    "initialize",
                    "-c",
                    source,
                ).stdout
            return self.compose("exec", "-T", "app", "python", "-c", source).stdout
        except subprocess.CalledProcessError as exc:
            if check:
                raise
            return exc


def run_owned(installation, evidence: Path, probe) -> int:
    if not evidence.is_dir():
        raise ValueError("Create private evidence directory before starting resources")
    result = {"passed": False, "failure": None, "cleanup_failure": None}
    if isinstance(installation, Installation):
        record_owner(installation, evidence)
    try:
        installation.start()
        probe(installation)
    except BaseException as exc:  # noqa: BLE001 - interruptions must also retain evidence
        result["failure"] = type(exc).__name__
        if isinstance(installation, Installation):
            (evidence / "failure.log").write_text(
                installation.redact(traceback.format_exc().encode())
            )
    finally:
        try:
            installation.diagnostics(evidence)
        except Exception as exc:  # noqa: BLE001 - diagnostics cannot mask the primary failure
            result["diagnostics_failure"] = type(exc).__name__
        try:
            installation.cleanup()
        except Exception as exc:  # noqa: BLE001 - cleanup is recorded separately from the probe
            result["cleanup_failure"] = type(exc).__name__
        result["passed"] = not any(
            result.get(key)
            for key in ("failure", "cleanup_failure", "diagnostics_failure")
        )
        result["checks"] = getattr(installation, "checks", [])
        (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return 0 if result["passed"] else 1


@contextmanager
def owned_child(project: Installation, evidence: Path):
    record_owner(project, evidence)
    primary = None
    errors = []
    try:
        yield project
    except BaseException as exc:
        primary = exc
        raise
    finally:
        for action in (lambda: project.diagnostics(evidence), project.cleanup):
            try:
                action()
            except Exception as exc:  # noqa: BLE001 - preserve any in-flight primary exception
                errors.append(type(exc).__name__)
        (evidence / (project.project + "-result.json")).write_text(
            json.dumps(
                {
                    "failure": type(primary).__name__ if primary else None,
                    "cleanup_errors": errors,
                }
            )
            + "\n"
        )
        if errors and primary is None:
            raise RuntimeError("Child diagnostics or owned cleanup failed")


def record_owner(project: Installation, evidence: Path) -> None:
    with (evidence / "owned-projects.jsonl").open("a") as stream:
        stream.write(
            json.dumps({"project": project.project, "owner": project.owner}) + "\n"
        )


class Http:
    def __init__(self, origin: str):
        self.origin = origin
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))
        self.headers = {"Origin": origin, "X-Game-Request": "1"}

    def raw(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        *,
        headers=None,
        status=200,
    ):
        request = Request(
            self.origin + path, body, self.headers | (headers or {}), method=method
        )
        try:
            response = self.opener.open(request, timeout=12)
        except HTTPError as exc:
            response = exc
        with response:
            data = response.read()
            if response.status != status:
                raise AssertionError(
                    f"HTTP {method} {path} returned {response.status}, expected {status}"
                )
            return data, response.headers

    def json(self, method: str, path: str, body=None, *, headers=None, status=200):
        data = None if body is None else json.dumps(body).encode()
        content, _ = self.raw(
            method,
            path,
            data,
            headers={"Content-Type": "application/json"} | (headers or {}),
            status=status,
        )
        return json.loads(content)

    def bootstrap(self):
        result = self.json("POST", "/api/v1/games/session")
        assert result["kind"] == "guest" and result["protocol_version"] == 2
        self.headers["X-Game-Context"] = result["context_id"]


STATE = """
import hashlib,json
from sqlalchemy import inspect,text
from app.core.db import engine
result={}
with engine.connect() as connection:
    connection.execute(text('SET TRANSACTION READ ONLY'))
    for table in inspect(connection).get_table_names():
        rows=connection.execute(text('SELECT to_jsonb(t)::text FROM "'+table+'" t ORDER BY to_jsonb(t)::text')).scalars().all()
        result[table]={'rows':len(rows),'digest':hashlib.sha256(json.dumps(rows).encode()).hexdigest()}
print(json.dumps(result,sort_keys=True))
"""


def state(project: Installation, *, initializer=False) -> dict:
    return json.loads(project.python(STATE, initializer=initializer))


def check_gameplay(project: Installation) -> tuple[Http, dict, list]:
    player, other = Http(project.origin), Http(project.origin)
    assert player.json("GET", "/healthz") == {"status": "ready"}
    options = player.json("GET", "/api/v1/games/options")
    assert options["protocol_version"] == 2
    assert options["catalog_release_id"] == "chronology-1276-runtime-v2"
    assert not player.cookies
    player.json("GET", "/api/v1/users/me", status=401)
    player.bootstrap()
    other.bootstrap()
    _, cookie = player.raw(
        "POST", "/api/v1/games/session", headers={"X-Forwarded-Proto": "https"}
    )
    assert "Secure" not in cookie["Set-Cookie"] and "HttpOnly" in cookie["Set-Cookie"]
    other.json(
        "POST",
        "/api/v1/games/session",
        headers={"Origin": "https://foreign.example"},
        status=403,
    )
    answers = json.loads(
        project.python(
            "from app.content.runtime import verify_default;from pathlib import Path;import json;print(json.dumps({str(e.event_id):e.year_index for e in verify_default(Path('/app/backend/catalogue')).events}))"
        )
    )
    assert len(answers) == 1276
    receipts = []
    for mode in ("daily", "freeplay"):
        command = {"protocol_version": 2, "operation_id": str(uuid4())}
        if mode == "freeplay":
            command |= {
                "catalog_release_id": options["catalog_release_id"],
                "config": {
                    "category_ids": [c["id"] for c in options["categories"]],
                    "start": options["start"],
                    "end": options["end"],
                    "min_gap": 1,
                },
            }
        run = player.json("POST", "/api/v1/games/" + mode, command)
        assert player.json("POST", "/api/v1/games/" + mode, command) == run
        url = "/api/v1/games/runs/" + run["run_id"]
        other.json("GET", url, status=404)
        assert set(run["pending"]) == {"event_id", "prompt", "category_ids", "media"}
        for card in [*run["timeline"], run["pending"]]:
            assert any("CC0" in credit["label"] for credit in card["media"]["credits"])
            for media_url in (card["media"]["url"], card["media"]["fallback_url"]):
                data, _ = player.raw("GET", media_url)
                assert (
                    hashlib.sha256(data).hexdigest()
                    == media_url.rsplit("/", 1)[1].split(".")[0]
                )
        assert run["timeline"][0]["sources"] and run["timeline"][0]["learn_more"][
            "url"
        ].startswith("https://")
        for index in range(4):
            pending = run["pending"]["event_id"]
            correct = sum(
                answers[card["event_id"]] < answers[pending] for card in run["timeline"]
            )
            slot = correct if index == 0 else (correct + 1) % (len(run["timeline"]) + 1)
            move = {
                "protocol_version": 2,
                "operation_id": str(uuid4()),
                "expected_revision": run["revision"],
                "event_id": pending,
                "slot": slot,
            }
            moved = player.json("POST", url + "/placements", move)
            assert moved["revision"] == index + 1 and moved["score"] == 1
            assert moved["feedback"]["correct"] == (index == 0)
            assert moved["streak"] == (1 if index == 0 else 0)
            assert moved["lives_remaining"] == 3 - index
            assert moved["status"] == ("lost" if index == 3 else "active")
            assert player.json("POST", url + "/placements", move) == moved
            assert player.json("GET", url) == moved
            other.json("POST", url + "/placements", move, status=404)
            receipts.append((url, move, moved))
            run = moved
    for path in (
        "/.env",
        "/assets/missing.js",
        "/catalogue/default.json",
        "/media/chronology-1276-runtime-v2/events.jsonl",
        "/media/%2e%2e/releases/default.json",
        "/api/missing",
        "/@fs/etc/passwd",
    ):
        player.raw("GET", path, status=404)
    assert b'<div id="root"' in player.raw("GET", "/freeplay")[0]
    project.checks.append(
        "daily-freeplay-three-lives-replay-ownership-media-privacy-http-origin"
    )
    return player, options, receipts


def check_login(project: Installation) -> None:
    account = Http(project.origin)
    body = urlencode(
        {
            "username": project.settings["FIRST_SUPERUSER"],
            "password": project.settings["FIRST_SUPERUSER_PASSWORD"],
        }
    ).encode()
    token, _ = account.raw(
        "POST",
        "/api/v1/login/access-token",
        body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    account.headers["Authorization"] = "Bearer " + json.loads(token)["access_token"]
    assert account.json("GET", "/api/v1/users/me")["is_superuser"]
    users = account.json("GET", "/api/v1/users/")
    assert (
        users["count"] == 1
        and users["data"][0]["email"] == project.settings["FIRST_SUPERUSER"]
    )
    account.headers.pop("Authorization")
    account.bootstrap()
    account.json("GET", "/api/v1/users/", status=401)
    project.checks.append("administrator-login-and-guest-admin-denial")


def check_failure_boundaries(project: Installation) -> None:
    before = state(project)
    for field in ("SECRET_KEY", "POSTGRES_PASSWORD", "FIRST_SUPERUSER_PASSWORD"):
        result = project.docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--label",
            "com.docker.compose.project=" + project.project,
            "--label",
            "hdg.distribution.owner=" + project.owner,
            "--env-file",
            str(project.directory / ".env"),
            "-e",
            field + "=changethis",
            project.image,
            "initialize",
            check=False,
        )
        assert result.returncode != 0 and b"configuration" in result.stderr
    volume = project.project + "_game-data"
    result = project.docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--label",
        "com.docker.compose.project=" + project.project,
        "--label",
        "hdg.distribution.owner=" + project.owner,
        "--env-file",
        str(project.directory / ".env"),
        "--mount",
        f"type=volume,source={volume},target=/data,readonly",
        project.image,
        "initialize",
        check=False,
    )
    assert result.returncode != 0 and b"Initialization failed" in result.stderr
    bad = project.directory / "invalid-catalogue.json"
    bad.write_text("{}")
    result = project.docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--label",
        "com.docker.compose.project=" + project.project,
        "--label",
        "hdg.distribution.owner=" + project.owner,
        "--env-file",
        str(project.directory / ".env"),
        "--mount",
        f"type=bind,source={bad},target=/app/backend/catalogue/default.json,readonly",
        project.image,
        "initialize",
        check=False,
    )
    assert result.returncode != 0 and b"Initialization failed" in result.stderr
    assert state(project) == before
    client = Http(project.origin)
    project.python(
        "from pathlib import Path;Path('/data/media').rename('/data/.probe-held-media')",
        initializer=True,
    )
    try:
        client.raw("GET", "/healthz", status=503)
    finally:
        project.python(
            "from pathlib import Path;Path('/data/.probe-held-media').rename('/data/media')",
            initializer=True,
        )
    assert client.json("GET", "/healthz") == {"status": "ready"}
    project.compose("stop", "db")
    try:
        client.raw("GET", "/healthz", status=503)
    finally:
        project.compose("up", "-d", "--wait", "db")
    assert client.json("GET", "/healthz") == {"status": "ready"}
    assert state(project) == before
    project.checks.append(
        "configuration-storage-fail-closed-readiness-db-media-recovery"
    )


def check_legacy_refusal(project: Installation, evidence: Path) -> None:
    prepare = """
from datetime import date
from alembic import command
from sqlmodel import Session,select
from app.distribution.startup import alembic_config
from app.core.db import engine
from app.core.config import settings
from app.game.runtime_catalog import PACKAGED_CATALOGUE,install_runtime
from app.game.models import EventRevision,DailyDefinition
command.upgrade(alembic_config(),'20261013_01')
with Session(engine) as session:
    release=install_runtime(session,PACKAGED_CATALOGUE,initialize_only=True,media_root=settings.GAME_DATA_DIR/'media')
    event=session.exec(select(EventRevision).where(EventRevision.release_id==release)).first()
    ids=[str(event.event_id)]
    session.add(DailyDefinition(day=date(2402,1,1),catalog_release_id=release,seed=b'd'*32,rules={'category_ids':event.snapshot['category_ids'],'start_year_index':-5000,'end_year_index':3000,'min_gap':1},pool=ids,order=ids,anchor_event_id=event.event_id))
    session.commit()
"""
    with tempfile.TemporaryDirectory(prefix="hdg-legacy-", dir=private_temp()) as tmp:
        child = project.child(Path(tmp) / "legacy", offline=True)
        with owned_child(child, evidence):
            assert not child.resources()
            child.compose("up", "-d", "--wait", "db")
            child.python(prepare, initializer=True)
            before = state(child, initializer=True)
            assert before["dailydefinition"]["rows"] == 1
            result = child.compose(
                "run", "--rm", "--no-deps", "initialize", check=False
            )
            assert result.returncode != 0 and b"Initialization failed" in result.stderr
            assert state(child, initializer=True) == before
    project.checks.append("populated-legacy-migration-refusal-all-row-hashes-preserved")


def check_shutdown(project: Installation) -> None:
    start = time.monotonic()
    project.compose("stop", "app", "db")
    assert time.monotonic() - start < 30
    ids = project.compose("ps", "-aq", "app", "db").stdout.decode().split()
    assert len(ids) == 2
    for identity in ids:
        info = json.loads(project.docker("container", "inspect", identity).stdout)[0]
        require_owned(info["Config"]["Labels"], project.project, project.owner)
        assert info["State"]["ExitCode"] == 0 and not info["State"]["OOMKilled"]
    project.checks.append("native-amd64-graceful-app-db-shutdown")


def documented_commands(guide: Path, name: str) -> str:
    if name not in {"backup", "restore"}:
        raise ValueError("Unknown documented operator command block")
    blocks = re.findall(
        r"<!-- distribution:" + name + r" -->\n```sh\n(.*?)```",
        guide.read_text(),
        re.DOTALL,
    )
    if len(blocks) != 1:
        raise ValueError("Shipped operator command block is missing or ambiguous")
    return blocks[0]


def stage_operator_directory(project: Installation, directory: Path) -> None:
    directory.mkdir(mode=0o700)
    # Render only the ownership/network test override. Docker Compose's rendered
    # JSON is valid YAML, so the guide's exact -f compose.yaml commands consume it
    # without a wrapper, altered shell blocks or an undocumented restore path.
    config = json.loads(project.compose("config", "--format", "json").stdout)
    assert config["name"] == project.project
    assert not any("build" in service for service in config["services"].values())
    for name, data in (
        ("compose.yaml", json.dumps(config).encode()),
        (".env", (project.directory / ".env").read_bytes()),
        ("image-digest.txt", json.dumps({"preview_image": project.image}).encode()),
    ):
        with (directory / name).open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)


def run_documented(project: Installation, name: str, directory: Path, *, check=True):
    return subprocess.run(
        [
            "bash",
            "-e",
            "-o",
            "pipefail",
            "-c",
            documented_commands(project.directory / "INSTALL.md", name),
        ],
        cwd=directory,
        env=project.env | {"HDG_RECOVERY_PROJECT": project.project},
        check=check,
        capture_output=True,
        timeout=180,
    )


def full_probe(project: Installation, evidence: Path, browser: bool = False) -> None:
    assert (
        project.python("import platform;assert platform.machine()=='x86_64'").strip()
        == b""
    )
    if project.offline:
        info = json.loads(
            project.docker("network", "inspect", project.project + "_default").stdout
        )[0]
        assert info["Internal"] is True
        project.python(
            "from pathlib import Path;assert not any(line.split()[1]=='00000000' for line in Path('/proc/net/route').read_text().splitlines()[1:])"
        )
        project.checks.append("internal-network-no-default-egress-route")
    player, _, receipts = check_gameplay(project)
    check_login(project)
    check_failure_boundaries(project)
    check_legacy_refusal(project, evidence)
    # Retained old immutable media must survive initialization/replacement/restore.
    old = b"<svg xmlns='http://www.w3.org/2000/svg'><title>old retained media</title></svg>"
    digest = hashlib.sha256(old).hexdigest()
    project.python(
        f"from pathlib import Path;p=Path('/data/media/smoke-retained/{digest}.svg');p.parent.mkdir();p.write_bytes({old!r})",
        initializer=True,
    )
    media_url = f"/media/smoke-retained/{digest}.svg"
    assert player.raw("GET", media_url)[0] == old
    if browser:
        environment = dict(os.environ) | {
            "DISTRIBUTION_BASE_URL": project.origin,
            "DISTRIBUTION_EVIDENCE_DIR": str(evidence.resolve() / "browser"),
        }
        with (evidence / "browser.log").open("wb") as log:
            subprocess.run(
                [
                    "node",
                    "node_modules/@playwright/test/cli.js",
                    "test",
                    "--config=playwright.distribution.config.ts",
                    "--retries=0",
                ],
                cwd=ROOT / "frontend",
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=180,
            )
        project.checks.append("compiled-desktop-mobile-browser-zero-retries")
    before = state(project)
    project.compose("stop", "app", "db")
    project.compose("up", "-d", "--force-recreate", "--wait", "--wait-timeout", "90")
    project.refresh_endpoint()
    assert state(project) == before
    for url, move, response in receipts:
        assert player.json("POST", url + "/placements", move) == response
    assert player.raw("GET", media_url)[0] == old
    project.checks.append("app-db-replacement-all-row-hashes-and-historical-media")
    # Execute the shipped guide's exact shell blocks on private, owned fixtures.
    with tempfile.TemporaryDirectory(prefix="hdg-backup-", dir=private_temp()) as tmp:
        root = Path(tmp)
        original = root / "original"
        stage_operator_directory(project, original)
        run_documented(project, "backup", original)
        project.refresh_endpoint()
        backup = original / "backup"
        database, media = backup / "database.dump", backup / "media.tar"
        environment_backup = backup / "environment.private"
        saved_settings = dict(
            line.split("=", 1) for line in environment_backup.read_text().splitlines()
        )
        restored = project.child(root / "restored", settings=saved_settings)
        with owned_child(restored, evidence):
            if restored.resources():
                raise ValueError("Restore target unexpectedly exists")
            recovery = root / "recovery-commands"
            stage_operator_directory(restored, recovery)
            for source in (database, media):
                shutil.copyfile(source, recovery / source.name)
                (recovery / source.name).chmod(0o600)
            run_documented(restored, "restore", recovery)
            restored.refresh_endpoint()
            assert state(restored) == before
            # Reexecute the actual guide: its guard must refuse populated state.
            rejected = run_documented(restored, "restore", recovery, check=False)
            assert rejected.returncode != 0
            with media.open("rb") as stream:
                rejected = restored.compose(
                    "run",
                    "--rm",
                    "-T",
                    "--no-deps",
                    "--entrypoint",
                    "python",
                    "initialize",
                    "/app/backup.py",
                    "restore-media",
                    stdin=stream,
                    check=False,
                )
            assert rejected.returncode != 0
            assert state(restored) == before
            player.origin = restored.origin
            player.headers["Origin"] = restored.origin
            for url, move, response in receipts:
                assert player.json("POST", url + "/placements", move) == response
            assert player.raw("GET", media_url)[0] == old
            check_login(restored)
            check_shutdown(restored)
            project.checks.append(
                "private-dump-media-restore-to-fresh-volumes-session-account-replay"
            )
    # Both guide procedures restarted their apps; verify graceful stop as well.
    check_shutdown(project)


def main() -> int:
    install_signal_handlers()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--platform", choices=("linux/amd64",), required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--install-dir", type=Path, default=ROOT)
    parser.add_argument("--browser", action="store_true")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="deny container internet access; use a test-only loopback relay",
    )
    args = parser.parse_args()
    args.evidence_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="hdg-install-", dir=private_temp()) as tmp:
        installation = Installation(
            args.image, args.install_dir, Path(tmp) / "install", offline=args.offline
        )
        return run_owned(
            installation,
            args.evidence_dir,
            lambda project: full_probe(project, args.evidence_dir, args.browser),
        )


if __name__ == "__main__":
    raise SystemExit(main())
