from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from fastmcp.exceptions import NotFoundError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from mcp import types
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from pydantic import ValidationError as PydanticValidationError


class OpenTelemetryMetrics:
    def __init__(self, meter: Any) -> None:
        self._request_counter = meter.create_counter("mcp.request", unit="{request}")
        self._duration_histogram = meter.create_histogram(
            "mcp.request.duration", unit="ms"
        )

    @classmethod
    def create(cls) -> OpenTelemetryMetrics:
        resource = Resource.create({SERVICE_NAME: "artie-mcp"})
        reader = PeriodicExportingMetricReader(OTLPMetricExporter())
        provider = MeterProvider(resource=resource, metric_readers=[reader])
        return cls(provider.get_meter("artie-mcp"))

    def record(
        self,
        operation: str,
        outcome: str,
        duration_ms: float,
        *,
        failure_class: str | None = None,
        tool: str | None = None,
    ) -> None:
        attributes = {"mcp.operation": operation, "mcp.outcome": outcome}
        if failure_class:
            attributes["mcp.failure_class"] = failure_class
        self._request_counter.add(1, attributes)
        self._duration_histogram.record(duration_ms, attributes)


class MCPObservability(Middleware):
    def __init__(
        self,
        metrics: OpenTelemetryMetrics,
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
