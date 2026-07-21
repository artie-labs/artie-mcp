import json
import logging
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastmcp import FastMCP
from fastmcp.server.auth.providers.debug import DebugTokenVerifier
from fastmcp.server.dependencies import get_http_headers
from fastmcp.tools.tool import Tool
from mcp.types import ToolAnnotations
from starlette.responses import Response

logger = logging.getLogger("artie-mcp")

_SPEC_PATH = Path(__file__).with_name("openapi.yaml")
_MCP_ANNOTATION_KEYS = frozenset(
    {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}
)

with _SPEC_PATH.open() as spec_file:
    openapi_spec = yaml.safe_load(spec_file)


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

mcp = FastMCP.from_openapi(
    openapi_spec=openapi_spec,
    client=client,
    name="Artie",
    auth=DebugTokenVerifier(),
    mcp_component_fn=_configure_tool,
)


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
