from __future__ import annotations

import json
import logging
import os
import socket
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx
from fastmcp.exceptions import NotFoundError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from mcp import types
from pydantic import ValidationError as PydanticValidationError


class MetricsSink(Protocol):
    def record(
        self,
        operation: str,
        outcome: str,
        duration_ms: float,
        *,
        failure_class: str | None = None,
        tool: str | None = None,
    ) -> None: ...


class StatsdMetrics:
    def __init__(self, address: tuple[str, int] | None) -> None:
        self._address = address
        self._socket = (
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if address else None
        )

    @classmethod
    def from_environment(cls) -> StatsdMetrics:
        host = os.getenv("TELEMETRY_HOST")
        port = os.getenv("TELEMETRY_PORT")
        if not host or not port:
            return cls(None)
        try:
            return cls((host, int(port)))
        except ValueError:
            logging.getLogger("artie-mcp").warning(
                "MCP metrics disabled because TELEMETRY_PORT is invalid"
            )
            return cls(None)

    def record(
        self,
        operation: str,
        outcome: str,
        duration_ms: float,
        *,
        failure_class: str | None = None,
        tool: str | None = None,
    ) -> None:
        tags = [f"operation:{operation}", f"outcome:{outcome}"]
        if failure_class:
            tags.append(f"failure_class:{failure_class}")
        if tool:
            tags.append(f"tool:{tool}")
        self._send(f"artie_mcp.mcp.request:1|c|#{','.join(tags)}")
        self._send(f"artie_mcp.mcp.duration:{duration_ms:.3f}|ms|#{','.join(tags)}")

    def _send(self, metric: str) -> None:
        if not self._socket or not self._address:
            return
        try:
            self._socket.sendto(metric.encode(), self._address)
        except OSError:
            logging.getLogger("artie-mcp").warning("failed to emit MCP metric")


class MCPObservability(Middleware):
    def __init__(
        self,
        metrics: MetricsSink,
        tool_names: frozenset[str],
        logger: logging.Logger | None = None,
    ) -> None:
        self._metrics = metrics
        self._tool_names = tool_names
        self._logger = logger or logging.getLogger("artie-mcp")

    async def on_initialize(
        self,
        context: MiddlewareContext[types.InitializeRequest],
        call_next: CallNext[types.InitializeRequest, types.InitializeResult | None],
    ) -> types.InitializeResult | None:
        return await self._observe("initialize", None, lambda: call_next(context))

    async def on_call_tool(
        self,
        context: MiddlewareContext[types.CallToolRequestParams],
        call_next: CallNext[types.CallToolRequestParams, Any],
    ) -> Any:
        tool = (
            context.message.name
            if context.message.name in self._tool_names
            else "unknown"
        )
        return await self._observe("tool_call", tool, lambda: call_next(context))

    async def _observe(
        self,
        operation: str,
        tool: str | None,
        call: Callable[[], Awaitable[Any]],
    ) -> Any:
        started_at = time.perf_counter()
        try:
            result = await call()
        except Exception as error:
            self._record(operation, tool, started_at, "error", _failure_class(error))
            raise
        self._record(operation, tool, started_at, "success", None)
        return result

    def _record(
        self,
        operation: str,
        tool: str | None,
        started_at: float,
        outcome: str,
        failure_class: str | None,
    ) -> None:
        duration_ms = (time.perf_counter() - started_at) * 1000
        self._metrics.record(
            operation,
            outcome,
            duration_ms,
            failure_class=failure_class,
            tool=tool,
        )
        event = {
            "duration_ms": round(duration_ms, 3),
            "event": "mcp_request",
            "operation": operation,
            "outcome": outcome,
        }
        if failure_class:
            event["failure_class"] = failure_class
        if tool:
            event["tool"] = tool
        self._logger.info(json.dumps(event, separators=(",", ":"), sort_keys=True))


def _failure_class(error: Exception) -> str:
    current: BaseException | None = error
    while current:
        if isinstance(current, PydanticValidationError):
            return "invalid_input"
        if isinstance(current, NotFoundError):
            return "unknown_tool"
        if isinstance(current, httpx.TimeoutException):
            return "upstream_timeout"
        if isinstance(current, httpx.HTTPStatusError):
            return "upstream_http_error"
        current = current.__cause__
    return "internal"
