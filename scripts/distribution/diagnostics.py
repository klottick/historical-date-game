"""Preserve sanitized first-failure evidence and clean only journalled test owners."""

import argparse
import io
import json
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path

from scripts.distribution.smoke import Installation, private_temp

SENSITIVE = re.compile(
    r"password|secret|token|authorization|cookie|credential", re.IGNORECASE
)


def scrub(value):
    # Diagnostic archives are not a safe channel for arbitrary application or
    # JavaScript values. Preserve structure/numbers and a small vocabulary only;
    # selectors, logs, serialized evaluation args/results and bodies are private.
    if isinstance(value, list):
        if len(value) == 2 and value[0] == "value" and isinstance(value[1], str):
            return ["value", "[REDACTED]"]
        return [scrub(item) for item in value]
    if isinstance(value, dict):
        if isinstance(value.get("name"), str) and value["name"].lower() in {
            "accept",
            "content-type",
        }:
            return {
                "name": value["name"],
                "value": value.get("value")
                if value.get("value")
                in {
                    "application/json",
                    "text/html",
                    "image/svg+xml",
                    "application/octet-stream",
                }
                else "[REDACTED]",
            }
        if "fill" in str(value.get("apiName", "")) and isinstance(
            value.get("params"), dict
        ):
            value = value | {"params": value["params"] | {"value": "[REDACTED]"}}
        if value.get("type") == "password" and "value" in value:
            value = value | {"value": "[REDACTED]"}
        if SENSITIVE.search(str(value.get("name", ""))) and "value" in value:
            value = value | {"value": "[REDACTED]"}
        result = {}
        for key, item in value.items():
            if SENSITIVE.search(key) or key in {
                "postData",
                "params",
                "result",
                "arg",
                "args",
                "expression",
                "stdout",
                "stderr",
                "error",
                "html",
            }:
                result[key] = "[REDACTED]"
            elif (
                key == "type"
                and isinstance(item, str)
                and item
                in {"before", "after", "event", "resource-snapshot", "context-options"}
                or key == "apiName"
                and isinstance(item, str)
                and re.fullmatch(r"[a-zA-Z]+\.[a-zA-Z]+", item)
                or isinstance(item, str)
                and (
                    (key == "owner" and re.fullmatch(r"[a-f0-9]{32}", item))
                    or (
                        key == "project"
                        and re.fullmatch(r"hdg-dist-[a-f0-9]{32}", item)
                    )
                )
            ):
                result[key] = item
            else:
                result[key] = scrub(item)
        return result
    if isinstance(value, str):
        return "[REDACTED]"
    return value


def sanitize_bytes(data: bytes) -> bytes:
    try:
        value = json.loads(data)
    except json.JSONDecodeError:
        pass  # Playwright trace events are JSONL, resources may be whole JSON.
    else:
        return (json.dumps(scrub(value), separators=(",", ":")) + "\n").encode()
    lines = []
    for line in data.decode().splitlines():
        if not line.strip():
            continue
        lines.append(json.dumps(scrub(json.loads(line)), separators=(",", ":")))
    return ("\n".join(lines) + "\n").encode()


def sanitize_archive(data: bytes, *, depth=0) -> bytes:
    if depth > 4:
        raise ValueError("Nested diagnostic archive limit exceeded")
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(data)) as source,
        zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target,
    ):
        if sum(item.file_size for item in source.infolist()) > 256 * 1024**2:
            raise ValueError("Diagnostic archive limit exceeded")
        for member in source.infolist():
            name = member.filename
            if name.endswith(".zip"):
                content = sanitize_archive(source.read(member), depth=depth + 1)
            elif name.startswith("resources/"):
                # HAR bodies can be JSON, form .dat, HTML, JS or images. None is
                # safe to copy. Original resources remain in private evidence.
                content = b"[REDACTED RESOURCE]"
            elif name.endswith((".network", ".trace", ".json", ".jsonl")):
                content = sanitize_bytes(source.read(member))
            else:
                content = b"[REDACTED RESOURCE]"
            target.writestr(member, content)
        target.writestr(
            "sanitization-policy.json",
            json.dumps(
                {
                    "policy": "metadata-only",
                    "viewer_complete": False,
                    "raw_evidence": "retained privately outside upload directories",
                    "removed": [
                        "body resources",
                        "screenshots",
                        "serialized values",
                        "arbitrary text",
                    ],
                }
            ),
        )
    return output.getvalue()


