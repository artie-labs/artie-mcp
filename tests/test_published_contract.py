import unittest
from types import SimpleNamespace

from published_contract import (
    PublishedContractError,
    add_published_schema_signatures,
    tool_schema_signatures,
    verify_published_schema_signatures,
)


class TestPublishedContract(unittest.TestCase):
    def setUp(self):
        self.tools = [
            SimpleNamespace(
                name="list_pipelines",
                parameters={"type": "object", "properties": {}},
                output_schema={"type": "object", "properties": {"items": {}}},
            )
        ]
        self.snapshot = {"tools": [{"name": "list_pipelines"}]}

    def test_add_and_verify_published_schema_signatures(self):
        signatures = tool_schema_signatures(self.tools)
        snapshot = add_published_schema_signatures(self.snapshot, signatures)

        verify_published_schema_signatures(snapshot, signatures)

    def test_uses_mcp_wire_schema_fields(self):
        signatures = tool_schema_signatures(
            [
                SimpleNamespace(
                    name="list_pipelines",
                    inputSchema={"type": "object", "properties": {}},
                    outputSchema={"type": "object", "properties": {"items": {}}},
                )
            ]
        )

        snapshot = add_published_schema_signatures(self.snapshot, signatures)
        verify_published_schema_signatures(snapshot, signatures)

    def test_rejects_a_changed_published_schema(self):
        signatures = tool_schema_signatures(self.tools)
        snapshot = add_published_schema_signatures(self.snapshot, signatures)
        changed_tools = [
            SimpleNamespace(
                name="list_pipelines",
                parameters={"type": "object", "properties": {"limit": {}}},
                output_schema={"type": "object", "properties": {"items": {}}},
            )
        ]

        with self.assertRaisesRegex(
            PublishedContractError,
            "published tool schemas do not match the policy contract snapshot",
        ):
            verify_published_schema_signatures(
                snapshot, tool_schema_signatures(changed_tools)
            )

    def test_rejects_a_missing_published_tool(self):
        signatures = tool_schema_signatures(self.tools)

        with self.assertRaisesRegex(
            PublishedContractError, "published tools do not match the policy contract"
        ):
            add_published_schema_signatures({"tools": []}, signatures)


if __name__ == "__main__":
    unittest.main()
