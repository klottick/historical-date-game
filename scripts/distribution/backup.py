"""Stream immutable media backups; restore only into empty, trusted storage."""

import argparse
import hashlib
import os
import re
import stat
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import BinaryIO

FILE = re.compile(r"media/[A-Za-z0-9][A-Za-z0-9._-]{0,127}/([0-9a-f]{64})\.(svg|webp)")
DIRECTORY = re.compile(r"media(?:/[A-Za-z0-9][A-Za-z0-9._-]{0,127})?")
MAX_BYTES = 4 * 1024**3
MAX_FILES = 100_000


def trusted_root(root: Path) -> None:
    if not root.is_dir() or any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("Media root must be an existing real directory")


def export_media(root: Path, destination: BinaryIO) -> None:
    trusted_root(root)
    media = root / "media"
    if not media.is_dir() or media.is_symlink():
        raise ValueError("No real media directory to export")
    total = 0
    with tarfile.open(fileobj=destination, mode="w|") as archive:
        paths = sorted(media.rglob("*"))
        if len(paths) > MAX_FILES:
            raise ValueError("Media file-count limit exceeded")
        for path in paths:
            info = path.lstat()
            name = path.relative_to(root).as_posix()
            if stat.S_ISDIR(info.st_mode) and DIRECTORY.fullmatch(name):
                continue
            match = FILE.fullmatch(name)
            if not match or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Unexpected or linked media file")
            total += info.st_size
            if total > MAX_BYTES:
                raise ValueError("Media byte limit exceeded")
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != match[1]:
                    raise ValueError("Corrupted immutable media")
                stream.seek(0)
                member = tarfile.TarInfo(name)
                member.size = info.st_size
                member.mode = 0o600
                archive.addfile(member, stream)


def restore_media(root: Path, source: BinaryIO) -> None:
    trusted_root(root)
    if any(root.iterdir()):
        raise ValueError("Restore requires an empty data volume; nothing was deleted")
    # Stage only our own files. Malformed/interrupted streams never leave a
    # partially selected media tree. No tarfile extraction or archive ownership.
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=root) as tmp:
        staging = Path(tmp)
        (staging / "media").mkdir(mode=0o700)
        seen = set()
        total = 0
        with tarfile.open(fileobj=source, mode="r|*") as archive:
            for member in archive:
                name = member.name
                if name in seen or len(seen) >= MAX_FILES:
                    raise ValueError("Duplicate media or file-count limit")
                seen.add(name)
                if member.isdir() and DIRECTORY.fullmatch(name):
                    continue
                match = FILE.fullmatch(name)
                if not member.isreg() or not match or member.size < 0:
                    raise ValueError("Unexpected or linked archive entry")
                total += member.size
                if total > MAX_BYTES:
                    raise ValueError("Media byte limit exceeded")
                target = staging / name
                target.parent.mkdir(mode=0o700, exist_ok=True)
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("Unreadable media entry")
                digest = hashlib.sha256()
                remaining = member.size
                with target.open("xb") as output:
                    os.fchmod(output.fileno(), 0o600)
                    while remaining:
                        data = stream.read(min(1024 * 1024, remaining))
                        if not data:
                            raise ValueError("Truncated media entry")
                        output.write(data)
                        digest.update(data)
                        remaining -= len(data)
                if digest.hexdigest() != match[1]:
                    raise ValueError("Corrupted immutable media")
        os.replace(staging / "media", root / "media")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("export-media", "restore-media"))
    parser.add_argument("--root", type=Path, default=Path("/data"))
    args = parser.parse_args()
    try:
        if args.command == "export-media":
            export_media(args.root, sys.stdout.buffer)
        else:
            restore_media(args.root, sys.stdin.buffer)
    except (ValueError, OSError, tarfile.TarError):
        sys.stderr.write(
            "Media backup/restore refused: verify archive integrity, paths and empty destination permissions.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
