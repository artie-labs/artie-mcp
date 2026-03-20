from pathlib import Path

import httpx
import yaml
from fastmcp import FastMCP
from fastmcp.server.auth.providers.debug import DebugTokenVerifier
from fastmcp.server.dependencies import get_http_headers


class _ForwardAuth(httpx.Auth):
    """Forward the MCP client's bearer token to the upstream Artie API."""

    def auth_flow(self, request):
        auth_header = get_http_headers(include={"authorization"}).get("authorization", "")
        if auth_header:
            request.headers["Authorization"] = auth_header
        yield request


client = httpx.AsyncClient(
    base_url="https://api.artie.com",
    auth=_ForwardAuth(),
)

spec_path = Path(__file__).parent / "openapi.yaml"
with open(spec_path) as f:
    openapi_spec = yaml.safe_load(f)

mcp = FastMCP.from_openapi(
    openapi_spec=openapi_spec,
    client=client,
    name="Artie",
    auth=DebugTokenVerifier(),
)

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)