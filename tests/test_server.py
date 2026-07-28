import asyncio
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from contract_snapshot import render_contract_snapshot


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._previous_server = sys.modules.pop("server", None)
        cls.server = importlib.import_module("server")
        cls.tools = asyncio.run(cls.server.mcp.list_tools())

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("server", None)
        if cls._previous_server is not None:
            sys.modules["server"] = cls._previous_server

    def tool(self, name):
        return next(tool for tool in self.tools if tool.name == name)

    def test_pinned_spec_checksum_is_verified(self):
        self.assertEqual("v1.0.53", self.server._PINNED_SPEC_VERSION)
        self.assertTrue(self.server._SPEC_PATH.is_file())
        self.assertEqual(
            self.server._PINNED_SPEC_VERSION,
            self.server.openapi_spec["info"]["version"],
        )
        self.assertEqual(
            self.server.openapi_spec,
            self.server._load_pinned_openapi_spec(),
        )

    def test_tampered_pinned_spec_fails_before_server_construction(self):
        with tempfile.TemporaryDirectory() as directory:
            spec_path = Path(directory) / "openapi.yaml"
            spec_path.write_bytes(self.server._SPEC_PATH.read_bytes() + b"\n")

            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                self.server._load_pinned_openapi_spec(spec_path)

    def test_server_construction_does_not_fetch_openapi(self):
        sys.modules.pop("server", None)
        try:
            with patch.object(httpx, "get") as get:
                server = importlib.import_module("server")
            get.assert_not_called()
            self.assertEqual(
                server._PINNED_SPEC_VERSION,
                server.openapi_spec["info"]["version"],
            )
        finally:
            sys.modules.pop("server", None)
            sys.modules["server"] = self.server

    def test_generated_contract_matches_snapshot(self):
        snapshot_path = Path(__file__).with_name("contract_snapshot.json")
        expected = json.loads(snapshot_path.read_text())

        self.assertEqual(expected, render_contract_snapshot(self.server))

    def test_snapshot_has_the_baseline_tool_inventory(self):
        snapshot = render_contract_snapshot(self.server)

        self.assertEqual(60, len(snapshot["tools"]))
        self.assertEqual(
            sorted(tool["name"] for tool in snapshot["tools"]),
            [tool["name"] for tool in snapshot["tools"]],
        )
        self.assertTrue(
            all(tool["annotations"] is not None for tool in snapshot["tools"])
        )

    def test_custom_ping_tool_receives_openapi_annotations(self):
        self.assertEqual(
            {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": True,
            },
            self.tool("Ping_a_connector").annotations.model_dump(exclude_none=True),
        )

    def test_204_operations_keep_annotations_without_an_output_schema(self):
        bodiless_tools = [
            tool
            for tool in self.tools
            if tool.output_schema is None and tool.annotations is not None
        ]

        self.assertTrue(bodiless_tools)

    def test_server_card_describes_the_authenticated_streamable_http_endpoint(self):
        response = self.server._server_card_response()

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            "application/mcp-server-card+json", response.headers["content-type"]
        )
        self.assertEqual("public, max-age=3600", response.headers["cache-control"])
        self.assertEqual("*", response.headers["access-control-allow-origin"])
        self.assertTrue(response.headers["etag"])
        self.assertEqual(
            {
                "$schema": "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json",
                "name": "com.artie/mcp",
                "version": "0.1.7",
                "description": "Manage, interact with, and provision Artie resources through the Artie MCP Server.",
                "title": "Artie MCP Server",
                "websiteUrl": "https://artie.com/docs/api/overview",
                "icons": [
                    {
                        "src": "https://www.artie.com/brand/logo.svg",
                        "mimeType": "image/svg+xml",
                        "sizes": ["any"],
                    }
                ],
                "remotes": [
                    {
                        "type": "streamable-http",
                        "url": "https://mcp.artie.com/mcp",
                        "headers": [
                            {
                                "name": "Authorization",
                                "value": "Bearer {artie_api_key}",
                                "variables": {
                                    "artie_api_key": {
                                        "description": "Artie API key",
                                        "isRequired": True,
                                        "isSecret": True,
                                        "format": "string",
                                    }
                                },
                            }
                        ],
                    }
                ],
            },
            json.loads(response.body),
        )

    def test_annotations_reject_malformed_openapi_extensions(self):
        valid_annotations = {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
        malformed_extensions = [
            {},
            {"x-artie-mcp": {}},
            {"x-artie-mcp": {**valid_annotations, "unknown": True}},
            {
                "x-artie-mcp": {
                    **valid_annotations,
                    "openWorldHint": "false",
                }
            },
        ]

        for route_extensions in malformed_extensions:
            with self.subTest(route_extensions=route_extensions):
                with self.assertRaises(ValueError):
                    self.server._tool_annotations(route_extensions)
