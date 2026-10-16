import hashlib
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

BODY = json.dumps(
    {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {"digest": "sha256:" + "a" * 64},
        "layers": [],
    }
).encode()
DIGEST = "sha256:" + hashlib.sha256(BODY).hexdigest()
IMAGE = "ghcr.io/klottick/historical-date-game"


class Response(io.BytesIO):
    status = 200

    def __init__(self, body=BODY, digest=DIGEST):
        super().__init__(body)
        self.headers = {
            "Docker-Content-Digest": digest,
            "Content-Type": "application/vnd.oci.image.manifest.v1+json",
        }


class RegistryTests(unittest.TestCase):
    def test_anonymous_token_request_does_not_use_inherited_workflow_credentials(self):
        import os

        from scripts.distribution.registry import token
        from scripts.distribution.tests.test_release import Fixture

        with Fixture() as fixture:
            fixture.routes[
                "/token?service=ghcr.io&scope=repository%3Aklottick%2Fhistorical-date-game%3Apull"
            ] = {"token": "anonymous-registry-token"}
            with (
                patch("scripts.distribution.registry.ROOT", fixture.url),
                patch.dict(
                    os.environ,
                    {"GH_TOKEN": "MUST-NOT-BE-SENT", "GITHUB_ACTOR": "private-actor"},
                ),
            ):
                self.assertEqual(
                    token(IMAGE, anonymous=True), "anonymous-registry-token"
                )
            self.assertEqual(fixture.authorization, [None])

    def test_registry_redirects_cannot_forward_the_bearer_token(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread
        from urllib.request import Request

        from scripts.distribution.registry import urlopen

        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/foreign")
                self.end_headers()

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        Thread(target=server.serve_forever, daemon=True).start()
        try:
            request = Request(
                f"http://127.0.0.1:{server.server_port}/manifest",
                headers={"Authorization": "Bearer synthetic-private"},
            )
            with self.assertRaises(HTTPError):
                urlopen(request, timeout=3)
            self.assertEqual(requests, ["/manifest"])
        finally:
            server.shutdown()
            server.server_close()

    def test_only_authenticated_explicit_manifest_unknown_means_absent(self):
        from scripts.distribution.registry import manifest

        for status, code in (
            (401, "UNAUTHORIZED"),
            (403, "DENIED"),
            (404, "NAME_UNKNOWN"),
            (404, None),
            (429, "TOOMANYREQUESTS"),
            (500, "UNKNOWN"),
        ):
            error = HTTPError(
                "https://ghcr.io/v2/test",
                status,
                "error",
                {},
                io.BytesIO(json.dumps({"errors": [{"code": code}]}).encode()),
            )
            with (
                self.subTest(status=status, code=code),
                patch("scripts.distribution.registry.urlopen", side_effect=error),
                self.assertRaises(HTTPError),
            ):
                manifest(IMAGE, "1.0.0", "token")
        error = HTTPError(
            "https://ghcr.io/v2/test",
            404,
            "missing",
            {},
            io.BytesIO(b'{"errors":[{"code":"MANIFEST_UNKNOWN"}]}'),
        )
        with patch("scripts.distribution.registry.urlopen", side_effect=error):
            self.assertIsNone(manifest(IMAGE, "1.0.0", "token"))
        with self.assertRaises(ValueError):
            manifest(IMAGE, "1.0.0", "")

    def test_digest_json_transport_uncertainty_never_allows_publication(self):
        from scripts.distribution.registry import manifest

        with patch("scripts.distribution.registry.urlopen", return_value=Response()):
            self.assertEqual(
                manifest(IMAGE, "1.0.0", "token"),
                (DIGEST, BODY, "application/vnd.oci.image.manifest.v1+json"),
            )
        for response in (
            Response(digest="sha256:" + "0" * 64),
            Response(body=b"not-json"),
            Response(body=b"{}", digest="sha256:" + hashlib.sha256(b"{}").hexdigest()),
        ):
            with (
                patch("scripts.distribution.registry.urlopen", return_value=response),
                self.assertRaises(ValueError),
            ):
                manifest(IMAGE, "1.0.0", "token")
        with (
            patch("scripts.distribution.registry.urlopen", side_effect=TimeoutError),
            self.assertRaises(TimeoutError),
        ):
            manifest(IMAGE, "1.0.0", "token")

    def test_existing_immutable_tags_stop_publication(self):
        from scripts.distribution.registry import require_absent_version

        with patch("scripts.distribution.registry.manifest", return_value=None):
            require_absent_version(IMAGE, "1.0.0", "a" * 40, "token")
        for existing in (
            ((DIGEST, BODY, "type"), None),
            (None, (DIGEST, BODY, "type")),
        ):
            with (
                patch("scripts.distribution.registry.manifest", side_effect=existing),
                self.assertRaises(ValueError),
            ):
                require_absent_version(IMAGE, "1.0.0", "a" * 40, "token")


if __name__ == "__main__":
    unittest.main()