def sanitize_tree(root: Path) -> None:
    if not root.exists():
        return
    for path in [item for item in root.rglob("*") if item.is_file()]:
        temporary = path.with_suffix(".sanitized")
        try:
            data = path.read_bytes()
            if path.suffix == ".zip":
                sanitized = sanitize_archive(data)
            elif path.suffix in {".json", ".jsonl", ".network", ".trace"}:
                sanitized = sanitize_bytes(data)
            else:
                sanitized = b"[REDACTED RESOURCE]"
            private = (
                Path(tempfile.mkdtemp(prefix="hdg-private-trace-", dir=private_temp()))
                / path.name
            )
            with private.open("xb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(data)
            temporary.write_bytes(sanitized)
            temporary.chmod(0o600)
            temporary.replace(path)
        except (ValueError, UnicodeError, zipfile.BadZipFile):
            # Keep original evidence privately, but never let an always-run
            # upload publish a trace whose redaction could not be proved.
            quarantine = (
                Path(tempfile.mkdtemp(prefix="hdg-unsanitized-", dir=private_temp()))
                / path.name
            )
            path.replace(quarantine)
            quarantine.chmod(0o600)
            path.with_suffix(".redaction-failed.json").write_text(
                json.dumps(
                    {
                        "failure": "trace_redaction_failed",
                        "private_copy": str(quarantine),
                    }
                )
                + "\n"
            )
            raise ValueError(
                "Trace redaction failed; original quarantined outside upload directory"
            ) from None
        finally:
            temporary.unlink(missing_ok=True)


def copy_evidence(source: Path, destination: Path) -> None:
    """Copy readable container outputs without changing their owners or modes."""
    if source.is_symlink():
        raise ValueError("Refusing linked diagnostic root")
    if not source.exists():
        return
    if not source.is_dir():
        raise ValueError("Diagnostic root must be a directory")
    destination.mkdir(mode=0o700)
    for path in source.rglob("*"):
        target = destination / path.relative_to(source)
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            target.mkdir(mode=0o700)
        elif stat.S_ISREG(mode):
            with target.open("xb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(path.read_bytes())
        else:
            raise ValueError("Refusing linked or special diagnostic file")


def cleanup_evidence(root: Path) -> None:
    journal = root / "owned-projects.jsonl"
    if not journal.exists():
        return
    seen = set()
    for line in journal.read_text().splitlines():
        item = json.loads(line)
        owner = item["owner"]
        if (
            not re.fullmatch(r"[a-f0-9]{32}", owner)
            or item["project"] != "hdg-dist-" + owner
        ):
            raise ValueError("Refusing malformed ownership journal")
        if owner in seen:
            continue
        seen.add(owner)
        installation = Installation.__new__(Installation)
        installation.project, installation.owner, installation.relay = (
            item["project"],
            owner,
            None,
        )
        installation.env = {
            key: value
            for key, value in os.environ.items()
            if key
            in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG", "XDG_RUNTIME_DIR")
        }
        # resources() inspects both labels on the entire set BEFORE mutations.
        resources = installation.resources()
        for kind, identity in resources:
            if kind != "container":
                continue
            info = json.loads(
                installation.docker("container", "inspect", identity).stdout
            )[0]
            environment = dict(entry.split("=", 1) for entry in info["Config"]["Env"])
            result = installation.docker("logs", identity, check=False)
            log = (result.stdout + result.stderr).decode(errors="replace")
            for key, value in environment.items():
                if value and SENSITIVE.search(key):
                    log = log.replace(value, "[REDACTED]")
            (root / (identity + "-interrupted.log")).write_text(log)
        installation.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True, action="append")
    parser.add_argument("--cleanup-owned", action="store_true")
    parser.add_argument(
        "--copy-to",
        type=Path,
        help="Sanitize fresh private copies, leaving source evidence untouched",
    )
    args = parser.parse_args()
    if args.copy_to:
        if args.cleanup_owned:
            parser.error("--copy-to cannot be combined with --cleanup-owned")
        if len({path.name for path in args.evidence}) != len(args.evidence):
            parser.error("Copy sources must have distinct directory names")
        if any(
            args.copy_to.resolve().is_relative_to(path.resolve())
            for path in args.evidence
        ):
            parser.error("Copy destination must be outside every source tree")
        try:
            args.copy_to.mkdir(mode=0o700, parents=True, exist_ok=False)
        except OSError:
            parser.error("Copy destination must be a new writable directory")
    failures = []
    for evidence in args.evidence:
        target = args.copy_to / evidence.name if args.copy_to else evidence
        actions = [lambda root=target: sanitize_tree(root)]
        if args.copy_to:
            actions.insert(
                0,
                lambda source=evidence, destination=target: copy_evidence(
                    source, destination
                ),
            )
        if args.cleanup_owned:
            actions.insert(0, lambda root=evidence: cleanup_evidence(root))
        errors = []
        for action in actions:
            try:
                action()
            except Exception as exc:  # noqa: BLE001 - handle every owned project before failing the step
                errors.append(type(exc).__name__)
        if errors:
            failures.extend(errors)
            if target.is_dir():
                try:
                    (target / "diagnostics-failure.json").write_text(
                        json.dumps({"errors": errors}) + "\n"
                    )
                except OSError:
                    # A read-only source can also reject the failure marker.
                    # Keep the original failure and a nonzero upload gate.
                    pass
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
