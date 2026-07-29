import asyncio
import json
import unittest
from unittest.mock import patch

from fastmcp.server.middleware import MiddlewareContext
from mcp import types
from pydantic import ValidationError as PydanticValidationError

from mcp_observability import MCPObservability, StatsdMetrics


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
            raise RuntimeError("Authorization: Bearer secret-token")

        context = MiddlewareContext(
            message=types.InitializeRequest.model_construct(), method="initialize"
        )
        with self.assertLogs("artie-mcp", level="INFO") as logs:
            with self.assertRaisesRegex(RuntimeError, "secret-token"):
                asyncio.run(self.middleware.on_initialize(context, call_next))

        record = self.metrics.records[0]
        self.assertEqual("initialize", record["operation"])
        self.assertEqual("error", record["outcome"])
        self.assertEqual("internal", record["failure_class"])
        self.assertNotIn("secret-token", logs.output[0])

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


class TestStatsdMetrics(unittest.TestCase):
    def test_emits_count_and_duration_with_allowlisted_tags(self):
        with patch("mcp_observability.socket.socket") as new_socket:
            metric_socket = new_socket.return_value
            metrics = StatsdMetrics(("127.0.0.1", 8125))

            metrics.record(
                "tool_call",
                "error",
                12.5,
                failure_class="invalid_input",
                tool="pipeline_list",
            )

        payloads = [
            call.args[0].decode() for call in metric_socket.sendto.call_args_list
        ]
        self.assertEqual(2, len(payloads))
        self.assertTrue(all("secret" not in payload for payload in payloads))
        self.assertTrue(all("tool:pipeline_list" in payload for payload in payloads))
        self.assertTrue(
            all("failure_class:invalid_input" in payload for payload in payloads)
        )


if __name__ == "__main__":
    unittest.main()
