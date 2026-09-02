"""OAuth discovery + DCR shim in front of the WorkOS emulator.

The WorkOS emulator (ghcr.io/workos/emulate) implements the AuthKit
authorize/authenticate/jwks surface but NOT the two things an MCP client (and
FastMCP's AuthKitProvider) need from an authorization server:

  1. RFC 8414 / OIDC discovery (`/.well-known/oauth-authorization-server`,
     `/.well-known/openid-configuration`) — emulator returns 401/404.
  2. RFC 7591 dynamic client registration (`POST /oauth2/register`) — 404.

Additionally, the emulator's `/oauth2/token` does not accept
`grant_type=authorization_code`; code exchange lives on the WorkOS-SDK-shaped
`POST /user_management/authenticate`, which requires the emulator API key as
`client_secret`.

This shim fills exactly those gaps, standard-library only. Local-dev only;
it is not a supported Artie product.

Token claims are NOT rewritten here. Run the emulator with
`--issuer <shim base url>` so `iss` matches this shim, and seed a `jwtTemplate`
that overrides `aud` with the MCP resource URL (the emulator explicitly allows
templates to override `aud`). Tokens stay genuinely emulator-signed and the
JWKS is the emulator's own.

Config (env vars):
  SHIM_PORT            default 4110
  SHIM_BASE_URL        default http://127.0.0.1:4110  (must equal emulator --issuer)
  EMULATOR_BASE_URL    default http://127.0.0.1:4100  (shim → emulator, may be a compose DNS name)
  EMULATOR_PUBLIC_URL  default EMULATOR_BASE_URL      (browser-facing authorize URL)
  EMULATOR_API_KEY     default sk_test_default
"""

import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SHIM_PORT = int(os.getenv("SHIM_PORT", "4110"))
SHIM_BASE_URL = os.getenv("SHIM_BASE_URL", f"http://127.0.0.1:{SHIM_PORT}").rstrip("/")
EMULATOR_BASE_URL = os.getenv("EMULATOR_BASE_URL", "http://127.0.0.1:4100").rstrip("/")
EMULATOR_PUBLIC_URL = os.getenv("EMULATOR_PUBLIC_URL", EMULATOR_BASE_URL).rstrip("/")
EMULATOR_API_KEY = os.getenv("EMULATOR_API_KEY", "sk_test_default")

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, mcp-protocol-version",
}


