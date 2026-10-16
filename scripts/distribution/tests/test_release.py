"""Release eligibility is recomputed from live, complete metadata."""

import copy
import json
import os
import subprocess
import sys
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch

SHA = "a" * 40
MAIN = "b" * 40
CURRENT = {
    "id": 7,
    "tag_name": "v1.10.0",
    "draft": False,
    "prerelease": False,
    "published_at": "2026-10-16T12:00:00Z",
}


class Fixture:
    def __enter__(self):
        self.requests = []
        self.authorization = []
        self.routes = {
            "/repos/owner/repo/releases/7": CURRENT,
            "/repos/owner/repo/releases?per_page=100&page=1": [CURRENT],
            "/repos/owner/repo/releases?per_page=100&page=2": [],
            "/repos/owner/repo/git/ref/tags/v1.10.0": {
                "object": {"type": "tag", "sha": "c" * 40}
            },
            "/repos/owner/repo/git/tags/" + "c" * 40: {
                "object": {"type": "commit", "sha": SHA}
            },
            "/repos/owner/repo/git/ref/heads/main": {
                "object": {"type": "commit", "sha": MAIN}
            },
            f"/repos/owner/repo/compare/{SHA}...{MAIN}": {
                "status": "ahead",
                "base_commit": {"sha": SHA},
                "merge_base_commit": {"sha": SHA},
            },
        }
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                fixture.requests.append(self.path)
                fixture.authorization.append(self.headers.get("Authorization"))
                value = fixture.routes.get(self.path, (404, {"message": "missing"}))
                code, data = value if isinstance(value, tuple) else (200, value)
                self.send_response(code)
                self.end_headers()
                self.wfile.write(
                    data if isinstance(data, bytes) else json.dumps(data).encode()
                )

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()


class ReleaseTests(unittest.TestCase):
    def test_canonical_numeric_versions_and_full_identity_are_required(self):
        from scripts.distribution.release import validate_release

        older = CURRENT | {
            "id": 1,
            "tag_name": "v1.9.9",
            "published_at": "2026-10-15T12:00:00Z",
        }
        self.assertEqual(
            validate_release(CURRENT, [older, CURRENT], 7, SHA, SHA, True), "1.10.0"
        )
        for change in (
            {"tag_name": "v01.0.0"},
            {"tag_name": "1.10.0"},
            {"tag_name": "v1.10.0-rc.1"},
            {"draft": True},
            {"prerelease": True},
            {"draft": "false"},
            {"published_at": None},
            {"published_at": "bad"},
            {"published_at": "2026-10-16T12:00:00"},
            {"id": True},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_release(
                    CURRENT | change, [CURRENT | change], 7, SHA, SHA, True
                )
        for identity in (
            (8, SHA, SHA, True),
            (7, SHA, "d" * 40, True),
            (7, SHA, SHA, False),
            (7, "main", "main", True),
        ):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                validate_release(CURRENT, [CURRENT], *identity)

    def test_old_failed_retry_and_malformed_history_fail_closed(self):
        from scripts.distribution.release import validate_release

        newer = CURRENT | {
            "id": 8,
            "tag_name": "v1.11.0",
            "published_at": "2026-10-17T12:00:00Z",
        }
        for history in (
            [],
            [CURRENT, newer],
            [CURRENT, newer | {"tag_name": "v1.9.0"}],
            [CURRENT, {}],
            [CURRENT, CURRENT],
            [CURRENT | {"prerelease": True}],
            [CURRENT, {"id": 3, "tag_name": "experimental"}],
        ):
            with self.subTest(history=history), self.assertRaises(ValueError):
                validate_release(CURRENT, history, 7, SHA, SHA, True)
        noncanonical = newer | {"tag_name": "experimental"}
        self.assertEqual(
            validate_release(CURRENT, [CURRENT, noncanonical], 7, SHA, SHA, True),
            "1.10.0",
        )

    def test_fresh_paginated_http_and_annotated_tags(self):
        from scripts.distribution.release import refresh_release

        with (
            Fixture() as fixture,
            patch("scripts.distribution.release.API", fixture.url),
        ):
            self.assertEqual(refresh_release("owner/repo", 7, SHA), "1.10.0")
            fixture.routes["/repos/owner/repo/releases?per_page=100&page=2"] = [
                CURRENT | {"id": 8, "tag_name": "v2.0.0"}
            ]
            fixture.routes["/repos/owner/repo/releases?per_page=100&page=3"] = []
            with self.assertRaises(ValueError):
                refresh_release("owner/repo", 7, SHA)
            self.assertEqual(fixture.requests.count("/repos/owner/repo/releases/7"), 2)

    def test_actual_cli_propagates_later_page_and_moved_deleted_tag_failures(self):
        with Fixture() as fixture:
            initial = copy.deepcopy(fixture.routes)
            for path, value in (
                (None, None),
                ("/repos/owner/repo/releases?per_page=100&page=2", (500, {})),
                (
                    "/repos/owner/repo/git/tags/" + "c" * 40,
                    {"object": {"type": "commit", "sha": "d" * 40}},
                ),
                ("/repos/owner/repo/git/ref/tags/v1.10.0", (404, {})),
                (f"/repos/owner/repo/compare/{SHA}...{MAIN}", {"status": "diverged"}),
            ):
                fixture.routes = copy.deepcopy(initial)
                if path:
                    fixture.routes[path] = value
                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        f"import runpy;from scripts.distribution import release;release.API={fixture.url!r};release.main()",
                        "check",
                        "--repository",
                        "owner/repo",
                        "--release-id",
                        "7",
                        "--expected-sha",
                        SHA,
                    ],
                    env=dict(os.environ) | {"GH_TOKEN": "", "GITHUB_TOKEN": ""},
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
                if path is None:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), "1.10.0")
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
