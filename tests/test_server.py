import asyncio
import unittest

import server


class TestMCPToolAnnotations(unittest.TestCase):
    def test_all_pinned_spec_tools_have_complete_annotations(self):
        tools = asyncio.run(server.mcp.list_tools())

        self.assertEqual("v1.0.53", server.openapi_spec["info"]["version"])
        self.assertEqual(60, len(tools))
        for tool in tools:
            self.assertIsNotNone(tool.annotations)
            self.assertIsNotNone(tool.annotations.readOnlyHint)
            self.assertIsNotNone(tool.annotations.destructiveHint)
            self.assertIsNotNone(tool.annotations.idempotentHint)
            self.assertIsNotNone(tool.annotations.openWorldHint)

    def test_tool_annotations_reject_missing_fields(self):
        with self.assertRaisesRegex(ValueError, "exactly"):
            server._tool_annotations({"x-artie-mcp": {}})

    def test_tool_annotations_reject_non_boolean_fields(self):
        with self.assertRaisesRegex(ValueError, "booleans"):
            server._tool_annotations(
                {
                    "x-artie-mcp": {
                        "readOnlyHint": True,
                        "destructiveHint": False,
                        "idempotentHint": False,
                        "openWorldHint": "false",
                    }
                }
            )
