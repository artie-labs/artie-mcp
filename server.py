import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastmcp import FastMCP
from fastmcp.server.auth.providers.debug import DebugTokenVerifier
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.providers.openapi import MCPType, RouteMap
from mcp.types import ToolAnnotations
from starlette.responses import Response

_PINNED_SPEC_VERSION = "v1.0.53"
_PINNED_SPEC_SHA256 = "fbd57a5d2b0a741022df2f577c7fd98647989cb93cbc292a182498a7fdc14495"
_SPEC_PATH = Path(__file__).parent / "openapi" / "openapi.yaml"
_MCP_ANNOTATION_EXTENSION = "x-artie-mcp"
_SERVER_CARD_MEDIA_TYPE = "application/mcp-server-card+json"

# Server Card names are stable reverse-DNS identities, not connection URLs.
# The endpoint stays separately declared in remotes; see SEP-2127:
# https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2127
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

# TODO: Replace API-key connection guidance with approved OAuth metadata and flow.
# TODO: Add supportedProtocolVersions after verifying the production MCP protocol version.
# TODO: Add repository metadata after artie-mcp becomes public.


def _load_pinned_openapi_spec(spec_path: Path = _SPEC_PATH) -> dict[str, Any]:
    try:
        spec_bytes = spec_path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"failed to read pinned OpenAPI spec: {spec_path}") from exc

    actual_sha256 = hashlib.sha256(spec_bytes).hexdigest()
    if actual_sha256 != _PINNED_SPEC_SHA256:
        raise RuntimeError(
            f"pinned OpenAPI spec checksum mismatch: expected {_PINNED_SPEC_SHA256}, got {actual_sha256}"
        )

    try:
        spec = yaml.safe_load(spec_bytes)
    except yaml.YAMLError as exc:
        raise RuntimeError("failed to parse pinned OpenAPI spec") from exc
    if not isinstance(spec, dict):
        raise RuntimeError("pinned OpenAPI spec must be an object")
    return spec


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


_SERVER_CARD_BODY = json.dumps(_SERVER_CARD, separators=(",", ":"))
_SERVER_CARD_ETAG = f'"{_hash(_SERVER_CARD_BODY)}"'


openapi_spec = _load_pinned_openapi_spec()


class _ForwardAuth(httpx.Auth):
    """Forward the MCP client's bearer token to the upstream Artie API."""

    def auth_flow(self, request):
        auth_header = get_http_headers(include={"authorization"}).get(
            "authorization", ""
        )
        if auth_header:
            request.headers["Authorization"] = auth_header
        yield request


_REDACTED_KEYS = frozenset({"sharedConfig"})


def _strip_secrets(obj):
    """Recursively remove keys that may contain credentials from a JSON structure."""
    if isinstance(obj, dict):
        return {k: _strip_secrets(v) for k, v in obj.items() if k not in _REDACTED_KEYS}
    if isinstance(obj, list):
        return [_strip_secrets(item) for item in obj]
    return obj


async def _redact_response(response: httpx.Response):
    """Strip credentials from API responses so the LLM never sees them."""
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type:
        return
    await response.aread()
    try:
        body = json.loads(response.content)
        response._content = json.dumps(_strip_secrets(body)).encode()
    except json.JSONDecodeError, UnicodeDecodeError:
        pass


_MCP_ANNOTATION_KEYS = frozenset(
    {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}
)
_OPENAPI_HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "patch", "head", "options", "trace"}
)


def _tool_annotations(route_extensions: dict[str, Any]) -> ToolAnnotations:
    annotations = route_extensions.get(_MCP_ANNOTATION_EXTENSION)
    if not isinstance(annotations, dict):
        raise ValueError(f"{_MCP_ANNOTATION_EXTENSION} must be an object")
    if set(annotations) != _MCP_ANNOTATION_KEYS:
        raise ValueError(
            f"{_MCP_ANNOTATION_EXTENSION} must contain exactly the MCP tool annotation fields"
        )
    if any(type(value) is not bool for value in annotations.values()):
        raise ValueError(
            f"{_MCP_ANNOTATION_EXTENSION} tool annotation fields must be booleans"
        )

    return ToolAnnotations(**annotations)


def _validate_openapi_annotations(spec: dict[str, Any]) -> None:
    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            raise ValueError(f"OpenAPI path {path} must be an object")
        for method, operation in path_item.items():
            if method.lower() not in _OPENAPI_HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                raise ValueError(
                    f"OpenAPI operation {method.upper()} {path} must be an object"
                )
            _tool_annotations(operation)


def _operation_annotations(path: str, method: str) -> ToolAnnotations:
    operation = openapi_spec["paths"][path][method]
    return _tool_annotations(operation)


def _configure_tool(route, component):
    """Apply the OpenAPI tool contract to each generated FastMCP tool."""
    from fastmcp.tools.tool import Tool

    if not isinstance(component, Tool):
        return

    component.annotations = _tool_annotations(route.extensions)

    # FastMCP's parser drops bodiless responses from route.responses, so we look
    # up the original spec. The MCP protocol requires structured output whenever
    # an outputSchema is declared, but a 204 has no body to return.
    if component.output_schema is None:
        return
    spec_responses = (
        openapi_spec.get("paths", {})
        .get(route.path, {})
        .get(route.method.lower(), {})
        .get("responses", {})
    )
    if "204" in spec_responses:
        component.output_schema = None


_validate_openapi_annotations(openapi_spec)

client = httpx.AsyncClient(
    base_url="https://api.artie.com",
    auth=_ForwardAuth(),
    event_hooks={"response": [_redact_response]},
)

_raw_client = httpx.AsyncClient(
    base_url="https://api.artie.com",
    auth=_ForwardAuth(),
)

mcp = FastMCP.from_openapi(
    openapi_spec=openapi_spec,
    client=client,
    name="Artie",
    auth=DebugTokenVerifier(),
    mcp_component_fn=_configure_tool,
    route_maps=[
        RouteMap(pattern=r"^/connectors/ping$", mcp_type=MCPType.EXCLUDE),
    ],
)


@mcp.tool(
    name="Ping_a_connector",
    annotations=_operation_annotations("/connectors/ping", "post"),
)
async def ping_connector(uuid: str) -> str:
    """Tests network connectivity and authentication for a saved connector."""
    get_resp = await _raw_client.get(f"/connectors/{uuid}")
    get_resp.raise_for_status()
    connector = get_resp.json()

    ping_resp = await _raw_client.post("/connectors/ping", json=connector)
    ping_resp.raise_for_status()
    return ping_resp.text or "Ping successful"


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
        return not any(p in msg for p in ("/health", "/ready"))


app = mcp.http_app(transport="streamable-http", stateless_http=True)

if __name__ == "__main__":
    import uvicorn

    logging.getLogger("uvicorn.access").addFilter(_HealthCheckFilter())
    uvicorn.run(app, host="0.0.0.0", port=8000, ws="none", timeout_graceful_shutdown=30)
