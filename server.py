import asyncio
import contextlib
import hashlib
import logging
import os
import signal

import httpx
import yaml
from fastmcp import FastMCP
from fastmcp.server.auth.providers.debug import DebugTokenVerifier
from fastmcp.server.dependencies import get_http_headers
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
        auth_header = get_http_headers(include={"authorization"}).get("authorization", "")
        if auth_header:
            request.headers["Authorization"] = auth_header
        yield request


client = httpx.AsyncClient(
    base_url="https://api.artie.com",
    auth=_ForwardAuth(),
)

mcp = FastMCP.from_openapi(
    openapi_spec=openapi_spec,
    client=client,
    name="Artie",
    auth=DebugTokenVerifier(),
)


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


if __name__ == "__main__":
    import uvicorn

    logging.getLogger("uvicorn.access").addFilter(_HealthCheckFilter())

    app = mcp.http_app(transport="streamable-http")

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
    uvicorn.run(app, host="0.0.0.0", port=8000, timeout_graceful_shutdown=30)