import asyncio
import atexit
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
from policy_adapter import PolicyAdapterError, SafeTrafficAdapter
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
_UPSTREAM_DETAIL_LIMIT = 500
_SERVER_CARD_MEDIA_TYPE = "application/mcp-server-card+json"
_OPENAI_APPS_CHALLENGE_TOKEN = "1kqGXSE8W91ZoiNotedhP3QeSzKShfsvP88VE_epI-A"
_SERVER_CARD = {
    "$schema": "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json",
    "name": "com.artie/mcp",
    "description": (
        "Manage, interact with, and provision Artie resources through the Artie "
        "MCP Server. Authenticate with OAuth (AuthKit); clients discover the "
        "authorization server via protected-resource metadata on this origin."
    ),
    "title": "Artie MCP Server",
    "websiteUrl": "https://artie.com/docs/api/overview",
    "icons": [
        {
            "src": "https://www.artie.com/brand/logo.svg",
            "mimeType": "image/svg+xml",
            "sizes": ["any"],
        }
    ],
    # OAuth is the primary path: remotes carry no required API-key header so
    # discovery clients follow AuthKit via /.well-known/oauth-protected-resource.
    # Legacy API keys remain accepted by the server; see README.
    "remotes": [
        {
            "type": "streamable-http",
            "url": "https://mcp.artie.com/mcp",
        }
    ],
}


def _build_auth_provider():
    authkit_domain = os.getenv("WORKOS_AUTHKIT_DOMAIN", "").rstrip("/")
    public_base_url = os.getenv("MCP_PUBLIC_BASE_URL", "").rstrip("/")
    if not authkit_domain or not public_base_url:
        raise RuntimeError("WORKOS_AUTHKIT_DOMAIN and MCP_PUBLIC_BASE_URL are required")

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
    # WorkOS access tokens are JWTs; Artie API keys are opaque.
    parts = token.split(".")
    return len(parts) == 3 and all(parts)


# Exchange credential is only valid on the host that issued it — exchange and
# tool calls must target the same base URL.
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

# Local testing against a self-signed Dashboard only.
_ARTIE_API_VERIFY_TLS = (
    os.getenv("ARTIE_API_INSECURE_SKIP_VERIFY", "").lower() != "true"
)

_ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"
_TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
# Re-exchange slightly before expiry to avoid racing the upstream call.
_EXCHANGE_EXPIRY_SKEW_SECONDS = 30.0
# Bounded retry when Dashboard rate-limits minting (RFC 8628 slow_down).
_SLOW_DOWN_MAX_ATTEMPTS = 5
_SLOW_DOWN_SECONDS = 5.0


@dataclass
class _PendingLink:
    user_code: str
    verification_uri: str


