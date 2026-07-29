import asyncio
import json
import unittest

from fastmcp.server.middleware import MiddlewareContext
from mcp import types
from pydantic import ValidationError as PydanticValidationError

from mcp_observability import MCPObservability, OpenTelemetryMetrics


class RecordingMetrics:
    def __init__(self):
        self.records = []

    def record(self, operation, outcome, duration_ms, **kwargs):
        self.records.append(
            {
                "operation": operation,
                "outcome": outcome,
                "duration_ms": duration_ms,
                **kwargs,
            }
        )


class TestMCPObservability(unittest.TestCase):
    def setUp(self):
        self.metrics = RecordingMetrics()
        self.middleware = MCPObservability(self.metrics, frozenset({"pipeline_list"}))

    def test_records_successful_initialization(self):
        async def call_next(_context):
            return None

        context = MiddlewareContext(
            message=types.InitializeRequest.model_construct(), method="initialize"
        )
        with self.assertLogs("artie-mcp", level="INFO") as logs:
            asyncio.run(self.middleware.on_initialize(context, call_next))

        self.assertEqual("initialize", self.metrics.records[0]["operation"])
        self.assertEqual("success", self.metrics.records[0]["outcome"])
        self.assertEqual(
            {"duration_ms", "event", "operation", "outcome"},
            set(json.loads(logs.records[0].getMessage())),
        )

    def test_records_a_redacted_initialization_failure(self):
        async def call_next(_context):
            raise RuntimeError("unlogged-error-detail")

        context = MiddlewareContext(
            message=types.InitializeRequest.model_construct(), method="initialize"
        )
        with self.assertLogs("artie-mcp", level="INFO") as logs:
            with self.assertRaisesRegex(RuntimeError, "unlogged-error-detail"):
                asyncio.run(self.middleware.on_initialize(context, call_next))

        record = self.metrics.records[0]
        self.assertEqual("initialize", record["operation"])
        self.assertEqual("error", record["outcome"])
        self.assertEqual("internal", record["failure_class"])
        self.assertNotIn("unlogged-error-detail", logs.output[0])

    def test_records_a_redacted_tool_failure(self):
        async def call_next(_context):
            raise PydanticValidationError.from_exception_data(
                "CallToolRequestParams",
                [{"type": "missing", "loc": ("arguments",), "input": {}}],
            )

        context = MiddlewareContext(
            message=types.CallToolRequestParams(
                name="pipeline_list", arguments={"credential": "secret-token"}
            ),
            method="tools/call",
        )
        with self.assertLogs("artie-mcp", level="INFO") as logs:
            with self.assertRaises(PydanticValidationError):
                asyncio.run(self.middleware.on_call_tool(context, call_next))

        record = self.metrics.records[0]
        self.assertEqual("tool_call", record["operation"])
        self.assertEqual("error", record["outcome"])
        self.assertEqual("invalid_input", record["failure_class"])
        self.assertEqual("pipeline_list", record["tool"])
        self.assertNotIn("secret-token", logs.output[0])
        self.assertNotIn("credential", logs.output[0])

    def test_unknown_tool_is_not_emitted_as_a_metric_tag(self):
        async def call_next(_context):
            return None

        context = MiddlewareContext(
            message=types.CallToolRequestParams(name="attacker-controlled-name"),
            method="tools/call",
        )
        asyncio.run(self.middleware.on_call_tool(context, call_next))

        self.assertEqual("unknown", self.metrics.records[0]["tool"])


class RecordingInstrument:
    def __init__(self):
        self.records = []

    def add(self, value, attributes):
        self.records.append((value, attributes))

    def record(self, value, attributes):
        self.records.append((value, attributes))


class RecordingMeter:
    def __init__(self):
        self.counter = RecordingInstrument()
        self.histogram = RecordingInstrument()

    def create_counter(self, _name, **_kwargs):
        return self.counter

    def create_histogram(self, _name, **_kwargs):
        return self.histogram


class TestOpenTelemetryMetrics(unittest.TestCase):
    def test_emits_count_and_duration_without_tool_name_attributes(self):
        meter = RecordingMeter()
        metrics = OpenTelemetryMetrics(meter)

        metrics.record(
            "tool_call",
            "error",
            12.5,
            failure_class="invalid_input",
            tool="pipeline_list",
        )

        expected_attributes = {
            "mcp.operation": "tool_call",
            "mcp.outcome": "error",
            "mcp.failure_class": "invalid_input",
        }
        self.assertEqual([(1, expected_attributes)], meter.counter.records)
        self.assertEqual([(12.5, expected_attributes)], meter.histogram.records)


if __name__ == "__main__":
    unittest.main()