def metadata() -> dict:
    return {
        "issuer": SHIM_BASE_URL,
        "authorization_endpoint": f"{EMULATOR_PUBLIC_URL}/user_management/authorize",
        "token_endpoint": f"{SHIM_BASE_URL}/oauth2/token",
        "jwks_uri": f"{SHIM_BASE_URL}/oauth2/jwks",
        "registration_endpoint": f"{SHIM_BASE_URL}/oauth2/register",
        "userinfo_endpoint": f"{SHIM_BASE_URL}/oauth2/userinfo",
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        "scopes_supported": ["openid", "profile", "email", "offline_access"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }


def _jwt_expires_in(token: str) -> int:
    """Best-effort expires_in from the JWT's own exp claim (unverified)."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        import base64

        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return max(0, int(payload["exp"]) - int(time.time()))
    except Exception:
        return 3600


def _emulator_request(
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict | bytes, str]:
    request_headers = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(
        f"{EMULATOR_BASE_URL}{path}",
        data=data,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "application/json")
            if "json" in content_type:
                return response.status, json.loads(raw), content_type
            return response.status, raw, content_type
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw), "application/json"
        except Exception:
            return (
                error.code,
                {
                    "error": "server_error",
                    "error_description": "emulator returned a non-JSON error",
                },
                "application/json",
            )


class Handler(BaseHTTPRequestHandler):
    server_version = "authkit-shim/0.1"

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in CORS_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        for name, value in CORS_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in (
            "/.well-known/oauth-authorization-server",
            "/.well-known/openid-configuration",
        ):
            self._send_json(200, metadata())
        elif path in ("/oauth2/authorize", "/authorize"):
            dest = f"{EMULATOR_PUBLIC_URL}/user_management/authorize"
            if parsed.query:
                dest = f"{dest}?{parsed.query}"
            self._redirect(dest)
        elif path == "/oauth2/jwks":
            status, payload, _ = _emulator_request("/oauth2/jwks")
            if status != 200 or not isinstance(payload, dict):
                self._send_json(
                    502,
                    {"error": "server_error", "error_description": "jwks proxy failed"},
                )
                return
            self._send_json(status, payload)
        elif path == "/oauth2/userinfo":
            auth = self.headers.get("Authorization", "")
            status, payload, _ = _emulator_request(
                "/oauth2/userinfo",
                headers={"Authorization": auth} if auth else None,
            )
            if not isinstance(payload, dict):
                self._send_json(
                    502,
                    {
                        "error": "server_error",
                        "error_description": "userinfo proxy failed",
                    },
                )
                return
            self._send_json(status, payload)
        elif path == "/health":
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not_found"})

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path in ("/register", "/oauth2/register"):
            self._handle_register()
        elif path == "/oauth2/token":
            self._handle_token()
        else:
            self._send_json(404, {"error": "not_found"})

    def _handle_register(self) -> None:
        # The emulator does not enforce registered clients on authorize, so any
        # syntactically valid registration works. Echo the client's metadata.
        try:
            requested = json.loads(self._read_body() or b"{}")
        except json.JSONDecodeError:
            requested = {}
        registration = {
            "client_id": f"client_shim_{secrets.token_hex(8)}",
            "client_id_issued_at": int(time.time()),
            "token_endpoint_auth_method": "none",
            "grant_types": requested.get(
                "grant_types", ["authorization_code", "refresh_token"]
            ),
            "response_types": requested.get("response_types", ["code"]),
            "redirect_uris": requested.get("redirect_uris", []),
        }
        for key in ("client_name", "scope", "client_uri"):
            if key in requested:
                registration[key] = requested[key]
        self._send_json(201, registration)

    def _handle_token(self) -> None:
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        raw = self._read_body()
        if content_type == "application/json":
            try:
                form = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                form = {}
        else:
            form = {
                key: values[0]
                for key, values in urllib.parse.parse_qs(raw.decode()).items()
            }

        grant_type = form.get("grant_type", "")
        upstream = {
            "grant_type": grant_type,
            "client_id": form.get("client_id") or "client_shim_default",
            # The emulator authenticates the exchange with its API key, not a
            # per-client secret; MCP clients are public (auth method "none").
            "client_secret": EMULATOR_API_KEY,
        }
        if grant_type == "authorization_code":
            upstream["code"] = form.get("code", "")
            if form.get("code_verifier"):
                upstream["code_verifier"] = form["code_verifier"]
        elif grant_type == "refresh_token":
            upstream["refresh_token"] = form.get("refresh_token", "")
        else:
            self._send_json(
                400,
                {
                    "error": "unsupported_grant_type",
                    "error_description": f"shim supports authorization_code and refresh_token, got {grant_type!r}",
                },
            )
            return

        status, payload, _ = _emulator_request(
            "/user_management/authenticate", method="POST", body=upstream
        )
        if (
            status != 200
            or not isinstance(payload, dict)
            or "access_token" not in payload
        ):
            error = {
                "error": payload.get("error", "invalid_grant")
                if isinstance(payload, dict)
                else "invalid_grant",
                "error_description": (
                    payload.get(
                        "error_description", f"emulator authenticate failed ({status})"
                    )
                    if isinstance(payload, dict)
                    else f"emulator authenticate failed ({status})"
                ),
            }
            self._send_json(400, error)
            return

        token_response = {
            "access_token": payload["access_token"],
            "token_type": "Bearer",
            "expires_in": _jwt_expires_in(payload["access_token"]),
        }
        if payload.get("refresh_token"):
            token_response["refresh_token"] = payload["refresh_token"]
        if form.get("scope"):
            token_response["scope"] = form["scope"]
        self._send_json(200, token_response)

    def log_message(self, format: str, *args) -> None:
        print(f"[authkit-shim] {self.address_string()} {format % args}", flush=True)


def main() -> None:
    print(
        f"[authkit-shim] listening on :{SHIM_PORT}\n"
        f"[authkit-shim]   issuer            = {SHIM_BASE_URL}\n"
        f"[authkit-shim]   emulator          = {EMULATOR_BASE_URL}\n"
        f"[authkit-shim]   emulator (public) = {EMULATOR_PUBLIC_URL}",
        flush=True,
    )
    ThreadingHTTPServer(("0.0.0.0", SHIM_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
