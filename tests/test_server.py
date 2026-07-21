import asyncio
import importlib
import sys
import unittest
from unittest.mock import patch

import httpx


class _OpenAPIResponse:
    text = """\
openapi: 3.1.0
info:
  title: Test API
  version: 1.0.0
paths:
  /read:
    get:
      operationId: readThing
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                type: object
      x-artie-mcp:
        readOnlyHint: true
        destructiveHint: false
        idempotentHint: true
        openWorldHint: false
  /write:
    post:
      operationId: writeThing
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                type: object
      x-artie-mcp:
        readOnlyHint: false
        destructiveHint: true
        idempotentHint: false
        openWorldHint: true
  /no-content:
    delete:
      operationId: deleteThing
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                type: object
        '204':
          description: No Content
      x-artie-mcp:
        readOnlyHint: false
        destructiveHint: true
        idempotentHint: true
        openWorldHint: false
"""

    def raise_for_status(self):
        return self


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._previous_server = sys.modules.pop("server", None)
        with patch.object(httpx, "get", return_value=_OpenAPIResponse()) as get:
            cls.server = importlib.import_module("server")
        get.assert_called_once_with(cls.server._SPEC_URL)
        cls.tools = asyncio.run(cls.server.mcp.list_tools())

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("server", None)
        if cls._previous_server is not None:
            sys.modules["server"] = cls._previous_server

    def tool(self, name):
        return next(tool for tool in self.tools if tool.name == name)

    def test_hash_is_deterministic(self):
        self.assertEqual(
            "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            self.server._hash("test"),
        )

    def test_strip_secrets_redacts_nested_dicts_and_lists(self):
        self.assertEqual(
            {
                "connector": {"name": "source"},
                "items": [{"id": 1}, {"nested": {"id": 2}}],
            },
            self.server._strip_secrets(
                {
                    "connector": {
                        "name": "source",
                        "sharedConfig": {"token": "secret"},
                    },
                    "items": [
                        {"id": 1, "sharedConfig": {"password": "secret"}},
                        {"nested": {"id": 2, "sharedConfig": "secret"}},
                    ],
                }
            ),
        )

    def test_generated_tools_receive_openapi_annotations(self):
        self.assertEqual(
            {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
            self.tool("readThing").annotations.model_dump(exclude_none=True),
        )
        self.assertEqual(
            {
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
            self.tool("writeThing").annotations.model_dump(exclude_none=True),
        )

    def test_204_operations_keep_annotations_without_an_output_schema(self):
        tool = self.tool("deleteThing")

        self.assertIsNone(tool.output_schema)
        self.assertEqual(
            {
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": False,
            },
            tool.annotations.model_dump(exclude_none=True),
        )

    def test_malformed_openapi_fails_during_server_construction(self):
        malformed_response = _OpenAPIResponse()
        malformed_response.text = malformed_response.text.replace(
            "readOnlyHint: true", "readOnlyHint: invalid", 1
        )
        sys.modules.pop("server", None)

        try:
            with patch.object(httpx, "get", return_value=malformed_response):
                with self.assertRaisesRegex(ValueError, "fields must be booleans"):
                    importlib.import_module("server")
        finally:
            sys.modules.pop("server", None)
            sys.modules["server"] = self.server

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
