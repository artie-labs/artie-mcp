import asyncio
import atexit
import base64
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os

import httpx
from fastmcp import FastMCP
from fastmcp.server.auth import MultiAuth
from fastmcp.server.auth.providers.debug import DebugTokenVerifier
from fastmcp.server.auth.providers.workos import AuthKitProvider
from fastmcp.server.dependencies import get_access_token, get_http_headers
from fastmcp.server.providers.openapi import MCPType
from mcp.types import ToolAnnotations
from starlette.responses import Response

from mcp_observability import MCPObservability, OpenTelemetryMetrics
from policy_adapter import SafeTrafficAdapter
from policy_contract import (
    PolicyContract,
    compile_policy,
    load_policy_bundle,
    snapshot_policy_contract,
)

logger = logging.getLogger("artie-mcp")

_DIAGNOSTIC_CLAIMS_ENABLED = "WORKOS_AUTHKIT_DIAGNOSTIC_CLAIMS"
_DIAGNOSTIC_CLAIM_NAMES = frozenset[str](
    {"iss", "aud", "sub", "sid", "scope", "org_id", "exp", "iat"}
)
_BUNDLE_DIR = Path(__file__).with_name("contract")
_SERVER_CARD_MEDIA_TYPE = "application/mcp-server-card+json"
_SERVER_CARD = {
    "$schema": "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json",
    "name": "com.artie/mcp",
    "version": "0.1.7",
    "description": "Manage, interact with, and provision Artie resources through the Artie MCP Server.",
    "title": "Artie MCP Server",
    "websiteUrl": "https://artie.com/docs/api/overview",
    "icons": [
        {
            "src": "https://www.artie.com/brand/logo.svg",
            "mimeType": "image/svg+xml",
            "sizes": ["any"],
        }
    ],
    "remotes": [
        {
            "type": "streamable-http",
            "url": "https://mcp.artie.com/mcp",
            "headers": [
                {
                    "name": "Authorization",
                    "value": "Bearer {artie_api_key}",
                    "variables": {
                        "artie_api_key": {
                            "description": "Artie API key",
                            "isRequired": True,
                            "isSecret": True,
                            "format": "string",
                        }
                    },
                }
            ],
        }
    ],
}


def _build_auth_provider():
    authkit_domain = os.getenv("WORKOS_AUTHKIT_DOMAIN", "").rstrip("/")
    public_base_url = os.getenv("MCP_PUBLIC_BASE_URL", "").rstrip("/")

    if not authkit_domain and not public_base_url:
        return DebugTokenVerifier()
    if not authkit_domain or not public_base_url:
        raise RuntimeError(
            "WORKOS_AUTHKIT_DOMAIN and MCP_PUBLIC_BASE_URL must be set together"
        )

    # Temporary dual auth during OAuth migration: AuthKit JWTs for OAuth
    # clients, plus accept-and-forward for legacy Artie API keys. The API-key
    # verifier only accepts non-JWTs so expired/invalid AuthKit tokens cannot
    # fall through and keep authenticating.
    return MultiAuth(
        server=AuthKitProvider(
            authkit_domain=authkit_domain,
            base_url=public_base_url,
            resource_base_url=public_base_url,
            resource_name="Artie MCP",
        ),
        verifiers=[DebugTokenVerifier(validate=lambda token: not _is_jwt(token))],
    )


def _is_jwt(token: str) -> bool:
    """Heuristic: WorkOS access tokens are JWTs; Artie API keys are opaque."""
    parts = token.split(".")
    return len(parts) == 3 and all(parts)


# Upstream Artie API configuration. The exchanged credential is only valid on the
# Artie Dashboard/API that issued it, so both the token exchange and the tool
# calls must target the same host.
_ARTIE_API_BASE_URL = os.getenv("ARTIE_API_BASE_URL", "https://api.artie.com").rstrip(
    "/"
)
_ARTIE_TOKEN_EXCHANGE_URL = os.getenv(
    "ARTIE_TOKEN_EXCHANGE_URL", f"{_ARTIE_API_BASE_URL}/oauth/token"
)
_ARTIE_DEVICE_AUTHORIZATION_URL = os.getenv(
    "ARTIE_DEVICE_AUTHORIZATION_URL",
    f"{_ARTIE_API_BASE_URL}/oauth/device_authorization",
)
# Set ARTIE_API_INSECURE_SKIP_VERIFY=true only for local testing against a
# self-signed Dashboard (e.g. https://localhost:8000).
_ARTIE_API_VERIFY_TLS = (
    os.getenv("ARTIE_API_INSECURE_SKIP_VERIFY", "").lower() != "true"
)

_ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"
_DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
# Re-link slightly before expiry to avoid racing the upstream call.
_EXCHANGE_EXPIRY_SKEW_SECONDS = 30.0


@dataclass
class _PendingLink:
    """A device-authorization request awaiting the user's Dashboard approval."""

    device_code: str
    user_code: str
    verification_uri: str


class _DeviceLinkAuth(httpx.Auth):
    """Attach an Artie API credential to upstream requests.

    JWT-shaped Bearer tokens (WorkOS) drive an OAuth 2.0 device-authorization
    (RFC 8628) linking flow against the Artie Dashboard: the WorkOS token starts
    a pending link, the user approves it from an authenticated Dashboard session
    (choosing environment + scopes), and the approved device code is redeemed for
    a short-lived Artie credential (never forwarding the WorkOS token raw). Opaque
    Bearer tokens are treated as legacy Artie API keys and forwarded as-is during
    the OAuth migration; upstream validates them.

    State is keyed by the WorkOS token subject (stable across the token's 5-minute
    refreshes) rather than the raw token, so a pending link survives token
    rotation between the first (approval-triggering) call and later retries. Both
    the approved credential and the device code are cached in-memory; on process
    restart the user re-approves.
    """

    def __init__(self) -> None:
        # subject -> (artie_credential, expires_at_monotonic)
        self._credentials: dict[str, tuple[str, float]] = {}
        # subject -> pending/approved device-authorization link
        self._pending: dict[str, _PendingLink] = {}
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(timeout=10.0, verify=_ARTIE_API_VERIFY_TLS)

    def _cached_credential(self, subject: str, now: float) -> str | None:
        cached = self._credentials.get(subject)
        if cached is not None and cached[1] - _EXCHANGE_EXPIRY_SKEW_SECONDS > now:
            return cached[0]
        return None

    async def _credential(self, workos_token: str) -> str:
        subject = _jwt_subject(workos_token)
        now = time.monotonic()
        credential = self._cached_credential(subject, now)
        if credential is not None:
            return credential

        async with self._lock:
            # Re-check under the lock in case a concurrent call already linked.
            credential = self._cached_credential(subject, time.monotonic())
            if credential is not None:
                return credential

            pending = self._pending.get(subject)
            if pending is not None:
                status, payload = await self._poll(pending.device_code)
                if status == "ok":
                    return self._store_credential(subject, payload)
                if status == "pending":
                    raise _authorization_required(pending)
                # denied/expired/invalid: discard and start a fresh link below.
                self._pending.pop(subject, None)

            pending = await self._device_authorize(workos_token)
            self._pending[subject] = pending
            raise _authorization_required(pending)

    def _store_credential(self, subject: str, payload: dict[str, Any]) -> str:
        access_token = payload.get("access_token")
        if not access_token:
            raise RuntimeError("Artie device token response is missing access_token")
        expires_in = float(payload.get("expires_in", 0) or 0)
        self._credentials[subject] = (access_token, time.monotonic() + expires_in)
        return access_token

    async def _poll(self, device_code: str) -> tuple[str, dict[str, Any]]:
        """Redeem an approved device code, or report why it isn't ready yet."""
        response = await self._client.post(
            _ARTIE_TOKEN_EXCHANGE_URL,
            data={"grant_type": _DEVICE_CODE_GRANT, "device_code": device_code},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code == 200:
            return "ok", response.json()

        body = _safe_json(response)
        error = body.get("error", "")
        if error == "authorization_pending":
            return "pending", body
        logger.info(
            "Artie device code not redeemable (%s): %s",
            response.status_code,
            error or response.text,
        )
        return "error", body

    async def _device_authorize(self, workos_token: str) -> _PendingLink:
        response = await self._client.post(
            _ARTIE_DEVICE_AUTHORIZATION_URL,
            data={
                "subject_token": workos_token,
                "subject_token_type": _ACCESS_TOKEN_TYPE,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            logger.warning(
                "Artie device authorization failed (%s): %s",
                response.status_code,
                response.text,
            )
            raise RuntimeError(
                f"Artie device authorization failed ({response.status_code})"
            )
        payload = response.json()
        verification_uri = payload.get("verification_uri_complete") or payload.get(
            "verification_uri", ""
        )
        return _PendingLink(
            device_code=payload.get("device_code", ""),
            user_code=payload.get("user_code", ""),
            verification_uri=verification_uri,
        )

    def _bearer_token(self) -> str:
        # Prefer the verified MCP token (reliable for Streamable HTTP). Fall
        # back to the raw Authorization header for safety.
        access = get_access_token()
        if access is not None and access.token:
            return access.token

        auth_header = get_http_headers(include={"authorization"}).get(
            "authorization", ""
        )
        if auth_header.lower().startswith("bearer "):
            return auth_header[len("bearer ") :].strip()
        return ""

    async def async_auth_flow(self, request):
        bearer_token = self._bearer_token()

        if bearer_token:
            if _is_jwt(bearer_token):
                credential = await self._credential(bearer_token)
                request.headers["Authorization"] = f"Bearer {credential}"
            else:
                # Temporary API-key passthrough — upstream validates.
                request.headers["Authorization"] = f"Bearer {bearer_token}"
        yield request


def _authorization_required(pending: _PendingLink) -> RuntimeError:
    """Instruct the user to approve the pending link from the Dashboard."""
    location = pending.verification_uri or "the Artie Dashboard linking page"
    return RuntimeError(
        "Authorization required to use Artie tools. In a browser signed in to "
        f"the Artie Dashboard, open {location} and enter code "
        f"{pending.user_code}, choose the environment and scopes, then run this "
        "command again."
    )


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError, ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _jwt_subject(token: str) -> str:
    """Return the JWT `sub` claim, falling back to the raw token if undecodable.

    The token was already verified by the auth provider before reaching here, so
    decoding the payload without re-verifying the signature is safe. Keying cache
    state on the subject keeps a pending link alive across WorkOS token refreshes.
    """
    try:
        payload_segment = token.split(".")[1]
        padding = "=" * (-len(payload_segment) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_segment + padding))
        subject = claims.get("sub")
        if isinstance(subject, str) and subject:
            return subject
    except IndexError, ValueError, json.JSONDecodeError:
        pass
    return token


def _load_contract() -> tuple[dict[str, Any], PolicyContract]:
    bundle = load_policy_bundle(_BUNDLE_DIR)
    contract = compile_policy(bundle.spec)
    policy_bytes = (_BUNDLE_DIR / "policy.openapi.yaml").read_bytes()
    expected_snapshot = json.loads((_BUNDLE_DIR / "policy.contract.json").read_text())
    actual_snapshot = snapshot_policy_contract(
        bundle.release_tag, hashlib.sha256(policy_bytes).hexdigest(), contract
    )
    if actual_snapshot != expected_snapshot:
        raise ValueError(
            "policy contract snapshot does not match the local policy bundle"
        )
    return bundle.spec, contract


openapi_spec, policy_contract = _load_contract()
policy_adapter = SafeTrafficAdapter(policy_contract)
_policy_tools = {(tool.method, tool.path): tool for tool in policy_contract.tools}


async def _shape_policy_response(response: httpx.Response) -> None:
    tool = policy_adapter.tool_for_route(
        response.request.method, response.request.url.path
    )
    await response.aread()
    if response.is_success:
        content = json.dumps(
            policy_adapter.shape_response(
                tool.name,
                response.status_code,
                response.headers.get("content-type", ""),
                response.content,
            )
        ).encode()
    else:
        content = b'{"error":"upstream request failed"}'
    response._content = content
    response.headers["content-type"] = "application/json"


def _route_map(route, _default_type):
    if (route.method.lower(), route.path) in _policy_tools:
        return MCPType.TOOL
    return MCPType.EXCLUDE


def _configure_tool(route, component):
    from fastmcp.server.providers.openapi.components import OpenAPITool

    if not isinstance(component, OpenAPITool):
        return
    tool = _policy_tools[(route.method.lower(), route.path)]
    component.title = tool.title
    component.description = tool.trigger_description
    component.annotations = ToolAnnotations(**tool.annotations)
    if tool.bodiless_success:
        component.output_schema = {
            "type": "object",
            "properties": {"success": {"const": True}},
            "required": ["success"],
            "additionalProperties": False,
        }


client = httpx.AsyncClient(
    base_url=_ARTIE_API_BASE_URL,
    auth=_DeviceLinkAuth(),
    verify=_ARTIE_API_VERIFY_TLS,
    event_hooks={"response": [_shape_policy_response]},
)
mcp = FastMCP.from_openapi(
    openapi_spec=openapi_spec,
    client=client,
    name="Artie",
    auth=_build_auth_provider(),
    mcp_names={tool.name: tool.name for tool in policy_contract.tools},
    route_map_fn=_route_map,
    mcp_component_fn=_configure_tool,
    strict_input_validation=True,
)
mcp_metrics = OpenTelemetryMetrics.create()
atexit.register(mcp_metrics.shutdown)
mcp.add_middleware(
    MCPObservability(
        mcp_metrics,
        frozenset(tool.name for tool in policy_contract.tools),
    )
)

_SERVER_CARD_BODY = json.dumps(_SERVER_CARD, separators=(",", ":"))
_SERVER_CARD_ETAG = f'"{hashlib.sha256(_SERVER_CARD_BODY.encode()).hexdigest()}"'


def _server_card_headers():
    return {
        "access-control-allow-headers": "Content-Type, If-None-Match",
        "access-control-allow-methods": "GET",
        "access-control-allow-origin": "*",
        "access-control-expose-headers": "ETag",
        "cache-control": "public, max-age=3600",
        "etag": _SERVER_CARD_ETAG,
    }


def _server_card_response(status_code=200):
    return Response(
        content=None if status_code == 304 else _SERVER_CARD_BODY,
        headers=_server_card_headers(),
        media_type=_SERVER_CARD_MEDIA_TYPE,
        status_code=status_code,
    )


if os.getenv(_DIAGNOSTIC_CLAIMS_ENABLED) == "true":

    @mcp.tool(name="AuthKit_token_diagnostics")
    def authkit_token_diagnostics() -> dict:
        """Returns a safe summary of the verified token for non-production OAuth diagnostics."""
        token = get_access_token()
        if token is None:
            raise RuntimeError("No authenticated access token is available")

        claims = {
            name: value
            for name, value in token.claims.items()
            if name in _DIAGNOSTIC_CLAIM_NAMES or name.startswith("urn:artie:")
        }
        return {
            "claims": claims,
            "client_id": token.client_id,
            "resource": token.resource,
            "scopes": token.scopes,
            "token_fingerprint": hashlib.sha256(token.token.encode()).hexdigest()[:16],
        }


@mcp.custom_route("/mcp/server-card", methods=["GET"])
async def server_card(request):
    if request.headers.get("if-none-match") == _SERVER_CARD_ETAG:
        return _server_card_response(status_code=304)
    return _server_card_response()


@mcp.custom_route("/health", methods=["GET"])
async def health_check(_request):
    return Response(status_code=200)


@mcp.custom_route("/ready", methods=["GET"])
async def ready_check(_request):
    return Response(status_code=200)


class _HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(path in msg for path in ("/health", "/ready"))


def _configure_logging() -> None:
    if any(handler.name == "artie-mcp-json" for handler in logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.name = "artie-mcp-json"
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


_configure_logging()
app = mcp.http_app(transport="streamable-http", stateless_http=True)

if __name__ == "__main__":
    import uvicorn

    logging.getLogger("uvicorn.access").addFilter(_HealthCheckFilter())
    uvicorn.run(app, host="0.0.0.0", port=8000, ws="none", timeout_graceful_shutdown=30)
