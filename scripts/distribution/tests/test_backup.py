import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path


class BackupTests(unittest.TestCase):
    def test_recovery_persists_project_for_later_unqualified_compose_commands(self):
        import json
        import os
        import shutil
        import subprocess

        from scripts.distribution.smoke import documented_commands
        from scripts.distribution.tests.test_image import ENV

        repo = Path(__file__).resolve().parents[3]
        real_docker = shutil.which("docker")
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            shutil.copyfile(repo / "compose.yaml", root / "compose.yaml")
            (root / ".env").write_text(
                "".join(f"{key}={value}\n" for key, value in ENV.items())
                + "COMPOSE_PROJECT_NAME=old-project\n"
            )
            fake = root / "docker"
            fake.write_text("#!/bin/sh\nexit 37\n")
            fake.chmod(0o700)
            environment = {
                "PATH": str(root) + ":" + os.environ["PATH"],
                "HOME": os.environ["HOME"],
                "HDG_RECOVERY_PROJECT": "hdg-recovery-new",
            }
            result = subprocess.run(
                [
                    "bash",
                    "-e",
                    "-c",
                    documented_commands(repo / "INSTALL.md", "restore"),
                ],
                env=environment,
                cwd=root,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 37, result.stderr)
            later = subprocess.run(
                [
                    real_docker,
                    "compose",
                    "--env-file",
                    ".env",
                    "-f",
                    "compose.yaml",
                    "config",
                    "--format",
                    "json",
                ],
                cwd=root,
                env=environment,
                capture_output=True,
                check=True,
            )
            config = json.loads(later.stdout)
            self.assertEqual(config["name"], "hdg-recovery-new")
            self.assertEqual(
                config["volumes"]["postgres-data"]["name"],
                "hdg-recovery-new_postgres-data",
            )
            self.assertEqual((root / ".env").stat().st_mode & 0o777, 0o600)

    def test_boundary_truncated_or_empty_exports_never_promote_partial_media(self):
        from scripts.distribution.backup import export_media, restore_media

        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            source = root / "source"
            (source / "media/r").mkdir(parents=True)
            for data in (b"<svg>one</svg>", b"<svg>two</svg>"):
                (
                    source / "media/r" / (hashlib.sha256(data).hexdigest() + ".svg")
                ).write_bytes(data)
            stream = io.BytesIO()
            export_media(source, stream)
            with tarfile.open(fileobj=io.BytesIO(stream.getvalue())) as archive:
                boundaries = [member.offset for member in archive.getmembers()][1:]
            for index, boundary in enumerate([0, *boundaries]):
                destination = root / f"destination-{index}"
                destination.mkdir()
                with (
                    self.subTest(boundary=boundary),
                    self.assertRaises((ValueError, tarfile.TarError)),
                ):
                    restore_media(destination, io.BytesIO(stream.getvalue()[:boundary]))
                self.assertEqual(list(destination.iterdir()), [])

    def test_removed_media_member_with_original_inventory_is_refused(self):
        from scripts.distribution.backup import export_media, restore_media

        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            source = root / "source"
            (source / "media/r").mkdir(parents=True)
            for data in (b"<svg>A</svg>", b"<svg>B</svg>"):
                (
                    source / "media/r" / (hashlib.sha256(data).hexdigest() + ".svg")
                ).write_bytes(data)
            stream = io.BytesIO()
            export_media(source, stream)
            damaged = io.BytesIO()
            with (
                tarfile.open(fileobj=io.BytesIO(stream.getvalue())) as original,
                tarfile.open(fileobj=damaged, mode="w") as target,
            ):
                for index, member in enumerate(original):
                    if index != 0:
                        target.addfile(member, original.extractfile(member))
            destination = root / "destination"
            destination.mkdir()
            with self.assertRaises(ValueError):
                restore_media(destination, io.BytesIO(damaged.getvalue()))
            self.assertEqual(list(destination.iterdir()), [])

    def test_operator_commands_are_extracted_from_the_shipped_guide_without_fallbacks(
        self,
    ):
        from scripts.distribution.smoke import documented_commands

        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            path = Path(tmp) / "INSTALL.md"
            path.write_text(
                "<!-- distribution:backup -->\n```sh\nset -eu\nprintf documented-command\n```\n"
            )
            self.assertEqual(
                documented_commands(path, "backup"),
                "set -eu\nprintf documented-command\n",
            )
            with self.assertRaises(ValueError):
                documented_commands(path, "restore")
            path.write_text(path.read_text() * 2)
            with self.assertRaises(ValueError):
                documented_commands(path, "backup")

    def archive(self, name, *, kind=tarfile.REGTYPE, data=b"<svg/>"):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.linkname = "/etc/passwd" if kind != tarfile.REGTYPE else ""
            member.size = len(data) if kind == tarfile.REGTYPE else 0
            archive.addfile(member, io.BytesIO(data) if member.size else None)
        stream.seek(0)
        return stream

    def test_restore_refuses_nonempty_or_unsafe_archives(self):
        from scripts.distribution.backup import restore_media

        digest = hashlib.sha256(b"<svg/>").hexdigest()
        for name, kind in (
            ("/etc/passwd", tarfile.REGTYPE),
            ("media/../../escape", tarfile.REGTYPE),
            (f"media/release/{digest}.svg", tarfile.SYMTYPE),
            (f"media/release/{digest}.svg", tarfile.LNKTYPE),
            ("media/r/.env", tarfile.REGTYPE),
            (f"media/../{digest}.svg", tarfile.REGTYPE),
            (f"media/r/{'0' * 64}.svg", tarfile.REGTYPE),
        ):
            with (
                self.subTest(name=name, kind=kind),
                tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp,
            ):
                root = Path(tmp)
                with self.assertRaises(ValueError):
                    restore_media(root, self.archive(name, kind=kind))
                self.assertEqual(
                    list(root.iterdir()), [], "invalid archive left partial media"
                )
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            (root / "retained").write_bytes(b"keep")
            with self.assertRaises(ValueError):
                restore_media(root, self.archive(f"media/r/{digest}.svg"))
            self.assertEqual((root / "retained").read_bytes(), b"keep")

    def test_backup_streams_preserve_private_permissions(self):
        from scripts.distribution.backup import export_media, restore_media

        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            source, destination = Path(tmp) / "source", Path(tmp) / "destination"
            source.mkdir()
            destination.mkdir()
            for release, data in (
                ("old-retained", b"<svg>old</svg>"),
                ("current", b"<svg>new</svg>"),
            ):
                path = (
                    source
                    / "media"
                    / release
                    / (hashlib.sha256(data).hexdigest() + ".svg")
                )
                path.parent.mkdir(parents=True)
                path.write_bytes(data)
            stream = io.BytesIO()
            export_media(source, stream)
            stream.seek(0)
            restore_media(destination, stream)
            for path in source.rglob("*.svg"):
                restored = destination / path.relative_to(source)
                self.assertEqual(restored.read_bytes(), path.read_bytes())
                self.assertEqual(restored.stat().st_mode & 0o777, 0o600)
                self.assertEqual(restored.parent.stat().st_mode & 0o777, 0o700)
            with self.assertRaises(ValueError):
                restore_media(destination, io.BytesIO(stream.getvalue()))
            (source / "media/current/leak.svg").symlink_to("/etc/passwd")
            with self.assertRaises(ValueError):
                export_media(source, io.BytesIO())


if __name__ == "__main__":
    unittest.main()
