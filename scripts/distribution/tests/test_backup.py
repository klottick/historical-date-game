import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path


class BackupTests(unittest.TestCase):
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