class _DeviceLinkAuth(httpx.Auth):
    """Attach an Artie API credential to upstream requests.

    JWT Bearers (WorkOS) are exchanged (RFC 8693) for a short-lived Artie
    credential against a durable grant the user approved once (environment +
    scopes). Exchange is stateless: every request trades the live WorkOS token
    for a fresh credential, so no long-lived token is held and any replica can
    serve any request. Pending grants surface authorization_pending + user_code;
    missing grants bootstrap via device authorization. Opaque Bearers are legacy
    API keys forwarded as-is during the OAuth migration.

    Cache and single-flight locks are keyed by a hash of the full bearer token
    so distinct OAuth clients (and refreshed tokens) never share credentials,
    without parsing unverified JWT claims. Only the short-lived Artie credential
    is cached; a WorkOS refresh re-exchanges against the durable grant.
    """

    def __init__(self) -> None:
        self._credentials: dict[str, tuple[str, float]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()
        self._client = httpx.AsyncClient(timeout=10.0, verify=_ARTIE_API_VERIFY_TLS)

    def _cached_credential(self, key: str, now: float) -> str | None:
        cached = self._credentials.get(key)
        if cached is not None and cached[1] - _EXCHANGE_EXPIRY_SKEW_SECONDS > now:
            return cached[0]
        return None

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    async def _credential(self, workos_token: str) -> str:
        key = _token_key(workos_token)
        now = time.monotonic()
        credential = self._cached_credential(key, now)
        if credential is not None:
            return credential

        lock = await self._lock_for(key)
        async with lock:
            credential = self._cached_credential(key, time.monotonic())
            if credential is not None:
                return credential

            for attempt in range(_SLOW_DOWN_MAX_ATTEMPTS):
                status, payload = await self._exchange(workos_token)
                if status == "ok":
                    return self._store_credential(key, payload)

                # Pending with user_code: surface it without creating another link.
                # The Dashboard is the source of truth for the pending state, so each
                # retry re-reads it from the exchange rather than caching it here.
                if status == "pending":
                    if payload.get("user_code"):
                        raise _authorization_required(
                            _PendingLink(
                                user_code=payload["user_code"],
                                verification_uri=payload.get("verification_uri", ""),
                            )
                        )
                    raise RuntimeError(
                        "Artie authorization is pending; try this command again shortly."
                    )

                if status == "slow_down":
                    if attempt + 1 >= _SLOW_DOWN_MAX_ATTEMPTS:
                        raise RuntimeError(
                            "Artie token exchange is rate-limited; try this command again shortly."
                        )
                    await asyncio.sleep(_SLOW_DOWN_SECONDS)
                    continue

                # No usable grant (none, denied, expired, or new session): bootstrap.
                raise _authorization_required(
                    await self._device_authorize(workos_token)
                )

    def _store_credential(self, key: str, payload: dict[str, Any]) -> str:
        access_token = payload.get("access_token")
        if not access_token:
            raise RuntimeError("Artie token exchange response is missing access_token")
        expires_in = float(payload.get("expires_in", 0) or 0)
        self._credentials[key] = (access_token, time.monotonic() + expires_in)
        return access_token

    async def _exchange(self, workos_token: str) -> tuple[str, dict[str, Any]]:
        response = await self._client.post(
            _ARTIE_TOKEN_EXCHANGE_URL,
            data={
                "grant_type": _TOKEN_EXCHANGE_GRANT,
                "subject_token": workos_token,
                "subject_token_type": _ACCESS_TOKEN_TYPE,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code == 200:
            return "ok", response.json()

        body = _safe_json(response)
        error = body.get("error", "")
        if error == "authorization_pending":
            return "pending", body
        if error == "slow_down":
            return "slow_down", body
        logger.info(
            "Artie token exchange not ready (%s): %s",
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
        return _PendingLink(
            user_code=payload.get("user_code", ""),
            verification_uri=payload.get("verification_uri", ""),
        )

    def _bearer_token(self) -> str:
        # get_access_token() is reliable for Streamable HTTP; header is fallback.
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


def _token_key(token: str) -> str:
    # Hash the full bearer so cache/locks stay scoped to this exact token
    # (client, session, and refresh) without parsing JWT claims.
    return hashlib.sha256(token.encode()).hexdigest()


def _load_contract() -> tuple[dict[str, Any], PolicyContract, str]:
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
    return bundle.spec, contract, bundle.release_tag


openapi_spec, policy_contract, policy_release_tag = _load_contract()
_SERVER_CARD["version"] = policy_release_tag.removeprefix("v")
policy_adapter = SafeTrafficAdapter(policy_contract)
_policy_tools = {(tool.method, tool.path): tool for tool in policy_contract.tools}


def _log_upstream_event(event: str, tool_name: str, **fields: Any) -> None:
    logger.warning(
        json.dumps(
            {"event": event, "tool": tool_name, **fields},
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _upstream_error_message(response: httpx.Response) -> str | None:
    message = _safe_json(response).get("error")
    if isinstance(message, str) and message:
        return message[:_UPSTREAM_DETAIL_LIMIT]
    return None


def _client_error_content(response: httpx.Response) -> bytes:
    # Dashboard 4xx bodies say what the caller must change (missing fields,
    # bad UUIDs), so their error message is passed through. 5xx bodies can
    # leak internals and stay generic.
    if 400 <= response.status_code < 500:
        if message := _upstream_error_message(response):
            return json.dumps({"error": message}).encode()
    return b'{"error":"upstream request failed"}'


def _upstream_error_detail(response: httpx.Response) -> str:
    # Only the dashboard's own error string is recorded: sibling fields in an
    # upstream error body can carry credentials. A body we cannot read that
    # string from is described by shape alone, which still distinguishes a
    # malformed payload from an empty one.
    if message := _upstream_error_message(response):
        return message
    content_type = response.headers.get("content-type", "unknown").split(";", 1)[0]
    return f"<unparsed {content_type.strip()} body, {len(response.content)} bytes>"


async def _shape_policy_response(response: httpx.Response) -> None:
    tool = policy_adapter.tool_for_route(
        response.request.method, response.request.url.path
    )
    await response.aread()
    if response.is_success:
        try:
            shaped = policy_adapter.shape_response(
                tool.name,
                response.status_code,
                response.headers.get("content-type", ""),
                response.content,
            )
        except PolicyAdapterError as error:
            # An approved upstream success we could not shape is our defect, not
            # the caller's; the client only sees a generic tool error.
            _log_upstream_event(
                "response_shaping_error",
                tool.name,
                status=response.status_code,
                detail=str(error),
            )
            raise
        content = json.dumps(shaped).encode()
    else:
        # 5xx details never reach the client, so the operator-facing reason has
        # to be recorded here or it is lost.
        _log_upstream_event(
            "upstream_error",
            tool.name,
            status=response.status_code,
            detail=_upstream_error_detail(response),
        )
        content = _client_error_content(response)
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
    timeout=15.0,
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


@mcp.custom_route("/.well-known/openai-apps-challenge", methods=["GET"])
async def openai_apps_challenge(_request):
    return Response(_OPENAI_APPS_CHALLENGE_TOKEN, media_type="text/plain")


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
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        ws="none",
        timeout_graceful_shutdown=30,
    )
