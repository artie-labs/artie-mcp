import http.client
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "authkit-shim"))

import shim  # noqa: E402


class _FakeEmulator(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/oauth2/jwks":
            self._send(200, {"keys": [{"kid": "test"}]})
        elif self.path == "/oauth2/userinfo":
            if self.headers.get("Authorization") != "Bearer good":
                self._send(401, {"error": "invalid_token"})
                return
            self._send(200, {"sub": "user_1", "email": "local@example.com"})
        else:
            self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path != "/user_management/authenticate":
            self._send(404, {"error": "not_found"})
            return
        if body.get("grant_type") != "authorization_code" or body.get("code") != "ok":
            self._send(400, {"error": "invalid_grant", "error_description": "bad code"})
            return
        self._send(
            200,
            {
                "access_token": "aaa.eyJleHAiOjQ3MDAwMDAwMDB9.ccc",
                "refresh_token": "refresh_1",
            },
        )

    def _send(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _serve(handler, host="127.0.0.1") -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer((host, 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


class AuthkitShimTests(unittest.TestCase):
    def setUp(self) -> None:
        self.emulator, _ = _serve(_FakeEmulator)
        emulator_url = f"http://127.0.0.1:{self.emulator.server_address[1]}"
        shim.EMULATOR_BASE_URL = emulator_url
        shim.EMULATOR_PUBLIC_URL = "http://127.0.0.1:4100"
        shim.SHIM_BASE_URL = "http://127.0.0.1:4110"
        self.shim, _ = _serve(shim.Handler)
        self.base = f"http://127.0.0.1:{self.shim.server_address[1]}"

    def tearDown(self) -> None:
        self.shim.shutdown()
        self.emulator.shutdown()

    def _json(
        self, path: str, method: str = "GET", body: dict | None = None, **headers
    ):
        data = None
        request_headers = dict(headers)
        if body is not None:
            data = json.dumps(body).encode()
            request_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(
            f"{self.base}{path}", data=data, headers=request_headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_discovery_points_browser_at_public_emulator(self):
        status, payload = self._json("/.well-known/oauth-authorization-server")
        self.assertEqual(200, status)
        self.assertEqual("http://127.0.0.1:4110", payload["issuer"])
        self.assertEqual(
            "http://127.0.0.1:4100/user_management/authorize",
            payload["authorization_endpoint"],
        )
        self.assertEqual(
            "http://127.0.0.1:4110/oauth2/register", payload["registration_endpoint"]
        )

    def test_register_and_token_exchange(self):
        status, registration = self._json("/oauth2/register", method="POST", body={})
        self.assertEqual(201, status)
        self.assertTrue(registration["client_id"].startswith("client_shim_"))

        status, token = self._json(
            "/oauth2/token",
            method="POST",
            body={"grant_type": "authorization_code", "code": "ok"},
        )
        self.assertEqual(200, status)
        self.assertEqual("aaa.eyJleHAiOjQ3MDAwMDAwMDB9.ccc", token["access_token"])
        self.assertEqual("refresh_1", token["refresh_token"])

    def test_jwks_and_userinfo_proxy(self):
        status, jwks = self._json("/oauth2/jwks")
        self.assertEqual(200, status)
        self.assertEqual([{"kid": "test"}], jwks["keys"])

        status, userinfo = self._json("/oauth2/userinfo", Authorization="Bearer good")
        self.assertEqual(200, status)
        self.assertEqual("user_1", userinfo["sub"])

    def test_authorize_redirects_to_emulator(self):
        host, port = self.shim.server_address
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request(
            "GET",
            "/oauth2/authorize?client_id=abc&redirect_uri=http://127.0.0.1/cb",
        )
        response = conn.getresponse()
        self.assertEqual(302, response.status)
        self.assertEqual(
            "http://127.0.0.1:4100/user_management/authorize?client_id=abc&redirect_uri=http://127.0.0.1/cb",
            response.getheader("Location"),
        )
        conn.close()


if __name__ == "__main__":
    unittest.main()
