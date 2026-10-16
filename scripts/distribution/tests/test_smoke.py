import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class SmokeTests(unittest.TestCase):
    def test_child_restore_keeps_the_same_isolated_docker_credentials(self):
        from scripts.distribution.smoke import Installation

        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            assets = root / "assets"
            assets.mkdir()
            (assets / "compose.yaml").write_text("services: {}")
            (assets / "env.example").write_text("HDG_IMAGE=\n")
            parent = Installation("image", assets, root / "parent")
            parent.env = {
                "DOCKER_CONFIG": str(root / "empty-config"),
                "PATH": "/usr/bin",
            }
            child = parent.child(root / "child", offline=True)
            self.assertEqual(child.env, parent.env)
            self.assertTrue(child.offline)
            self.assertNotEqual(child.owner, parent.owner)
            self.assertEqual(
                child.settings["SECRET_KEY"], parent.settings["SECRET_KEY"]
            )

    def test_sigterm_is_a_recorded_interruption_instead_of_skipping_cleanup(self):
        import signal

        from scripts.distribution.smoke import install_signal_handlers

        old = signal.getsignal(signal.SIGTERM)
        self.addCleanup(signal.signal, signal.SIGTERM, old)
        install_signal_handlers()
        with self.assertRaises(InterruptedError):
            signal.raise_signal(signal.SIGTERM)

    def test_cli_refuses_missing_image_and_keeps_failure_evidence(self):
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            evidence = Path(tmp) / "evidence"
            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts/distribution/smoke.py"),
                    "--image",
                    "hdg-distribution-intentionally-missing:never-pull",
                    "--platform",
                    "linux/amd64",
                    "--evidence-dir",
                    str(evidence),
                ],
                check=False,
                capture_output=True,
                timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(
                json.loads((evidence / "result.json").read_text())["passed"]
            )
            self.assertTrue((evidence / "failure.log").is_file())

    def test_missing_evidence_directory_fails_before_start(self):
        from unittest.mock import Mock

        from scripts.distribution.smoke import run_owned

        installation = Mock()
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            with self.assertRaises(ValueError):
                run_owned(installation, Path(tmp) / "missing", lambda _: None)
            installation.start.assert_not_called()

    def test_smoke_preserves_failure_logs_before_owned_cleanup(self):
        from scripts.distribution.smoke import run_owned

        class Installation:
            def __init__(self, error, events, root):
                self.error = error
                self.events = events
                self.root = root

            def start(self):
                self.events.append("start")
                raise self.error

            def diagnostics(self, destination):
                self.events.append("diagnostics")
                (destination / "services.log").write_text("first failure")

            def cleanup(self):
                self.events.append("cleanup")
                self.assert_evidence = (self.root / "services.log").read_text()
                raise RuntimeError("cleanup also failed")

        for error in (RuntimeError("image start refused"), KeyboardInterrupt()):
            with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
                events = []
                code = run_owned(
                    Installation(error, events, Path(tmp)), Path(tmp), lambda _: None
                )
                self.assertEqual(code, 1)
                self.assertEqual(events, ["start", "diagnostics", "cleanup"])
                result = json.loads((Path(tmp) / "result.json").read_text())
                self.assertFalse(result["passed"])
                self.assertEqual(result["failure"], type(error).__name__)
                self.assertEqual(result["cleanup_failure"], "RuntimeError")

    def test_cleanup_refuses_foreign_labels(self):
        from scripts.distribution.smoke import require_owned

        for labels in (
            {},
            {"com.docker.compose.project": "mine"},
            {"com.docker.compose.project": "other", "hdg.distribution.owner": "owner"},
            {"com.docker.compose.project": "mine", "hdg.distribution.owner": "foreign"},
        ):
            with self.subTest(labels=labels), self.assertRaises(ValueError):
                require_owned(labels, "mine", "owner")
        require_owned(
            {"com.docker.compose.project": "mine", "hdg.distribution.owner": "owner"},
            "mine",
            "owner",
        )

    def test_smoke_never_builds_or_reuses_services(self):
        from scripts.distribution.smoke import Installation

        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            assets = root / "assets"
            assets.mkdir()
            (assets / "compose.yaml").write_text("services: {}")
            (assets / "env.example").write_text("HDG_IMAGE=\n")
            one = Installation("image:one", assets, root / "one", offline=True)
            two = Installation("image:two", assets, root / "two")
            self.assertNotEqual(one.project, two.project)
            self.assertNotEqual(one.owner, two.owner)
            self.assertNotEqual(one.settings["SECRET_KEY"], two.settings["SECRET_KEY"])
            self.assertEqual(
                one.compose_command("up", "-d")[-3:], ["up", "-d", "--no-build"]
            )
            self.assertIn("internal: true", (one.directory / "owned.yaml").read_text())
            self.assertFalse((assets / ".env").exists())
            with self.assertRaises(FileExistsError):
                Installation("image", assets, root / "one")

    def test_offline_relay_forwards_bytes_without_an_external_network(self):
        import http.server
        import threading
        from urllib.request import urlopen

        from scripts.distribution.smoke import Relay

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"owned isolated upstream")

            def log_message(self, *args):
                pass

        upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=upstream.serve_forever, daemon=True)
        worker.start()
        try:
            relay = Relay(("127.0.0.1", 0), upstream.server_address)
            with urlopen(
                f"http://127.0.0.1:{relay.server_address[1]}/probe", timeout=3
            ) as response:
                self.assertEqual(response.read(), b"owned isolated upstream")
            relay.close()
        finally:
            upstream.shutdown()
            upstream.server_close()


if __name__ == "__main__":
    unittest.main()
