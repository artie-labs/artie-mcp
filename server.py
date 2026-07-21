import asyncio
import contextlib
import hashlib
import json
import logging
import os
import signal
from typing import Any

import httpx
import yaml
from fastmcp import FastMCP
from fastmcp.server.auth.providers.debug import DebugTokenVerifier
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.providers.openapi import MCPType, RouteMap
from mcp.types import ToolAnnotations
from starlette.responses import Response

logger = logging.getLogger("artie-mcp")

_SPEC_URL = "https://raw.githubusercontent.com/artie-labs/artie-api-spec/refs/heads/master/openapi.yaml"
_SPEC_POLL_INTERVAL = 120
_DRAIN_DELAY = 5

_shutting_down = False


def _fetch_spec_text() -> str:
    return httpx.get(_SPEC_URL).raise_for_status().text


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


_spec_text = _fetch_spec_text()
_spec_hash = _hash(_spec_text)
openapi_spec = yaml.safe_load(_spec_text)


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


def _tool_annotations(route_extensions: dict[str, Any]) -> ToolAnnotations:
    annotations = route_extensions.get("x-artie-mcp")
    if not isinstance(annotations, dict):
        raise ValueError("x-artie-mcp must be an object")
    if set(annotations) != _MCP_ANNOTATION_KEYS:
        raise ValueError(
            "x-artie-mcp must contain exactly the MCP tool annotation fields"
        )
    if any(type(value) is not bool for value in annotations.values()):
        raise ValueError("x-artie-mcp tool annotation fields must be booleans")

    return ToolAnnotations(**annotations)


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


@mcp.tool(name="Ping_a_connector")
async def ping_connector(uuid: str) -> str:
    """Tests network connectivity and authentication for a saved connector."""
    get_resp = await _raw_client.get(f"/connectors/{uuid}")
    get_resp.raise_for_status()
    connector = get_resp.json()

    ping_resp = await _raw_client.post("/connectors/ping", json=connector)
    ping_resp.raise_for_status()
    return ping_resp.text or "Ping successful"


async def _poll_spec():
    global _shutting_down
    while not _shutting_down:
        await asyncio.sleep(_SPEC_POLL_INTERVAL)
        try:
            new_hash = _hash(_fetch_spec_text())
        except Exception:
            logger.exception("Failed to fetch spec for change detection")
            continue

        if new_hash != _spec_hash:
            logger.info("OpenAPI spec changed, initiating graceful shutdown")
            _shutting_down = True
            await asyncio.sleep(_DRAIN_DELAY)
            os.kill(os.getpid(), signal.SIGTERM)
            return


@mcp.custom_route("/health", methods=["GET"])
async def health_check(_request):
    return Response(status_code=200)


@mcp.custom_route("/ready", methods=["GET"])
async def ready_check(_request):
    if _shutting_down:
        return Response(status_code=503)
    return Response(status_code=200)


class _HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(p in msg for p in ("/health", "/ready"))


app = mcp.http_app(transport="streamable-http", stateless_http=True)

_original_lifespan = app.lifespan


@contextlib.asynccontextmanager
async def _lifespan(a):
    async with _original_lifespan(a):
        task = asyncio.create_task(_poll_spec())
        try:
            yield
        finally:
            task.cancel()


app.router.lifespan_context = _lifespan

if __name__ == "__main__":
    import uvicorn

    logging.getLogger("uvicorn.access").addFilter(_HealthCheckFilter())
    uvicorn.run(app, host="0.0.0.0", port=8000, ws="none", timeout_graceful_shutdown=30)
